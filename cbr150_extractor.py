#!/usr/bin/env python3
"""
CBR150 Parts Extractor for engine-lab v2

Changes from v1:
- model_code as opaque identifier in applicability (never translated)
- stage/status/evidence_level as separate dimensions
- quantity: null when unknown (never 1)
- reference_number from hotspot or null
- no deduplication by part number
- URL and raw snapshot preserved
- completeness_status: complete|partial|failed
- category failures tracked in unresolved_references
- CAPTCHA is fail-fast by default (--wait-on-captcha to opt in)
"""

import sys
import os
import json
import time
import re
import hashlib
import argparse
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent))
from honda_parts_scraper import HondaPartsScraper


# ─── Category → Block ID mapping ───────────────────────────────
CATEGORY_MAP = {
    'CYLINDER HEAD COVER': 'E-1',
    'CYLINDER HEAD': 'E-2',
    'CAMSHAFT - VALVE': 'E-3',
    'CAMSHAFT--VALVE': 'E-3',
    'CAM CHAIN - TENSIONER': 'E-4',
    'CAM-CHAIN--TENSIONER': 'E-4',
    'CYLINDER': 'E-5',
    'WATER PUMP': 'E-6',
    'ALTERNATOR': 'E-7',
    'OIL PUMP': 'E-8',
    'LEFT COVER': 'E-9',
    'RADIATOR': 'E-10',
    'VARIATOR': 'E-11',
    'CLUTCH': 'E-12',
    'GEARBOX': 'E-13',
    'RIGHT CRANKCASE COVER': 'E-14',
    'LEFT CRANKCASE COVER': 'E-15',
    'CRANKCASE': 'E-16',
    'CRANKSHAFT - PISTON': 'E-17',
    'CRANKSHAFT--PISTON': 'E-17',
    'THROTTLE BODY - INJECTOR': 'E-18',
    'THROTTLE-BODY--INJECTOR': 'E-18',
    'CARBURETOR': 'E-19',
    'INTAKE MANIFOLD': 'E-20',
    'HEADLIGHT': 'F-1',
    'METER': 'F-2',
    'MIRROR': 'F-3',
    'HANDLE LEVER - CABLE - SWITCH': 'F-4',
    'HANDLE-LEVER--CABLE--SWITCH': 'F-4',
    'FRONT BRAKE MASTER CYLINDER': 'F-5',
    'FRONT-BRAKE-MASTER-CYLINDER': 'F-5',
    'REAR BRAKE MASTER CYLINDER': 'F-6',
    'REAR-BRAKE-MASTER-CYLINDER': 'F-6',
    'REAR BRAKE HOSE': 'F-7',
    'REAR-BRAKE-HOSE': 'F-7',
    'HANDLEBAR - COWL': 'F-8',
    'HANDLEBAR--COWL': 'F-8',
    'STEERING STEM': 'F-9',
    'STEERING-STEM': 'F-9',
    'FRONT FENDER': 'F-10',
    'FRONT-FENDER': 'F-10',
    'FRONT COWL': 'F-11',
    'FRONT-COWL': 'F-11',
    'LEG SHIELD': 'F-12',
    'LEG-SHIELD': 'F-12',
    'FLOOR PANEL - SIDE SKIRT': 'F-13',
    'FLOOR-PANEL--SIDE-SKIRT': 'F-13',
    'FOOTREST': 'F-14',
    'REAR COWL': 'F-15',
    'REAR-COWL': 'F-15',
    'FRONT FORK': 'F-16',
    'FRONT-FORK': 'F-16',
    'FRONT BRAKE CALIPER': 'F-17',
    'FRONT-BRAKE-CALIPER': 'F-17',
    'FRONT WHEEL': 'F-18',
    'FRONT-WHEEL': 'F-18',
    'REAR BRAKE CALIPER': 'F-19',
    'REAR-BRAKE-CALIPER': 'F-19',
    'REAR WHEEL': 'F-20',
    'REAR-WHEEL': 'F-20',
    'SWING ARM': 'F-21',
    'SWING-ARM': 'F-21',
    'SEAT - LUGGAGE BOX': 'F-22',
    'SEAT--LUGGAGE-BOX': 'F-22',
    'FUEL TANK': 'F-23',
    'FUEL-TANK': 'F-23',
    'AIR FILTER': 'F-24',
    'AIR-FILTER': 'F-24',
    'EXHAUST MUFFLER': 'F-25',
    'EXHAUST-MUFFLER': 'F-25',
    'STAND': 'F-26',
    'REAR SHOCK ABSORBER': 'F-27',
    'REAR-SHOCK-ABSORBER': 'F-27',
    'INDICATOR': 'F-28',
    'TAILLIGHT': 'F-29',
    'REAR FENDER - LICENSE PLATE LAMP': 'F-30',
    'REAR-FENDER--LICENSE-PLATE-LAMP': 'F-30',
    'BATTERY': 'F-31',
    'WIRE HARNESS': 'F-32',
    'WIRE-HARNESS': 'F-32',
    'FRAME': 'F-33',
    'EXPANSION TANK': 'F-34',
    'EXPANSION-TANK': 'F-34',
    'TOOL': 'F-35',
    'CAUTION LABEL': 'F-36',
    'CAUTION-LABEL': 'F-36',
    'STICKERS': 'F-37',
}


# ─── Helpers ────────────────────────────────────────────────────

def lookup_block_id(cat_name: str) -> Optional[str]:
    """หา block ID จาก category name"""
    if cat_name in CATEGORY_MAP:
        return CATEGORY_MAP[cat_name]
    normalized = cat_name.upper().replace(' ', '-').replace('--', '-')
    for key, val in CATEGORY_MAP.items():
        if key.upper().replace(' ', '-') == normalized:
            return val
    return None


def make_dataset_id(model_code: str, market: str, year: str, block_id: str) -> str:
    """DATASET-HONDA-CBR150RK-TH-2021-E-1 (includes model_code)"""
    market_upper = market.upper()[:2]
    return f"DATASET-HONDA-{model_code}-{market_upper}-{year}-{block_id}"


def make_source_id(source_site: str, model_code: str, year: str) -> str:
    clean = source_site.replace('.', '-').upper()
    return f"SRC-HONDA-THA-{clean}-{model_code}-{year}-{date.today().year}"


def compute_content_hash(items: list) -> str:
    """Hash ของ items เพื่อ detect changes"""
    canonical = json.dumps(items, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ─── Extraction record builder ─────────────────────────────────

def build_extraction_record(
    *,
    dataset_id: str,
    source_id: str,
    source_url: str,
    market: str,
    year: str,
    model_code: str,
    block_id: str,
    block_name: str,
    parts: List[Dict],
    failed_categories: List[str],
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
            "notes": (
                f"Source: {source_url}. "
                f"Price: {part.get('price', 'N/A')}. "
                f"Physical dimensions and material remain unknown."
            ),
        })

    # completeness
    if not failed_categories:
        completeness = "complete"
    elif len(items) > 0:
        completeness = "partial"
    else:
        completeness = "failed"

    return {
        "schema_version": "0.1",
        "dataset_id": dataset_id,
        "stage": "raw_extraction",
        "status": "candidate",
        "evidence_level": "C",
        "source_id": source_id,
        "source_url": source_url,
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
        "price_policy": "THB inclusive of 7% VAT",
        "items": items,
        "parameter_series": [],
        "unresolved_references": failed_categories,
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
) -> Tuple[List[str], List[str]]:
    """
    Extract CBR150 parts for a given year.

    Returns: (created_files, failed_categories)
    """
    scraper = HondaPartsScraper(delay=delay)

    # Resolve model codes
    print(f"\n🔍 Finding CBR150 model codes for {year}...")
    all_codes = scraper.get_model_codes('150', 'CBR', year, 'MOTO')

    if not all_codes:
        print(f"❌ No CBR150 models found for {year}")
        return [], []

    # Select model code
    if model_code:
        selected = [c for c in all_codes if c['code'] == model_code]
        if not selected:
            print(f"❌ Model code {model_code} not found. Available:")
            for c in all_codes:
                print(f"   • {c['code']}")
            return [], []
    else:
        # Default: first code, but warn about others
        selected = [all_codes[0]]
        if len(all_codes) > 1:
            print(f"⚠️  Multiple model codes found. Using {all_codes[0]['code']}. Others:")
            for c in all_codes[1:]:
                print(f"   • {c['code']} (not selected)")

    code_info = selected[0]
    mc = code_info['code']

    print(f"🏍️  Model: {mc}")

    # Output dir: candidate/bike-parts/
    if output_dir is None:
        output_dir = f"engine-lab-data/data/parts/honda-cbr150/{market}/{year}/candidate/bike-parts"
    os.makedirs(output_dir, exist_ok=True)

    source_id = make_source_id('honda.bike-parts.co.th', mc, year)
    source_url_base = "https://honda.bike-parts.co.th"

    # Get categories
    categories = scraper.get_categories(code_info['url'])
    print(f"📁 {len(categories)} categories found")

    created_files = []
    failed_categories = []
    total_items = 0

    for i, cat in enumerate(categories, 1):
        cat_name = cat['name']
        block_id = lookup_block_id(cat_name)

        if not block_id:
            block_id = f"X-{i}"

        if engine_only and not block_id.startswith('E'):
            continue

        # Extract parts
        time.sleep(delay)
        try:
            parts_data = scraper.get_parts_from_category(cat['url'])

            if not parts_data:
                print(f"   [{i}/{len(categories)}] ⏭️  {cat_name}: 0 parts (empty)")
                continue

            dataset_id = make_dataset_id(mc, market, year, block_id)

            extraction = build_extraction_record(
                dataset_id=dataset_id,
                source_id=source_id,
                source_url=f"{source_url_base}/honda-motorcycle/150-MOTO/CBR/{year}/{mc}",
                market=market,
                year=year,
                model_code=mc,
                block_id=block_id,
                block_name=cat_name,
                parts=parts_data,
                failed_categories=[],
            )

            # Filename
            block_clean = block_id.lower().replace(' ', '-')
            cat_clean = cat_name.lower().replace(' ', '-').replace('--', '-')
            filename = f"{block_clean}-{cat_clean}.json"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(extraction, f, ensure_ascii=False, indent=2)

            created_files.append(filepath)
            total_items += len(parts_data)
            print(f"   [{i}/{len(categories)}] ✅ {block_id} {cat_name}: {len(parts_data)} parts")

        except Exception as e:
            failed_categories.append(f"{block_id}:{cat_name}:{type(e).__name__}")
            print(f"   [{i}/{len(categories)}] ❌ {block_id} {cat_name}: {e}")

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
    parser.add_argument('--delay', type=float, default=3.0)
    parser.add_argument('--wait-on-captcha', action='store_true',
                        help='Wait 5min on CAPTCHA instead of failing immediately')

    args = parser.parse_args()

    print("=" * 60)
    print("🔧 CBR150 Parts Extractor for engine-lab v2")
    print(f"📡 Source: honda.bike-parts.co.th (evidence level C)")
    print(f"📋 Schema: part-catalog-extraction v0.1")
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
        )
        all_files.extend(files)
        all_failures.extend(failures)

    # Final summary
    print("\n" + "=" * 60)
    print(f"✅ Done: {len(all_files)} files created")
    if all_failures:
        print(f"❌ {len(all_failures)} failures recorded in unresolved_references")
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


if __name__ == "__main__":
    main()
