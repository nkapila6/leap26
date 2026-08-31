#!/usr/bin/env python3
"""Fetch all LEAP 2026 exhibitors from Swapcard GraphQL and enrich the local CSV."""

import csv
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Configuration
API_URL = "https://connect.onegiantleap.com/api/graphql"
EVENT_ID = "RXZlbnRfMjc3NzQ3Mw=="
VIEW_ID = "RXZlbnRWaWV3XzEyMTczMTE="
CSV_PATH = "/Users/nkapila6/onegiantleap_2026_exhibitors.csv"
CHECKPOINT_PATH = "/Users/nkapila6/.swapcard_checkpoint.json"
LIST_HASH = "b3cb76208b6de3d96c5ba1a8f02e6be6135d5ff1db0a2eecd64b7d15e7e6b5e2"
DETAIL_HASH = "fe9f995a579b65a3453f7f576cd37bea71539cf7cf12ed9e59eb2a41706c9630"
DETAIL_WORKERS = 10
CHECKPOINT_INTERVAL = 50

HEADERS = {
    "content-type": "application/json",
    "x-client-origin": "connect.onegiantleap.com",
    "x-client-platform": "Event App",
    "x-client-version": "2.310.186",
    "User-Agent": "Mozilla/5.0",
}


def graphql_request(operation_name, sha256_hash, variables):
    """Send a persisted GraphQL request. Retry once after 1s, then raise."""
    payload = {
        "operationName": operation_name,
        "variables": variables,
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha256_hash}},
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(API_URL, data=body, headers=HEADERS, method="POST")

    last_err = None
    for attempt in range(2):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as e:
            last_err = e
            time.sleep(1.0)
        except json.JSONDecodeError as e:
            last_err = e
            time.sleep(1.0)
    raise last_err


def fetch_all_exhibitors():
    """Paginate through the exhibitor list using endCursor."""
    exhibitors = []
    end_cursor = None
    page = 0
    while True:
        page += 1
        variables = {
            "withEvent": True,
            "viewId": VIEW_ID,
            "eventId": EVENT_ID,
            "search": "",
        }
        if end_cursor is not None:
            variables["endCursor"] = end_cursor

        data = graphql_request(
            "EventExhibitorListViewConnectionQuery", LIST_HASH, variables
        )
        view = data.get("data", {}).get("view", {})
        conn = view.get("exhibitors", {})
        nodes = conn.get("nodes", [])
        page_info = conn.get("pageInfo", {})

        for node in nodes:
            exhibitor = {
                "id": node.get("id"),
                "name": node.get("name"),
                "type": node.get("type"),
                "logoUrl": node.get("logoUrl"),
                "booth": (node.get("withEvent") or {}).get("booth"),
            }
            exhibitors.append(exhibitor)

        print(
            f"  list page {page}: got {len(nodes)} exhibitors (total {len(exhibitors)})"
        )

        if not page_info.get("hasNextPage"):
            break
        end_cursor = page_info.get("endCursor")
        if not end_cursor:
            break

    return exhibitors


def extract_field_text(fields, name):
    """Extract a single text value from a custom field."""
    for field in fields:
        if (field.get("definition") or {}).get("name") == name:
            value = field.get("value")
            if value and value.get("text"):
                return value["text"].strip()
            values = field.get("values")
            if values:
                texts = [v.get("text", "").strip() for v in values if v.get("text")]
                return "; ".join(texts)
    return ""


def extract_social_profile(social_networks, network_type):
    """Return the profile URL/handle for a social network type."""
    for network in social_networks or []:
        if network.get("type") == network_type:
            return (network.get("profile") or "").strip()
    return ""


def fetch_exhibitor_detail(exhibitor_id):
    """Fetch detail for one exhibitor and return a flat dict."""
    variables = {
        "withEvent": True,
        "skipMeetings": True,
        "selfUserId": "",
        "withSelfMember": False,
        "exhibitorId": exhibitor_id,
        "eventId": EVENT_ID,
    }
    data = graphql_request("EventExhibitorDetailsViewQuery", DETAIL_HASH, variables)
    exhibitor = (data.get("data") or {}).get("exhibitor") or {}

    with_event = exhibitor.get("withEvent") or {}
    fields = with_event.get("fields") or []
    address = exhibitor.get("address") or {}
    socials = exhibitor.get("socialNetworks") or []

    country_field = extract_field_text(fields, "Country")
    country = country_field or (address.get("country") or "").strip()

    booths = with_event.get("booths") or []
    booth = ""
    if booths and booths[0].get("name"):
        booth = booths[0]["name"].strip()

    return {
        "websiteUrl": (exhibitor.get("websiteUrl") or "").strip(),
        "description": (exhibitor.get("description") or "").strip(),
        "country": country,
        "companyIndustry": extract_field_text(fields, "Company Industry"),
        "sectors": extract_field_text(fields, "Sector(s)"),
        "regions": extract_field_text(fields, "Region(s)"),
        "fundingStage": extract_field_text(fields, "Funding Stage"),
        "businessType": extract_field_text(fields, "Business type"),
        "foundingYear": extract_field_text(fields, "Founding Year"),
        "numberOfEmployees": extract_field_text(fields, "Number of Employees"),
        "booth": booth,
        "linkedin": extract_social_profile(socials, "LINKEDIN"),
        "instagram": extract_social_profile(socials, "INSTAGRAM"),
    }


def normalize_name(name):
    """Lowercase and strip for case-insensitive matching."""
    return (name or "").strip().lower()


def load_checkpoint():
    """Load previously fetched detail results if present."""
    if os.path.exists(CHECKPOINT_PATH):
        try:
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_checkpoint(checkpoint):
    """Write the checkpoint file atomically-ish."""
    tmp = CHECKPOINT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CHECKPOINT_PATH)


def fetch_details_with_checkpoint(exhibitors):
    """Fetch detail for every exhibitor, resuming from checkpoint."""
    checkpoint = load_checkpoint()
    print(f"Loaded checkpoint with {len(checkpoint)} already-fetched exhibitors")

    ids_to_fetch = [
        ex["id"] for ex in exhibitors if ex["id"] and ex["id"] not in checkpoint
    ]
    total = len(exhibitors)

    lock = threading.Lock()
    completed_since_save = 0

    def fetch_one(exhibitor_id):
        nonlocal completed_since_save
        try:
            detail = fetch_exhibitor_detail(exhibitor_id)
        except Exception as e:
            print(f"    Warning: failed to fetch detail for {exhibitor_id}: {e}")
            detail = {}

        with lock:
            checkpoint[exhibitor_id] = detail
            completed_since_save += 1
            if completed_since_save >= CHECKPOINT_INTERVAL:
                save_checkpoint(checkpoint)
                completed_since_save = 0
        return exhibitor_id, detail

    fetched_count = len(checkpoint)
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as executor:
        futures = {executor.submit(fetch_one, eid): eid for eid in ids_to_fetch}
        for future in as_completed(futures):
            eid = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"    Warning: unexpected error for {eid}: {e}")
            fetched_count += 1
            if fetched_count % 100 == 0:
                print(f"Fetched {fetched_count}/{total} exhibitor details")

    # Final save
    save_checkpoint(checkpoint)
    return checkpoint


def clean_html_text(text):
    """Strip basic HTML and unescape entities from a description."""
    if not text:
        return ""
    # Remove <br> variants and paragraphs by replacing with spaces
    text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<\s*p\s*/?\s*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return " ".join(text.split())


def main():
    start = time.time()

    # 1. Read existing CSV
    print("Reading existing CSV...")
    existing_rows = []
    existing_by_name = {}
    with open(CSV_PATH, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_rows.append(row)
            name = normalize_name(row.get("Company Name"))
            if name:
                existing_by_name.setdefault(name, []).append(row)

    print(f"Existing CSV rows: {len(existing_rows)}")

    # 2. Fetch all exhibitors list
    print("Fetching exhibitor list from Swapcard...")
    exhibitors = fetch_all_exhibitors()
    swapcard_count = len(exhibitors)
    print(f"Swapcard exhibitors: {swapcard_count}")

    # Build swapcard lookup by normalized name, keeping only one entry per id.
    seen_ids = set()
    swapcard_by_name = {}
    for ex in exhibitors:
        eid = ex.get("id")
        if not eid or eid in seen_ids:
            continue
        seen_ids.add(eid)
        key = normalize_name(ex.get("name"))
        if key:
            swapcard_by_name.setdefault(key, []).append(ex)

    # 3. Fetch rich details
    print("Fetching exhibitor details...")
    checkpoint = fetch_details_with_checkpoint(exhibitors)

    # 4. Merge with existing CSV
    print("Merging data...")
    output_columns = [
        "Company Name",
        "Logo URL",
        "Website URL",
        "Type",
        "Booth",
        "Country",
        "Company Industry",
        "Sector(s)",
        "Region(s)",
        "Funding Stage",
        "Business type",
        "Founding Year",
        "Number of Employees",
        "LinkedIn",
        "Instagram",
        "Description",
    ]

    matched = 0
    unmatched = 0
    output_rows = []

    for row in existing_rows:
        name = normalize_name(row.get("Company Name"))
        swapcard_entries = swapcard_by_name.get(name, [])

        if not swapcard_entries:
            unmatched += 1
            merged = {
                "Company Name": row.get("Company Name", ""),
                "Logo URL": row.get("Logo URL", ""),
                "Website URL": row.get("Website URL", ""),
                "Type": "",
                "Booth": "",
                "Country": "",
                "Company Industry": "",
                "Sector(s)": "",
                "Region(s)": "",
                "Funding Stage": "",
                "Business type": "",
                "Founding Year": "",
                "Number of Employees": "",
                "LinkedIn": "",
                "Instagram": "",
                "Description": "",
            }
            output_rows.append(merged)
            continue

        # Use the first matching Swapcard entry for this existing row.
        ex = swapcard_entries[0]
        matched += 1
        detail = checkpoint.get(ex.get("id"), {})

        swapcard_website = detail.get("websiteUrl", "")
        existing_website = (row.get("Website URL") or "").strip()
        website = swapcard_website or existing_website

        merged = {
            "Company Name": row.get("Company Name", ""),
            "Logo URL": row.get("Logo URL", ""),
            "Website URL": website,
            "Type": ex.get("type", ""),
            "Booth": detail.get("booth", "") or ex.get("booth", ""),
            "Country": detail.get("country", ""),
            "Company Industry": detail.get("companyIndustry", ""),
            "Sector(s)": detail.get("sectors", ""),
            "Region(s)": detail.get("regions", ""),
            "Funding Stage": detail.get("fundingStage", ""),
            "Business type": detail.get("businessType", ""),
            "Founding Year": detail.get("foundingYear", ""),
            "Number of Employees": detail.get("numberOfEmployees", ""),
            "LinkedIn": detail.get("linkedin", ""),
            "Instagram": detail.get("instagram", ""),
            "Description": clean_html_text(detail.get("description", "")),
        }
        output_rows.append(merged)

    # 5. Write final CSV
    print(f"Writing enriched CSV to {CSV_PATH}...")
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=output_columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(output_rows)

    elapsed = time.time() - start

    # Summary
    print("\n=== Summary ===")
    print(f"Swapcard exhibitor count: {swapcard_count}")
    print(f"CSV row count: {len(output_rows)}")
    print(f"Matched: {matched}")
    print(f"Unmatched: {unmatched}")
    print(f"Time: {elapsed:.1f}s")

    print("\n=== 3 sample enriched rows ===")
    samples = output_rows[:3] if len(output_rows) >= 3 else output_rows
    for i, sample in enumerate(samples, 1):
        print(f"\nSample {i}:")
        for col in output_columns:
            val = sample.get(col, "")
            display = val if len(val) <= 120 else val[:120] + "..."
            print(f"  {col}: {display}")


if __name__ == "__main__":
    main()
