"""Add any job to the app: paste the address of a job ad (a small company's careers page, a
recruiter's site...) or paste the ad's text, and it is scored like every other job.

How it reads a page:
  1. Most job pages include the ad as structured data for Google Jobs (schema.org "JobPosting"):
     title, employer, location, date posted and the full description. That is used when present.
  2. Otherwise it takes the page title and the visible text of the page.
Sites that need JavaScript or block programs can't be read this way: paste the ad's text instead.
Jobs you add are saved in data/processed/jobs_manual.csv (source "manual").
Run on its own:  python job_from_url.py https://example.com/careers/data-analyst
"""
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

OUT = Path("data/processed/jobs_manual.csv")
HEADERS = {"User-Agent": "Mozilla/5.0 (job-match personal job-search tool)",
           "Accept-Language": "en-IE,en;q=0.9"}


def plain(raw):
    text = html.unescape(str(raw or ""))
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"</?(p|div|li|h\d|br|tr|section|ul|ol)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in html.unescape(text).split("\n")]
    return "\n".join(line for line in lines if line)


def job_postings(page_html):
    """Every schema.org JobPosting found in the page's JSON-LD blocks."""
    found = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page_html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                kind = item.get("@type")
                if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                    found.append(item)
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return found


def meta(page_html, name):
    m = re.search(rf'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]+content=["\']([^"\']+)', page_html, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def place_of(posting):
    loc = posting.get("jobLocation") or {}
    loc = loc[0] if isinstance(loc, list) and loc else loc
    address = loc.get("address", {}) if isinstance(loc, dict) else {}
    if isinstance(address, dict):
        return ", ".join(str(address[k]) for k in ("addressLocality", "addressRegion", "addressCountry")
                         if address.get(k) and isinstance(address[k], str))
    return str(address)


def read_job_page(url):
    """{title, company, location, first_published, description, url} from a job ad's web page."""
    response = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    response.raise_for_status()
    page = response.text
    postings = job_postings(page)
    if postings:
        p = postings[0]
        org = p.get("hiringOrganization") or {}
        return {"title": plain(p.get("title")), "company": plain(org.get("name") if isinstance(org, dict) else org),
                "location": place_of(p), "first_published": p.get("datePosted"),
                "description": plain(p.get("description")), "url": response.url}
    title = meta(page, "og:title") or plain((re.search(r"<title>(.*?)</title>", page, re.S | re.I) or [None, ""])[1])
    body = re.search(r"<(main|article)[^>]*>(.*?)</\1>", page, re.S | re.I)
    company = meta(page, "og:site_name")
    if company:  # page titles often end with the site's name: "Reporting Analyst | Small Co"
        title = re.sub(rf"\s*[|\-–—:]\s*{re.escape(company)}\s*$", "", title, flags=re.I)
    return {"title": title, "company": company, "location": "", "first_published": None,
            "description": plain(body.group(2) if body else page)[:20000], "url": response.url}


def add_job(job):
    """Save a job to jobs_manual.csv (replacing an earlier copy of the same ad). Returns its id."""
    job = dict(job)
    job.setdefault("url", "")
    job["job_id"] = "M" + hashlib.md5((job["url"] or job["title"] + job["company"]).encode()).hexdigest()[:10]
    job["source"] = "manual"
    published = pd.to_datetime(job.get("first_published"), utc=True, errors="coerce")
    job["first_published"] = published if pd.notna(published) else datetime.now(timezone.utc)
    job["days_old"] = (datetime.now(timezone.utc) - job["first_published"]).days
    job["added_on"] = datetime.now().strftime("%Y-%m-%d")
    jobs = pd.read_csv(OUT, dtype={"job_id": str}) if OUT.exists() else pd.DataFrame()
    if len(jobs):
        jobs = jobs[jobs["job_id"] != job["job_id"]]
    jobs = pd.concat([jobs, pd.DataFrame([job])], ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    jobs.to_csv(OUT, index=False)
    return job["job_id"]


if __name__ == "__main__":
    found = read_job_page(sys.argv[1])
    print(f"{found['title']} | {found['company']} | {found['location']} | posted {found['first_published']}")
    print(found["description"][:800], "...")
    if input("Add this job? [y/N] ").strip().lower() == "y":
        print("Added as", add_job(found))
