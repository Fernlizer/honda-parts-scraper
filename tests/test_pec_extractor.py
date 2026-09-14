import unittest

from pec_extractor import (
    PecExtractionError,
    block_event_target,
    card_submit_name,
    parse_parts_table,
    reference_numbers,
)


class PecParserTests(unittest.TestCase):
    def test_card_submit_name_uses_exact_visible_label(self):
        html = """
        <table onclick="document.getElementById('yearButton').click();">
          <tr><td><span>รุ่นปี 2021</span></td></tr>
        </table>
        <input id="yearButton" name="ctl00$yearButton" type="submit" />
        """
        self.assertEqual("ctl00$yearButton", card_submit_name(html, "รุ่นปี 2021"))

    def test_missing_card_is_an_explicit_failure(self):
        with self.assertRaises(PecExtractionError):
            card_submit_name("<html></html>", "CBR150R")

    def test_block_target_comes_from_exact_image_path(self):
        html = """
        <table><tr><td><a href="javascript:__doPostBack('ctl00$block4','')">
          <img src="../../../Image/E-4.jpg?ver=1" />
        </a></td></tr></table>
        """
        self.assertEqual("ctl00$block4", block_event_target(html, "E-4"))

    def test_reference_numbers_are_unique_and_naturally_sorted(self):
        html = """
        <map>
          <area onclick="document.getElementById('ctl00_mainCopy_hidSelItemNo').value='10';" />
          <area onclick="document.getElementById('ctl00_mainCopy_hidSelItemNo').value='2';" />
          <area onclick="document.getElementById('ctl00_mainCopy_hidSelItemNo').value='2';" />
        </map>
        """
        self.assertEqual(["2", "10"], reference_numbers(html))

    def test_parts_table_preserves_description_and_quantity(self):
        html = """
        <table id="Table1"><tbody><tr>
          <td><input type="checkbox" checked /></td>
          <td><span id="x_desPRT">14401-K56-N01</span><span id="x_desPNM">โซ่ราวลิ้น (120 ข้อ)</span></td>
          <td><span id="x_desQTY">1</span></td><td>553.00</td><td></td>
        </tr></tbody></table>
        """
        self.assertEqual(
            [{
                "reference_number": "1",
                "part_number": "14401-K56-N01",
                "description": "โซ่ราวลิ้น (120 ข้อ)",
                "quantity": 1,
                "status": "candidate",
                "notes": "Automated transcription from Thai Honda PEC; pending human review.",
            }],
            parse_parts_table(html, "1"),
        )

    def test_previous_unchecked_rows_are_not_reassigned(self):
        html = """
        <table id="Table1"><tbody>
          <tr><td><input type="checkbox" /></td><td>14401-K56-N01 old</td><td>1</td></tr>
          <tr><td><input type="checkbox" checked /></td><td>14510-K56-N00 current</td><td>1</td></tr>
        </tbody></table>
        """
        rows = parse_parts_table(html, "2")
        self.assertEqual(["14510-K56-N00"], [row["part_number"] for row in rows])


if __name__ == "__main__":
    unittest.main()
