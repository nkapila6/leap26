# LEAP 2026 Exhibitors

Scraped and enriched exhibitor data for LEAP x DeepFest 2026 (Aug 31 - Sep 3, Riyadh).

## What's in the CSV

`onegiantleap_2026_exhibitors.csv` - 1,495 exhibitors, 18 columns:

| Column | Source | Coverage |
|---|---|---|
| Company Name | Drupal | 100% |
| Logo URL | Drupal | 69% |
| Website URL | Exhibitly + Firecrawl | 94% |
| Type (Exhibitor/Startup) | Swapcard GraphQL | 65% |
| Booth | Swapcard GraphQL | 65% |
| Country | Swapcard + LLM web extraction | 88% |
| Company Industry | Swapcard + LLM web extraction | 88% |
| Sector(s) | Swapcard GraphQL | 10% |
| Region(s) | Swapcard GraphQL | 33% |
| Funding Stage | Swapcard GraphQL | 15% |
| Business type | Swapcard GraphQL | 30% |
| Founding Year | Swapcard + LLM web extraction | 52% |
| Number of Employees | Swapcard + LLM web extraction | 40% |
| LinkedIn | Swapcard + Firecrawl | 32% |
| Instagram | Swapcard + Firecrawl | 23% |
| Description | Swapcard + LLM verification | 96% |
| Category | LLM classification | 94% |
| Is_AI | LLM classification | 100% |

## Pipeline

Run `./run_pipeline.sh` for the base pipeline. The LLM enrichment scripts run separately (they take 1-2 hours each).

| Stage | Script | What it does | Time |
|---|---|---|---|
| 1. Scrape | `scrape_leap_exhibitors.py` | Fetches all exhibitor names + logos from Drupal AJAX endpoint (16 pages of 300) | ~30s |
| 2. Website lookup | `enrich_exhibitors_websites.py` | Queries Exhibitly company-search API for domains (20 threads) | ~10 min |
| 3. Swapcard | `enrich_swapcard.py` | Calls Swapcard GraphQL for booth, country, industry, social, description (10 threads) | ~1 min |
| 4. Firecrawl | `enrich_ddgs.py` | Firecrawl search API to fill remaining website/LinkedIn/Instagram/description gaps (10 threads) | ~7 min |
| 5. LLM verify | `enrich_llm.py` | Uses `opencode run` (deepseek-v4-flash with web search) to verify each description and classify company as AI/non-AI with a category tag (6 threads) | ~100 min |
| 6. LLM extract | `enrich_llm_structured.py` | Uses `opencode run` to fetch each company's website and extract country, industry, founding year, employee count (10 threads) | ~57 min |
| -. Google fill | `enrich_google_websites.py` | Optional: pinchtab headless browser for the last ~80 websites Firecrawl couldn't find | ~30 min |

## Data analysis highlights

### What's exhibiting at LEAP 2026?

**Top categories (1,407 classified):**
- Enterprise IT: 314 (21%)
- AI/ML: 138 (9%)
- HealthTech: 64 (4%)
- E-commerce/Retail: 64 (4%)
- FinTech: 61 (4%)
- Manufacturing: 60 (4%)
- Cybersecurity: 56 (3%)
- IoT/Embedded: 55 (3%)
- Data/Analytics: 54 (3%)
- Telecom: 54 (3%)
- EdTech: 52 (3%)
- AdTech/Marketing: 51 (3%)
- Cloud/DevOps: 50 (3%)

**AI vs non-AI:**
- AI companies: 360 (24%)
- Non-AI: 1,135 (75%)

About 1 in 4 exhibitors is an AI-focused company. Enterprise IT is the largest segment.

### Top countries (1,322 with country data)

| Country | Count | % |
|---|---|---|
| Saudi Arabia | 475 | 31% |
| United States | 188 | 12% |
| United Arab Emirates | 75 | 5% |
| India | 53 | 3% |
| United Kingdom | 52 | 3% |
| China | 40 | 2% |
| Pakistan | 31 | 2% |
| Turkey | 31 | 2% |
| Oman | 27 | 1% |

Saudi hosts roughly a third of exhibitors, with the US second at 12%.

### AI companies by category

AI is concentrated in: AI/ML (138), Enterprise IT (36), HealthTech (30), AdTech/Marketing (21), Data/Analytics (19), Robotics (13), EdTech (13).

## Dependencies

- Python 3.10+ (uses `uv` for environment management)
- [opencode](https://github.com/nkapila6/opencode) CLI for LLM enrichment stages 5-6
- [pinchtab](https://github.com/nkapila6/pinchtab) for optional Google search stage
- Internet access

Setup:
```bash
uv sync          # install ddgs dependency
```

## Data sources

| Source | What it provides | Auth |
|---|---|---|
| Drupal AJAX (`onegiantleap.com/views/ajax`) | Company name, logo | None |
| Exhibitly company-search (`exhibitly.onegiantleap.com/api/company-search`) | Website domain | None |
| Swapcard GraphQL (`connect.onegiantleap.com/api/graphql`) | Booth, type, country, industry, social, description | None (persisted queries) |
| Firecrawl search (`api.firecrawl.dev/v2/search`) | Website, LinkedIn, Instagram, description snippets | None (free tier) |
| opencode run (deepseek-v4-flash) | Description verification, category classification, AI flag, structured field extraction from company websites | opencode CLI |

## Notes

- The Drupal page lists 1,495 exhibitors; Swapcard has 998. The 511 difference are on the Drupal site but not in the Swapcard event app.
- All scripts are resumable via checkpoint files (`.json`) - re-running continues from where it left off.
- LLM enrichment uses `opencode run -m ollama-cloud/deepseek-v4-flash` which has built-in web search via WebFetch. Each call fetches the company's website, verifies the description, and extracts structured fields.
- The Swapcard GraphQL persisted query hashes (`sha256Hash`) are tied to specific query versions and may change if Swapcard updates their schema.
- Firecrawl's keyless free tier has a rate limit (~1500 requests). If you hit it, the search stage will fail - get a free API key from firecrawl.dev.