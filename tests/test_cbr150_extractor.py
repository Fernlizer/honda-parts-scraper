import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cbr150_extractor import (
    build_extraction_record,
    lookup_block_id,
    make_source_id,
    scrape_cbr150_year,
)


class HelperTests(unittest.TestCase):
    def test_block_id_comes_from_catalog_url(self):
        self.assertEqual(
            "E-23",
            lookup_block_id("https://example.test/THROTTLE-BODY/108614/E23/0/41739"),
        )
        self.assertIsNone(lookup_block_id("https://example.test/no-block"))

    def test_source_id_is_stable_and_model_specific(self):
        self.assertEqual(
            "SRC-HONDA-BIKE-PARTS-TH-CBR150RK-2021",
            make_source_id("thailand", "CBR150RK", "2021"),
        )

    def test_unknown_quantity_keeps_dataset_partial(self):
        record = build_extraction_record(
            dataset_id="DATASET-HONDA-CBR150RK-TH-2021-E-1",
            source_id="SRC-HONDA-BIKE-PARTS-TH-CBR150RK-2021",
            source_url="https://example.test/E1/0/41739",
            source_content_hash="a" * 64,
            market="thailand",
            year="2021",
            model_code="CBR150RK",
            block_id="E-1",
            block_name="CYLINDER HEAD COVER",
            parts=[{
                "ref_number": "3",
                "part_number": "90017-KGH-900",
                "name": "โบลต์ยึดฝาครอบฝาสูบ",
                "price": "49,22 ฿",
                "quantity": None,
            }],
        )

        self.assertEqual("partial", record["completeness_status"])
        self.assertEqual(None, record["items"][0]["quantity"])
        self.assertNotIn("49,22", record["items"][0]["notes"])
        self.assertIn("catalog_quantity:one_or_more_items:unknown", record["unresolved_references"])


class FakeHondaPartsScraper:
    def __init__(self, **_kwargs):
        pass

    def get_model_codes(self, *_args):
        return [{"code": "CBR150RK", "url": "https://example.test/model"}]

    def get_categories(self, _url):
        return [
            {"name": "CYLINDER HEAD COVER", "url": "https://example.test/E1/0/41739"},
            {"name": "CYLINDER HEAD", "url": "https://example.test/E2/0/41739"},
        ]

    def get_category_extraction(self, url):
        if "/E2/" in url:
            raise TimeoutError("fixture timeout")
        return {
            "source_url": url,
            "source_content_hash": "b" * 64,
            "parts": [{
                "ref_number": "1",
                "part_number": "12311-K56-N00",
                "name": "ฝาครอบฝาสูบ",
                "price": "651,63 ฿",
                "quantity": None,
            }],
        }


class RunManifestTests(unittest.TestCase):
    def test_partial_run_is_recorded_in_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cbr150_extractor.HondaPartsScraper", FakeHondaPartsScraper):
                files, failures = scrape_cbr150_year(
                    year="2021",
                    market="thailand",
                    model_code="CBR150RK",
                    output_dir=temp_dir,
                    engine_only=True,
                    delay=0,
                )

            manifest = json.loads(
                (Path(temp_dir) / "_extraction-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, len(files))
            self.assertEqual(1, len(failures))
            self.assertEqual("partial", manifest["run_status"])
            self.assertEqual(2, manifest["attempted_category_count"])
            self.assertEqual(failures, manifest["failures"])

    def test_requested_block_missing_from_catalog_is_a_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cbr150_extractor.HondaPartsScraper", FakeHondaPartsScraper):
                files, failures = scrape_cbr150_year(
                    year="2021",
                    market="thailand",
                    model_code="CBR150RK",
                    output_dir=temp_dir,
                    delay=0,
                    blocks=["E-99"],
                )

            manifest = json.loads(
                (Path(temp_dir) / "_extraction-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual([], files)
            self.assertIn("E-99:not_present_in_model_catalog", failures)
            self.assertEqual("failed", manifest["run_status"])


if __name__ == "__main__":
    unittest.main()
