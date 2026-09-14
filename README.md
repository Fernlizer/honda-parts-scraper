# Honda Parts Scraper

ดึงรายการอะไหล่ Honda จาก [honda.bike-parts.co.th](https://honda.bike-parts.co.th) — เว็บสาธารณะ ไม่ต้อง login

สร้างมาเพื่อช่วยงานวิจัย [engine-lab](https://github.com/Fernlizer/engine-lab) แต่ใช้งานทั่วไปได้

## ทำไมต้อง tool นี้?

- **PEC (pec.thaihonda.co.th)** ต้อง dealer login, ไม่มี public API
- **honda.bike-parts.co.th** เป็นสาธารณะ มีข้อมูลครบ ทุกรุ่น ทุกปี
- Manual copy ใช้เวลานาน — tool นี้ดึงให้อัตโนมัติ
- Output ตรงตาม [engine-lab data schema](https://github.com/Fernlizer/engine-lab/blob/main/specs/data-schema.md)

## ติดตั้ง

```bash
git clone https://github.com/Fernlizer/honda-parts-scraper.git
cd honda-parts-scraper
pip install -r requirements.txt
```

## การใช้งาน

### 1. Honda Parts Scraper (ทั่วไป)

```bash
# ค้นหาตามหมายเลขชิ้นส่วน
python honda_parts_scraper.py search 16450-K35-V01

# ดู CC ที่มี (SCOOTER / MOTO)
python honda_parts_scraper.py cc
python honda_parts_scraper.py cc --type MOTO

# ดูรุ่นรถ
python honda_parts_scraper.py models --cc 160
python honda_parts_scraper.py models --cc 150 --type MOTO

# ดูปีที่มี
python honda_parts_scraper.py years --cc 150 --model CBR --type MOTO

# ดึงแคตตาล็อกทั้งหมด
python honda_parts_scraper.py catalog --cc 160 --model CLICK --year 2024
python honda_parts_scraper.py catalog --cc 150 --model CBR --year 2021 --type MOTO --format json
```

### 2. CBR150 Extractor (สำหรับ engine-lab)

```bash
# ดึง engine parts ปี 2021
python cbr150_extractor.py --year 2021 --engine-only

# ดึงทุก category
python cbr150_extractor.py --year 2021 --all

# ดึงหลายปี
python cbr150_extractor.py --year 2021 2022 2024 --engine-only

# กำหนด output directory
python cbr150_extractor.py --year 2021 --output ~/Desktop/engine-lab/data/parts/honda-cbr150/thailand/2021
```

## Output Format

### honda_parts_scraper.py

CSV หรือ JSON:

| Field | Description |
|-------|-------------|
| Part Number | 12300-K0R-V00 |
| Part Number (Raw) | 12300K0RV00 |
| Name | ฝาครอบฝาสูบ |
| Price | 277,13 ฿ |
| Category | CYLINDER HEAD COVER |
| Model | CLICK 160 ABS |
| Year | 2024 |
| Model Code | ACB160CATR |

### cbr150_extractor.py

JSON ตาม [part-catalog-extraction.schema.json](https://github.com/Fernlizer/engine-lab/blob/main/specs/schemas/part-catalog-extraction.schema.json):

```json
{
  "schema_version": "0.1",
  "dataset_id": "DATASET-HONDA-CBR150-TH-2021-E-1",
  "status": "working",
  "source_id": "SRC-HONDA-THA-BIKE-PARTS-CBR150-2021-2026",
  "observed_at": "2026-09-14",
  "applicability": {
    "manufacturer": "Honda",
    "model": "CBR150R",
    "market": "thailand",
    "year": 2021
  },
  "catalog_locator": {
    "block": "E-1 CYLINDER HEAD COVER"
  },
  "items": [
    {
      "reference_number": "1",
      "part_number": "12311-K56-N00",
      "description": "ฝาครอบฝาสูบ",
      "quantity": 1,
      "status": "candidate"
    }
  ]
}
```

## CBR150 Engine Block Mapping

| Block | Category | CBR150 |
|-------|----------|--------|
| E-1 | CYLINDER HEAD COVER | ✅ |
| E-2 | CYLINDER HEAD | ✅ |
| E-3 | CAMSHAFT - VALVE | ✅ |
| E-4 | CAM CHAIN - TENSIONER | ✅ |
| E-5 | CYLINDER | ✅ |
| E-6 | WATER PUMP | ✅ |
| E-7 | ALTERNATOR | ✅ |
| E-8 | OIL PUMP | ✅ |
| E-9 | LEFT COVER | ❌ ไม่มีใน CBR150RK |
| E-10 | RADIATOR | ✅ |
| E-11 | VARIATOR | ❌ manual gearbox |
| E-12 | CLUTCH | ✅ |
| E-13 | GEARBOX | ✅ |
| E-14 | RIGHT CRANKCASE COVER | ✅ |
| E-15 | LEFT CRANKCASE COVER | ✅ |
| E-16 | CRANKCASE | ❌ |
| E-17 | CRANKSHAFT - PISTON | ✅ |
| E-18 | THROTTLE BODY - INJECTOR | ❌ |
| E-19 | CARBURETOR | ❌ fuel injected |
| E-20 | INTAKE MANIFOLD | ❌ |

## ⚠️ Rate Limiting

เว็บมี reCAPTCHA ถ้าส่ง request เร็วเกินไป:

- **Default delay**: 3 วินาที
- **เจอ CAPTCHA**: รอ 5 นาที หรือเปิด browser แก้
- **แนะนำ**: ใช้ `--delay 5` สำหรับการดึงข้อมูลจำนวนมาก

```bash
# ใช้ delay สูงเพื่อหลีกเลี่ยง CAPTCHA
python cbr150_extractor.py --year 2021 --delay 5
```

## Data Source

- **Website**: [honda.bike-parts.co.th](https://honda.bike-parts.co.th)
- **Type**: Public, no login required
- **Data**: Honda motorcycle/scooter parts catalog
- **Coverage**: Thailand market, all models, all years
- **Format**: Schema.org Microdata (Product)
- **Price**: THB inclusive of 7% VAT

## License

MIT
