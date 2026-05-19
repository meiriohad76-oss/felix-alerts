from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import BinaryIO, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from zipfile import ZipFile

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

VALID_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
WorkbookSource = Union[str, Path, BinaryIO]


def _open_xlsx(source: WorkbookSource) -> ZipFile:
    if hasattr(source, "seek"):
        source.seek(0)
    return ZipFile(source)


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        raise ValueError("Invalid cell reference: %s" % cell_ref)
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - 64
    return value - 1


def _shared_strings(zf: ZipFile) -> Tuple[str, ...]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return ()
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    values = []
    for item in root.findall("main:si", NS):
        values.append("".join(node.text or "" for node in item.iter("{%s}t" % NS["main"])))
    return tuple(values)


def _cell_value(cell: ET.Element, shared_strings: Sequence[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("main:v", NS)
    if cell_type == "s":
        if value is None or value.text is None:
            return ""
        return shared_strings[int(value.text)]
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter("{%s}t" % NS["main"]))
    return value.text if value is not None and value.text is not None else ""


def _sheet_targets(zf: ZipFile) -> Dict[str, str]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    targets = {}
    for sheet in workbook.find("main:sheets", NS):
        rid = sheet.attrib["{%s}id" % NS["rel"]]
        targets[sheet.attrib["name"]] = relmap[rid]
    return targets


def _sheet_path(target: str) -> str:
    normalized = target.lstrip("/")
    return normalized if normalized.startswith("xl/") else "xl/%s" % normalized


def list_xlsx_sheets(source: WorkbookSource) -> Tuple[str, ...]:
    with _open_xlsx(source) as zf:
        return tuple(_sheet_targets(zf))


def read_xlsx_sheet(source: WorkbookSource, sheet_name: str) -> List[List[str]]:
    """Read a worksheet into rows using only the Python standard library."""

    with _open_xlsx(source) as zf:
        targets = _sheet_targets(zf)
        if sheet_name not in targets:
            raise ValueError("Workbook does not contain sheet: %s" % sheet_name)
        target = targets[sheet_name]
        sheet_path = _sheet_path(target)
        shared = _shared_strings(zf)
        root = ET.fromstring(zf.read(sheet_path))
        rows: List[List[str]] = []
        for row in root.findall(".//main:sheetData/main:row", NS):
            values: List[str] = []
            last_idx = -1
            for cell in row.findall("main:c", NS):
                idx = _column_index(cell.attrib["r"])
                while last_idx + 1 < idx:
                    values.append("")
                    last_idx += 1
                values.append(_cell_value(cell, shared))
                last_idx = idx
            rows.append(values)
        return rows


def rows_to_dicts(rows: Sequence[Sequence[str]]) -> List[Dict[str, str]]:
    if not rows:
        return []
    headers = [header.strip() for header in rows[0]]
    output = []
    for row in rows[1:]:
        item = {}
        for idx, header in enumerate(headers):
            if not header:
                continue
            item[header] = row[idx].strip() if idx < len(row) else ""
        output.append(item)
    return output


def _filter_holdings_rows(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    holdings = []
    seen = set()
    for row in rows:
        symbol = row.get("Symbol", "").strip().upper()
        if not symbol or symbol == "TOTAL" or not VALID_TICKER_RE.match(symbol):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        holdings.append(row)
    return holdings


def extract_holdings_rows(source: WorkbookSource, *, sheet_name: str = "Holdings") -> List[Dict[str, str]]:
    rows = rows_to_dicts(read_xlsx_sheet(source, sheet_name))
    return _filter_holdings_rows(rows)


def extract_holdings_rows_auto(
    source: WorkbookSource,
    *,
    preferred_sheet_name: str = "Holdings",
) -> Tuple[str, List[Dict[str, str]]]:
    sheets = list(list_xlsx_sheets(source))
    candidates = []
    if preferred_sheet_name in sheets:
        candidates.append(preferred_sheet_name)
    candidates.extend(sheet for sheet in sheets if sheet not in candidates)

    for sheet_name in candidates:
        rows = rows_to_dicts(read_xlsx_sheet(source, sheet_name))
        if rows and "Symbol" in rows[0]:
            return sheet_name, _filter_holdings_rows(rows)

    if preferred_sheet_name not in sheets:
        raise ValueError(
            "Workbook does not contain sheet '%s' and no sheet with a Symbol column was found."
            % preferred_sheet_name
        )
    raise ValueError("Workbook sheet '%s' does not contain a Symbol column." % preferred_sheet_name)


def holdings_to_sentinel_csv(holdings: Iterable[Dict[str, str]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "ticker",
            "type",
            "shares",
            "entry_price",
            "entry_date",
            "current_profit_lock",
            "notes",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in holdings:
        ticker = row.get("Symbol", "").strip().upper()
        notes = "source=xlsx holdings"
        if row.get("Value"):
            notes += "; value=%s" % row["Value"]
        if row.get("Weight"):
            notes += "; weight=%s" % row["Weight"]
        writer.writerow(
            {
                "ticker": ticker,
                "type": "investor",
                "shares": row.get("Shares", ""),
                "entry_price": row.get("Cost", ""),
                "entry_date": "",
                "current_profit_lock": "",
                "notes": notes,
            }
        )
    return output.getvalue()


def xlsx_to_sentinel_csv(source: WorkbookSource, *, sheet_name: str = "Holdings") -> str:
    return holdings_to_sentinel_csv(extract_holdings_rows(source, sheet_name=sheet_name))


def xlsx_to_sentinel_csv_auto(
    source: WorkbookSource,
    *,
    preferred_sheet_name: str = "Holdings",
) -> Tuple[str, str]:
    sheet_name, holdings = extract_holdings_rows_auto(
        source,
        preferred_sheet_name=preferred_sheet_name,
    )
    return sheet_name, holdings_to_sentinel_csv(holdings)


def xlsx_bytes_to_sentinel_csv(
    content: bytes,
    *,
    preferred_sheet_name: str = "Holdings",
) -> Tuple[str, str]:
    return xlsx_to_sentinel_csv_auto(
        io.BytesIO(content),
        preferred_sheet_name=preferred_sheet_name,
    )
