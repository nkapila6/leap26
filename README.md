# LEAP 2026 Exhibitors

Scraped and enriched exhibitor data for LEAP x DeepFest 2026 (Aug 31 - Sep 3, Riyadh).

## What's in the CSV

`onegiantleap_2026_exhibitors.csv` - 1,495 exhibitors, 16 columns:

| Column | Source | Coverage |
|---|---|---|
| Company Name | Drupal exhibitor page | 100% |
| Logo URL | Drupal exhibitor page | 69% |
| Website URL | Exhibitly company-search + Google | 91% |
| Type (Exhibitor/Startup) | Swapcard GraphQL | 65% |
| Booth | Swapcard GraphQL | 65% |
| Country | Swapcard GraphQL | 41% |
| Company Industry | Swapcard GraphQL | 33% |
| Sector(s) | Swapcard GraphQL | 10% |
| Region(s) | Swapcard GraphQL | 33% |
| Funding Stage | Swapcard GraphQL | 15% |
| Business type | Swapcard GraphQL | 30% |
| Founding Year | Swapcard GraphQL | 22% |
| Number of Employees | Swapcard GraphQL | 26% |
| LinkedIn | Swapcard GraphQL | 23% |
| Instagram | Swapcard GraphQL | 11% |
| Description | Swapcard GraphQL | 33% |

## Pipeline

Run `./run_pipeline.sh` to execute the full pipeline. It chains four stages, each depends on the previous output.

| Stage | Script | What it does |
|---|---|---|
| 1. Scrape | `scrape_leap_exhibitors.py` | Fetches all exhibitor names + logos from the Drupal AJAX endpoint (16 pages of 300) |
| 2. Website lookup | `enrich_exhibitors_websites.py` | Queries the Exhibitly company-search API for each company's domain (threaded, 20 workers) |
| 3. Swapcard enrichment | `enrich_swapcard.py` | Calls the Swapcard GraphQL API for booth, country, industry, founding year, employees, LinkedIn, description, etc. |
| 4. Google fill | `enrich_google_websites.py` | Uses pinchtab (headless Chromium) to Google-search the remaining companies missing a website |

All scripts are pure Python stdlib - no pip install needed.

## Dependencies

- Python 3.10+
- [pinchtab](https://github.com/nkapila6/pinchtab) running locally for stage 4 (Google searches via headless browser)
- Internet access

## Data sources

- **Drupal AJAX endpoint** (`onegiantleap.com/views/ajax`) - the public exhibitor list page, returns name + logo
- **Exhibitly company-search API** (`exhibitly.onegiantleap.com/api/company-search`) - domain autocomplete, returns website URL
- **Swapcard GraphQL** (`connect.onegiantleap.com/api/graphql`) - the event app backend, returns full exhibitor profiles (booth, country, industry, social links, description). Public persisted queries, no auth needed.
- **Google search** (via pinchtab headless browser) - fills remaining gaps for companies not found in the above

## Notes

- The Drupal page lists 1,495 exhibitors; Swapcard has 998. The 511 difference are companies on the Drupal site but not in the Swapcard event app - they keep their name/logo/website but have blank Swapcard fields.
- All scripts are resumable via checkpoint files (`.json`) - re-running continues from where it left off.
- The Swapcard GraphQL persisted query hashes (`sha256Hash`) are tied to specific query versions and may change if Swapcard updates their schema.