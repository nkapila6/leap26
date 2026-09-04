#!/usr/bin/env python3
"""Enrich the LEAP 2026 exhibitors CSV using the Firecrawl search API."""

from __future__ import annotations

import csv
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "onegiantleap_2026_exhibitors.csv"
)
CHECKPOINT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".ddgs_checkpoint.json"
)

FIRECRAWL_URL = "https://api.firecrawl.dev/v2/search"
SEARCH_LIMIT = 3

MAX_WORKERS = 10
CHECKPOINT_EVERY = 25
PROGRESS_EVERY = 50

COL_COMPANY = 0
COL_WEBSITE = 2
COL_LINKEDIN = 13
COL_INSTAGRAM = 14
COL_DESCRIPTION = 15

ENRICH_COLS = {
    "website": COL_WEBSITE,
    "linkedin": COL_LINKEDIN,
    "instagram": COL_INSTAGRAM,
    "description": COL_DESCRIPTION,
}

SOCIAL_DOMAINS = {
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "twitter.com",
    "x.com",
    "wikipedia.org",
    "crunchbase.com",
    "bloomberg.com",
    "zoominfo.com",
}

# Used for co.uk / com.au style domain root extraction.
SECOND_LEVEL_DOMAINS = {
    "co",
    "com",
    "org",
    "net",
    "gov",
    "edu",
    "ltd",
    "plc",
    "gmbh",
    "sarl",
    "sa",
    "inc",
    "llc",
}

# Common standalone suffixes to strip when normalising company names.
SUFFIXES = ("inc", "llc", "ltd", "co", "company", "group")

_lock = threading.Lock()
_checkpoint: dict[str, dict[str, str]] = {}
_completed_count = 0
_total_rows = 0


def _normalize(text: str) -> str:
    """Lowercase, keep alphanumerics only, strip common suffixes."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    for suffix in SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _english_name(company: str) -> str:
    """For Arabic/piped names use the English part after '|'."""
    if "|" in company:
        return company.split("|")[-1].strip()
    return company


def _is_social_or_blocked(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    if not host and "://" not in url:
        host = url.split("/")[0].lower()
    return any(blocked in host for blocked in SOCIAL_DOMAINS)


def _domain_root(url: str) -> str | None:
    """Extract the registrable/root domain part (before TLD)."""
    if "://" not in url:
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    host = re.sub(r"^(www\.|m\.)", "", host)
    if not host:
        return None
    parts = host.split(".")
    if len(parts) == 1:
        return parts[0]
    # Handle second-level ccTLDs like example.co.uk -> root is example.
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL_DOMAINS and len(parts[-1]) <= 3:
        root = parts[-3]
    else:
        root = parts[-2]
    return root or None


def _normalize_domain(url: str) -> str | None:
    """Return https://<clean-domain>, stripping path/query/fragment and www."""
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc.lower().split(":")[0]
    netloc = re.sub(r"^(www\.|m\.)", "", netloc)
    if not netloc:
        return None
    return f"https://{netloc}"


def _domain_matches(root: str, company: str) -> bool:
    """Check if domain root relates to the company name."""
    company = _english_name(company)
    comp_norm = _normalize(company)
    root_norm = _normalize(root)
    if not comp_norm or not root_norm or len(root_norm) < 3:
        return False
    if root_norm in comp_norm:
        return True
    if len(root_norm) >= 4 and len(comp_norm) >= 4:
        if comp_norm[:4] == root_norm[:4]:
            return True
    return False


def _firecrawl_search(query: str) -> list[dict[str, str]]:
    """Call the Firecrawl search endpoint; retry once after 2s on failure."""
    body = json.dumps({"query": query, "limit": SEARCH_LIMIT}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    for attempt in range(2):
        try:
            req = urllib.request.Request(
                FIRECRAWL_URL, data=body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, dict):
                return []
            web_data = data.get("data", {}).get("web", [])
            results: list[dict[str, str]] = []
            for item in web_data:
                if not isinstance(item, dict):
                    continue
                results.append(
                    {
                        "url": str(item.get("url", "")).strip(),
                        "title": str(item.get("title", "")).strip(),
                        "description": str(item.get("description", "")).strip(),
                    }
                )
            return results
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            if attempt == 0:
                time.sleep(2)
                continue
            return []
        except json.JSONDecodeError:
            return []


def _extract_website(results: list[dict[str, str]], company: str) -> str | None:
    for r in results:
        url = r.get("url", "")
        if not url or _is_social_or_blocked(url):
            continue
        root = _domain_root(url)
        if root and _domain_matches(root, company):
            return _normalize_domain(url)
    return None


def _extract_linkedin(results: list[dict[str, str]]) -> str | None:
    for r in results:
        url = r.get("url", "")
        m = re.search(r"linkedin\.com/company/([^/?#]+)", url, re.I)
        if m:
            handle = m.group(1).strip("/").lower()
            if handle:
                return handle
    return None


def _extract_instagram(results: list[dict[str, str]]) -> str | None:
    blocked_handles = {"p", "accounts", "explore", "directory"}
    for r in results:
        url = r.get("url", "")
        m = re.search(r"instagram\.com/([^/?#]+)", url, re.I)
        if m:
            handle = m.group(1).strip("/").lower()
            if handle and handle not in blocked_handles:
                return handle
    return None


def _extract_description(results: list[dict[str, str]]) -> str | None:
    for i, r in enumerate(results):
        desc = html.unescape(r.get("description", "")).strip()
        # Skip social/wikipedia for the first result only; use it if nothing else.
        if i == 0 and _is_social_or_blocked(r.get("url", "")):
            continue
        if desc:
            return desc[:500]
    return None


def _load_checkpoint() -> dict[str, dict[str, str]]:
    if not os.path.exists(CHECKPOINT_PATH):
        return {}
    try:
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    migrated: dict[str, dict[str, str]] = {}
    key_map = {
        "Website URL": "website",
        "LinkedIn": "linkedin",
        "Instagram": "instagram",
        "Description": "description",
        # New-style keys already map to themselves.
        "website": "website",
        "linkedin": "linkedin",
        "instagram": "instagram",
        "description": "description",
    }
    for company, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        out: dict[str, str] = {}
        for old_key, new_key in key_map.items():
            value = entry.get(old_key, "")
            if value and new_key not in out:
                out[new_key] = str(value).strip()
        if out:
            migrated[company] = out
    return migrated


def _write_checkpoint() -> None:
    tmp = CHECKPOINT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_checkpoint, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CHECKPOINT_PATH)


def _apply_checkpoint(rows: list[list[str]]) -> int:
    skipped = 0
    for row in rows:
        company = row[COL_COMPANY].strip()
        entry = _checkpoint.get(company, {})
        filled = False
        for key, col in ENRICH_COLS.items():
            value = entry.get(key, "")
            if value and not row[col].strip():
                row[col] = value
                filled = True
        if not any(not row[col].strip() for col in ENRICH_COLS.values()):
            skipped += 1
    return skipped


def _process_company(row: list[str]) -> dict[str, str]:
    """Search once and return newly found non-empty fields."""
    company = row[COL_COMPANY].strip()
    if not company:
        return {}

    needs_website = not row[COL_WEBSITE].strip()
    needs_linkedin = not row[COL_LINKEDIN].strip()
    needs_instagram = not row[COL_INSTAGRAM].strip()
    needs_description = not row[COL_DESCRIPTION].strip()

    if not any([needs_website, needs_linkedin, needs_instagram, needs_description]):
        return {}

    query = f'"{company}" official website'
    results = _firecrawl_search(query)

    found: dict[str, str] = {}

    if needs_website:
        website = _extract_website(results, company)
        if website:
            found["website"] = website

    website_present = (row[COL_WEBSITE].strip() or found.get("website", "")).strip()

    if needs_linkedin:
        linkedin = _extract_linkedin(results)
        if linkedin:
            found["linkedin"] = linkedin

    if needs_instagram and website_present:
        instagram = _extract_instagram(results)
        if instagram:
            found["instagram"] = instagram

    if needs_description:
        description = _extract_description(results)
        if description:
            found["description"] = description

    return found


def _task(row: list[str]) -> dict[str, str]:
    try:
        return _process_company(row)
    except Exception:
        # Never let a single failure kill the worker.
        return {}


def _print_progress(row: list[str]) -> None:
    company = row[COL_COMPANY].strip() or "<unknown>"
    web = "Y" if row[COL_WEBSITE].strip() else "N"
    li = "Y" if row[COL_LINKEDIN].strip() else "N"
    if row[COL_INSTAGRAM].strip():
        ig = "Y"
    elif row[COL_WEBSITE].strip():
        ig = "N"
    else:
        ig = "skip"
    desc = "Y" if row[COL_DESCRIPTION].strip() else "N"
    print(
        f"{_completed_count}/{_total_rows} - {company} (web:{web}, li:{li}, ig:{ig}, desc:{desc})"
    )


def main() -> None:
    global _checkpoint, _completed_count, _total_rows

    if not os.path.exists(CSV_PATH):
        print(f"CSV not found: {CSV_PATH}")
        return

    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    _total_rows = len(rows)

    _checkpoint = _load_checkpoint()
    already_done = _apply_checkpoint(rows)
    print(
        f"Loaded {_total_rows} rows. {already_done} already complete from checkpoint."
    )

    # Build work list: rows that still need at least one allowed field.
    rows_to_process = [
        row for row in rows if any(not row[col].strip() for col in ENRICH_COLS.values())
    ]
    print(f"Processing {len(rows_to_process)} rows with {MAX_WORKERS} workers...")

    start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_task, row): row for row in rows_to_process}

        for future in as_completed(futures):
            row = futures[future]
            found = future.result()

            company = row[COL_COMPANY].strip()

            # Apply found values, but only to blank cells.
            for key, value in found.items():
                col = ENRICH_COLS[key]
                if value and not row[col].strip():
                    row[col] = value

            # Update checkpoint with non-empty discovered values.
            if company:
                entry = _checkpoint.setdefault(company, {})
                for key, value in found.items():
                    if value:
                        entry[key] = value

            with _lock:
                _completed_count += 1
                if _completed_count % CHECKPOINT_EVERY == 0:
                    _write_checkpoint()
                if _completed_count % PROGRESS_EVERY == 0:
                    _print_progress(row)

    _write_checkpoint()

    # Overwrite CSV preserving column order and existing data.
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    elapsed = time.perf_counter() - start

    # Count filled cells per allowed column.
    filled_counts = {name: 0 for name in ENRICH_COLS.keys()}
    enriched_rows: list[list[str]] = []
    for row in rows:
        newly_filled: dict[str, str] = {}
        for key, col in ENRICH_COLS.items():
            value = row[col].strip()
            if value:
                filled_counts[key] += 1
                # We can't know if it was filled this run, but sample rows are useful
                # even if they were already filled.
        if any(row[col].strip() for col in ENRICH_COLS.values()):
            enriched_rows.append(row)

    print("\n=== Final summary ===")
    print(f"Total companies: {len(rows)}")
    print(f"Companies processed this run: {len(rows_to_process)}")
    print(f"Time taken: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
    print("Fields with values (after enrichment):")
    print(f"  Website URL: {filled_counts['website']}")
    print(f"  LinkedIn: {filled_counts['linkedin']}")
    print(f"  Instagram: {filled_counts['instagram']}")
    print(f"  Description: {filled_counts['description']}")

    print("\n=== 5 sample enriched rows ===")
    for row in enriched_rows[:5]:
        print(f"Company: {row[COL_COMPANY]}")
        if row[COL_WEBSITE].strip():
            print(f"  Website URL: {row[COL_WEBSITE]}")
        if row[COL_LINKEDIN].strip():
            print(f"  LinkedIn: {row[COL_LINKEDIN]}")
        if row[COL_INSTAGRAM].strip():
            print(f"  Instagram: {row[COL_INSTAGRAM]}")
        if row[COL_DESCRIPTION].strip():
            desc = row[COL_DESCRIPTION]
            preview = desc[:120] + "..." if len(desc) > 120 else desc
            print(f"  Description: {preview}")
        print()


if __name__ == "__main__":
    main()
