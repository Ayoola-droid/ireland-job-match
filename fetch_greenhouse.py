"""Greenhouse offers a free, public job-board API (no key needed).
For each company in companies.csv this script:
  1. downloads its job list with descriptions; saves a dated raw copy in data/raw/greenhouse/
  2. keeps jobs located in Ireland
  3. works out how many days ago each job was first published
and saves the result to data/processed/jobs_greenhouse.csv for score_jobs.py.
"""
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

IRELAND_PATTERN = r"ireland|dublin|cork|galway|limerick|waterford"

COMPANIES = Path("companies.csv")
RAW_DIR = Path("data/raw/greenhouse")
OUT = Path("data/processed/jobs_greenhouse.csv")
API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


def clean_text(raw_html):
    """Turn the HTML job description into plain text."""
    text = html.unescape(raw_html or "")       # &lt;p&gt; -> <p>
    text = re.sub(r"<[^>]+>", " ", text)       # remove tags like <p>, <li>
    text = html.unescape(text)                 # second pass for &amp; etc.
    return re.sub(r"\s+", " ", text).strip()


def fetch_board(token):
    """Download one company's job list. Returns a list of job dicts ([] on error)."""
    try:
        response = requests.get(API.format(token=token), timeout=60)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"  ! could not fetch '{token}': {error}")
        return []
    data = response.json()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    (RAW_DIR / f"{token}_{stamp}.json").write_text(json.dumps(data), encoding="utf-8")
    return data.get("jobs", [])


def main():
    companies = pd.read_csv(COMPANIES)
    companies = companies[companies["ats"].str.lower() == "greenhouse"]
    print(f"Checking {len(companies)} Greenhouse career boards...\n")

    rows = []
    for _, company in companies.iterrows():
        jobs = fetch_board(company["board_token"])
        print(f"  {company['company']:<15} {len(jobs):>4} jobs on the board")
        for job in jobs:
            rows.append({
                "company": company["company"],
                "title": job.get("title", ""),
                "location": (job.get("location") or {}).get("name", ""),
                "first_published": job.get("first_published"),
                "url": job.get("absolute_url", ""),
                "job_id": job.get("id"),
                "source": "greenhouse",
                "description": clean_text(job.get("content")),
            })

    jobs = pd.DataFrame(rows)
    if jobs.empty:
        print("\nNo jobs downloaded. Check your internet connection and companies.csv.")
        return

    jobs["first_published"] = pd.to_datetime(jobs["first_published"], utc=True, errors="coerce")
    jobs["days_old"] = (datetime.now(timezone.utc) - jobs["first_published"]).dt.days.astype("Int64")
    ireland = jobs[jobs["location"].str.contains(IRELAND_PATTERN, case=False, na=False)].copy()

    no_text = (ireland["description"].str.len() < 200).sum()
    print(f"\nAll jobs downloaded: {len(jobs):,}")
    print(f"Located in Ireland: {len(ireland):,}")
    print(f"Ireland jobs with little or no description text: {no_text}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ireland.sort_values("days_old").to_csv(OUT, index=False)
    print(f"\nSaved {len(ireland):,} Ireland jobs to {OUT}")
    print("Next: run score_jobs.py")


if __name__ == "__main__":
    main()
