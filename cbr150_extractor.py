#!/usr/bin/env python3
"""
CBR150 Parts Extractor for engine-lab
Output ตรงตาม part-catalog-extraction.schema.json

ดึงข้อมูลจาก honda.bike-parts.co.th และสร้าง JSON files
ที่พร้อม commit เข้า data/parts/honda-cbr150/{market}/{year}/

Usage:
  # ดึงข้อมูล CBR150 ปี 2021 (Thailand)
  python3 cbr150_extractor.py --year 2021 --market thailand
  
  # ดึงข้อมูล CBR150 หลายปี
  python3 cbr150_extractor.py --year 2021 2022 2024 --market thailand
  
  # ดึงเฉพาะ engine categories (E1-E20)
  python3 cbr150_extractor.py --year 2021 --engine-only
  
  # ดึงทุก category
  python3 cbr150_extractor.py --year 2021 --all
"""

import sys
import os
import json
import time
import re
import argparse
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent))
from honda_parts_scraper import HondaPartsScraper


# CBR150 category mapping: honda.bike-parts category -> engine-lab block ID
# E = Engine, F = Frame/Body
CATEGORY_MAP = {
    # Engine categories (most important for engine-lab)
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
    
    # Frame/Body categories
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

# CBR150 Thai market primary model codes per year
# Only the primary Thai-market model is scraped to avoid duplicates
CBR150_PRIMARY_CODES = {
'2021': 'CBR150RK',
'2022': 'CBR150RK',
'2024': 'CBR150RK',
}


def get_cbr150_model_name(code: str) -> str:
    """แปลง model code เป็น model name"""
    # All Thai CBR150 codes map to CBR150R
    if 'CBR150' in code:
        return 'CBR150R'
    return code


def make_dataset_id(market: str, year: str, block_id: str) -> str:
    """สร้าง dataset ID ตาม convention"""
    market_upper = market.upper()[:2]
    return f"DATASET-HONDA-CBR150-{market_upper}-{year}-{block_id}"


def make_part_id(market: str, year: str, part_number: str) -> str:
    """สร้าง part record ID"""
    market_upper = market.upper()[:2]
    pn_clean = part_number.replace('-', '').upper()
    return f"PART-HONDA-{pn_clean}-{market_upper}-{year}"


def make_source_id(market: str, year: str) -> str:
    """สร้าง source ID"""
    return f"SRC-HONDA-THA-BIKE-PARTS-CBR150-{year}-{date.today().year}"


def build_extraction_record(
    dataset_id: str,
    source_id: str,
    market: str,
    year: str,
    model_code: str,
    model_name: str,
    block_id: str,
    block_name: str,
    parts: List[Dict],
    price_policy: str = "THB inclusive of 7% VAT"
) -> Dict:
    """
    สร้าง part-catalog-extraction record ตาม schema
    
    Args:
        dataset_id: DATASET-HONDA-CBR150-TH-2021-E1
        source_id: SRC-HONDA-THA-BIKE-PARTS-CBR150-2021-2026
        market: thailand
        year: 2021
        model_code: CBR150RK
        model_name: CBR150R
        block_id: E-1
        block_name: CYLINDER HEAD COVER
        parts: [{part_number, name, price, ref_number}]
        price_policy: THB inclusive of 7% VAT
    """
    items = []
    for i, part in enumerate(parts, 1):
        ref_num = part.get('ref_number', str(i))
        part_number = part['part_number']
        
        items.append({
            "reference_number": ref_num,
            "part_number": part_number,
            "description": part['name'],
            "quantity": part.get('quantity', 1),
            "status": "candidate",
            "notes": f"Extracted from honda.bike-parts.co.th for {model_name} {market} {year}. Price: {part.get('price', 'N/A')}. Physical dimensions and material remain unknown."
        })
    
    return {
        "schema_version": "0.1",
        "dataset_id": dataset_id,
        "status": "working",
        "source_id": source_id,
        "observed_at": str(date.today()),
        "applicability": {
            "manufacturer": "Honda",
            "model": model_name,
            "market": market,
            "year": int(year) if year.isdigit() else year,
            "serial_range": None,
            "area_code": None
        },
        "catalog_locator": {
            "block": f"{block_id} {block_name}",
            "page": None
        },
        "price_policy": price_policy,
        "items": items,
        "parameter_series": [],
        "unresolved_references": [],
        "notes": f"Automated extraction from honda.bike-parts.co.th. Model code: {model_code}. Block: {block_id} {block_name}."
    }


def scrape_cbr150_year(
    year: str,
    market: str = "thailand",
    output_dir: str = None,
    engine_only: bool = False,
    delay: float = 3.0
) -> List[str]:
    """
    ดึงข้อมูล CBR150 ทั้งหมดของปีที่กำหนด
    
    Returns:
        รายการไฟล์ที่สร้าง
    """
    scraper = HondaPartsScraper(delay=delay)
    
    # หารหัสรุ่น CBR150
    print(f"\n🔍 กำลังหารหัสรุ่น CBR150 ปี {year}...")
    all_model_codes = scraper.get_model_codes('150', 'CBR', year, 'MOTO')
    
    if not all_model_codes:
        print(f"❌ ไม่พบรุ่น CBR150 ปี {year}")
        return []
    
    # ใช้ primary Thai market model code เพื่อหลีกเลี่ยง duplicate
    primary_code = CBR150_PRIMARY_CODES.get(year, all_model_codes[0]['code'])
    model_codes = [c for c in all_model_codes if c['code'] == primary_code]
    
    if not model_codes:
        # Fallback: ใช้ตัวแรก
        model_codes = [all_model_codes[0]]
    
    print(f"📋 พบ {len(all_model_codes)} รหัสรุ่น ใช้ primary: {primary_code}")
    for c in model_codes:
        print(f"   • {c['name']} ({c['code']})")
    
    # สร้าง output directory
    if output_dir is None:
        output_dir = f"engine-lab-data/data/parts/honda-cbr150/{market}/{year}"
    
    os.makedirs(output_dir, exist_ok=True)
    
    source_id = make_source_id(market, year)
    created_files = []
    
    # ดึงข้อมูลแต่ละรหัสรุ่น
    for code_info in model_codes:
        model_code = code_info['code']
        model_name = get_cbr150_model_name(model_code)
        
        print(f"\n🏍️  {model_name} ({model_code})")
        
        # ดึงหมวดอะไหล่
        categories = scraper.get_categories(code_info['url'])
        print(f"   📁 {len(categories)} หมวดอะไหล่")
        
        for i, cat in enumerate(categories, 1):
            cat_name = cat['name']
            
            # หา block ID
            block_id = CATEGORY_MAP.get(cat_name)
            if not block_id:
                # ลองหาจากชื่อที่ normalize แล้ว
                normalized = cat_name.upper().replace(' ', '-').replace('--', '-')
                for key, val in CATEGORY_MAP.items():
                    if key.upper().replace(' ', '-') == normalized:
                        block_id = val
                        break
            
            if not block_id:
                block_id = f"X-{i}"
            
            # ถ้า engine-only ให้ข้าม non-engine categories
            if engine_only and not block_id.startswith('E'):
                continue
            
            # ดึงอะไหล่
            time.sleep(delay)
            try:
                parts_data = scraper.get_parts_from_category(cat['url'])
                
                if not parts_data:
                    print(f"   [{i}/{len(categories)}] ⏭️  {cat_name}: 0 อะไหล่ (skip)")
                    continue
                
                # สร้าง dataset ID
                dataset_id = make_dataset_id(market, year, block_id)
                
                # สร้าง extraction record
                extraction = build_extraction_record(
                    dataset_id=dataset_id,
                    source_id=source_id,
                    market=market,
                    year=year,
                    model_code=model_code,
                    model_name=model_name,
                    block_id=block_id,
                    block_name=cat_name,
                    parts=parts_data
                )
                
                # สร้างชื่อไฟล์
                block_id_clean = block_id.lower().replace(' ', '-')
                cat_name_clean = cat_name.lower().replace(' ', '-').replace('--', '-')
                filename = f"{block_id_clean}-{cat_name_clean}.json"
                filepath = os.path.join(output_dir, filename)
                
                # บันทึกไฟล์
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(extraction, f, ensure_ascii=False, indent=2)
                
                created_files.append(filepath)
                print(f"   [{i}/{len(categories)}] ✅ {block_id} {cat_name}: {len(parts_data)} อะไหล่ -> {filename}")
                
            except Exception as e:
                print(f"   [{i}/{len(categories)}] ❌ {cat_name}: {e}")
    
    return created_files


def main():
    parser = argparse.ArgumentParser(
        description='CBR150 Parts Extractor for engine-lab',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ตัวอย่าง:
  # ดึงข้อมูล CBR150 ปี 2021
  python3 cbr150_extractor.py --year 2021
  
  # ดึงเฉพาะ engine parts
  python3 cbr150_extractor.py --year 2021 --engine-only
  
  # ดึงหลายปี
  python3 cbr150_extractor.py --year 2021 2022 2024
  
  # กำหนด output directory
  python3 cbr150_extractor.py --year 2021 --output ./my-output
        """
    )
    
    parser.add_argument('--year', nargs='+', required=True, help='ปีที่ต้องการ (เช่น 2021 2022)')
    parser.add_argument('--market', default='thailand', help='ตลาด (default: thailand)')
    parser.add_argument('--output', '-o', help='Output directory')
    parser.add_argument('--engine-only', action='store_true', help='ดึงเฉพาะ engine categories (E-xx)')
    parser.add_argument('--all', action='store_true', help='ดึงทุก category (default)')
    parser.add_argument('--delay', type=float, default=3.0, help='หน่วงเวลา (วินาที)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🔧 CBR150 Parts Extractor for engine-lab")
    print(f"📡 Source: honda.bike-parts.co.th")
    print(f"📋 Schema: part-catalog-extraction v0.1")
    print("=" * 60)
    
    all_files = []
    
    for year in args.year:
        output_dir = args.output
        if not output_dir:
            output_dir = f"engine-lab-data/data/parts/honda-cbr150/{args.market}/{year}"
        
        files = scrape_cbr150_year(
            year=year,
            market=args.market,
            output_dir=output_dir,
            engine_only=args.engine_only,
            delay=args.delay
        )
        all_files.extend(files)
    
    # Summary
    print("\n" + "=" * 60)
    print(f"✅ เสร็จสิ้น: สร้าง {len(all_files)} ไฟล์")
    print("=" * 60)
    
    if all_files:
        print("\n📁 ไฟล์ที่สร้าง:")
        for f in all_files:
            print(f"   • {f}")
        
        print(f"\n💡 ขั้นตอนถัดไป:")
        print(f"   1. ตรวจสอบข้อมูลในไฟล์")
        print(f"   2. Copy ไปยัง engine-lab/data/parts/honda-cbr150/")
        print(f"   3. Register source ใน sources/registry/sources.yaml")
        print(f"   4. Review และเปลี่ยน status จาก 'candidate' เป็น 'verified'")


if __name__ == "__main__":
    main()
