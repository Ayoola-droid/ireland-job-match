"""Add visa-sponsorship evidence to each scored job and rank the shortlist.

Joins data/processed/jobs_scored.csv to the DETE sponsor list through
company_aliases.csv (your checked list of brand name -> legal name keys).
Writes data/processed/jobs_ranked.csv.
"""
from pathlib import Path

import pandas as pd

JOBS = Path("data/processed/jobs_scored.csv")
SPONSORS = Path("data/processed/sponsors_2026.csv")
ALIASES = Path("company_aliases.csv")
OUT = Path("data/processed/jobs_ranked.csv")

# ---- Settings you can change ------------------------------------------------
STRONG_PERMITS = 10  # "strong sponsor": at least this many permits so far this year...
STRONG_MONTHS = 6    # ...issued in at least this many different months
# -----------------------------------------------------------------------------


def sponsor_level(permits, months):
    if permits == 0:
        return "not on list"
    if permits >= STRONG_PERMITS and months >= STRONG_MONTHS:
        return "strong"
    return "some"


def main():
    jobs = pd.read_csv(JOBS)
    sponsors = pd.read_csv(SPONSORS)
    aliases = pd.read_csv(ALIASES).fillna("")

    # Add up every legal entity listed for each company (e.g. Stripe has two)
    by_key = sponsors.groupby("name_key").agg(permits=("total", "sum"),
                                             months=("months_active", "max"))
    rows = []
    for _, a in aliases.iterrows():
        keys = [k.strip() for k in a["dete_name_keys"].split(";") if k.strip()]
        unknown = [k for k in keys if k not in by_key.index]
        if unknown:
            print(f"  ! {a['company']}: name key not found on sponsor list: {unknown}")
        found = by_key.loc[[k for k in keys if k in by_key.index]]
        permits = int(found["permits"].sum()) if len(found) else 0
        months = int(found["months"].max()) if len(found) else 0
        rows.append({"company": a["company"], "sponsor_permits_2026": permits,
                     "sponsor_months_active": months,
                     "sponsor_level": sponsor_level(permits, months)})
    lookup = pd.DataFrame(rows)

    missing = sorted(set(jobs["company"]) - set(lookup["company"]))
    if missing:
        print(f"  ! companies not in company_aliases.csv yet: {missing}")

    print("Sponsor evidence per company (DETE permits, Jan-Sep 2026):")
    print(lookup.sort_values("sponsor_permits_2026", ascending=False).to_string(index=False))

    jobs = jobs.merge(lookup, on="company", how="left")
    jobs["sponsor_level"] = jobs["sponsor_level"].fillna("unknown")
    jobs["sponsor_permits_2026"] = jobs["sponsor_permits_2026"].fillna(0).astype(int)

    # Rank: shortlisted first, then strong sponsors, then best skill match
    level_order = {"strong": 0, "some": 1, "not on list": 2, "unknown": 3}
    jobs["sponsor_rank"] = jobs["sponsor_level"].map(level_order)
    jobs = jobs.sort_values(["shortlist", "sponsor_rank", "skill_score"],
                            ascending=[False, True, False])

    shortlist = jobs[jobs["shortlist"]]
    print(f"\nSHORTLIST WITH SPONSOR EVIDENCE ({len(shortlist)} jobs):")
    for _, j in shortlist.iterrows():
        print(f"\n  {j['company']} | {j['title']} | {j['days_old']} days old")
        print(f"    skill score {j['skill_score']:.0%} | sponsor: {j['sponsor_level']} "
              f"({j['sponsor_permits_2026']} permits, {int(j['sponsor_months_active'] or 0)} of 9 months)")
        print(f"    {j['url']}")

    print("\nRecent Ireland jobs by sponsor level:")
    print(jobs[jobs["ok_recent"]]["sponsor_level"].value_counts().to_string())

    jobs.drop(columns=["sponsor_rank"]).to_csv(OUT, index=False)
    print(f"\nSaved {len(jobs):,} ranked jobs to {OUT}")


if __name__ == "__main__":
    main()
