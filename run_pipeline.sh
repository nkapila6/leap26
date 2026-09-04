#!/usr/bin/env bash
set -euo pipefail

# LEAP 2026 exhibitor data pipeline.
# Runs all stages end-to-end. Each stage is resumable via checkpoints.
# Usage: ./run_pipeline.sh [--skip-llm]
#   --skip-llm  skip the LLM enrichment stages (5-6) which take ~2 hours

cd "$(dirname "$0")"

SKIP_LLM=false
if [[ "${1:-}" == "--skip-llm" ]]; then
	SKIP_LLM=true
fi

echo "=========================================="
echo "  LEAP 2026 Exhibitor Data Pipeline"
echo "=========================================="
if [ "$SKIP_LLM" = true ]; then
	echo "  (LLM stages skipped)"
fi
echo

# --- Stage 1: Scrape exhibitor names + logos from Drupal ---
echo "[1/8] Scraping exhibitor names + logos from Drupal..."
uv run python scrape_leap_exhibitors.py
echo

# --- Stage 2: Website lookup via Exhibitly company-search ---
echo "[2/8] Looking up websites via Exhibitly company-search API..."
uv run python enrich_exhibitors_websites.py
echo

# --- Stage 3: Swapcard GraphQL enrichment (booth, country, industry, etc.) ---
echo "[3/8] Enriching with Swapcard GraphQL data..."
uv run python enrich_swapcard.py
echo

# --- Stage 4: Firecrawl search (website, LinkedIn, Instagram, description gaps) ---
echo "[4/8] Filling gaps via Firecrawl search API..."
uv run python enrich_ddgs.py
echo

# --- Stage 5: LLM verification (descriptions, category, is_ai) ---
if [ "$SKIP_LLM" = false ]; then
	echo "[5/8] Verifying descriptions + classifying companies via LLM..."
	if command -v opencode &>/dev/null; then
		uv run python enrich_llm.py
	else
		echo "  opencode not installed. Skipping LLM stage 5."
		echo "  Install: https://github.com/nkapila6/opencode"
	fi
	echo
else
	echo "[5/8] Skipped (--skip-llm)"
	echo
fi

# --- Stage 6: LLM structured field extraction (country, industry, founding year, employees) ---
if [ "$SKIP_LLM" = false ]; then
	echo "[6/8] Extracting structured fields from company websites via LLM..."
	if command -v opencode &>/dev/null; then
		uv run python enrich_llm_structured.py
	else
		echo "  opencode not installed. Skipping LLM stage 6."
	fi
	echo
else
	echo "[6/8] Skipped (--skip-llm)"
	echo
fi

# --- Stage 7: Analysis + charts ---
echo "[7/8] Generating analysis and charts..."
uv run python analyze.py
echo

# --- Stage 8: Build dashboard data ---
echo "[8/8] Building dashboard data (data.json)..."
uv run python -c "
import csv, json
rows = list(csv.reader(open('onegiantleap_2026_exhibitors.csv', encoding='utf-8')))
header = rows[0]
data = rows[1:]
records = []
for r in data:
    records.append({
        'name': r[0], 'logo': r[1], 'website': r[2], 'type': r[3],
        'booth': r[4], 'country': r[5], 'industry': r[6], 'sector': r[7],
        'region': r[8], 'funding': r[9], 'biz_type': r[10], 'founded': r[11],
        'employees': r[12], 'linkedin': r[13], 'instagram': r[14],
        'description': r[15], 'category': r[16],
        'is_ai': r[17].lower() == 'true'
    })
json.dump(records, open('data.json', 'w', encoding='utf-8'), ensure_ascii=False)
print(f'  data.json: {len(records)} records')
"
echo

echo "=========================================="
echo "  Pipeline complete."
echo
echo "  Output:"
echo "    onegiantleap_2026_exhibitors.csv  ($ (wc -l < onegiantleap_2026_exhibitors.csv) rows)"
echo "    charts/                          ($(ls charts/*.png 2>/dev/null | wc -l | tr -d ' ') charts)"
echo "    data.json                        (dashboard data)"
echo "    index.html                       (dashboard)"
echo
echo "  View dashboard: open index.html"
echo "  Or deploy: https://nkapila6.github.io/leap26/"
echo "=========================================="
