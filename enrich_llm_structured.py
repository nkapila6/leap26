#!/usr/bin/env python3
"""Extract structured fields (country, industry, founding year, employees) from company websites using opencode run.

For each company that has a website but is missing structured fields, calls opencode run
with the company's website URL and verified description, asking the LLM to fetch the website
and extract the missing fields. Multithreaded with ThreadPoolExecutor.
"""

import csv
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

CSV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "onegiantleap_2026_exhibitors.csv"
)
CHECKPOINT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".llm_structured_checkpoint.json"
)
MAX_WORKERS = 10
MODEL = "ollama-cloud/deepseek-v4-flash"
TIMEOUT = 120

# Fields we can extract from a company website
EXTRACT_FIELDS = ["country", "industry", "founding_year", "employees"]

PROMPT_TEMPLATE = """You are extracting structured data about a LEAP 2026 tech conference exhibitor by visiting their website.

Company: "{name}"
Website: "{website}"
What they do: "{desc}"

Fetch the website URL above (and its about/team page if needed). Extract these fields:
1. country: The country where the company is headquartered (just the country name, e.g. "Saudi Arabia")
2. industry: The company's primary industry (e.g. "Technology, Software and IT Services", "Financial Services", "Healthcare", "Manufacturing", "Telecommunications", "Education", "Retail", "Energy", "Media", "Real Estate", "Automotive", "Logistics", "Construction")
3. founding_year: The year the company was founded (4-digit year, e.g. "2004"). If not found, leave empty.
4. employees: Employee count or range (e.g. "1-5", "51-99", "500+", "1000+"). If not found, leave empty.

Rules:
- Only provide values you found on the website or can confidently infer. Do NOT fabricate.
- If a field cannot be determined, use empty string "".
- For industry, use a broad category, not a marketing tagline.

Respond ONLY with this JSON and nothing else:
{{"country": "...", "industry": "...", "founding_year": "...", "employees": "..."}}"""


def call_llm(name, website, desc):
    prompt = PROMPT_TEMPLATE.format(name=name, website=website, desc=desc[:300])
    try:
        result = subprocess.run(
            ["opencode", "run", "-m", MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {
            "country": "",
            "industry": "",
            "founding_year": "",
            "employees": "",
            "error": "timeout",
        }
    except Exception as e:
        return {
            "country": "",
            "industry": "",
            "founding_year": "",
            "employees": "",
            "error": str(e),
        }

    # Find JSON with the expected fields
    matches = re.findall(
        r'\{[^{}]*"country"[^{}]*"industry"[^{}]*\}',
        output,
        re.S,
    )
    if not matches:
        matches = re.findall(r'\{.*?"country".*?"industry".*?\}', output, re.S)

    if matches:
        try:
            obj = json.loads(matches[-1])
            return {
                "country": obj.get("country", "").strip(),
                "industry": obj.get("industry", "").strip(),
                "founding_year": obj.get("founding_year", "").strip(),
                "employees": obj.get("employees", "").strip(),
            }
        except json.JSONDecodeError:
            pass

    return {
        "country": "",
        "industry": "",
        "founding_year": "",
        "employees": "",
        "error": "no_json",
    }


def load_checkpoint():
    if os.path.exists(CHECKPOINT):
        try:
            return json.load(open(CHECKPOINT, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_checkpoint(cp):
    tmp = CHECKPOINT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CHECKPOINT)


def main():
    rows = list(csv.reader(open(CSV_PATH, encoding="utf-8")))
    header = rows[0]
    data = rows[1:]

    name_idx = header.index("Company Name")
    web_idx = header.index("Website URL")
    desc_idx = header.index("Description")

    # Fields to check for gaps
    field_indices = {
        "Country": header.index("Country"),
        "Company Industry": header.index("Company Industry"),
        "Founding Year": header.index("Founding Year"),
        "Number of Employees": header.index("Number of Employees"),
    }

    cp = load_checkpoint()
    print(f"Checkpoint: {len(cp)} companies already processed")

    # Find companies that have a website but are missing at least one structured field
    todo = []
    for r in data:
        name = r[name_idx].strip()
        website = r[web_idx].strip()
        if not name or not website or name in cp:
            continue
        # Check if any of the 4 target fields are missing
        missing = [f for f, idx in field_indices.items() if not r[idx].strip()]
        if missing:
            desc = r[desc_idx].strip()
            todo.append((name, website, desc))

    total = len(todo)
    print(f"To process: {total} (companies with website but missing structured fields)")
    print(f"Workers: {MAX_WORKERS}")
    print()

    processed = 0
    filled_any = 0
    errors = 0
    save_counter = 0
    t0 = time.time()

    def process_one(item):
        name, website, desc = item
        result = call_llm(name, website, desc)
        return name, result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_one, item): item for item in todo}

        for future in as_completed(futures):
            name, result = future.result()
            processed += 1

            has_any = any(result.get(k) for k in EXTRACT_FIELDS)
            if has_any:
                filled_any += 1
            if result.get("error"):
                errors += 1

            cp[name] = result
            save_counter += 1

            if save_counter >= 10:
                save_checkpoint(cp)
                save_counter = 0

            if processed % 20 == 0 or processed == total:
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (total - processed) / rate / 60 if rate > 0 else 0
                country = result.get("country", "")
                industry = result.get("industry", "")[:20]
                yr = result.get("founding_year", "")
                emp = result.get("employees", "")
                print(
                    f"  {processed}/{total} {name[:30]:30} "
                    f"co={country:15} ind={industry:20} yr={yr:5} emp={emp:10} "
                    f"({elapsed:.0f}s, eta {eta:.0f}min)"
                )

    save_checkpoint(cp)

    # Update CSV
    print("\nUpdating CSV...")
    field_map = {
        "country": "Country",
        "industry": "Company Industry",
        "founding_year": "Founding Year",
        "employees": "Number of Employees",
    }

    updated = {f: 0 for f in field_map.values()}
    for r in data:
        name = r[name_idx]
        if name not in cp:
            continue
        entry = cp[name]
        for llm_key, csv_col in field_map.items():
            idx = header.index(csv_col)
            val = entry.get(llm_key, "").strip()
            if val and not r[idx].strip():
                r[idx] = val
                updated[csv_col] += 1

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed / 60:.1f} min")
    print(f"  Processed: {processed}")
    print(f"  Filled at least one field: {filled_any}")
    print(f"  Errors: {errors}")
    print(f"  Fields updated:")
    for col, count in updated.items():
        print(f"    {col:25} +{count}")
    print(f"  Output: {CSV_PATH}")


if __name__ == "__main__":
    main()
