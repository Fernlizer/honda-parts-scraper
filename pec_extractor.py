#!/usr/bin/env python3
"""Bounded Thai Honda PEC extraction for Engine Lab candidate datasets.

The site is an ASP.NET Web Forms application. This client follows only the
public model/year/block workflow and records each source response hash. It does
not retain prices or promote automated rows to verified status.
"""

import argparse
import hashlib
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

try:
    from curl_cffi import requests
except ImportError:
    import requests

from bs4 import BeautifulSoup


START_URL = "https://pec.thaihonda.co.th/Applications/Common/Programs/StartApp.aspx"
SOURCE_ID = "SRC-HONDA-THA-PEC-CBR150R-2021-2026"


class PecExtractionError(RuntimeError):
    """PEC workflow or response did not satisfy an expected invariant."""


def hidden_fields(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    return {
        element["name"]: element.get("value", "")
        for element in soup.select("input[type=hidden][name]")
    }


def popup_url(html: str, base_url: str) -> str:
    match = re.search(r"src\s*:\s*'([^']*SYP00010[^']*)'", html)
    if not match:
        raise PecExtractionError("terms popup URL was not present")
    return urljoin(base_url, match.group(1))


def card_submit_name(html: str, exact_text: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    label = next(
        (
            element
            for element in soup.find_all("span")
            if element.get_text(strip=True) == exact_text
        ),
        None,
    )
    if label is None:
        raise PecExtractionError(f"card not found: {exact_text}")
    table = label.find_parent("table")
    match = re.search(
        r"getElementById\('([^']+)'\)",
        table.get("onclick", "") if table else "",
    )
    button = soup.find(id=match.group(1)) if match else None
    if button is None or not button.get("name"):
        raise PecExtractionError(f"card submit control not found: {exact_text}")
    return button["name"]


def block_event_target(html: str, block: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    image = next(
        (
            element
            for element in soup.select("img[src]")
            if re.search(rf"/{re.escape(block)}\.jpg(?:\?|$)", element["src"], re.I)
        ),
        None,
    )
    link = image.find_parent("table").find("a", href=True) if image else None
    match = re.search(r"__doPostBack\('([^']+)'", link["href"] if link else "")
    if not match:
        raise PecExtractionError(f"catalog block not found: {block}")
    return match.group(1)


def reference_numbers(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    observed = []
    for area in soup.find_all("area", onclick=True):
        match = re.search(r"hidSelItemNo'\)\.value='([^']+)'", area["onclick"])
        if match and match.group(1) not in observed:
            observed.append(match.group(1))
    if not observed:
        raise PecExtractionError("no exploded-diagram references were present")
    return sorted(observed, key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value))


def parse_parts_table(html: str, reference_number: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for row in soup.select("#Table1 tbody tr"):
        # PEC retains previously selected rows in the table. Only the row(s)
        # checked by the current hotspot postback belong to this reference.
        if row.select_one('input[type="checkbox"][checked]') is None:
            continue
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        part_element = row.select_one('[id$="_desPRT"]')
        description_element = row.select_one('[id$="_desPNM"]')
        quantity_element = row.select_one('[id$="_desQTY"]')
        identity = cells[1].get_text(" ", strip=True)
        fallback_match = re.search(r"\b\d{5}-[A-Z0-9-]+\b", identity, re.I)
        part_number = (
            part_element.get_text(strip=True)
            if part_element
            else (fallback_match.group(0) if fallback_match else "")
        )
        if not part_number:
            continue
        description = (
            description_element.get_text(" ", strip=True)
            if description_element
            else identity[fallback_match.end():].strip()
        )
        quantity_text = (
            quantity_element.get_text(strip=True)
            if quantity_element
            else cells[2].get_text(" ", strip=True)
        )
        quantity_match = re.fullmatch(r"\d+", quantity_text)
        rows.append(
            {
                "reference_number": reference_number,
                "part_number": part_number.upper(),
                "description": description,
                "quantity": int(quantity_match.group(0)) if quantity_match else None,
                "status": "candidate",
                "notes": "Automated transcription from Thai Honda PEC; pending human review.",
            }
        )
    return rows


class PecClient:
    def __init__(self, delay: float = 1.0, timeout: float = 20.0, sleep_fn=time.sleep):
        self.delay = delay
        self.timeout = timeout
        self.sleep = sleep_fn
        try:
            self.session = requests.Session(impersonate="chrome131")
        except TypeError:
            self.session = requests.Session()
        self._request_count = 0

    def _get(self, url: str):
        if self._request_count:
            self.sleep(self.delay)
        self._request_count += 1
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response

    def _post(self, response, data: Dict[str, str]):
        self.sleep(self.delay)
        self._request_count += 1
        result = self.session.post(response.url, data=data, timeout=self.timeout)
        result.raise_for_status()
        return result

    def _submit(self, response, name: str, value: str = ""):
        data = hidden_fields(response.text)
        data[name] = value
        return self._post(response, data)

    def _event(self, response, target: str):
        data = hidden_fields(response.text)
        data["__EVENTTARGET"] = target
        return self._post(response, data)

    def open_catalog(self):
        landing = self._get(START_URL)
        data = hidden_fields(landing.text)
        data.update({"btn01.x": "1", "btn01.y": "1"})
        popup_host = self._post(landing, data)
        terms = self._get(popup_url(popup_host.text, str(popup_host.url)))
        accepted = self._event(terms, "ctl00$mainCopy$btnAccept")
        if "close" not in accepted.text.lower():
            raise PecExtractionError("terms acceptance response was not recognized")
        catalog = self._submit(popup_host, "btnPopup")
        if "cboMDL_Inq" not in catalog.text:
            raise PecExtractionError("model catalog did not open")
        return catalog

    def select_model_year(self, response, model: str, year: str):
        response = self._submit(response, card_submit_name(response.text, model))
        response = self._submit(response, card_submit_name(response.text, f"รุ่นปี {year}"))
        soup = BeautifulSoup(response.text, "html.parser")
        button = soup.find(id="ctl00_mainCopy_btnPartPict")
        if button is None or not button.get("name"):
            raise PecExtractionError("parts-picture control was not present")
        data = hidden_fields(response.text)
        data.update({f"{button['name']}.x": "1", f"{button['name']}.y": "1"})
        return self._post(response, data)

    def select_block(self, response, block: str):
        return self._event(response, block_event_target(response.text, block))

    def extract_reference(self, response, reference_number: str):
        data = hidden_fields(response.text)
        data["ctl00$mainCopy$hidSelItemNo"] = reference_number
        data["ctl00$mainCopy$btnIMG"] = ""
        return self._post(response, data)


def extract_block(model: str, year: str, block: str, delay: float = 1.0) -> Dict:
    client = PecClient(delay=delay)
    response = client.open_catalog()
    response = client.select_model_year(response, model, year)
    response = client.select_block(response, block)
    references = reference_numbers(response.text)
    transcript_hash = hashlib.sha256()
    observations = []
    items = []
    failures = []

    for reference in references:
        try:
            response = client.extract_reference(response, reference)
            transcript_hash.update(response.content)
            parsed = parse_parts_table(response.text, reference)
            if not parsed:
                failures.append(f"{block}:reference:{reference}:empty_result")
            items.extend(parsed)
            observations.append(
                {
                    "reference_number": reference,
                    "source_url": str(response.url),
                    "source_content_hash": hashlib.sha256(response.content).hexdigest(),
                    "items": len(parsed),
                }
            )
        except Exception as error:
            failures.append(f"{block}:reference:{reference}:{type(error).__name__}")
            break

    unresolved = list(failures)
    if any(item["quantity"] is None for item in items):
        unresolved.append("catalog_quantity:one_or_more_items:unknown")
    completeness = "complete" if not unresolved else ("partial" if items else "failed")
    normalized = json.dumps(items, ensure_ascii=False, sort_keys=True).encode()
    return {
        "schema_version": "0.2",
        "dataset_id": f"DATASET-HONDA-{model}-TH-{year}-PEC-{block}",
        "stage": "raw_extraction",
        "status": "candidate",
        "evidence_level": "A",
        "source_id": SOURCE_ID,
        "source_url": START_URL,
        "source_content_hash": transcript_hash.hexdigest(),
        "source_observations": observations,
        "observed_at": str(date.today()),
        "content_hash": hashlib.sha256(normalized).hexdigest(),
        "applicability": {
            "manufacturer": "Honda",
            "model": model,
            "model_code": None,
            "market": "thailand",
            "year": int(year) if year.isdigit() else year,
            "serial_range": None,
            "area_code": None,
        },
        "catalog_locator": {"block": block, "page": None},
        "completeness_status": completeness,
        "price_policy": "PEC retail prices are excluded because they are volatile and are not engineering parameters.",
        "items": items,
        "parameter_series": [],
        "unresolved_references": unresolved,
        "notes": "Automated Thai Honda PEC extraction. Evidence level describes the primary source; candidate status requires human review before normalization.",
    }


def main():
    parser = argparse.ArgumentParser(description="Extract one Thai Honda PEC block")
    parser.add_argument("--model", default="CBR150R")
    parser.add_argument("--year", required=True)
    parser.add_argument("--block", required=True, help="Exact PEC block, e.g. E-4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    record = extract_block(args.model, args.year, args.block.upper(), args.delay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{record['completeness_status']}: {len(record['items'])} rows -> {args.output}")
    if record["completeness_status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
