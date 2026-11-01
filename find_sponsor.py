"""Search the sponsor list for a company, to fill in company_aliases.csv.

Run it, type part of a company name (e.g. 'stripe'), and it lists every
employer on the DETE list whose name contains that text. Press Enter on an
empty line to stop.
"""
from pathlib import Path

import pandas as pd

SPONSORS = Path("data/processed/sponsors_2026.csv")


def main():
    sponsors = pd.read_csv(SPONSORS)
    while True:
        text = input("\nCompany name to search (Enter to stop): ").strip()
        if not text:
            break
        hits = sponsors[sponsors["employer"].str.contains(text, case=False, regex=False)]
        if hits.empty:
            print("  no employer on the 2026 list contains that text")
            continue
        print(hits[["employer", "name_key", "total", "months_active"]]
              .sort_values("total", ascending=False).head(15).to_string(index=False))
        print("  -> copy the right name_key(s) into company_aliases.csv (separate several with ;)")


if __name__ == "__main__":
    main()
