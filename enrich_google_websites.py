#!/usr/bin/env python3
"""
Fill missing Website URLs in the OGL exhibitors CSV by searching Google
via the pinchtab headless-browser CLI. Pure stdlib.
"""

import csv
import json
import os
import re
import subprocess
import time
import urllib.parse
from urllib.parse import urlparse

CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "onegiantleap_2026_exhibitors.csv"
)
CHECKPOINT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".google_website_checkpoint.json"
)
SLEEP_AFTER_NAV = 2
SLEEP_LONG = 4
RATE_LIMIT_STREAK_THRESHOLD = 5

IGNORED_DOMAINS = [
    "google.",
    "gstatic",
    "googleapis",
    "duckduckgo.com",
    "wikipedia.org",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "play.google.com",
    "apps.apple.com",
    "crunchbase.com",
    "bloomberg.com",
    "zoominfo.com",
    "connect.onegiantleap",
    "onegiantleap.com",
]

SUFFIXES_REMOVAL = re.compile(
    r"\b(inc|llc|ltd|co|company|group|gmbh|pte|fzc|fz\s*llc|s\.?a\.?|llp|plc|corp|corporation|international|technologies|solutions|systems)\b",
    re.I,
)


def normalize_name(name: str) -> str:
    # Use English part after pipe for bilingual names
    if "|" in name:
        parts = [p.strip() for p in name.split("|")]
        # Prefer the ASCII/Latin part
        for p in parts:
            if any("a" <= ch.lower() <= "z" for ch in p):
                name = p
                break
        else:
            name = parts[-1]
    # Strip parenthetical translations too
    name = re.sub(r"\([^)]*\)", "", name)
    name = SUFFIXES_REMOVAL.sub("", name)
    # Keep alphanumerics and spaces, then collapse spaces
    name = re.sub(r"[^a-zA-Z0-9\s]", "", name)
    name = re.sub(r"\s+", "", name).lower()
    return name


def is_arabic(name: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" or "\u0750" <= ch <= "\u077f" for ch in name)


def domain_root(domain: str) -> str:
    # Domain is already lowercased and stripped of leading www. by caller
    parts = domain.split(".")
    if parts[0] == "www":
        parts = parts[1:]
    # Root is the part immediately before the TLD
    if len(parts) >= 2:
        root = parts[-2]
    else:
        root = domain
    # Remove leading 'www' if any and digits-only prefixes
    root = root.lstrip("www")
    return root


def tld(domain: str) -> str:
    parts = domain.split(".")
    return parts[-1] if parts else ""


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    netloc = parsed.netloc
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return f"https://{netloc.lower()}"


def url_domain(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def validate_candidate(url: str, company: str) -> bool:
    url_lower = url.lower()
    if any(b in url_lower for b in IGNORED_DOMAINS):
        return False
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not domain:
            return False
    except Exception:
        return False

    # Pure Arabic: accept first clean result that is not a search engine/social
    if is_arabic(company):
        if (
            domain
            and "." in domain
            and not any(b in domain for b in ["google", "duckduckgo", "wikipedia"])
        ):
            return True
        return False

    root = domain_root(domain)
    if not root or len(root) < 3:
        return False

    norm_company = normalize_name(company)
    if not norm_company:
        # Fallback for weird non-Arabic/non-ASCII names: accept reasonably clean domain
        return "." in domain and len(domain.split(".")[0]) >= 3

    root_norm = re.sub(r"[^a-z0-9]", "", root)
    if root_norm in norm_company:
        return True
    if len(norm_company) >= 4 and norm_company[:4] in root_norm:
        return True
    # Also allow if the company normalized name (without vowels maybe) is close
    # e.g. "Athek Information Technology" -> atek vs atek
    if len(norm_company) >= 5:
        for i in range(len(norm_company) - 3):
            chunk = norm_company[i : i + 4]
            if len(chunk) >= 4 and chunk in root_norm:
                return True
    return False


def extract_urls(snap_output: str) -> list:
    urls = re.findall(
        r"https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}[^ \"\)\]\>\n]*", snap_output, re.I
    )
    # Normalize/clean trailing punctuation and fragments
    cleaned = []
    for u in urls:
        u = re.sub(r"[)\]\>\"]+$", "", u)
        if u.endswith(".") or u.endswith(","):
            u = u[:-1]
        cleaned.append(u)
    # Filter out ignored hosts and de-dupe preserving order
    seen = set()
    filtered = []
    for u in cleaned:
        low = u.lower()
        if any(b in low for b in IGNORED_DOMAINS):
            continue
        if u in seen:
            continue
        seen.add(u)
        filtered.append(u)
    return filtered


def pinchtab(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["pinchtab"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_search(company: str, use_google: bool = True) -> list:
    query = company + (" official website" if use_google else " official website")
    if use_google:
        full = "!g " + query
    else:
        full = query
    encoded = urllib.parse.quote(full)
    url = f"https://duckduckgo.com/?q={encoded}"

    try:
        r = pinchtab(["nav", url], timeout=30)
    except Exception as e:
        print(f"    nav error for '{company}': {e}")
        return []

    time.sleep(SLEEP_AFTER_NAV)

    # Try snap a couple of times
    candidates = []
    for attempt in range(2):
        try:
            snap = pinchtab(["snap"], timeout=15)
            urls = extract_urls(snap.stdout)
            if urls:
                candidates = urls
                break
        except Exception as e:
            print(f"    snap error for '{company}' attempt {attempt}: {e}")
        time.sleep(2)

    if not candidates:
        # Fallback to text extraction
        try:
            text = pinchtab(["text"], timeout=15)
            urls = extract_urls(text.stdout)
            if urls:
                candidates = urls
        except Exception as e:
            print(f"    text error for '{company}': {e}")

    if not candidates and use_google:
        # Try plain company name without "official website"
        return run_search(company, use_google=False)

    return candidates


def choose_url(company: str, rate_limit_streak: int) -> tuple:
    """Return (url, rate_limited)."""
    use_google = rate_limit_streak < RATE_LIMIT_STREAK_THRESHOLD
    candidates = run_search(company, use_google=use_google)

    # Detect rate limiting: too few candidates or duckduckgo-only
    if not candidates or all(
        "duckduckgo.com" in u.lower() or "google.com" in u.lower() for u in candidates
    ):
        # Likely interstitial/rate-limit
        return None, True

    for url in candidates[:3]:
        if validate_candidate(url, company):
            return normalize_url(url), False

    # If no candidate validates, return blank but not rate-limited
    return "", False


def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_checkpoint(checkpoint: dict) -> None:
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)


def main() -> None:
    start_time = time.time()

    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    header = rows[0]
    data_rows = rows[1:]
    total_rows = len(data_rows)

    # Find companies with missing website and not already in checkpoint
    checkpoint = load_checkpoint()
    todo = []
    for idx, row in enumerate(data_rows):
        if len(row) <= 2:
            continue
        name = row[0].strip()
        website = row[2].strip() if len(row) > 2 else ""
        if not website and name and name not in checkpoint:
            todo.append((idx, name))

    total_todo = len(todo)
    print(f"Rows in CSV: {total_rows}")
    print(
        f"Missing website: {total_rows - sum(1 for r in data_rows if len(r) > 2 and r[2].strip())}"
    )
    print(f"Already resolved (checkpoint): {len(checkpoint)}")
    print(f"To process now: {total_todo}")

    matched = 0
    blank = 0
    rate_limit_streak = 0
    example_matches = []
    example_blanks = []

    for i, (idx, name) in enumerate(todo, start=1):
        try:
            result, rate_limited = choose_url(name, rate_limit_streak)
        except Exception as e:
            print(f"ERROR processing '{name}': {e}")
            result = ""
            rate_limited = False

        if result is None:
            # Rate limited
            rate_limit_streak += 1
            result = ""
            print(f"    Rate limit streak: {rate_limit_streak}")
        else:
            rate_limit_streak = 0

        if result:
            matched += 1
            if len(example_matches) < 5:
                example_matches.append((name, result))
        else:
            blank += 1
            if len(example_blanks) < 5:
                example_blanks.append(name)

        checkpoint[name] = result
        save_checkpoint(checkpoint)
        data_rows[idx][2] = result

        if i % 20 == 0 or i == total_todo:
            print(
                f"{i}/{total_todo} - {name} -> {result or '(blank)'} (matched: {matched}, blank: {blank})"
            )

        # Pace requests
        if rate_limit_streak > 0:
            time.sleep(SLEEP_LONG)
        else:
            time.sleep(1)

    # Write CSV back
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(data_rows)

    elapsed = time.time() - start_time
    print("\n=== Summary ===")
    print(f"Total processed this run: {total_todo}")
    print(f"Matched: {matched}")
    print(f"Blank: {blank}")
    print(f"Time: {elapsed / 60:.1f} minutes")
    print("\nExample matches:")
    for name, url in example_matches:
        print(f"  {name} -> {url}")
    print("\nExample blanks:")
    for name in example_blanks:
        print(f"  {name}")


if __name__ == "__main__":
    main()
