"""Find the job boards of employers that sponsor work permits, so the app can read their
vacancies straight from their own hiring system.

The DETE permit list names employers but gives no website, so for each employer with at least
MIN_PERMITS permits this year, this script guesses the short name its hiring system would use
("Dawn Meats Ireland UC" -> dawnmeats, dawn-meats, dawn) and asks each system's free public feed
(Greenhouse, Workable, Lever, Ashby) whether that board exists:
  - Greenhouse and Workable say the board's company name, so a board only counts when that name
    matches the employer's ("match").
  - Lever and Ashby don't say the name, so only the employer's full name is tried there, and a
    hit is marked "check" for you to confirm.
  - A board is only useful if it has jobs where you search: big employers often have one board per
    country (Forvis Mazars' Greenhouse board is its German one). So every board found is read once
    and its jobs in your locations (the location_words setting) are counted; a board with none is
    marked "no jobs here". Boards found on an earlier run are counted again on the next run.
Employers with no board found are listed too: paste their careers page address in the app.
The four systems are asked at the same time (they are different websites), each one politely.
Employers checked on an earlier run aren't checked again.
Saves data/processed/sponsor_boards.csv; the app's "Find sponsors' career sites" shows it.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

from ats_feeds import fetch, probe
from clean_sponsors import name_key
from settings import setting

MIN_PERMITS = setting("sponsor_board_min_permits", 10)  # employers with at least this many permits
LOCATION_PATTERN = setting("location_words", "ireland|dublin|cork|galway|limerick|waterford")
SPONSORS = Path("data/processed/sponsors_2026.csv")
COMPANIES = Path("companies.csv")
OUT = Path("data/processed/sponsor_boards.csv")
PAUSE = 0.25  # seconds between requests to the same system
# Words that are part of legal names but never of a board's short name
GENERIC = {"IRELAND", "IRISH", "GROUP", "HOLDINGS", "UNLIMITED", "COMPANY", "LIMITED", "LTD", "DAC", "UC", "PLC",
           "CLG", "EUROPE", "EUROPEAN", "INTERNATIONAL", "THE", "AND", "OF", "SERVICES", "SERVICE", "SOLUTIONS",
           "TECHNOLOGIES", "TECHNOLOGY", "OPERATIONS", "MANAGEMENT", "IRL", "EMEA", "GLOBAL", "R", "D", "INC", "LLC",
           "CORP", "CORPORATION", "CO"}


def words_of(employer):
    return [w for w in name_key(employer).split() if w not in GENERIC]


def slugs(employer):
    """Short names a hiring system might use: dawnmeats, dawn-meats, dawn (most specific first)."""
    words = [w.lower() for w in words_of(employer) if w.isalnum()]
    found = ["".join(words), "-".join(words)] + (words[:1] if len(words) > 1 else [])
    return [s for s in dict.fromkeys(found) if len(s) >= 3]


def same_company(board_name, employer):
    """True when the board's name and the employer's name share most of their words
    ("Dawn Health" is not "Dawn Meats": one shared word out of two each isn't enough)."""
    a, b = set(words_of(board_name)), set(words_of(employer))
    return bool(a and b) and len(a & b) / max(len(a), len(b)) >= 0.6


def check_system(ats, employer):
    """(token, board name, jobs now, status) for the first board found on one system, else None."""
    tries = slugs(employer)
    if ats in ("lever", "ashby"):  # no company name to compare: only try the full name
        tries = tries[:2]
    for token in tries:
        time.sleep(PAUSE)
        found = probe(ats, token)
        if found is None:
            continue
        name, jobs = found
        if name:
            if same_company(name, employer):
                return token, name, jobs, "match"
            continue  # a different company happens to use this short name
        return token, "", jobs, "check"
    return None


def jobs_in_your_area(ats, token):
    """How many of a board's jobs are in your locations (same test as fetch_boards.py)."""
    jobs = fetch(ats, token)
    return sum(bool(re.search(LOCATION_PATTERN, str(j.get("location") or ""), re.IGNORECASE)) for j in jobs)


def check_employer(employer):
    """Ask the four systems at the same time; the first 'match' wins, else the first 'check'."""
    systems = ["greenhouse", "workable", "lever", "ashby"]
    with ThreadPoolExecutor(len(systems)) as pool:
        results = dict(zip(systems, pool.map(lambda ats: check_system(ats, employer), systems)))
    hits = [(ats, r) for ats, r in results.items() if r]
    hits.sort(key=lambda h: h[1][3] != "match")
    return hits[0] if hits else (None, None)


def main():
    if not SPONSORS.exists():
        raise SystemExit(f"No sponsor list at {SPONSORS}. Download the DETE file and click 'Update sponsor list'.")
    sponsors = pd.read_csv(SPONSORS)
    # One row per employer (some appear under two legal entities), largest first
    sponsors["key"] = sponsors["employer"].apply(lambda e: " ".join(words_of(e)))
    employers = (sponsors.sort_values("total", ascending=False)
                 .groupby("key").agg(employer=("employer", "first"), permits=("total", "sum"),
                                     months=("months_active", "max"))
                 .query("permits >= @MIN_PERMITS").sort_values("permits", ascending=False))
    earlier = pd.read_csv(OUT, dtype=str).fillna("") if OUT.exists() else pd.DataFrame(columns=["employer"])
    if "jobs_here" not in earlier:  # files from before this column existed
        earlier["jobs_here"] = ""
    # Boards found on an earlier run but not yet counted: count their jobs in your locations now
    for idx in earlier.index[(earlier.get("board_token", pd.Series(dtype=str)) != "") & (earlier["jobs_here"] == "")]:
        row = earlier.loc[idx]
        here = jobs_in_your_area(row["ats"], row["board_token"])
        earlier.loc[idx, "jobs_here"] = str(here)
        if here == 0:
            earlier.loc[idx, "status"] = "no jobs here"
        print(f"  Counted again: {row['employer'][:45]:<45} {here} of {row['jobs_now']} jobs in your locations"
              + ("  <- added to your boards: you can delete it there" if here == 0 and row["added"] == "yes" else ""))
    have_boards = set(pd.read_csv(COMPANIES, dtype=str)["company"].fillna("").map(lambda c: " ".join(words_of(c))))
    todo = employers[~employers["employer"].isin(earlier["employer"]) & ~employers.index.isin(have_boards)]
    print(f"{len(employers)} employers with {MIN_PERMITS}+ permits; {len(todo)} not checked before"
          + (f" (about {len(todo) * 2 // 60 + 1} minutes)" if len(todo) else "") + "\n")

    rows = []
    for i, (_, e) in enumerate(todo.iterrows(), 1):
        ats, hit = check_employer(e["employer"])
        token, name, jobs, status = hit if hit else ("", "", "", "not found")
        here = jobs_in_your_area(ats, token) if hit else ""
        if hit and here == 0:
            status = "no jobs here"  # a board in another country, or no vacancies here right now
        rows.append({"employer": e["employer"], "permits": int(e["permits"]), "months": int(e["months"]),
                     "ats": ats or "", "board_token": token, "board_name": name, "jobs_now": jobs, "jobs_here": here,
                     "status": status, "careers_page": "", "added": "", "checked_on": datetime.now().strftime("%Y-%m-%d")})
        if hit:
            print(f"  [{i}/{len(todo)}] {e['employer'][:45]:<45} {ats:<10} {token:<20} {status} "
                  f"({jobs} jobs, {here} in your locations)")
        elif i % 25 == 0:
            print(f"  [{i}/{len(todo)}] ...")

    result = pd.concat([earlier, pd.DataFrame(rows).astype(str)], ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT, index=False)
    found = result[result["status"] != "not found"]
    print(f"\nBoards found for {len(found)} of {len(result)} employers "
          f"({(found['status'] == 'match').sum()} name matches, {(found['status'] == 'check').sum()} to check, "
          f"{(found['status'] == 'no jobs here').sum()} with no jobs in your locations).")
    print(f"Saved {OUT}. Add them in the app: 2. Find jobs > Find sponsors' career sites.")


if __name__ == "__main__":
    main()
