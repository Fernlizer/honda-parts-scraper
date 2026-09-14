#!/usr/bin/env python3
"""
Honda Parts Scraper v3 - ดึงรายการอะไหล่ Honda จาก honda.bike-parts.co.th
ใช้แทน PEC (pec.thaihonda.co.th) ที่ต้อง login

เว็บนี้เป็นสาธารณะ ไม่ต้อง login ใช้ Schema.org Microdata สำหรับข้อมูลอะไหล่

⚠️ หมายเหตุ: เว็บมี rate limiting (reCAPTCHA) ถ้าส่ง request เร็วเกินไป
   - เพิ่ม delay ระหว่าง request (default 2 วินาที)
   - ถ้าเจอ CAPTCHA ให้รอ 5 นาทีแล้วลองใหม่
   - ใช้ browser แก้ CAPTCHA แล้ว scraper จะทำงานต่อได้

รองรับ:
1. ค้นหาตามหมายเลขชิ้นส่วน (Part Number) - POST /honda-motorcycle/price
2. ค้นหาตามรุ่นรถ - เดิน tree: cc -> model -> year -> code -> category
3. ดึงแคตตาล็อกอะไหล่ทั้งหมดของรุ่นรถ - ใช้ Schema.org Product microdata
"""

import time
import json
import csv
import re
import sys
import hashlib
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

# ใช้ curl_cffi เพื่อ bypass TLS fingerprinting
try:
    from curl_cffi import requests as curl_requests
    USE_CURL_CFFI = True
except ImportError:
    import requests
    USE_CURL_CFFI = False

from bs4 import BeautifulSoup


class CaptchaError(RuntimeError):
    """The source redirected the request to its CAPTCHA page."""


def parse_category_html(html: str) -> List[Dict]:
    """Parse one static category page without inventing missing fields."""
    soup = BeautifulSoup(html, 'html.parser')
    parts = []

    # Each Product wrapper contains the diagram reference in its leading
    # col-etape7 child. Alternatives remain separate Product wrappers and can
    # legitimately share the same reference number.
    for product in soup.find_all(itemtype='http://schema.org/Product'):
        ref_span = product.select_one('span.ref-libelle')
        ref_number = ref_span.get_text(strip=True) if ref_span else None
        name_elem = product.find(itemprop='name')
        mpn_elem = product.find(itemprop='mpn')
        price_elem = product.find(itemprop='price')

        name = name_elem.get_text(strip=True) if name_elem else ''
        mpn = mpn_elem.get_text(strip=True) if mpn_elem else ''
        price = price_elem.get_text(strip=True) if price_elem else ''
        if not mpn:
            continue

        ref_link = product.find('span', class_='JS_ref_link')
        part_number = ref_link.get_text(strip=True) if ref_link else mpn
        parts.append({
            'part_number': part_number,
            'part_number_raw': mpn,
            'name': name,
            'price': price,
            'ref_number': ref_number,
            # The visible order input defaults to 1 for shopping-cart use;
            # it is not the catalog assembly quantity.
            'quantity': None,
        })

    return parts


@dataclass
class Part:
    """ข้อมูลอะไหล่แต่ละชิ้น"""
    part_number: str          # 12300-K0R-V00
    part_number_raw: str      # 12300K0RV00
    name: str                 # ฝาครอบฝาสูบ
    price: str                # 277,13 ฿
    category: str             # CYLINDER HEAD COVER
    model: str                # CLICK 160 ABS
    year: str                 # 2024
    model_code: str           # ACB160CATR


class HondaPartsScraper:
    """Scraper สำหรับดึงข้อมูลอะไหล่ Honda จาก honda.bike-parts.co.th"""
    
    BASE_URL = "https://honda.bike-parts.co.th"
    
    def __init__(
        self,
        delay: float = 2.0,
        max_retries: int = 3,
        wait_on_captcha: bool = False,
        request_timeout: float = 20.0,
        captcha_wait_seconds: float = 300.0,
        sleep_fn=time.sleep,
    ):
        """
        Args:
            delay: หน่วงเวลาระหว่าง request (วินาที) - เพิ่มถ้าเจอ CAPTCHA
            max_retries: จำนวนครั้งที่ลองใหม่เมื่อเจอ CAPTCHA
        """
        self.delay = delay
        self.max_retries = max_retries
        self.wait_on_captcha = wait_on_captcha
        self.request_timeout = request_timeout
        self.captcha_wait_seconds = captcha_wait_seconds
        self._sleep = sleep_fn
        self.last_failures: List[str] = []
        
        if USE_CURL_CFFI:
            self.session = curl_requests.Session(impersonate='chrome131')
        else:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            })
        
        self._csrf_cache = {}
        self._request_count = 0
    
    def _is_captcha(self, response) -> bool:
        """ตรวจสอบว่าถูก redirect ไปหน้า CAPTCHA หรือไม่"""
        return 'captcha' in response.url.lower()
    
    def _get_with_retry(self, url: str) -> 'Response':
        """
        GET request with CAPTCHA retry logic
        
        ถ้าเจอ CAPTCHA จะ:
        1. แจ้งเตือนผู้ใช้
        2. รอ 5 นาที
        3. ลองใหม่ (สูงสุด max_retries ครั้ง)
        """
        for attempt in range(self.max_retries):
            # หน่วงเวลาก่อน request
            if self._request_count > 0:
                self._sleep(self.delay)
            
            self._request_count += 1
            response = self.session.get(url, timeout=self.request_timeout)
            
            if self._is_captcha(response):
                if not self.wait_on_captcha:
                    raise CaptchaError(f"CAPTCHA required for {url}")

                wait_time = self.captcha_wait_seconds
                print(f"   ⚠️  CAPTCHA detected! Waiting {wait_time//60} minutes...")
                print(f"   💡 Tip: Open the URL in browser and solve the CAPTCHA manually:")
                print(f"      {response.url}")
                print(f"   ⏳ Waiting {wait_time} seconds (attempt {attempt+1}/{self.max_retries})...")
                if attempt + 1 < self.max_retries:
                    self._sleep(wait_time)
                continue
            
            response.raise_for_status()
            return response
        
        raise Exception(f"CAPTCHA not resolved after {self.max_retries} attempts. Try again later.")
    
    def _get_csrf(self, url: str) -> str:
        """ดึง CSRF token จากหน้า"""
        if url in self._csrf_cache:
            return self._csrf_cache[url]
        
        r = self._get_with_retry(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        csrf = soup.find('input', {'name': 'csrf_test_name'})
        token = csrf['value'] if csrf else ''
        self._csrf_cache[url] = token
        return token
    
    # ==========================================
    # 1. ค้นหาตามหมายเลขชิ้นส่วน
    # ==========================================
    
    def search_by_part_number(self, part_number: str) -> Dict:
        """
        ค้นหาอะไหล่ตามหมายเลขชิ้นส่วน
        
        Args:
            part_number: หมายเลขชิ้นส่วน เช่น 16450-K35-V01 หรือ 16450K35V01
        
        Returns:
            ข้อมูลอะไหล่ + รุ่นที่เข้ากันได้
        """
        search_url = f"{self.BASE_URL}/honda-motorcycle/price"
        
        # ดึง CSRF token
        r0 = self._get_with_retry(search_url)
        soup0 = BeautifulSoup(r0.text, 'html.parser')
        csrf = soup0.find('input', {'name': 'csrf_test_name'})
        csrf_token = csrf['value'] if csrf else ''
        
        # POST search
        data = {
            'csrf_test_name': csrf_token,
            'chercher_reference': part_number
        }
        
        self._sleep(self.delay)
        r = self.session.post(search_url, data=data, timeout=self.request_timeout)
        
        if self._is_captcha(r):
            raise CaptchaError(f"CAPTCHA required for {search_url}")
        
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        
        result = {
            'query': part_number,
            'found': False,
            'part_number': '',
            'part_number_raw': '',
            'name': '',
            'price': '',
            'description': '',
        }
        
        # ดึงจาก Schema.org Microdata
        product = soup.find(itemtype='http://schema.org/Product')
        if product:
            name_elem = product.find(itemprop='name')
            mpn_elem = product.find(itemprop='mpn')
            price_elem = product.find(itemprop='price')
            desc_elem = product.find(itemprop='description')
            
            if name_elem:
                result['name'] = name_elem.get_text(strip=True)
            if mpn_elem:
                result['part_number_raw'] = mpn_elem.get_text(strip=True)
            if price_elem:
                result['price'] = price_elem.get_text(strip=True)
            if desc_elem:
                result['description'] = desc_elem.get_text(strip=True)
            
            # หา part number ที่มีขีด
            for span in soup.find_all('span', class_='fw-bold'):
                text = span.get_text(strip=True)
                if '-' in text and re.match(r'\d{5}', text):
                    result['part_number'] = text
                    break
            
            if not result['part_number']:
                title = soup.find('title')
                if title:
                    match = re.search(r'(\d{5}-[A-Z0-9]+-[A-Z0-9]+)', title.get_text())
                    if match:
                        result['part_number'] = match.group(1)
            
            result['found'] = True
        
        return result
    
    # ==========================================
    # 2. เดิน tree หารุ่นรถ
    # ==========================================
    
    def get_cc_categories(self, vehicle_type: str = "SCOOTER") -> List[str]:
        """ดึงรายการ CC ที่มี"""
        url = f"{self.BASE_URL}/honda-motorcycle"
        r = self._get_with_retry(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        categories = []
        
        pattern = re.compile(rf'/honda-motorcycle/(\d+)-{vehicle_type}')
        for link in soup.find_all('a', href=pattern):
            match = pattern.search(link['href'])
            if match:
                cc = match.group(1)
                if cc not in categories:
                    categories.append(cc)
        
        return sorted(categories, key=int)
    
    def get_models(self, cc: str, vehicle_type: str = "SCOOTER") -> List[Dict]:
        """ดึงรายการรุ่นรถตาม CC"""
        url = f"{self.BASE_URL}/honda-motorcycle/{cc}-{vehicle_type}"
        r = self._get_with_retry(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        models = []
        seen = set()
        
        pattern = re.compile(rf'/honda-motorcycle/{cc}-{vehicle_type}/([^/]+)$')
        for link in soup.find_all('a', href=pattern):
            match = pattern.search(link['href'])
            if match:
                model_name = match.group(1)
                if model_name not in seen:
                    seen.add(model_name)
                    models.append({
                        'name': model_name,
                        'url': self.BASE_URL + link['href']
                    })
        
        return models
    
    def get_years(self, cc: str, model: str, vehicle_type: str = "SCOOTER") -> List[str]:
        """ดึงรายการปีของรุ่นรถ"""
        url = f"{self.BASE_URL}/honda-motorcycle/{cc}-{vehicle_type}/{model}"
        r = self._get_with_retry(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        years = []
        
        pattern = re.compile(rf'/honda-motorcycle/{cc}-{vehicle_type}/{model}/(\d{{4}})')
        for link in soup.find_all('a', href=pattern):
            match = pattern.search(link['href'])
            if match:
                year = match.group(1)
                if year not in years:
                    years.append(year)
        
        return sorted(years, reverse=True)
    
    def get_model_codes(self, cc: str, model: str, year: str, 
                         vehicle_type: str = "SCOOTER") -> List[Dict]:
        """ดึงรายการรหัสรุ่นรถ"""
        url = f"{self.BASE_URL}/honda-motorcycle/{cc}-{vehicle_type}/{model}/{year}"
        r = self._get_with_retry(url)
        soup = BeautifulSoup(r.text, 'html.parser')
        codes = []
        seen = set()
        
        pattern = re.compile(
            rf'/honda-motorcycle/{cc}-{vehicle_type}/{model}/{year}/([A-Z0-9]+)/(\d+)$'
        )
        for link in soup.find_all('a', href=pattern):
            match = pattern.search(link['href'])
            if match:
                code = match.group(1)
                vehicle_id = match.group(2)
                if code not in seen:
                    seen.add(code)
                    text = link.get_text(strip=True)
                    name = text.split('\n')[0].strip() if '\n' in text else text.strip()
                    name = name.split('Honda')[0].strip()
                    name = re.sub(r'\s+', ' ', name)
                    codes.append({
                        'name': name,
                        'code': code,
                        'url': self.BASE_URL + link['href'],
                        'vehicle_id': vehicle_id
                    })
        
        return codes
    
    def get_categories(self, catalog_url: str) -> List[Dict]:
        """ดึงรายการหมวดอะไหล่"""
        r = self._get_with_retry(catalog_url)
        soup = BeautifulSoup(r.text, 'html.parser')
        categories = []
        seen = set()
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text(strip=True)
            
            if 'สำหรับ Honda' in text and '/honda-motorcycle/' in href:
                cat_name = text.split('สำหรับ')[0].strip()
                
                if cat_name and cat_name not in seen:
                    seen.add(cat_name)
                    categories.append({
                        'name': cat_name,
                        'url': self.BASE_URL + href if href.startswith('/') else href
                    })
        
        return categories
    
    def get_category_extraction(self, category_url: str) -> Dict:
        """
        ดึงรายการอะไหล่จากหมวด
        
        Extracts:
        - part_number, name, price: from Schema.org Microdata
        - ref_number: from span.ref-libelle (diagram reference)
        - quantity: null (only available in JS-rendered exploded diagram)
        
        No deduplication — same part in multiple positions is preserved.
        """
        r = self._get_with_retry(category_url)
        return {
            'source_url': r.url,
            'source_content_hash': hashlib.sha256(r.content).hexdigest(),
            'parts': parse_category_html(r.text),
        }

    def get_parts_from_category(self, category_url: str) -> List[Dict]:
        """Backward-compatible list-only category extraction."""
        return self.get_category_extraction(category_url)['parts']
    
    # ==========================================
    # 3. ดึงอะไหล่ทั้งหมดของรุ่นรถ
    # ==========================================
    
    def scrape_full_model(self, cc: str, model: str, year: str,
                          vehicle_type: str = "SCOOTER") -> List[Part]:
        """
        ดึงอะไหล่ทั้งหมดของรุ่นรถ
        """
        all_parts = []
        self.last_failures = []
        captcha_encountered = False
        
        print(f"🔍 กำลังดึงรหัสรุ่น Honda {model} {cc}cc ปี {year}...")
        model_codes = self.get_model_codes(cc, model, year, vehicle_type)
        print(f"📋 พบ {len(model_codes)} รหัสรุ่น")
        if not model_codes:
            self.last_failures.append(f"MODEL_DISCOVERY:{model}:{year}:empty")
        
        for code_info in model_codes:
            print(f"\n🏍️  {code_info['name']} ({code_info['code']})")
            
            categories = self.get_categories(code_info['url'])
            print(f"   📁 {len(categories)} หมวดอะไหล่")
            
            for i, cat in enumerate(categories, 1):
                try:
                    parts_data = self.get_parts_from_category(cat['url'])
                    
                    for p in parts_data:
                        all_parts.append(Part(
                            part_number=p['part_number'],
                            part_number_raw=p['part_number_raw'],
                            name=p['name'],
                            price=p['price'],
                            category=cat['name'],
                            model=code_info['name'],
                            year=year,
                            model_code=code_info['code'],
                        ))
                    
                    print(f"   [{i}/{len(categories)}] ✅ {cat['name']}: {len(parts_data)} อะไหล่")
                    
                except CaptchaError as e:
                    self.last_failures.append(
                        f"{code_info['code']}:{cat['name']}:CAPTCHA"
                    )
                    print(f"   [{i}/{len(categories)}] ❌ {cat['name']}: {e}")
                    captcha_encountered = True
                    break
                except Exception as e:
                    self.last_failures.append(
                        f"{code_info['code']}:{cat['name']}:{type(e).__name__}"
                    )
                    print(f"   [{i}/{len(categories)}] ❌ {cat['name']}: {e}")

            if captcha_encountered:
                break
        
        return all_parts
    
    # ==========================================
    # บันทึกไฟล์
    # ==========================================
    
    def save_to_csv(self, parts: List[Part], filename: str):
        """บันทึกข้อมูลอะไหล่ลง CSV"""
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow([
                'Part Number', 'Part Number (Raw)', 'Name', 'Price',
                'Category', 'Model', 'Year', 'Model Code'
            ])
            for part in parts:
                writer.writerow([
                    part.part_number, part.part_number_raw, part.name,
                    part.price, part.category, part.model, part.year,
                    part.model_code,
                ])
        print(f"💾 บันทึก {len(parts)} อะไหล่ลง {filename}")
    
    def save_to_json(self, parts: List[Part], filename: str):
        """บันทึกข้อมูลอะไหล่ลง JSON"""
        data = [asdict(part) for part in parts]
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 บันทึก {len(parts)} อะไหล่ลง {filename}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Honda Parts Scraper - ดึงรายการอะไหล่ Honda จาก honda.bike-parts.co.th',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ตัวอย่างการใช้งาน:

  # ค้นหาตามหมายเลขชิ้นส่วน
  python honda_parts_scraper.py search 16450-K35-V01
  
  # ดึงอะไหล่ทั้งหมดของรุ่นรถ
  python honda_parts_scraper.py catalog --cc 160 --model CLICK --year 2024
  
  # ดึงอะไหล่รถมอเตอร์ไซค์ (ไม่ใช่สกู๊ตเตอร์)
  python honda_parts_scraper.py catalog --cc 125 --model WAVE --year 2024 --type MOTO
  
  # ดูรายการรุ่นรถที่มี
  python honda_parts_scraper.py models --cc 160
  
  # ดู CC ที่มี
  python honda_parts_scraper.py cc

⚠️ หมายเหตุ: เว็บมี rate limiting ถ้าเจอ CAPTCHA ให้:
  1. เปิด URL ใน browser แล้วแก้ CAPTCHA
  2. รอ 5 นาทีแล้วลองใหม่
  3. เพิ่ม --delay เป็น 5 หรือมากกว่า
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='คำสั่ง')
    
    # search
    search_parser = subparsers.add_parser('search', help='ค้นหาตามหมายเลขชิ้นส่วน')
    search_parser.add_argument('part_number', help='หมายเลขชิ้นส่วน')
    
    # cc
    cc_parser = subparsers.add_parser('cc', help='ดูรายการ CC ที่มี')
    cc_parser.add_argument('--type', default='SCOOTER', choices=['SCOOTER', 'MOTO'])
    
    # models
    models_parser = subparsers.add_parser('models', help='ดูรายการรุ่นรถ')
    models_parser.add_argument('--cc', required=True, help='ขนาด CC')
    models_parser.add_argument('--type', default='SCOOTER', choices=['SCOOTER', 'MOTO'])
    
    # years
    years_parser = subparsers.add_parser('years', help='ดูรายการปี')
    years_parser.add_argument('--cc', required=True, help='ขนาด CC')
    years_parser.add_argument('--model', required=True, help='ชื่อรุ่น')
    years_parser.add_argument('--type', default='SCOOTER', choices=['SCOOTER', 'MOTO'])
    
    # catalog
    catalog_parser = subparsers.add_parser('catalog', help='ดึงแคตตาล็อกอะไหล่ทั้งหมด')
    catalog_parser.add_argument('--cc', required=True, help='ขนาด CC')
    catalog_parser.add_argument('--model', required=True, help='ชื่อรุ่น')
    catalog_parser.add_argument('--year', required=True, help='ปี')
    catalog_parser.add_argument('--type', default='SCOOTER', choices=['SCOOTER', 'MOTO'])
    catalog_parser.add_argument('--output', '-o', help='ชื่อไฟล์ output')
    catalog_parser.add_argument('--format', '-f', default='csv', choices=['csv', 'json'])
    catalog_parser.add_argument('--delay', type=float, default=2.0, help='หน่วงเวลา (วินาที)')
    catalog_parser.add_argument(
        '--allow-partial',
        action='store_true',
        help='อนุญาตให้เขียน output แม้มี category ล้มเหลว (ค่าเริ่มต้นไม่เขียน)',
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    scraper = HondaPartsScraper(delay=getattr(args, 'delay', 2.0))
    
    print("=" * 60)
    print("🏍️ Honda Parts Scraper")
    print(f"📡 Source: honda.bike-parts.co.th (สาธารณะ ไม่ต้อง login)")
    print("=" * 60)
    
    if args.command == 'search':
        print(f"\n🔍 ค้นหา: {args.part_number}")
        result = scraper.search_by_part_number(args.part_number)
        
        if result.get('error') == 'CAPTCHA':
            print("❌ CAPTCHA - ลองใหม่ภายหลัง")
        elif result['found']:
            print(f"✅ พบข้อมูล:")
            print(f"   หมายเลข: {result['part_number']}")
            print(f"   ชื่อ: {result['name']}")
            print(f"   ราคา: {result['price']}")
            if result['description']:
                print(f"   รายละเอียด: {result['description'][:100]}")
        else:
            print("❌ ไม่พบข้อมูล")
    
    elif args.command == 'cc':
        print(f"\n📋 รายการ CC ({args.type}):")
        ccs = scraper.get_cc_categories(args.type)
        for cc in ccs:
            print(f"   • {cc} cc")
    
    elif args.command == 'models':
        print(f"\n📋 รายการรุ่น ({args.cc}cc {args.type}):")
        models = scraper.get_models(args.cc, args.type)
        for m in models:
            print(f"   • {m['name']}")
    
    elif args.command == 'years':
        print(f"\n📋 รายการปี ({args.model} {args.cc}cc):")
        years = scraper.get_years(args.cc, args.model, args.type)
        for y in years:
            print(f"   • {y}")
    
    elif args.command == 'catalog':
        print(f"\n🏍️ กำลังดึงข้อมูล Honda {args.model} {args.cc}cc ปี {args.year}")
        print(f"⏱️  Delay: {args.delay} วินาที")
        
        parts = scraper.scrape_full_model(args.cc, args.model, args.year, args.type)

        if scraper.last_failures and not args.allow_partial:
            print("\n❌ ไม่เขียน output เพราะ extraction ไม่ครบ:")
            for failure in scraper.last_failures:
                print(f"   • {failure}")
            print("ใช้ --allow-partial เมื่อยอมรับ partial output อย่างชัดเจน")
            raise SystemExit(1)
        
        if parts:
            print(f"\n✅ ดึงข้อมูลสำเร็จ: {len(parts)} อะไหล่")
            
            if args.output:
                output_file = args.output
            else:
                output_file = f"honda_{args.model}_{args.cc}_{args.year}.{args.format}"
            
            if args.format == 'csv':
                scraper.save_to_csv(parts, output_file)
            else:
                scraper.save_to_json(parts, output_file)
            
            print(f"\n📋 ตัวอย่างข้อมูล:")
            for i, part in enumerate(parts[:10]):
                print(f"   {i+1}. {part.part_number} - {part.name} - {part.price}")
            
            if len(parts) > 10:
                print(f"   ... และอีก {len(parts) - 10} อะไหล่")

            if scraper.last_failures:
                print("\n⚠️  Partial output — failures:")
                for failure in scraper.last_failures:
                    print(f"   • {failure}")
                raise SystemExit(1)
        else:
            print("❌ ไม่พบข้อมูลอะไหล่")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
