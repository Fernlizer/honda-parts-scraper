# Honda Parts Scraper

ดึงรายการอะไหล่ Honda จาก [honda.bike-parts.co.th](https://honda.bike-parts.co.th) — เว็บสาธารณะ ไม่ต้อง login

สร้างมาเพื่อช่วยงานวิจัย [engine-lab](https://github.com/Fernlizer/engine-lab) แต่ใช้งานทั่วไปได้

## ทำไมต้อง tool นี้?

- **PEC (pec.thaihonda.co.th)** ต้อง dealer login, ไม่มี public API
- **honda.bike-parts.co.th** เป็นสาธารณะ มีข้อมูลครบ ทุกรุ่น ทุกปี
- Manual copy ใช้เวลานาน — tool นี้ดึงให้อัตโนมัติ
- Output ตรงตาม [engine-lab data schema](https://github.com/Fernlizer/engine-lab/blob/main/specs/data-schema.md) v0.1

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

# เลือก model code เฉพาะ
python cbr150_extractor.py --year 2021 --model-code CBR150RK --engine-only

# ดึงหลายปี
python cbr150_extractor.py --year 2021 2022 2024 --engine-only

# กำหนด output directory
python cbr150_extractor.py --year 2021 --output ~/engine-lab/data/parts/honda-cbr150/thailand/2021

# รอ CAPTCHA แทน fail-fast
python cbr150_extractor.py --year 2021 --wait-on-captcha
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
  "dataset_id": "DATASET-HONDA-CBR150RK-TH-2021-E-1",
  "stage": "raw_extraction",
  "status": "candidate",
  "evidence_level": "C",
  "source_id": "SRC-HONDA-THA-BIKE-PARTS-CO-TH-CBR150RK-2021-2026",
  "source_url": "https://honda.bike-parts.co.th/honda-motorcycle/150-MOTO/CBR/2021/CBR150RK/41739",
  "observed_at": "2026-09-14",
  "content_hash": "efaecbcfdfb714f6",
  "applicability": {
    "manufacturer": "Honda",
    "model": "CBR150R",
    "model_code": "CBR150RK",
    "market": "thailand",
    "year": 2021,
    "serial_range": null,
    "area_code": null
  },
  "catalog_locator": {
    "block": "E-1 CYLINDER HEAD COVER",
    "page": null
  },
  "completeness_status": "partial",
  "price_policy": "THB inclusive of 7% VAT",
  "items": [
    {
      "reference_number": "1",
      "part_number": "12311-K56-N00",
      "description": "ฝาครอบฝาสูบ",
      "quantity": null,
      "status": "candidate",
      "notes": "Source: https://... Price: 651,63 ฿. Physical dimensions and material remain unknown."
    }
  ],
  "parameter_series": [],
  "unresolved_references": [
    "E-9:LEFT COVER:CAPTCHA",
    "E-18:THROTTLE BODY:timeout"
  ],
  "notes": "Evidence level C — secondary source, pending PEC cross-check."
}
```

## Key Design Decisions

### Three separate dimensions

```json
{
  "stage": "raw_extraction",
  "status": "candidate",
  "evidence_level": "C"
}
```

- **stage**: pipeline position — `raw_extraction` → `cross_checked` → `normalized`
- **status**: trust level — `candidate` → `verified` / `disputed`
- **evidence_level**: source quality — A (factory) → F (derived) / UNKNOWN

### Model codes are opaque identifiers

```json
{
  "model": "CBR150R",
  "model_code": "CBR150RK"
}
```

Model codes are **never translated** to market names. `CBR150RM` does not mean Malaysia — it's a generation/year revision indicator per OEM evidence.

### Quantity is null when unknown

```json
{
  "reference_number": "3",
  "part_number": "90017-KGH-900",
  "quantity": null
}
```

The scraper extracts `reference_number` from `span.ref-libelle` (diagram reference). Quantity is only available in the JavaScript-rendered exploded diagram and cannot be extracted from static HTML. Setting `null` preserves the "no invented values" principle.

### No deduplication by part number

Same part number can appear in multiple positions with different quantities. Deduplication would lose positional information.

### Output directory convention

```
data/parts/honda-cbr150/{market}/{year}/
├── candidate/
│   └── bike-parts/       # scraper output (evidence level C)
└── verified/
    └── pec/              # PEC cross-checked (evidence level A)
```

Candidate and verified data must never overwrite each other.

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

## Known Limitations

| Limitation | Impact | Workaround |
|-----------|--------|------------|
| Quantity not in static HTML | `quantity: null` | Browser-based extraction needed |
| Reference only, not exploded diagram position | `ref_number` from list, not diagram | Interactive PEC session |
| honda.bike-parts.co.th is secondary source | `evidence_level: C` | Cross-check with PEC |
| Rate limiting (reCAPTCHA) | ~15min block after too many requests | `--delay 5`, `--wait-on-captcha` |
| Model code selection | Manual or first-match | `--model-code` flag |

## PEC Cross-Check Findings

Real discrepancies found between scraper and Thai Honda PEC:

| Category | Scraper | PEC | Issue |
|----------|---------|-----|-------|
| E-1 | — | 90017-KPP-900 | Missing alternative bolt |
| E-2 | 17111-K15-920 | 17111-K15-921 | Different revision |
| E-3 | 14771-MFL-000 | 14771-K45-NL0 | Different part |
| All | qty: 1 | qty: 2, 4, 8 | Quantity not extracted |

This confirms: **scraper alone is not sufficient** — PEC cross-check is required for verified data.

## Data Source

- **Website**: [honda.bike-parts.co.th](https://honda.bike-parts.co.th)
- **Type**: Public, no login required
- **Data**: Honda motorcycle/scooter parts catalog
- **Coverage**: Thailand market, all models, all years
- **Format**: Schema.org Microdata (Product) + HTML ref-libelle
- **Price**: THB inclusive of 7% VAT
- **Evidence Level**: C (secondary source)

## License

MIT
