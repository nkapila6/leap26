#!/usr/bin/env python3
"""Verify and enrich exhibitor descriptions + categories using opencode run (LLM with web search).

Processes companies in parallel, calling `opencode run` as a subprocess for each.
Each LLM call searches the web, verifies the description, and returns JSON with
a corrected description, a category tag, and an is_ai flag.
"""

import csv
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

CSV_PATH = os.path.join(os.path.dirname(__file__), "onegiantleap_2026_exhibitors.csv")
CHECKPOINT = os.path.join(os.path.dirname(__file__), ".llm_enrichment.json")
MAX_WORKERS = 6
MODEL = "ollama-cloud/deepseek-v4-flash"
TIMEOUT = 120  # seconds per opencode run call

CATEGORIES = [
    "AI/ML",
    "Cybersecurity",
    "Cloud/DevOps",
    "IoT/Embedded",
    "Enterprise IT",
    "FinTech",
    "HealthTech",
    "EdTech",
    "E-commerce/Retail",
    "AdTech/Marketing",
    "Telecom",
    "Robotics",
    "Data/Analytics",
    "Energy",
    "GovTech",
    "Manufacturing",
    "Logistics",
    "RealEstate/PropTech",
    "Media/Entertainment",
    "Automotive",
    "Other",
]

PROMPT_TEMPLATE = """You are verifying and enriching data for a LEAP 2026 tech conference exhibitor.

Company: "{name}"
Website: "{website}"
Current description: "{desc}"

Search the web to verify this is correct. If the description is wrong, about a different entity (e.g. a movie, a place, a person), or misleading, replace it with a correct one. If you cannot find information about this company, provide your best assessment from the name and website.

Provide:
1. A correct 1-2 sentence description of what the company does
2. A primary category (pick exactly one from: {categories})
3. is_ai: true if the company's core product or service is AI/ML-powered, false otherwise

Respond ONLY with this JSON format and nothing else:
{{"description": "...", "category": "...", "is_ai": true}}"""


def build_prompt(name, website, desc):
    return PROMPT_TEMPLATE.format(
        name=name,
        website=website,
        desc=desc[:200],
        categories=", ".join(CATEGORIES),
    )


def call_llm(name, website, desc):
    """Call opencode run and return parsed JSON dict."""
    prompt = build_prompt(name, website, desc)
    try:
        result = subprocess.run(
            ["opencode", "run", "-m", MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {"description": "", "category": "", "is_ai": False, "error": "timeout"}
    except Exception as e:
        return {"description": "", "category": "", "is_ai": False, "error": str(e)}

    # Find JSON in output
    # Look for the last JSON object with description/category/is_ai
    matches = re.findall(
        r'\{[^{}]*"description"[^{}]*"category"[^{}]*"is_ai"[^{}]*\}',
        output,
        re.S,
    )
    if not matches:
        # Broader search
        matches = re.findall(
            r'\{.*?"description".*?"category".*?"is_ai".*?\}', output, re.S
        )

    if matches:
        try:
            obj = json.loads(matches[-1])
            return {
                "description": obj.get("description", "").strip(),
                "category": obj.get("category", "").strip(),
                "is_ai": bool(obj.get("is_ai", False)),
            }
        except json.JSONDecodeError:
            pass

    return {
        "description": "",
        "category": "",
        "is_ai": False,
        "error": "no_json",
        "raw": output[-200:],
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

    # Find column indices
    name_idx = header.index("Company Name")
    web_idx = header.index("Website URL")
    desc_idx = header.index("Description")

    cp = load_checkpoint()
    print(f"Checkpoint has {len(cp)} companies already processed")

    # Find companies to process
    todo = []
    for r in data:
        name = r[name_idx].strip()
        if name and name not in cp:
            website = r[web_idx].strip() if len(r) > web_idx else ""
            desc = r[desc_idx].strip() if len(r) > desc_idx else ""
            todo.append((name, website, desc))

    total = len(todo)
    print(f"To process: {total}")
    print(f"Workers: {MAX_WORKERS}")
    print()

    processed = 0
    matched = 0
    errors = 0
    lock_saved = 0
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

            has_data = bool(result.get("description"))
            if has_data:
                matched += 1
            if result.get("error"):
                errors += 1

            cp[name] = result
            lock_saved += 1

            if lock_saved >= 10:
                save_checkpoint(cp)
                lock_saved = 0

            if processed % 10 == 0 or processed == total:
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                eta = (total - processed) / rate if rate > 0 else 0
                status = "OK" if has_data else "ERR"
                cat = result.get("category", "")
                print(
                    f"  {processed}/{total} [{status}] {name[:35]:35} "
                    f"cat={cat:20} ai={result.get('is_ai', False)}  "
                    f"({elapsed:.0f}s, eta {eta / 60:.0f}min)"
                )

    save_checkpoint(cp)

    # Update CSV
    print("\nUpdating CSV...")
    if "Category" not in header:
        header.append("Category")
        header.append("Is_AI")
        for r in data:
            r.append("")
            r.append("")

    cat_idx = header.index("Category")
    ai_idx = header.index("Is_AI")
    updated = 0

    for r in data:
        name = r[name_idx]
        if name in cp:
            entry = cp[name]
            desc = entry.get("description", "").strip()
            cat = entry.get("category", "").strip()
            is_ai = entry.get("is_ai", False)
            if desc:
                r[desc_idx] = desc
                updated += 1
            if cat:
                r[cat_idx] = cat
            r[ai_idx] = "true" if is_ai else "false"

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed / 60:.1f} min")
    print(f"  Processed: {processed}")
    print(f"  Verified/enriched: {matched}")
    print(f"  Errors: {errors}")
    print(f"  CSV updated: {updated} descriptions, all categories + is_ai flags")
    print(f"  Output: {CSV_PATH}")


if __name__ == "__main__":
    main()
