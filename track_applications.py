"""Keep a log of the jobs you apply to, so you never apply twice.

Run it to:
  1. mark a shortlisted job as applied (records the date and the CV file)
  2. update an application's status (applied, interview, offer, rejected, no reply, withdrawn)
  3. list your applications
The log is data/applications.csv (private: the data folder is not in Git).
score_jobs.py uses the same log to leave out jobs you have already applied to,
and to flag jobs that look like a repeat of one (re-posted, or listed on another site).
"""
import re
from datetime import date
from pathlib import Path

import pandas as pd

LOG = Path("data/applications.csv")
RANKED = Path("data/processed/jobs_ranked.csv")
COLUMNS = ["job_id", "source", "company", "title", "url", "applied_on", "cv_file", "status", "status_date", "notes"]
STATUSES = ["applied", "interview", "offer", "rejected", "no reply", "withdrawn"]
REPEAT_SIMILARITY = 0.8  # share of title words in common for "looks like the same job"

# Words that change between re-posts of the same job, so they are ignored when comparing titles
NOISE = re.compile(r"\b(amended|rolling|campaign|phase\s*\d+|re-?advert\w*|re-?post\w*|panel)\b")


def load_log():
    if LOG.exists():
        log = pd.read_csv(LOG, dtype=str).fillna("")
        # Excel can leave empty rows behind when a row is deleted: ignore them
        return log[log["job_id"].str.strip() != ""].reset_index(drop=True)
    return pd.DataFrame(columns=COLUMNS)


def clean_title(title):
    """'Grade VII Data Analyst NRS15476 - Amended' -> 'analyst data grade vii'"""
    text = NOISE.sub(" ", str(title).lower())
    words = [w for w in re.findall(r"[a-z]+(?:\d+[a-z]*)?|\d+", text) if not re.search(r"\d", w)]
    return " ".join(sorted(set(words)))


def similarity(a, b):
    a, b = set(a.split()), set(b.split())
    return len(a & b) / len(a | b) if a | b else 0.0


def match_applications(jobs, log):
    """Add two columns to a jobs table:
    applied_on     - date you applied to this exact job (same source and job id), else ''
    possible_repeat - a past application to the same company with a near-identical title"""
    jobs = jobs.copy()
    jobs["applied_on"] = ""
    jobs["possible_repeat"] = ""
    if log.empty:
        return jobs
    exact = {(r["source"], str(r["job_id"])): r["applied_on"] for _, r in log.iterrows()}
    log_titles = [(r["company"].lower(), clean_title(r["title"]), r) for _, r in log.iterrows()]
    for idx, job in jobs.iterrows():
        key = (job["source"], str(job["job_id"]))
        if key in exact:
            jobs.at[idx, "applied_on"] = exact[key]
            continue
        cleaned = clean_title(job["title"])
        for company, title, row in log_titles:
            if company == str(job["company"]).lower() and similarity(cleaned, title) >= REPEAT_SIMILARITY:
                jobs.at[idx, "possible_repeat"] = f"{row['title']} (applied {row['applied_on']})"
                break
    return jobs


def mark_applied(log):
    ranked = pd.read_csv(RANKED)
    shortlist = match_applications(ranked[ranked["shortlist"]], log).reset_index(drop=True)
    if shortlist.empty:
        print("No shortlisted jobs. Run score_jobs.py and add_sponsors.py first.")
        return log
    for i, j in shortlist.iterrows():
        tag = f"  [already applied {j['applied_on']}]" if j["applied_on"] else (
              f"  [looks like: {j['possible_repeat']}]" if j["possible_repeat"] else "")
        print(f"  {i + 1}. {j['company']} | {j['title']}{tag}")
    choice = input("Number of the job you applied to (Enter to cancel): ").strip()
    if not choice:
        return log
    job = shortlist.iloc[int(choice) - 1]
    if job["applied_on"]:
        print(f"Already in your log (applied {job['applied_on']}). Nothing added.")
        return log
    if job["possible_repeat"]:
        sure = input(f"This looks like {job['possible_repeat']}. Add it anyway? (y/n): ").strip().lower()
        if sure != "y":
            return log
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{job['company']}_{job['job_id']}").strip("_")
    cv_file = f"CV_{slug}.docx" if Path("output", f"CV_{slug}.docx").exists() else ""
    today = date.today().isoformat()
    row = {"job_id": str(job["job_id"]), "source": job["source"], "company": job["company"],
           "title": job["title"], "url": job["url"], "applied_on": today, "cv_file": cv_file,
           "status": "applied", "status_date": today, "notes": ""}
    print(f"Logged: {job['company']} | {job['title']} | CV: {cv_file or 'none found in output/'}")
    return pd.concat([log, pd.DataFrame([row])], ignore_index=True)


def update_status(log):
    if log.empty:
        print("Your log is empty.")
        return log
    show_log(log)
    choice = input("Number of the application to update (Enter to cancel): ").strip()
    if not choice:
        return log
    idx = int(choice) - 1
    for i, s in enumerate(STATUSES, 1):
        print(f"  {i}. {s}")
    status = STATUSES[int(input("New status number: ").strip()) - 1]
    log.loc[idx, "status"] = status
    log.loc[idx, "status_date"] = date.today().isoformat()
    note = input("Note (optional, Enter to skip): ").strip()
    if note:
        log.loc[idx, "notes"] = note
    print(f"Updated: {log.loc[idx, 'company']} | {log.loc[idx, 'title']} -> {status}")
    return log


def show_log(log):
    if log.empty:
        print("No applications yet.")
        return
    for i, r in log.iterrows():
        print(f"  {i + 1}. {r['applied_on']} | {r['company']} | {r['title']} | {r['status']} ({r['status_date']})")
    print("\n  Status counts:", log["status"].value_counts().to_dict())


def main():
    log = load_log()
    while True:
        print("\n1. Mark a shortlisted job as applied\n2. Update an application's status\n"
              "3. Show my applications\n(Enter to quit)")
        choice = input("Choose: ").strip()
        if choice == "1":
            log = mark_applied(log)
        elif choice == "2":
            log = update_status(log)
        elif choice == "3":
            show_log(log)
        else:
            break
        LOG.parent.mkdir(parents=True, exist_ok=True)
        log[COLUMNS].to_csv(LOG, index=False)


if __name__ == "__main__":
    main()
