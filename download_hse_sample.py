"""Download ONE page of HSE job listings and look at how it is built.

HSE jobs (about.hse.ie) have no API or feed, but the jobs pages are open to
robots (checked robots.txt on 1 Nov 2026). Before writing a reader for the
page we save a copy and inspect it - the same 'look before you clean' habit
as inspect_sponsors.py. This script makes a single request.
"""
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import requests

URL = "https://about.hse.ie/jobs/job-search/"
HEADERS = {"User-Agent": "ireland-job-match/0.1 (personal job-search portfolio project)"}
RAW_DIR = Path("data/raw/hse")


def main():
    response = requests.get(URL, headers=HEADERS, timeout=60)
    print(f"Status: {response.status_code}   Size: {len(response.text):,} characters")
    response.raise_for_status()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"search_page1_{datetime.now():%Y-%m-%d}.html"
    out.write_text(response.text, encoding="utf-8")
    print(f"Saved a copy to {out}")

    page = response.text
    job_links = sorted(set(re.findall(r'href="(/jobs/job-search/[^"#?]+/)"', page)))
    print(f"\nLinks to individual jobs on this page: {len(job_links)}")
    for link in job_links[:5]:
        print("  ", link)

    params = Counter(re.findall(r'[?&](\w+)=', page))
    print("\nURL settings used on the page (name: times seen), e.g. for paging or filters:")
    for name, count in params.most_common(15):
        print(f"   {name}: {count}")

    inputs = sorted(set(re.findall(r'<(?:input|select)[^>]*name="([^"]+)"', page)))
    print(f"\nForm fields on the page: {inputs}")


if __name__ == "__main__":
    main()
