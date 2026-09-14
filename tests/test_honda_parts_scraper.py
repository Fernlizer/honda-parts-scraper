import unittest
from pathlib import Path

from honda_parts_scraper import CaptchaError, HondaPartsScraper, parse_category_html


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, url):
        self.url = url

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)

    def get(self, _url, timeout):
        self.timeout = timeout
        return next(self.responses)


class CategoryParserTests(unittest.TestCase):
    def test_reference_is_read_from_outer_row_and_alternatives_are_preserved(self):
        html = (FIXTURES / "category-e1.html").read_text(encoding="utf-8")

        parts = parse_category_html(html)

        self.assertEqual(3, len(parts))
        self.assertEqual(["1", "3", "3"], [part["ref_number"] for part in parts])
        self.assertEqual(
            ["12311-K56-N00", "90017-KGH-900", "90017-KPP-900"],
            [part["part_number"] for part in parts],
        )
        self.assertTrue(all(part["quantity"] is None for part in parts))


class CaptchaPolicyTests(unittest.TestCase):
    def test_captcha_fails_immediately_by_default(self):
        sleeps = []
        scraper = HondaPartsScraper(delay=0, sleep_fn=sleeps.append)
        scraper.session = FakeSession([FakeResponse("https://example.test/captcha/unlock")])

        with self.assertRaises(CaptchaError):
            scraper._get_with_retry("https://example.test/catalog")

        self.assertEqual([], sleeps)

    def test_explicit_wait_retries_with_bounded_attempts(self):
        sleeps = []
        scraper = HondaPartsScraper(
            delay=0,
            max_retries=2,
            wait_on_captcha=True,
            captcha_wait_seconds=5,
            sleep_fn=sleeps.append,
        )
        scraper.session = FakeSession([
            FakeResponse("https://example.test/captcha/unlock"),
            FakeResponse("https://example.test/catalog"),
        ])

        response = scraper._get_with_retry("https://example.test/catalog")

        self.assertEqual("https://example.test/catalog", response.url)
        self.assertIn(5, sleeps)


class FullCatalogFailureTests(unittest.TestCase):
    def test_partial_category_failure_is_exposed(self):
        scraper = HondaPartsScraper(delay=0)
        scraper.get_model_codes = lambda *_args: [{
            "code": "TESTCODE",
            "name": "TEST MODEL",
            "url": "https://example.test/model",
        }]
        scraper.get_categories = lambda _url: [
            {"name": "FIRST", "url": "https://example.test/first"},
            {"name": "SECOND", "url": "https://example.test/second"},
        ]

        def category(url):
            if url.endswith("second"):
                raise TimeoutError("fixture timeout")
            return [{
                "part_number": "12345-TEST-000",
                "part_number_raw": "12345TEST000",
                "name": "Fixture part",
                "price": "",
            }]

        scraper.get_parts_from_category = category
        parts = scraper.scrape_full_model("150", "TEST", "2021", "MOTO")

        self.assertEqual(1, len(parts))
        self.assertEqual(["TESTCODE:SECOND:TimeoutError"], scraper.last_failures)

    def test_captcha_stops_remaining_categories(self):
        calls = []
        scraper = HondaPartsScraper(delay=0)
        scraper.get_model_codes = lambda *_args: [{
            "code": "TESTCODE",
            "name": "TEST MODEL",
            "url": "https://example.test/model",
        }]
        scraper.get_categories = lambda _url: [
            {"name": "FIRST", "url": "https://example.test/first"},
            {"name": "SECOND", "url": "https://example.test/second"},
        ]

        def category(url):
            calls.append(url)
            raise CaptchaError("fixture captcha")

        scraper.get_parts_from_category = category
        parts = scraper.scrape_full_model("150", "TEST", "2021", "MOTO")

        self.assertEqual([], parts)
        self.assertEqual(["https://example.test/first"], calls)
        self.assertEqual(["TESTCODE:FIRST:CAPTCHA"], scraper.last_failures)


if __name__ == "__main__":
    unittest.main()
