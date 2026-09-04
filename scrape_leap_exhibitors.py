#!/usr/bin/env python3
"""Scrape One Giant Leap 2026 exhibitors from Drupal AJAX endpoint."""

import csv
import html
import json
import os
import re
import time
import urllib.request
import urllib.parse

BASE_URL = "https://onegiantleap.com"
AJAX_URL = f"{BASE_URL}/views/ajax"
REFERER = "https://onegiantleap.com/exhibit/our-2026-exhibitors"
VIEW_DOM_ID = "9ce6531029e58467d5839b1ed4df01e10137fb413d9e8362e29e6970523dcda1"
SELECTOR_NEEDLE = f"js-view-dom-id-{VIEW_DOM_ID[:11]}"
PLACEHOLDER_LOGO = "/themes/custom/sass_theme/images/exhibitor-logo.png"


def fetch_page(page_num):
    """Fetch a single page via Drupal AJAX. Returns the HTML data string or None."""
    url = f"{AJAX_URL}?page={page_num}"
    body = urllib.parse.urlencode(
        {
            "view_name": "swapcard_exhibitors_page",
            "view_display_id": "block_2",
            "view_args": "",
            "view_path": "/node/13904",
            "view_base_path": "null",
            "view_dom_id": VIEW_DOM_ID,
        }
    )

    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": REFERER,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    }

    req = urllib.request.Request(
        url, data=body.encode("utf-8"), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")

    data = json.loads(raw)
    for command in data:
        if command.get("command") == "insert" and command.get("data"):
            selector = command.get("selector", "")
            if SELECTOR_NEEDLE in selector:
                return command["data"]
    return None


def parse_exhibitors(html_data):
    """Parse exhibitor cards from page HTML. Returns list of (company, logo_url)."""
    exhibitors = []

    # Split on card start marker to avoid regex catastrophic backtracking.
    parts = re.split(r'<div class="exhibutors-card-sec">', html_data)
    for chunk in parts[1:]:
        # The card ends at first closing </div></div></div></div> sequence.
        card = chunk.split("</div>\n</div>\n</div>\n</div>")[0]

        # Company name - use the title span specifically.
        title_match = re.search(
            r'<div class="views-field views-field-title">\s*<span class="field-content">(.*?)</span>',
            card,
            re.DOTALL,
        )
        if not title_match:
            continue
        company = html.unescape(title_match.group(1).strip())

        # Logo URL - only look inside the views-field-nothing container.
        nothing_match = re.search(
            r'<div class="views-field views-field-nothing">\s*<span class="field-content">(.*?)</span>',
            card,
            re.DOTALL,
        )
        logo_url = ""
        if nothing_match:
            nothing_html = nothing_match.group(1)
            logo_match = re.search(r'<img[^>]*src="([^"]+)"', nothing_html)
            if logo_match:
                raw_src = logo_match.group(1).strip()
                if raw_src and raw_src != PLACEHOLDER_LOGO:
                    if raw_src.startswith("https://") or raw_src.startswith("http://"):
                        logo_url = raw_src
                    elif raw_src.startswith("//"):
                        logo_url = f"https:{raw_src}"
                    elif raw_src.startswith("/"):
                        logo_url = f"{BASE_URL}{raw_src}"
                    else:
                        logo_url = f"{BASE_URL}/{raw_src}"

        exhibitors.append((company, logo_url))

    return exhibitors


def main():
    all_exhibitors = []  # ordered list of (company, logo_url)
    seen = set()
    page = 0

    while True:
        try:
            html_data = fetch_page(page)
        except Exception as e:
            print(f"Page {page}: error fetching: {e}")
            break

        if html_data is None:
            print(f"Page {page}: no insert command found; stopping.")
            break

        page_exhibitors = parse_exhibitors(html_data)

        # Deduplicate per page while preserving order.
        new_count = 0
        for company, logo in page_exhibitors:
            key = company.lower().strip()
            if key not in seen:
                seen.add(key)
                all_exhibitors.append((company, logo))
                new_count += 1

        print(
            f"Page {page}: found {len(page_exhibitors)} exhibitors (total so far: {len(all_exhibitors)})"
        )

        if len(page_exhibitors) == 0:
            break

        page += 1
        time.sleep(0.5)

    csv_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "onegiantleap_2026_exhibitors.csv"
    )
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Company Name", "Logo URL"])
        writer.writerows(all_exhibitors)

    print(f"\nDone. Wrote {len(all_exhibitors)} unique exhibitors to {csv_path}")
    print(f"Pages fetched: {page + 1}")
    print("\nFirst 5:")
    for name, _ in all_exhibitors[:5]:
        print(f"  {name}")
    print("\nLast 5:")
    for name, _ in all_exhibitors[-5:]:
        print(f"  {name}")


if __name__ == "__main__":
    main()
