#!/usr/bin/env python3
"""Enrich exhibitor CSV with website URLs via the company-search API (multithreaded)."""

import csv
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Semaphore

CSV_PATH = "/Users/nkapila6/onegiantleap_2026_exhibitors.csv"
CHECKPOINT_PATH = "/Users/nkapila6/.enrichment_checkpoint.json"
API_URL_BASE = (
    "https://exhibitly.onegiantleap.com/api/company-search"
    "?event_id=01bc3715-1f0b-46d3-ab4d-389e87a66388&q="
)
MAX_WORKERS = 20
REQUEST_TIMEOUT = 15
CHECKPOINT_EVERY = 50

# Limit simultaneous in-flight API calls. The endpoint rate-limits under
# sustained load, so we keep at most this many requests open at once while
# still using a larger thread pool for parsing/resilience.
API_CONCURRENCY = 4
_API_SEM = Semaphore(API_CONCURRENCY)

SUFFIXES = [
    "inc",
    "llc",
    "ltd",
    "co",
    "corp",
    "company",
    "group",
    "gmbh",
    "pte",
    "fzc",
    "llp",
    "private",
    "limited",
    "the",
]
SUFFIX_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in SUFFIXES) + r")\b", re.I
)
NON_ALNUM_RE = re.compile(r"[^\w\s]", re.UNICODE)
UNDERSCORE_RE = re.compile(r"_+", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+", re.UNICODE)

STOPWORDS = {
    "information",
    "technology",
    "systems",
    "company",
    "services",
    "solutions",
    "trading",
    "holding",
    "group",
    "international",
    "global",
    "middle",
    "east",
    "united",
    "finance",
    "general",
    "business",
    "data",
    "tech",
    "digital",
    "innovation",
    "consulting",
    "management",
    "development",
    "engineering",
    "software",
    "computer",
    "communication",
    "electronics",
    "automotive",
    "industry",
    "industries",
    "enterprises",
    "network",
    "networks",
    "cloud",
    "ai",
    "intelligence",
    "security",
    "automation",
    "platform",
    "applications",
    "application",
    "mobile",
    "web",
    "online",
    "media",
    "marketing",
    "education",
    "training",
    "learning",
    "health",
    "healthcare",
    "medical",
    "pharma",
    "energy",
    "power",
    "electric",
    "construction",
    "building",
    "real",
    "estate",
    "transport",
    "logistics",
    "supply",
    "chain",
    "retail",
    "consumer",
    "food",
    "beverage",
    "agriculture",
    "mining",
    "oil",
    "gas",
    "petroleum",
    "chemical",
    "plastics",
    "textile",
    "fashion",
    "apparel",
    "sports",
    "entertainment",
    "gaming",
    "tourism",
    "travel",
    "hospitality",
    "financial",
    "bank",
    "banking",
    "insurance",
    "investment",
    "capital",
    "venture",
    "law",
    "legal",
    "government",
    "public",
    "sector",
    "private",
    "limited",
    "llc",
    "ltd",
    "inc",
    "corp",
    "co",
    "the",
    "and",
    "for",
    "of",
    "saudi",
    "arabia",
    "ksa",
    "uae",
    "dubai",
    "abudhabi",
    "emirates",
}


def normalize_name(name):
    """Normalize a company name for fuzzy comparison."""
    s = str(name).lower().strip()
    if "|" in s:
        s = s.split("|")[-1].strip()
    s = SUFFIX_RE.sub(" ", s)
    s = NON_ALNUM_RE.sub(" ", s)
    s = UNDERSCORE_RE.sub(" ", s)
    s = WHITESPACE_RE.sub(" ", s).strip()
    return s


def first_significant_token(norm, min_len=4):
    """Return the first non-stopword token that is at least min_len characters."""
    for t in norm.split():
        if len(t) >= min_len and t not in STOPWORDS:
            return t
    return ""


def alphanumeric_prefix(norm, length=8):
    """Return the first N word characters joined together."""
    chars = re.sub(r"\W", "", norm, flags=re.UNICODE)
    return chars[:length]


def domain_root(domain):
    """Return the part of the domain before the TLD (e.g. accenture from accenture.com)."""
    if not domain:
        return ""
    domain = domain.lower().strip()
    if domain.startswith("http://"):
        domain = domain[7:]
    elif domain.startswith("https://"):
        domain = domain[8:]
    if "/" in domain:
        domain = domain.split("/")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    parts = domain.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else domain


def core_form(name):
    """Sorted normalized tokens, useful for substring checks."""
    norm = normalize_name(name)
    return "".join(sorted(norm.split()))


def is_match(exhibitor_norm, result_norm):
    """Return True only when the result is clearly the same company."""
    if not exhibitor_norm or not result_norm:
        return False

    if exhibitor_norm == result_norm:
        return True

    if exhibitor_norm in result_norm or result_norm in exhibitor_norm:
        shorter = (
            exhibitor_norm if len(exhibitor_norm) <= len(result_norm) else result_norm
        )
        if len(shorter.replace(" ", "")) >= 5:
            return True

    ex_first = first_significant_token(exhibitor_norm, min_len=4)
    res_first = first_significant_token(result_norm, min_len=4)
    if ex_first and ex_first == res_first:
        return True

    pre_a = alphanumeric_prefix(exhibitor_norm, 6)
    pre_b = alphanumeric_prefix(result_norm, 6)
    if pre_a and pre_a == pre_b and len(pre_a) >= 6:
        return True

    return False


def domain_sanity_check(exhibitor_name, domain):
    """Reject matches where the domain root is unrelated to the exhibitor name."""
    if not domain:
        return False

    ex_norm = normalize_name(exhibitor_name)
    sig = first_significant_token(ex_norm, min_len=4)
    if not sig:
        return False

    root = domain_root(domain)
    if len(root) < 4:
        return False

    core = core_form(exhibitor_name)
    root_tokens = set(re.split(r"[^a-z0-9]", root))
    if sig == root or root in core or (len(sig) >= 5 and sig in root_tokens):
        return True

    return False


def pick_match(exhibitor_name, results):
    """Pick the best-matching result domain, or None when uncertain."""
    exhibitor_norm = normalize_name(exhibitor_name)
    if not exhibitor_norm:
        return None

    for result in results:
        result_name = result.get("name", "")
        result_domain = result.get("domain", "")
        if not result_name or not result_domain:
            continue

        result_norm = normalize_name(result_name)
        if not result_norm:
            continue

        if is_match(exhibitor_norm, result_norm):
            if domain_sanity_check(exhibitor_name, result_domain):
                return result_domain

    return None


def api_lookup(company_name):
    """Query the search API and return a list of result dicts, or [] on failure."""
    query = company_name.strip()
    if "|" in query:
        query = query.split("|")[-1].strip()

    url = API_URL_BASE + urllib.parse.quote(query)
    headers = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        ),
    }
    req = urllib.request.Request(url, headers=headers)

    with _API_SEM:
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data.get("results", [])
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    if attempt < 4:
                        sleep_seconds = 2**attempt  # 1, 2, 4, 8
                        time.sleep(sleep_seconds)
                        continue
                    print(
                        f"  Rate-limited for '{company_name}' after retries, leaving blank.",
                        flush=True,
                    )
                    return []
                # Other HTTP errors: retry once after 1s, then blank.
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                print(f"  HTTP error for '{company_name}': {e}", flush=True)
                return []
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                # Retry once after 1s, then blank.
                if attempt == 0:
                    print(f"  Retry for '{company_name}' after error: {e}", flush=True)
                    time.sleep(1.0)
                    continue
                print(f"  Failed for '{company_name}' after retries: {e}", flush=True)
                return []

    return []


def process_company(company_name):
    """Run the API lookup, pick a match, and return (company, website)."""
    results = api_lookup(company_name)
    domain = pick_match(company_name, results)
    website = f"https://{domain}" if domain else ""
    return company_name, website


def load_checkpoint():
    if os.path.exists(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_checkpoint(checkpoint):
    tmp = CHECKPOINT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CHECKPOINT_PATH)


def main():
    start_time = time.time()

    exhibitors = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if not row:
                continue
            name = row[0]
            logo = row[1] if len(row) > 1 else ""
            exhibitors.append((name, logo))

    total = len(exhibitors)
    print(f"Loaded {total} exhibitors from {CSV_PATH}", flush=True)

    checkpoint = load_checkpoint()
    print(f"Checkpoint has {len(checkpoint)} resolved companies", flush=True)

    lock = Lock()
    completions_since_save = 0

    unresolved = [
        (company, logo) for company, logo in exhibitors if company not in checkpoint
    ]
    print(f"Unresolved companies to process: {len(unresolved)}", flush=True)

    def handle_result(company, website):
        nonlocal completions_since_save
        with lock:
            checkpoint[company] = website
            completions_since_save += 1
            if completions_since_save >= CHECKPOINT_EVERY:
                save_checkpoint(checkpoint)
                completions_since_save = 0
                print(f"Checkpoint saved ({len(checkpoint)} resolved)", flush=True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_company = {
            executor.submit(process_company, company): company
            for company, logo in unresolved
        }

        for future in as_completed(future_to_company):
            company, website = future.result()
            handle_result(company, website)

    # Final checkpoint save under lock.
    with lock:
        save_checkpoint(checkpoint)

    # Write output CSV from complete checkpoint.
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["Company Name", "Logo URL", "Website URL"])
        for company, logo in exhibitors:
            writer.writerow([company, logo, checkpoint.get(company, "")])

    matched_count = sum(1 for v in checkpoint.values() if v)
    no_match_count = sum(1 for v in checkpoint.values() if not v)

    elapsed = time.time() - start_time
    print(f"\nDone.", flush=True)
    print(f"Total companies: {total}", flush=True)
    print(f"Matched: {matched_count}", flush=True)
    print(f"No-match: {no_match_count}", flush=True)
    print(f"Time taken: {elapsed:.1f}s", flush=True)
    print(f"Output: {CSV_PATH}", flush=True)

    # Quality checks.
    checks = {
        "ACES": "",
        "AWS": "",
        "ALT": "",
        "10Pearls": "https://10pearls.com",
        "Accenture Saudi Arabia Limited": "https://accenture.com",
    }
    print("\nVerification:", flush=True)
    for company, expected in checks.items():
        actual = checkpoint.get(company, "")
        status = "OK" if actual == expected else "FAIL"
        print(
            f"  {status}: {company} -> {actual!r} (expected {expected!r})", flush=True
        )

    zain_value = checkpoint.get("Zain KSA", "")
    if zain_value and "zain" in zain_value.lower():
        print(f"  OK: Zain KSA -> {zain_value!r}", flush=True)
    else:
        print(
            f"  FAIL: Zain KSA -> {zain_value!r} (expected a zain domain)", flush=True
        )

    matched = [(c, v) for c, v in checkpoint.items() if v]
    if matched:
        print("\n10 random matched samples:", flush=True)
        for c, v in random.sample(matched, min(10, len(matched))):
            print(f"  {c} -> {v}", flush=True)


if __name__ == "__main__":
    main()
