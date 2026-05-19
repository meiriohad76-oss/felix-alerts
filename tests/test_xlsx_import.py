from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from sentinel_core.xlsx_import import (
    extract_holdings_rows,
    holdings_to_sentinel_csv,
    xlsx_bytes_to_sentinel_csv,
    xlsx_to_sentinel_csv,
)


def write_minimal_xlsx(path: Path) -> None:
    workbook = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Holdings" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    shared = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="9" uniqueCount="9">
  <si><t>Symbol</t></si><si><t>Shares</t></si><si><t>Cost</t></si><si><t>Value</t></si><si><t>Weight</t></si>
  <si><t>AAPL</t></si><si><t>TOTAL</t></si><si><t>QQQ</t></si><si><t>45000</t></si>
</sst>"""
    sheet = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c><c r="E1" t="s"><v>4</v></c></row>
    <row r="2"><c r="A2" t="s"><v>5</v></c><c r="B2"><v>10</v></c><c r="C2"><v>100</v></c><c r="D2"><v>1000</v></c><c r="E2"><v>0.1</v></c></row>
    <row r="3"><c r="A3" t="s"><v>8</v></c><c r="B3"><v>99</v></c><c r="C3"><v>1</v></c><c r="D3"><v>99</v></c><c r="E3"><v>0.01</v></c></row>
    <row r="4"><c r="A4" t="s"><v>7</v></c><c r="B4"><v>3</v></c><c r="C4"><v>400</v></c><c r="D4"><v>1200</v></c><c r="E4"><v>0.2</v></c></row>
    <row r="5"><c r="A5" t="s"><v>6</v></c><c r="B5"><v>13</v></c><c r="C5"><v>1</v></c><c r="D5"><v>13</v></c><c r="E5"><v>0.03</v></c></row>
  </sheetData>
</worksheet>"""
    with ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/sharedStrings.xml", shared)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


class XlsxImportTests(unittest.TestCase):
    def test_extract_holdings_skips_invalid_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.xlsx"
            write_minimal_xlsx(path)
            rows = extract_holdings_rows(path)
            self.assertEqual([row["Symbol"] for row in rows], ["AAPL", "QQQ"])

    def test_xlsx_to_sentinel_csv_maps_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.xlsx"
            write_minimal_xlsx(path)
            csv_text = xlsx_to_sentinel_csv(path)
            self.assertIn("AAPL,investor,10,100,", csv_text)
            self.assertIn("QQQ,investor,3,400,", csv_text)

    def test_xlsx_conversion_defaults_broad_etfs_to_investor(self):
        csv_text = holdings_to_sentinel_csv([{"Symbol": "VOO", "Shares": "2", "Cost": "400"}])

        self.assertIn("VOO,investor,2,400,", csv_text)
        self.assertNotIn("VOO,index", csv_text)

    def test_xlsx_bytes_to_sentinel_csv_returns_sheet_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.xlsm"
            write_minimal_xlsx(path)
            sheet_name, csv_text = xlsx_bytes_to_sentinel_csv(path.read_bytes())
            self.assertEqual(sheet_name, "Holdings")
            self.assertIn("AAPL,investor,10,100,", csv_text)


if __name__ == "__main__":
    unittest.main()
