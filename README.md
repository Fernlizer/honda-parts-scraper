# Honda Parts Scraper

ดึงรายการอะไหล่ Honda จาก [honda.bike-parts.co.th](https://honda.bike-parts.co.th) — เว็บสาธารณะ ไม่ต้อง login

สร้างมาเพื่อช่วยงานวิจัย [engine-lab](https://github.com/Fernlizer/engine-lab) แต่ใช้งานทั่วไปได้

## ทำไมต้อง tool นี้?

- **PEC (pec.thaihonda.co.th)** เป็น official dynamic catalog ที่ automation และการอ้าง deep link ทำได้ยาก
- **honda.bike-parts.co.th** เป็นแหล่งสาธารณะสำหรับ candidate extraction แต่ไม่รับประกัน coverage ทุก model/year
- Manual copy ใช้เวลานาน — tool นี้ดึงให้อัตโนมัติ
- Output ตรงตาม [engine-lab data schema](https://github.com/Fernlizer/engine-lab/blob/main/specs/data-schema.md) v0.2 และมี run manifest แยกต่างหาก

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

# ค่าเริ่มต้นจะไม่เขียนไฟล์ถ้ามี category ล้มเหลว
# ใช้เฉพาะเมื่อยอมรับ partial output และ non-zero exit code
python honda_parts_scraper.py catalog --cc 150 --model CBR --year 2021 --type MOTO --allow-partial
```

### 2. CBR150 Extractor (สำหรับ engine-lab)

```bash
# ดึง engine parts ปี 2021 (ต้องระบุ model code ถ้าพบหลาย code)
python cbr150_extractor.py --year 2021 --model-code CBR150RK --engine-only

# ดึงทุก category
python cbr150_extractor.py --year 2021 --all

# เลือก model code เฉพาะ
python cbr150_extractor.py --year 2021 --model-code CBR150RK --engine-only

# ดึงเฉพาะ block เพื่อลดจำนวน request
python cbr150_extractor.py --year 2021 --model-code CBR150RK --block E-4 E-5

# ดึงหลายปี
python cbr150_extractor.py --year 2021 2022 2024 --engine-only

# กำหนด output directory
python cbr150_extractor.py --year 2021 --model-code CBR150RK \
  --output ~/engine-lab/data/parts/honda-cbr150/thailand/2021/candidate/bike-parts/CBR150RK

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
  "schema_version": "0.2",
  "dataset_id": "DATASET-HONDA-CBR150RK-TH-2021-E-1",
  "stage": "raw_extraction",
  "status": "candidate",
  "evidence_level": "C",
  "source_id": "SRC-HONDA-BIKE-PARTS-TH-CBR150RK-2021",
  "source_url": "https://honda.bike-parts.co.th/honda-motorcycle/150-MOTO/CBR/2021/CBR150RK/CYLINDER-HEAD-COVER/108614/E1/0/41739",
  "source_content_hash": "c605ef6b06eaa5335c8e75eec97255da43387d76415de2170d41847f18e385bd",
  "observed_at": "2026-09-14",
  "content_hash": "c24fd03da1d3a12262749283c86144e465b73dc808ecbc85e770be7aab36465f",
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
  "price_policy": "Observed retail prices are excluded from Engine Lab extraction records because they are volatile and are not engineering parameters.",
  "items": [
    {
      "reference_number": "1",
      "part_number": "12311-K56-N00",
      "description": "ฝาครอบฝาสูบ",
      "quantity": null,
      "status": "candidate",
      "notes": "Secondary-source catalog identity. Physical engineering attributes remain UNKNOWN."
    }
  ],
  "parameter_series": [],
  "unresolved_references": ["catalog_quantity:one_or_more_items:unknown"],
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

### Run status and dataset completeness are separate

Every run writes `_extraction-manifest.json`. `run_status: complete` means every requested page was fetched and parsed. It does not mean all engineering fields are known. For example, a successfully fetched page still has `completeness_status: partial` while catalog quantity remains unknown.

### Output directory convention

```
data/parts/honda-cbr150/{market}/{year}/
├── candidate/
│   └── bike-parts/       # scraper output (evidence level C)
│       └── CBR150RK/      # exact model code prevents variant overwrite
└── verified/
    └── pec/              # PEC cross-checked (evidence level A)
```

Candidate and verified data must never overwrite each other.

## Catalog Block IDs

Block ID ถูกอ่านจาก URL ของ catalog โดยตรง เช่น `/E1/` → `E-1` และ `/E23/` → `E-23` ไม่ใช้ตารางชื่อหมวดแบบ hardcode เพราะลำดับ block แตกต่างกันได้ตาม model code และ revision ของ catalog

## Known Limitations

| Limitation | Impact | Workaround |
|-----------|--------|------------|
| Quantity not in observed static product rows | `quantity: null` | Cross-check with PEC or another source that explicitly reports BOM quantity |
| Reference comes from product-row label | Cannot prove hotspot geometry | Cross-check exploded diagram in PEC |
| honda.bike-parts.co.th is secondary source | `evidence_level: C` | Cross-check with PEC |
| Rate limiting (reCAPTCHA) | Extraction stops immediately by default | Reduce scope with `--block`; opt in to bounded waiting with `--wait-on-captcha` |
| Multiple model codes | Extraction refuses to guess | Provide `--model-code` explicitly |

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
- **Price**: Present on the website but intentionally excluded from Engine Lab records
- **Evidence Level**: C (secondary source)

## License

MIT
