#!/usr/bin/env bash
set -euo pipefail

# LEAP 2026 exhibitor data pipeline.
# Runs all four stages in order. Each stage is resumable.
# Usage: ./run_pipeline.sh

cd "$(dirname "$0")"

echo "=========================================="
echo "  LEAP 2026 Exhibitor Data Pipeline"
echo "=========================================="
echo

# --- Stage 1: Scrape exhibitor names + logos from Drupal ---
echo "[1/4] Scraping exhibitor names + logos from Drupal..."
python3 scrape_leap_exhibitors.py
echo

# --- Stage 2: Website lookup via Exhibitly company-search ---
echo "[2/4] Looking up websites via Exhibitly company-search API..."
python3 enrich_exhibitors_websites.py
echo

# --- Stage 3: Swapcard GraphQL enrichment (booth, country, industry, etc.) ---
echo "[3/4] Enriching with Swapcard GraphQL data..."
python3 enrich_swapcard.py
echo

# --- Stage 4: Google search for remaining missing websites ---
echo "[4/4] Filling remaining gaps via Google search (pinchtab)..."
if command -v pinchtab &>/dev/null; then
	if pinchtab health &>/dev/null; then
		python3 enrich_google_websites.py
	else
		echo "  pinchtab server not running. Start it with: pinchtab server &"
		echo "  Skipping stage 4. Run it manually after starting pinchtab."
	fi
else
	echo "  pinchtab not installed. Skipping stage 4."
	echo "  Install: brew install pinchtab"
fi
echo

echo "=========================================="
echo "  Pipeline complete."
echo "  Output: onegiantleap_2026_exhibitors.csv"
echo "=========================================="
