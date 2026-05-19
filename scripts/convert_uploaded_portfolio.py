from __future__ import annotations

import argparse
from pathlib import Path

from sentinel_core.xlsx_import import xlsx_to_sentinel_csv


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert uploaded portfolio XLSX to Sentinel CSV.")
    parser.add_argument("input", help="Path to the uploaded .xlsx or .xlsm workbook.")
    parser.add_argument("--output", help="Optional output CSV path. Defaults to stdout.")
    parser.add_argument("--sheet", default="Holdings")
    args = parser.parse_args()

    csv_text = xlsx_to_sentinel_csv(args.input, sheet_name=args.sheet)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(csv_text)
        print("Wrote %s" % output)
    else:
        print(csv_text, end="")


if __name__ == "__main__":
    main()
