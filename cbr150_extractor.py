#!/usr/bin/env python3
"""
CBR150 Parts Extractor for engine-lab v2

Changes from v1:
- model_code as opaque identifier in applicability (never translated)
- stage/status/evidence_level as separate dimensions
- quantity: null when unknown (never 1)
- reference_number from the static product row or null
- no deduplication by part number
- exact category URL plus raw-response and normalized-content hashes preserved
- completeness_status: complete|partial|failed
- category failures tracked in unresolved_references
- CAPTCHA is fail-fast by default (--wait-on-captcha to opt in)
"""

import sys
import os
import json
import re
import hashlib
import argparse
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from honda_parts_scraper import CaptchaError, HondaPartsScraper


# ─── Helpers ────────────────────────────────────────────────────

def lookup_block_id(category_url: str) -> Optional[str]:
    """Read the catalog's own E/F block identifier from its URL."""
    match = re.search(r'/([EF])(\d+[A-Z0-9]*)/', category_url, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1).upper()}-{match.group(2).upper()}"


def make_dataset_id(model_code: str, market: str, year: str, block_id: str) -> str:
    """DATASET-HONDA-CBR150RK-TH-2021-E-1 (includes model_code)"""
    market_upper = market.upper()[:2]
    return f"DATASET-HONDA-{model_code}-{market_upper}-{year}-{block_id}"


def make_source_id(market: str, model_code: str, year: str) -> str:
    market_code = market.upper()[:2]
    return f"SRC-HONDA-BIKE-PARTS-{market_code}-{model_code}-{year}"


def compute_content_hash(items: list) -> str:
    """Hash ของ items เพื่อ detect changes"""
    canonical = json.dumps(items, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ─── Extraction record builder ─────────────────────────────────

def build_extraction_record(
    *,
    dataset_id: str,
    source_id: str,
    source_url: str,
    source_content_hash: str,
    market: str,
    year: str,
    model_code: str,
    block_id: str,
    block_name: str,
    parts: List[Dict],
    observed_at: str = None,
) -> Dict:
    """
    Build part-catalog-extraction record v2.

    - stage: raw_extraction
    - status: candidate
    - evidence_level: C (secondary source)
    - model_code opaque, never translated
    - quantity: null when not observed
    - reference_number: from hotspot or null
    """
    if observed_at is None:
        observed_at = str(date.today())

    items = []
    for part in parts:
        items.append({
            "reference_number": part.get('ref_number'),  # null if not from hotspot
            "part_number": part['part_number'],
            "description": part['name'],
            "quantity": part.get('quantity'),  # null if not observed
            "status": "candidate",
            "notes": "Secondary-source catalog identity. Physical engineering attributes remain UNKNOWN.",
        })

    unresolved = []
    if any(item["reference_number"] is None for item in items):
        unresolved.append("reference_number:one_or_more_items:unknown")
    if any(item["quantity"] is None for item in items):
        unresolved.append("catalog_quantity:one_or_more_items:unknown")
    completeness = "complete" if not unresolved else "partial"

    return {
        "schema_version": "0.2",
        "dataset_id": dataset_id,
        "stage": "raw_extraction",
        "status": "candidate",
        "evidence_level": "C",
        "source_id": source_id,
        "source_url": source_url,
        "source_content_hash": source_content_hash,
        "observed_at": observed_at,
        "content_hash": compute_content_hash(items),
        "applicability": {
            "manufacturer": "Honda",
            "model": "CBR150R",
            "model_code": model_code,  # opaque, never translated
            "market": market,
            "year": int(year) if year.isdigit() else year,
            "serial_range": None,
            "area_code": None,
        },
        "catalog_locator": {
            "block": f"{block_id} {block_name}",
            "page": None,
        },
        "completeness_status": completeness,
        "price_policy": "Observed retail prices are excluded from Engine Lab extraction records because they are volatile and are not engineering parameters.",
        "items": items,
        "parameter_series": [],
        "unresolved_references": unresolved,
        "notes": (
            f"Automated extraction from honda.bike-parts.co.th. "
            f"Model code: {model_code} (opaque identifier). "
            f"Evidence level C — secondary source, pending PEC cross-check. "
            f"Block: {block_id} {block_name}."
        ),
    }


# ─── Main extraction logic ─────────────────────────────────────

def scrape_cbr150_year(
    year: str,
    market: str = "thailand",
    model_code: Optional[str] = None,
    output_dir: Optional[str] = None,
    engine_only: bool = False,
    delay: float = 3.0,
    wait_on_captcha: bool = False,
    blocks: Optional[List[str]] = None,
) -> Tuple[List[str], List[str]]:
    """
    Extract CBR150 parts for a given year.

    Returns: (created_files, failed_categories)
    """
    scraper = HondaPartsScraper(
        delay=delay,
        wait_on_captcha=wait_on_captcha,
    )

    # Resolve model codes
    print(f"\n🔍 Finding CBR150 model codes for {year}...")
    all_codes = scraper.get_model_codes('150', 'CBR', year, 'MOTO')

    if not all_codes:
        print(f"❌ No CBR150 models found for {year}")
        return [], [f"MODEL_DISCOVERY:{year}:empty"]

    # Select model code
    if model_code:
        selected = [c for c in all_codes if c['code'] == model_code]
        if not selected:
            print(f"❌ Model code {model_code} not found. Available:")
            for c in all_codes:
                print(f"   • {c['code']}")
            return [], [f"MODEL_SELECTION:{model_code}:not_found"]
    else:
        if len(all_codes) > 1:
            print("❌ Multiple model codes found; --model-code is required:")
            for c in all_codes:
                print(f"   • {c['code']}")
            return [], [f"MODEL_SELECTION:{year}:ambiguous"]
        selected = [all_codes[0]]

    code_info = selected[0]
    mc = code_info['code']

    print(f"🏍️  Model: {mc}")

    # Output dir: candidate/bike-parts/
    if output_dir is None:
        output_dir = f"engine-lab-data/data/parts/honda-cbr150/{market}/{year}/candidate/bike-parts/{mc}"
    os.makedirs(output_dir, exist_ok=True)

    source_id = make_source_id(market, mc, year)

    # Get categories
    categories = scraper.get_categories(code_info['url'])
    print(f"📁 {len(categories)} categories found")

    created_files = []
    failed_categories = []
    successful_categories = []
    total_items = 0
    requested_blocks = {b.upper() for b in blocks} if blocks else None
    attempted_categories = 0
    discovered_blocks = set()

    for i, cat in enumerate(categories, 1):
        cat_name = cat['name']
        block_id = lookup_block_id(cat['url'])

        if not block_id:
            failed_categories.append(f"UNKNOWN_BLOCK:{cat_name}:url_missing_block_id")
            continue
        discovered_blocks.add(block_id)

        if engine_only and not block_id.startswith('E'):
            continue
        if requested_blocks and block_id not in requested_blocks:
            continue

        # Extract parts
        attempted_categories += 1
        try:
            category = scraper.get_category_extraction(cat['url'])
            parts_data = category['parts']

            if not parts_data:
                failed_categories.append(f"{block_id}:{cat_name}:empty_result")
                print(f"   [{i}/{len(categories)}] ❌ {cat_name}: 0 parts (unexpected empty result)")
                continue

            dataset_id = make_dataset_id(mc, market, year, block_id)

            extraction = build_extraction_record(
                dataset_id=dataset_id,
                source_id=source_id,
                source_url=category['source_url'],
                source_content_hash=category['source_content_hash'],
                market=market,
                year=year,
                model_code=mc,
                block_id=block_id,
                block_name=cat_name,
                parts=parts_data,
            )

            # Filename
            block_clean = block_id.lower().replace(' ', '-')
            cat_clean = cat_name.lower().replace(' ', '-').replace('--', '-')
            filename = f"{block_clean}-{cat_clean}.json"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(extraction, f, ensure_ascii=False, indent=2)

            created_files.append(filepath)
            successful_categories.append({
                "block": block_id,
                "category": cat_name,
                "source_url": category['source_url'],
                "items": len(parts_data),
                "file": filename,
            })
            total_items += len(parts_data)
            print(f"   [{i}/{len(categories)}] ✅ {block_id} {cat_name}: {len(parts_data)} parts")

        except CaptchaError as e:
            failed_categories.append(f"{block_id}:{cat_name}:CAPTCHA")
            print(f"   [{i}/{len(categories)}] ❌ {block_id} {cat_name}: {e}")
            if not wait_on_captcha:
                break
        except Exception as e:
            failed_categories.append(f"{block_id}:{cat_name}:{type(e).__name__}")
            print(f"   [{i}/{len(categories)}] ❌ {block_id} {cat_name}: {e}")

    if requested_blocks:
        for missing_block in sorted(requested_blocks - discovered_blocks):
            failed_categories.append(f"{missing_block}:not_present_in_model_catalog")

    manifest = {
        "schema_version": "0.1",
        "run_status": "failed" if not created_files else ("partial" if failed_categories else "complete"),
        "evidence_level": "C",
        "observed_at": str(date.today()),
        "source_site": "https://honda.bike-parts.co.th",
        "source_id": source_id,
        "applicability": {
            "manufacturer": "Honda",
            "model": "CBR150R",
            "model_code": mc,
            "market": market,
            "year": int(year) if year.isdigit() else year,
        },
        "requested_blocks": sorted(requested_blocks) if requested_blocks else None,
        "discovered_category_count": len(categories),
        "discovered_blocks": sorted(discovered_blocks),
        "attempted_category_count": attempted_categories,
        "successful_categories": successful_categories,
        "failures": failed_categories,
    }
    manifest_path = os.path.join(output_dir, "_extraction-manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Print summary
    print(f"\n📊 Summary for {mc}:")
    print(f"   ✅ {len(created_files)} categories extracted, {total_items} total parts")
    if failed_categories:
        print(f"   ❌ {len(failed_categories)} categories failed:")
        for fc in failed_categories:
            print(f"      • {fc}")

    return created_files, failed_categories


def main():
    parser = argparse.ArgumentParser(
        description='CBR150 Parts Extractor for engine-lab',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cbr150_extractor.py --year 2021 --engine-only
  python cbr150_extractor.py --year 2021 --model-code CBR150RK
  python cbr150_extractor.py --year 2021 2022 --engine-only --delay 5
  python cbr150_extractor.py --year 2021 --wait-on-captcha

Output structure:
  engine-lab-data/data/parts/honda-cbr150/{market}/{year}/candidate/bike-parts/
        """
    )

    parser.add_argument('--year', nargs='+', required=True)
    parser.add_argument('--market', default='thailand')
    parser.add_argument('--model-code', help='Specific model code (e.g. CBR150RK)')
    parser.add_argument('--output', '-o', default=None)
    parser.add_argument('--engine-only', action='store_true')
    parser.add_argument('--block', dest='blocks', nargs='+',
                        help='Only extract exact catalog blocks, e.g. E-1 E-3')
    parser.add_argument('--delay', type=float, default=3.0)
    parser.add_argument('--wait-on-captcha', action='store_true',
                        help='Wait 5min on CAPTCHA instead of failing immediately')

    args = parser.parse_args()

    print("=" * 60)
    print("🔧 CBR150 Parts Extractor for engine-lab v2")
    print(f"📡 Source: honda.bike-parts.co.th (evidence level C)")
    print(f"📋 Schema: part-catalog-extraction v0.2")
    print(f"⏱️  Delay: {args.delay}s")
    print(f"🤖 CAPTCHA: {'wait' if args.wait_on_captcha else 'fail-fast'}")
    print("=" * 60)

    all_files = []
    all_failures = []

    for year in args.year:
        output_dir_arg: Optional[str] = args.output
        if not output_dir_arg:
            output_dir_arg = None

        files, failures = scrape_cbr150_year(
            year=year,
            market=args.market,
            model_code=args.model_code,
            output_dir=output_dir_arg,
            engine_only=args.engine_only,
            delay=args.delay,
            wait_on_captcha=args.wait_on_captcha,
            blocks=args.blocks,
        )
        all_files.extend(files)
        all_failures.extend(failures)

    # Final summary
    print("\n" + "=" * 60)
    print(f"✅ Done: {len(all_files)} files created")
    if all_failures:
        print(f"❌ {len(all_failures)} run failures recorded in _extraction-manifest.json")
    print("=" * 60)

    if all_files:
        print("\n📁 Files:")
        for f in all_files:
            print(f"   • {f}")

        print(f"\n💡 Next steps:")
        print(f"   1. Review files in candidate/bike-parts/")
        print(f"   2. Cross-check with PEC data")
        print(f"   3. Move verified records to verified/pec/")
        print(f"   4. Register source in sources/registry/sources.yaml")

    if all_failures or not all_files:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
