"""This script only READS the raw file and prints what is inside.
It never changes or overwrites anything in data/raw.
"""
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/employment-permits-issued-to-companies-2026.xlsx")


def main():
    if not RAW.exists():
        print(f"File not found: {RAW.resolve()}")
        print("Download it first (see README > Setup).")
        return

    # header=None: show every row exactly as it is, including any title rows
    sheets = pd.read_excel(RAW, sheet_name=None, header=None)
    print(f"File: {RAW.name}  ({RAW.stat().st_size:,} bytes)")
    print(f"Sheets: {list(sheets)}\n")

    for name, df in sheets.items():
        print("=" * 70)
        print(f"Sheet '{name}': {df.shape[0]:,} rows x {df.shape[1]} columns")
        print("First 12 rows (raw, no header):")
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(df.head(12).to_string())
        print("Last 3 rows (checking for a TOTAL row):")
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(df.tail(3).to_string())
        print()


if __name__ == "__main__":
    main()