"""Search Jooble, a job search engine that gathers ads from thousands of sites, including small
companies' own career pages and recruitment agencies that aren't on Greenhouse.

For each search word in the "jooble_keywords" setting, it asks Jooble's API for jobs in
"jooble_location" (e.g. Ireland) and keeps those posted in the last DAYS days. Jooble only sends a
short snippet of each ad, so (when "jooble_full_ads" is on) it then opens each ad, politely, one
per second, and reads the full text so the skill scoring has something to work with.
Saves data/processed/jobs_jooble.csv in the same layout as the other job files.

Setup: request a free API key from your country's Jooble site, e.g. https://ie.jooble.org/api/about
for Ireland (the key from jooble.org itself searches the US). Then put the key in an
environment variable called JOOBLE_API_KEY (never in a file):
    PowerShell:  setx JOOBLE_API_KEY "your-key"     (then close and reopen the terminal and the app)
"""
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from settings import setting

# ---- Settings (change them in the app, or in app_settings.json) ----------------
KEYWORDS = setting("jooble_keywords", ["data analyst", "business analyst", "reporting analyst"])
LOCATION = setting("jooble_location", "Ireland")
DAYS = setting("days", 30)
MAX_PAGES = setting("jooble_max_pages", 3)        # pages of results per search word
FULL_ADS = setting("jooble_full_ads", True)       # open each ad to read the full text
COUNTRY = setting("jooble_country", "ie")          # Jooble runs one site per country: ie.jooble.org, uk.jooble.org...
API_HOST = setting("jooble_host", "") or f"https://{COUNTRY}.jooble.org"  # (jooble_host only for testing)
PAUSE_SECONDS = 1.0
# -----------------------------------------------------------------------------

KEY_ENV = "JOOBLE_API_KEY"
RAW_DIR = Path("data/raw/jooble")
OUT = Path("data/processed/jobs_jooble.csv")
HEADERS = {"User-Agent": "job-match/0.1 (personal job-search portfolio project)"}


def clean_text(raw_html):
    text = html.unescape(raw_html or "")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def search(key, keywords, page):
    """One page of Jooble results for one search ([] on error)."""
    body = {"keywords": keywords, "location": LOCATION, "page": str(page)}
    try:
        response = requests.post(f"{API_HOST}/api/{key}", json=body, headers=HEADERS, timeout=60)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"  ! Jooble search '{keywords}' page {page} failed: {error}")
        return []
    data = response.json()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    safe = re.sub(r"[^a-z0-9]+", "_", keywords.lower())
    (RAW_DIR / f"{safe}_p{page}_{stamp}.json").write_text(json.dumps(data), encoding="utf-8")
    return data.get("jobs", [])


def full_text(url):
    """The ad's full text, read from the page the Jooble link leads to ('' if it can't be read).
    Many career sites include the ad as structured data (schema.org JobPosting): that is used first."""
    from job_from_url import read_job_page  # same reader as 'Add a job by link'
    try:
        time.sleep(PAUSE_SECONDS)
        job = read_job_page(url)
        return job.get("description", "")
    except Exception:  # a site that blocks robots or needs JavaScript: keep the snippet
        return ""


def main():
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise SystemExit(f"No Jooble API key. Request a free key at https://{COUNTRY}.jooble.org/api/about, then in "
                         f"PowerShell run:  setx {KEY_ENV} \"your-key\"  and restart the app.")
    print(f"Searching {API_HOST} for {KEYWORDS} in {LOCATION} ...")
    rows = []
    for keywords in KEYWORDS:
        found = 0
        for page in range(1, MAX_PAGES + 1):
            jobs = search(key, keywords, page)
            if not jobs:
                break
            for j in jobs:
                link = j.get("link", "")
                rows.append({
                    "company": (j.get("company") or "").strip() or "(not given)",
                    "title": clean_text(j.get("title")),
                    "location": j.get("location", ""),
                    "first_published": j.get("updated"),
                    "url": link,
                    "job_id": str(j.get("id") or hashlib.md5(link.encode()).hexdigest()[:12]),
                    "source": "jooble",
                    "description": clean_text(j.get("snippet")),
                    "salary_text": j.get("salary", ""),
                    "found_via": j.get("source", ""),
                })
                found += 1
            time.sleep(PAUSE_SECONDS)
        print(f"  '{keywords}': {found} results")

    jobs = pd.DataFrame(rows)
    if jobs.empty:
        print("No jobs found. Check the key, the search words and the location.")
        jobs.to_csv(OUT, index=False)
        return
    # The same ad often comes back for several search words
    jobs = jobs.drop_duplicates("url").drop_duplicates(["company", "title", "location"])
    jobs["first_published"] = pd.to_datetime(jobs["first_published"], utc=True, errors="coerce")
    jobs["days_old"] = (datetime.now(timezone.utc) - jobs["first_published"]).dt.days.astype("Int64")
    jobs = jobs[jobs["days_old"].isna() | (jobs["days_old"] <= DAYS)].copy()

    if FULL_ADS:
        print(f"\nReading the full text of {len(jobs)} ads (one per second) ...")
        full = jobs["url"].apply(full_text)
        longer = full.str.len() > jobs["description"].str.len()
        jobs.loc[longer, "description"] = full[longer]
        print(f"  full text read for {int(longer.sum())} of {len(jobs)}; the rest are scored on Jooble's snippet")
    jobs["short_text"] = jobs["description"].str.len() < 400
    # Pay written in the listing (e.g. "€45k - €55k") is added to the text so score_jobs.py can read it
    jobs["description"] = (jobs["description"] + " " + jobs["salary_text"].fillna("")).str.strip()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    jobs.drop(columns=["salary_text"]).sort_values("days_old").to_csv(OUT, index=False)
    print(f"\nSaved {len(jobs):,} Jooble jobs to {OUT} ({jobs['company'].nunique()} employers)")
    print(f"Most common sources: {jobs['found_via'].value_counts().head(5).to_dict()}")


if __name__ == "__main__":
    main()
