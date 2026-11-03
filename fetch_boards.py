"""Read every company career board in companies.csv and keep the jobs in your locations.

Each row of companies.csv names a company, its hiring system ("ats": greenhouse, lever, ashby,
workable or careers_page) and its board token (for careers_page: the careers page's address).
The free public feeds are read by ats_feeds.py. For each company this script:
  1. downloads its job list (saving a dated raw copy in data/raw/boards/)
  2. keeps jobs in the places in the "location_words" setting (careers-page ads with no
     location are kept: they come from employers you chose because they hire here)
  3. works out how many days ago each job was first published
Companies are read four at a time (each from a different website), to save time.
Saves data/processed/jobs_boards.csv for score_jobs.py.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ats_feeds import fetch
from settings import setting

LOCATION_PATTERN = setting("location_words", "ireland|dublin|cork|galway|limerick|waterford")
COMPANIES = Path("companies.csv")
RAW_DIR = Path("data/raw/boards")
OUT = Path("data/processed/jobs_boards.csv")
WORKERS = 4


def read_company(company, known):
    """All jobs on one company's board, labelled with the company and its hiring system."""
    ats = str(company["ats"]).strip().lower() or "greenhouse"
    options = {"known": known} if ats == "careers_page" else {}
    try:
        jobs = fetch(ats, company["board_token"], **options)
    except Exception as error:  # one broken board shouldn't stop the others
        print(f"  ! {company['company']}: {error}")
        jobs = []
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    safe = "".join(c if c.isalnum() else "_" for c in str(company["company"]))[:40]
    (RAW_DIR / f"{safe}_{stamp}.json").write_text(json.dumps(jobs), encoding="utf-8")
    return [{**j, "company": company["company"], "source": ats} for j in jobs]


def main():
    companies = pd.read_csv(COMPANIES, dtype=str).fillna("")
    companies = companies[companies["board_token"].str.strip() != ""]
    # Ads already read from careers pages on an earlier run aren't opened again (saves minutes)
    known = {}
    if OUT.exists() and OUT.stat().st_size > 5:
        old = pd.read_csv(OUT, dtype=str).fillna("")
        old = old[old["source"] == "careers_page"]
        known = {r["url"]: {k: r[k] for k in ("title", "location", "first_published", "url", "job_id", "description")}
                 for _, r in old.iterrows()}
    print(f"Checking {len(companies)} career boards, {WORKERS} at a time...\n")
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(lambda row: read_company(row, known), [r for _, r in companies.iterrows()]))
    for (_, company), jobs in zip(companies.iterrows(), results):
        print(f"  {company['company'][:32]:<32} {company['ats']:<12} {len(jobs):>4} jobs")

    jobs = pd.DataFrame([j for found in results for j in found])
    if jobs.empty:
        print("\nNo jobs downloaded. Check your internet connection and companies.csv.")
        jobs = pd.DataFrame(columns=["company", "title", "location", "first_published", "url", "job_id", "source",
                                     "description", "days_old"])
        jobs.to_csv(OUT, index=False)
        return
    jobs["first_published"] = pd.to_datetime(jobs["first_published"], utc=True, errors="coerce", format="mixed")
    # Careers pages often show no date: count from the day the app first saw the ad (kept between runs)
    jobs["first_published"] = jobs["first_published"].fillna(pd.Timestamp.now(tz="UTC").normalize())
    jobs["days_old"] = (datetime.now(timezone.utc) - jobs["first_published"]).dt.days.astype("Int64")
    in_place = jobs["location"].fillna("").str.contains(LOCATION_PATTERN, case=False, regex=True)
    no_place = (jobs["source"] == "careers_page") & (jobs["location"].fillna("") == "")
    local = jobs[in_place | no_place].copy()

    print(f"\nAll jobs downloaded: {len(jobs):,}")
    print(f"In your locations ({LOCATION_PATTERN}): {len(local):,}")
    print(f"Of those, with little or no description text: {(local['description'].str.len() < 200).sum()}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    local.sort_values("days_old").to_csv(OUT, index=False)
    print(f"\nSaved {len(local):,} jobs to {OUT}")


if __name__ == "__main__":
    main()
