"""Read jobs from the public job feeds of hiring systems (applicant tracking systems, "ATS").

Many employers advertise through a hiring system that publishes their open jobs as a free,
public feed, meant for exactly this kind of use (career pages, job widgets):

  greenhouse    https://boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true
  lever         https://api.lever.co/v0/postings/<token>?mode=json
  ashby         https://api.ashbyhq.com/posting-api/job-board/<token>
  workable      https://www.workable.com/api/accounts/<token>?details=true
  careers_page  any careers web page (the token is its address): job ads on it are read
                through their schema.org JobPosting data, like "Add a job by link"

(SmartRecruiters is left out on purpose: its robots.txt asks programs not to read its feed.)
Every reader returns jobs in one layout: title, location, first_published, url, job_id, description.
"""
import html
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

HEADERS = {"User-Agent": "job-match/0.1 (personal job-search portfolio project)"}
ATS_TYPES = ["greenhouse", "lever", "ashby", "workable", "careers_page"]


def get_json(url, timeout=30):
    """The JSON at a URL, or None when the page doesn't exist (404) or can't be read."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def plain(raw):
    text = html.unescape(str(raw or ""))
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


# ---------- one reader per hiring system --------------------------------------------
def greenhouse(token):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true", 60) or {}
    return [{"title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
             "first_published": j.get("first_published") or j.get("updated_at"), "url": j.get("absolute_url", ""),
             "job_id": str(j.get("id", "")), "description": plain(j.get("content"))} for j in data.get("jobs", [])]


def lever(token):
    data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json", 60) or []
    jobs = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        places = cats.get("allLocations") or [cats.get("location", "")]
        lists = " ".join(f"{l.get('text', '')}: {plain(l.get('content'))}" for l in j.get("lists") or [])
        created = j.get("createdAt")
        jobs.append({"title": j.get("text", ""), "location": " / ".join(p for p in places if p),
                     "first_published": datetime.fromtimestamp(created / 1000, timezone.utc).isoformat()
                     if isinstance(created, (int, float)) else None,
                     "url": j.get("hostedUrl", ""), "job_id": str(j.get("id", "")),
                     "description": " ".join([j.get("descriptionPlain", ""), lists, j.get("additionalPlain", "")]).strip()})
    return jobs


def ashby(token):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}", 60) or {}
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        places = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        jobs.append({"title": j.get("title", ""), "location": " / ".join(p for p in places if p),
                     "first_published": j.get("publishedAt"), "url": j.get("jobUrl", ""),
                     "job_id": str(j.get("id", "")),
                     "description": j.get("descriptionPlain") or plain(j.get("descriptionHtml"))})
    return jobs


def workable(token):
    data = get_json(f"https://www.workable.com/api/accounts/{token}?details=true", 60) or {}
    jobs = []
    for j in data.get("jobs", []):
        loc = j.get("location") if isinstance(j.get("location"), dict) else {}
        place = loc.get("location_str") or ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
        jobs.append({"title": j.get("title", ""), "location": place,
                     "first_published": j.get("published_on") or j.get("created_at"),
                     "url": j.get("url") or j.get("shortlink") or j.get("application_url", ""),
                     "job_id": str(j.get("shortcode") or j.get("id") or j.get("url", "")),
                     "description": plain(j.get("description")) + " " + plain(j.get("requirements"))})
    return jobs


JOB_LINK = re.compile(r"job|vacanc|career|position|opening|role|recruit", re.I)


def careers_page(url, max_ads=30, pause=1.0, known=None):
    """Job ads linked from a company's careers page. Ads embedded on the page itself are read
    directly; otherwise links that look like job ads (same website) are opened one per second.
    `known` maps ad addresses already read on an earlier run to their job, so they aren't read again."""
    from job_from_url import HEADERS as PAGE_HEADERS, job_postings, read_job_page
    known = known or {}
    try:
        response = requests.get(url, headers=PAGE_HEADERS, timeout=30)
        if "charset" not in response.headers.get("Content-Type", "").lower():
            response.encoding = "utf-8"
        page = response.text
    except requests.RequestException:
        return []
    jobs = []
    for p in job_postings(page):  # several ads embedded on the careers page itself
        org = p.get("hiringOrganization") or {}
        jobs.append({"title": plain(p.get("title")), "location": "", "first_published": p.get("datePosted"),
                     "url": p.get("url") or url, "job_id": p.get("url") or plain(p.get("title")),
                     "description": plain(p.get("description"))})
    if jobs:
        return jobs
    site = urlparse(url).netloc
    links = []
    for href in re.findall(r'href=["\']([^"\'#]+)', page):
        full = urljoin(url, html.unescape(href))
        if urlparse(full).netloc == site and JOB_LINK.search(urlparse(full).path) and full.rstrip("/") != url.rstrip("/"):
            links.append(full)
    for link in list(dict.fromkeys(links))[:max_ads]:
        if link in known:
            jobs.append(known[link])
            continue
        time.sleep(pause)
        try:
            ad = read_job_page(link)
        except Exception:
            continue
        # an ad, not a menu page: structured job data (it names the employer) or a long text
        if ad.get("title") and (ad.get("company") and len(ad.get("description", "")) > 100
                                or len(ad.get("description", "")) > 300):
            jobs.append({"title": ad["title"], "location": ad.get("location", ""),
                         "first_published": ad.get("first_published"), "url": link, "job_id": link,
                         "description": ad["description"]})
    return jobs


READERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workable": workable}


def fetch(ats, token, **options):
    ats = str(ats).strip().lower()
    if ats == "careers_page":
        return careers_page(token, **options)
    reader = READERS.get(ats)
    return reader(str(token).strip()) if reader else []


# ---------- does an employer have a board on this system? ----------------------------
def probe(ats, token):
    """(board name or "", number of jobs) if `token` is a live board on this system, else None.
    Only Greenhouse and Workable say the employer's name, so only they can be checked by name."""
    if ats == "greenhouse":
        info = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}", 20)
        if not info:
            return None
        jobs = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", 20) or {}
        return info.get("name", ""), len(jobs.get("jobs", []))
    if ats == "workable":
        data = get_json(f"https://www.workable.com/api/accounts/{token}", 20)
        return (data.get("name", ""), len(data.get("jobs", []))) if isinstance(data, dict) else None
    if ats == "lever":
        data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json&limit=100", 20)
        return ("", len(data)) if isinstance(data, list) else None
    if ats == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}", 20)
        return ("", len(data.get("jobs", []))) if isinstance(data, dict) and "jobs" in data else None
    return None
