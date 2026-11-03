"""Add visa-sponsorship evidence to each scored job and rank the shortlist.

Joins data/processed/jobs_scored.csv to the DETE sponsor list through
company_aliases.csv (your checked list of brand name -> legal name keys).
Writes data/processed/jobs_ranked.csv.

Don't need a work permit? Untick "Check visa sponsorship" in the app (setting
"check_sponsorship": false): the jobs are then ranked by skill match only.
"""
from pathlib import Path

import pandas as pd

from clean_sponsors import name_key
from settings import setting

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


def rank_without_sponsors(jobs, reason):
    print(f"Sponsorship not checked ({reason}): ranking by skill match only.")
    jobs["sponsor_level"] = "not checked"
    jobs["sponsor_permits_2026"] = 0
    jobs["sponsor_months_active"] = 0
    jobs = jobs.sort_values(["shortlist", "skill_score"], ascending=[False, False])
    jobs.to_csv(OUT, index=False)
    print(f"Saved {len(jobs):,} ranked jobs to {OUT} ({int(jobs['shortlist'].sum())} on the shortlist)")


def main():
    jobs = pd.read_csv(JOBS)
    if not setting("check_sponsorship", True):
        return rank_without_sponsors(jobs, "switched off in the settings")
    if not SPONSORS.exists():
        return rank_without_sponsors(jobs, f"no sponsor list at {SPONSORS}; see README > Setup")
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
    # Companies not in company_aliases.csv (e.g. small firms found through Jooble): try the
    # employer's own name against the DETE list. Only exact matches of the cleaned name count
    # (also with "Ireland" added, as in "Google Ireland"), so there are no false sponsors.
    missing = sorted(set(jobs["company"].dropna()) - {r["company"] for r in rows})
    auto = []
    for company in missing:
        key = name_key(company)
        keys = [k for k in (key, f"{key} IRELAND") if key and k in by_key.index]
        if keys:
            found = by_key.loc[keys]
            permits, months = int(found["permits"].sum()), int(found["months"].max())
            rows.append({"company": company, "sponsor_permits_2026": permits, "sponsor_months_active": months,
                         "sponsor_level": sponsor_level(permits, months), "sponsor_match": "name match, check"})
            auto.append(company)
    lookup = pd.DataFrame(rows)
    if "sponsor_match" not in lookup:
        lookup["sponsor_match"] = ""
    lookup["sponsor_match"] = lookup["sponsor_match"].fillna("checked alias")
    print(f"Matched {len(auto)} more employers to the sponsor list by name: {auto[:15]}")
    unmatched = sorted(set(missing) - set(auto))
    if unmatched:
        print(f"  ! {len(unmatched)} companies not found on the sponsor list (or named differently): {unmatched[:20]}")

    print("Sponsor evidence per company (DETE permits, Jan-Sep 2026):")
    print(lookup.sort_values("sponsor_permits_2026", ascending=False).to_string(index=False))

    jobs = jobs.merge(lookup, on="company", how="left")
    jobs["sponsor_level"] = jobs["sponsor_level"].fillna("not found")  # name not on the DETE list
    jobs["sponsor_permits_2026"] = jobs["sponsor_permits_2026"].fillna(0).astype(int)
    jobs["sponsor_months_active"] = jobs["sponsor_months_active"].fillna(0).astype(int)
    jobs["sponsor_match"] = jobs["sponsor_match"].fillna("")

    # Rank: shortlisted first, then strong sponsors, then best skill match
    level_order = {"strong": 0, "some": 1, "not on list": 2, "not found": 2, "unknown": 3}
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
