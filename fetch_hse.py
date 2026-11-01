"""Fetch HSE jobs from about.hse.ie (public pages, allowed by robots.txt).

1. Reads every page of the HSE job search (10 jobs per page), politely,
   one request per second, and saves dated raw copies in data/raw/hse/.
2. Keeps jobs in your chosen categories posted in the last DAYS days.
3. Opens each of those jobs to read grade, advertisement type (who can
   apply), closing date and the short role summary. If the job has a Word
   job specification attached, it reads the text from that too.
Contact names, emails and phone numbers on the pages are NOT kept.
Saves data/processed/jobs_hse.csv in the same layout as jobs_greenhouse.csv.
"""
import html
import io
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ---- Settings you can change ------------------------------------------------
DAYS = 30
CATEGORIES = ["Management/Admin/ICT"]
MAX_PAGES = 40           # safety stop
PAUSE_SECONDS = 1.0      # wait between requests, to be polite to the HSE site
# -----------------------------------------------------------------------------

BASE = "https://about.hse.ie"
LIST_URL = BASE + "/jobs/job-search/?page={page}"
HEADERS = {"User-Agent": "ireland-job-match/0.1 (personal job-search portfolio project)"}
RAW_DIR = Path("data/raw/hse")
OUT = Path("data/processed/jobs_hse.csv")
TODAY = datetime.now().strftime("%Y-%m-%d")

CARD = re.compile(r'<li class="hse-listing__item[^"]*"[^>]*>(.*?)</li>\s*(?=<li class="hse-listing__item|</ul>)', re.S)


def get(url, save_as=None):
    time.sleep(PAUSE_SECONDS)
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    if save_as:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / save_as).write_bytes(response.content)
    return response


def parse_listing(page_html):
    """Return one dict per job card on a search-results page."""
    jobs = []
    for card in CARD.findall(page_html):
        link = re.search(r'href="(/jobs/job-search/[^"]+)"[^>]*>([^<]+)</a>', card)
        if not link:
            continue
        category = re.search(r'Category:\s*([^<]+)</p>', card)
        county = re.search(r'County:\s*([^<]+)</p>', card)
        posted = re.search(r'dateTime="([^"]+)"', card)
        jobs.append({
            "title": html.unescape(link.group(2)).replace("\xa0", " ").strip(),
            "url": BASE + link.group(1),
            "category": html.unescape(category.group(1)).strip() if category else "",
            "location": html.unescape(county.group(1)).strip() if county else "",
            "first_published": posted.group(1) if posted else None,
        })
    return jobs


def page_text(page_html):
    """Plain text with one line per block, so labels like 'Grade' sit on their own line."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page_html, flags=re.S)
    text = re.sub(r"</?(p|div|li|h\d|dt|dd|br|tr|section|ul)[^>]*>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


LABELS = ["Reference", "Category", "Grade", "Advertisement source", "Advertisement Type",
          "Important Information", "Health region", "County", "Location", "Recruiter",
          "Contract type", "Post specific related information", "Closing date",
          "Proposed interview date", "Informal enquiries", "Application details",
          "External link", "Related files", "Before you apply"]


def field(text, label):
    """The text that follows a label, up to the next known label."""
    others = "|".join(re.escape(l) for l in LABELS if l != label)
    # the label must sit alone on its line (so a title starting "Grade VII..." is not mistaken for it)
    m = re.search(rf"(?:^|\n){re.escape(label)}[ \t]*:?[ \t]*\n(.*?)(?=\n(?:{others})[ \t]*:?[ \t]*\n|\Z)",
                  text, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def docx_text(content):
    """Read the words out of a .docx file without extra libraries:
    a .docx is a zip file, and the text lives in word/document.xml."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def main():
    # 1. All listing pages (numbered from 1: page 0 comes back empty)
    cards, page, last_page = [], 1, MAX_PAGES
    while page <= last_page:
        page_html = get(LIST_URL.format(page=page), f"list_page{page}_{TODAY}.html").text
        found = parse_listing(page_html)
        if page == 1:
            total = re.search(r"Page 1 of (\d+)", page_html)
            last_page = min(int(total.group(1)), MAX_PAGES) if total else MAX_PAGES
            print(f"The HSE site says there are {last_page} pages of jobs")
        if not found:
            print(f"  page {page}: no job cards found, stopping")
            break
        cards += found
        page += 1
    if not cards:
        print("No HSE jobs could be read. The saved page in data/raw/hse/ shows what came back.")
        return
    jobs = pd.DataFrame(cards).drop_duplicates("url")
    print(f"HSE job listings read: {len(jobs)} from {page - 1} pages")
    print(jobs["category"].value_counts().to_string(), "\n")

    jobs["first_published"] = pd.to_datetime(jobs["first_published"], utc=True, errors="coerce")
    jobs["days_old"] = (datetime.now(timezone.utc) - jobs["first_published"]).dt.days.astype("Int64")
    picked = jobs[jobs["category"].isin(CATEGORIES) & (jobs["days_old"] <= DAYS)].copy()
    print(f"In {CATEGORIES} and posted in the last {DAYS} days: {len(picked)}")

    # 2. Details for the picked jobs
    rows = []
    for _, job in picked.iterrows():
        slug = job["url"].rstrip("/").split("/")[-1]
        text = page_text(get(job["url"], f"job_{slug}_{TODAY}.html").text)
        detail = {label: field(text, label) for label in
                  ["Reference", "Grade", "Advertisement Type", "Contract type", "Closing date",
                   "Post specific related information", "Before you apply"]}
        spec_text, spec_url = "", ""
        raw_page = (RAW_DIR / f"job_{slug}_{TODAY}.html").read_text(encoding="utf-8", errors="ignore")
        spec = re.search(r'href="([^"]+\.docx)"', raw_page, re.I)
        if spec:
            spec_url = html.unescape(spec.group(1))
            if spec_url.startswith("/"):
                spec_url = BASE + spec_url
            try:
                spec_text = docx_text(get(spec_url).content)
            except Exception as error:  # a broken attachment shouldn't stop the run
                print(f"  ! could not read job spec for {slug}: {error}")
        closing = pd.to_datetime(detail["Closing date"][:10], format="%d/%m/%Y", errors="coerce")
        rows.append({
            "company": "HSE",
            "title": job["title"],
            "location": job["location"],
            "first_published": job["first_published"],
            "url": job["url"],
            "job_id": detail["Reference"] or slug,
            "source": "hse",
            "description": " ".join([detail["Post specific related information"],
                                     detail["Before you apply"], spec_text]).strip(),
            "days_old": job["days_old"],
            "grade": detail["Grade"],
            "ad_type": detail["Advertisement Type"],
            "contract": detail["Contract type"],
            "closing_date": closing.date() if pd.notna(closing) else None,
            "still_open": bool(pd.notna(closing) and closing.date() >= datetime.now().date()),
            "has_job_spec": bool(spec_text),
        })
        print(f"  {job['title'][:60]:<60} | {detail['Grade'][:18]:<18} | {detail['Advertisement Type'] or '?'}"
              f" | closes {detail['Closing date'][:10] or '?'} | spec: {'yes' if spec_text else 'no'}")

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    if len(out):
        print(f"\nAdvertisement types: {out['ad_type'].value_counts().to_dict()}")
        print(f"Still open: {out['still_open'].sum()} of {len(out)}   With a job spec: {out['has_job_spec'].sum()}")
    print(f"Saved {len(out)} HSE jobs to {OUT}")


if __name__ == "__main__":
    main()
