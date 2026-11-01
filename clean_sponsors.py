"""Reads the raw file (never changes it), removes the Total row after checking
the employers add up to it, and saves a clean table to data/processed/.
"""
import re
from pathlib import Path

import pandas as pd

RAW = Path("data/raw/employment-permits-issued-to-companies-2026.xlsx")
OUT_DIR = Path("data/processed")
OUT = OUT_DIR / "sponsors_2026.csv"

# Legal endings that job ads usually leave out ("Stripe" vs "Stripe ... Limited")
LEGAL_SUFFIXES = [
    "DESIGNATED ACTIVITY COMPANY", "COMPANY LIMITED BY GUARANTEE",
    "UNLIMITED COMPANY", "PUBLIC LIMITED COMPANY", "LIMITED", "LTD", "DAC",
    "PLC", "CLG", "ULC", "UC",
]


def name_key(name):
    """Make a simple matching key: upper case, & -> AND, no punctuation, no legal ending."""
    key = str(name).upper().replace("&", " AND ")
    key = re.sub(r"[^A-Z0-9 ]", " ", key)      # punctuation becomes a space
    key = re.sub(r"\s+", " ", key).strip()      # squeeze repeated spaces
    changed = True
    while changed:                              # remove endings like "LIMITED" or "DAC LIMITED"
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if key.endswith(" " + suffix):
                key = key[: -len(suffix) - 1].strip()
                changed = True
    return key


def main():
    df = pd.read_excel(RAW, sheet_name="Export")
    print(f"Loaded {len(df):,} rows (including the Total row)")

    # Rename columns to short names: employer, jan ... sep, total
    rename = {"Employer Name": "employer", "Permits Issued Grand Total": "total"}
    for col in df.columns:
        if col.startswith("Permits Issued ") and col not in rename:
            rename[col] = col.replace("Permits Issued ", "").lower()
    df = df.rename(columns=rename)
    month_cols = [c for c in df.columns if c not in ("employer", "total")]
    print(f"Months in the file: {', '.join(month_cols)}")

    # 1. Separate the Total row, then reconcile before dropping it
    is_total = df["employer"].astype(str).str.strip().str.lower() == "total"
    total_row = df[is_total]
    df = df[~is_total].copy()
    if len(total_row) != 1:
        print(f"WARNING: expected 1 Total row, found {len(total_row)}")

    # 2. Blank cells mean zero permits that month
    df[month_cols + ["total"]] = df[month_cols + ["total"]].fillna(0).astype(int)

    print("\nReconciliation (employers added up vs the file's Total row):")
    all_ok = True
    for col in month_cols + ["total"]:
        ours = int(df[col].sum())
        theirs = int(total_row[col].iloc[0]) if len(total_row) else None
        ok = ours == theirs
        all_ok &= ok
        print(f"  {col:>5}: {ours:>6,} vs {theirs:>6,}  {'OK' if ok else 'MISMATCH'}")
    row_ok = (df[month_cols].sum(axis=1) == df["total"]).all()
    print(f"  Each employer's months add up to its total: {'OK' if row_ok else 'MISMATCH'}")
    print("RESULT:", "PASS" if all_ok and row_ok else "CHECK THE MISMATCHES ABOVE")

    # 3. Matching key and a simple activity measure
    df["employer"] = df["employer"].astype(str).str.strip()
    df["name_key"] = df["employer"].apply(name_key)
    df["months_active"] = (df[month_cols] > 0).sum(axis=1)

    # 4. Flag (don't merge) names that become the same key
    dupes = df[df.duplicated("name_key", keep=False)].sort_values("name_key")
    print(f"\nEmployers sharing a matching key (flagged for review, not merged): {len(dupes)}")
    if len(dupes):
        print(dupes[["employer", "name_key", "total"]].head(20).to_string(index=False))

    # 5. Quick profile
    print(f"\nEmployers: {len(df):,}   Permits Jan-{month_cols[-1].title()}: {df['total'].sum():,}")
    print(f"Employers with just 1 permit: {(df['total'] == 1).sum():,} "
          f"({(df['total'] == 1).mean():.0%})")
    print(f"Employers with 10+ permits: {(df['total'] >= 10).sum():,}")
    print("\nTop 15 sponsors so far in 2026:")
    print(df.nlargest(15, "total")[["employer", "total", "months_active"]].to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cols = ["employer", "name_key", "total", "months_active"] + month_cols
    df[cols].sort_values("total", ascending=False).to_csv(OUT, index=False)
    print(f"\nSaved {len(df):,} employers to {OUT}")


if __name__ == "__main__":
    main()
