"""Score each job against your skills and build a shortlist.

Reads every job file in JOB_FILES (from the fetch_*.py scripts, plus jobs you added yourself) and
skills_vocab.csv (your editable skills list). For each job it finds:
  - which skills the ad asks for, and how many of those you have (skill score)
  - the highest "X years" of experience the ad mentions
  - any non-English language the ad requires
  - whether the title is senior/manager level
Writes every job with its scores to data/processed/jobs_scored.csv.
"""
import re
from pathlib import Path

import pandas as pd

from settings import setting
from track_applications import load_log, match_applications

# ---- Settings (edit app_settings.json, or use the sliders in the app) ---------
DAYS = setting("days", 30)                        # posting time frame: jobs first published in the last N days
MAX_YEARS = setting("max_years", 4)               # the most "years of experience" you will apply for
MY_LANGUAGES = setting("languages", ["english"])
MIN_SCORE = setting("min_score", 0.6)             # weighted share of the ad's skills you must have
MIN_SKILLS_MATCHED = setting("min_skills_matched", 3)
SALARY_FLOOR = setting("salary_floor", 0)         # lowest yearly pay you'll accept (0 = no floor)
CURRENCY = setting("currency", "€")               # the symbol pay is written with in the ads: €, £ or $
INCLUDE_INTERNAL = setting("include_internal", False)  # True if eligible for HSE "Internal and Confined" jobs
# -----------------------------------------------------------------------------

SOURCES = {"greenhouse": Path("data/processed/jobs_greenhouse.csv"), "hse": Path("data/processed/jobs_hse.csv"),
           "jooble": Path("data/processed/jobs_jooble.csv")}
MANUAL = Path("data/processed/jobs_manual.csv")  # jobs you added by link or pasted text: always scored
JOB_FILES = [path for name, path in SOURCES.items() if setting(f"use_{name}", name != "jooble")] + [MANUAL]
VOCAB = Path("skills_vocab.csv")
HSE_PAY = Path("hse_grade_pay.csv")  # HSE pay scales by grade (June 2026)
OUT = Path("data/processed/jobs_scored.csv")

LANGUAGES = ["german", "french", "spanish", "italian", "dutch", "portuguese", "polish",
             "japanese", "korean", "mandarin", "arabic", "swedish", "danish",
             "norwegian", "finnish", "hebrew", "turkish", "czech", "greek", "nordic"]
SENIOR_PATTERN = r"senior|\bsr\b|staff|principal|\blead\b|head of|director|(?<!account )manager|\bvp\b"
YEARS_PATTERN = r"(\d{1,2})\s*\+?\s*(?:years|yrs)"
BOILERPLATE_SHARE = 0.3  # a sentence in 30%+ of one company's ads is company boilerplate


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def remove_boilerplate(jobs):
    """Drop sentences that repeat across many ads from the same company
    (the 'About us', benefits and equal-opportunity text), keeping the
    part of each ad that is about the actual job."""
    cores = pd.Series("", index=jobs.index)
    for company, group in jobs.groupby("company"):
        sentence_lists = group["description"].apply(split_sentences)
        if len(group) < 3:  # too few ads to tell what repeats
            cores[group.index] = group["description"]
            continue
        counts = {}
        for sentences in sentence_lists:
            for sentence in set(sentences):
                counts[sentence] = counts.get(sentence, 0) + 1
        limit = max(2, BOILERPLATE_SHARE * len(group))
        for idx, sentences in sentence_lists.items():
            # short sentences ("Python.") are always kept: too short to be boilerplate
            cores[idx] = " ".join(s for s in sentences if len(s) <= 20 or counts[s] < limit)
    return cores


PAY_AMOUNT = re.compile(re.escape(CURRENCY) + r"\s?(\d{2,3}(?:[,.]\d{3})+|\d{2,3}\s?[kK])\b")


def salary_from_text(text):
    """Find yearly pay amounts in the ad (e.g. '€66.000 — €78.000', '€45k'), in your currency.
    Amounts under 15,000 are ignored (monthly pay, bonuses). Returns (min, max) or (None, None)."""
    amounts = []
    for raw in PAY_AMOUNT.findall(text or ""):
        raw = raw.replace(" ", "")
        value = int(raw[:-1]) * 1000 if raw[-1] in "kK" else int(re.sub(r"[,.]", "", raw))
        if 15000 <= value <= 500000:
            amounts.append(value)
    return (min(amounts), max(amounts)) if amounts else (None, None)


def find_skills(text, vocab):
    """Return the skills in the ad you have, the ones you don't, and their weights."""
    have, missing, w_have, w_missing = [], [], 0, 0
    for _, row in vocab.iterrows():
        flags = 0 if row["case_sensitive"] == "yes" else re.IGNORECASE
        if re.search(row["pattern"], text, flags):
            if row["i_have_it"] == "yes":
                have.append(row["skill"])
                w_have += row["weight"]
            else:
                missing.append(row["skill"])
                w_missing += row["weight"]
    return have, missing, w_have, w_missing


def years_required(text):
    numbers = [int(n) for n in re.findall(YEARS_PATTERN, text, re.IGNORECASE) if int(n) <= 20]
    return max(numbers) if numbers else None


def languages_required(title, text):
    """Non-English languages the ad asks for (in the title, or as fluent/native/proficient)."""
    found = set()
    for lang in LANGUAGES:
        if lang in MY_LANGUAGES:
            continue
        in_title = re.search(rf"\b{lang}\b", title, re.IGNORECASE)
        in_text = re.search(rf"(fluen\w*|native|business[- ]level|proficien\w*|speak\w*)"
                            rf"[^.]{{0,60}}\b{lang}\b|\b{lang}\b[^.]{{0,20}}(speak\w*|fluen\w*)",
                            text, re.IGNORECASE)
        if in_title or in_text:
            found.add(lang.title())
    return sorted(found)


def main():
    frames = [pd.read_csv(p, dtype={"job_id": str}) for p in JOB_FILES if p.exists() and p.stat().st_size > 5]
    if not frames:
        raise SystemExit("No job files yet. Fetch jobs first (the 'Fetch new jobs' button).")
    jobs = pd.concat(frames, ignore_index=True)
    # The same ad can come from two sources (e.g. a company's own board and Jooble): keep the first,
    # which is the direct source, because the sources are read in that order
    same = jobs["company"].str.lower().str.strip() + "|" + jobs["title"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    first_source = jobs.groupby(same)["source"].transform("first")
    repeat = jobs["source"] != first_source  # same company and title, but from a later source
    if repeat.any():
        print(f"Removed {int(repeat.sum())} ads also found on the company's own board or another source")
        jobs = jobs[~repeat].reset_index(drop=True)
    print("Jobs per source:", jobs["source"].value_counts().to_dict())
    vocab = pd.read_csv(VOCAB)
    jobs["description"] = jobs["description"].fillna("")
    print(f"Scoring {len(jobs):,} jobs against {(vocab['i_have_it'] == 'yes').sum()} "
          f"of your skills ({len(vocab)} skills in the list)\n")

    jobs["core_text"] = remove_boilerplate(jobs)
    jobs["boilerplate_share"] = 1 - jobs["core_text"].str.len() / jobs["description"].str.len().clip(lower=1)
    print("Share of each company's ad text removed as boilerplate (About us, benefits, etc.):")
    print(jobs.groupby("company")["boilerplate_share"].mean().map("{:.0%}".format).to_string(), "\n")

    results = jobs.apply(lambda j: find_skills(j["title"] + " " + j["core_text"], vocab), axis=1)
    jobs["skills_you_have"] = [", ".join(r[0]) for r in results]
    jobs["skills_missing"] = [", ".join(r[1]) for r in results]
    jobs["n_have"] = [len(r[0]) for r in results]
    jobs["n_asked"] = [len(r[0]) + len(r[1]) for r in results]
    # Weighted score: technical skills (weight 3) count more than general ones (weight 1)
    w_have = pd.Series([r[2] for r in results], index=jobs.index)
    w_all = pd.Series([r[2] + r[3] for r in results], index=jobs.index)
    jobs["skill_score"] = (w_have / w_all).where(w_all > 0).round(2)

    jobs["years_required"] = jobs["core_text"].apply(years_required)
    jobs["languages_required"] = jobs.apply(
        lambda j: ", ".join(languages_required(j["title"], j["description"])), axis=1)
    jobs["senior"] = jobs["title"].str.contains(SENIOR_PATTERN, case=False, na=False)

    # HSE jobs: the grade (not the title) sets the level and the pay
    if "grade" in jobs and HSE_PAY.exists():
        pay = pd.read_csv(HSE_PAY)
        jobs["grade_band"] = jobs["grade"].fillna("").str.extract(r"Grade\s+(VIII|VII|VI|V|IV|III)\b", expand=False)
        jobs = jobs.merge(pay[["grade", "pay_min", "pay_max", "suits_your_level"]]
                          .rename(columns={"grade": "grade_band"}), on="grade_band", how="left")
        is_hse = jobs["source"] == "hse"
        jobs.loc[is_hse, "senior"] = jobs.loc[is_hse, "suits_your_level"].ne("yes")
    else:
        jobs["pay_min"] = float("nan")
        jobs["pay_max"] = float("nan")
    jobs["pay_source"] = jobs["pay_min"].notna().map({True: "HSE grade", False: "unknown"})

    # Other jobs: look for a pay range written in the ad itself
    from_text = jobs["description"].apply(salary_from_text)
    found = jobs["pay_min"].isna() & from_text.str[0].notna()
    jobs.loc[found, "pay_min"] = from_text[found].str[0]
    jobs.loc[found, "pay_max"] = from_text[found].str[1]
    jobs.loc[found, "pay_source"] = "ad text"
    print("Where the pay figure came from:", jobs["pay_source"].value_counts().to_dict(), "\n")
    jobs["recent"] = (jobs["days_old"] <= DAYS) | (jobs["source"] == "manual")  # you chose these yourself

    # Each test on its own column, so you can see WHY a job was left out
    jobs["ok_recent"] = jobs["recent"]
    jobs["ok_level"] = ~jobs["senior"]
    jobs["ok_years"] = jobs["years_required"].isna() | (jobs["years_required"] <= MAX_YEARS)
    jobs["ok_language"] = jobs["languages_required"] == ""
    # HSE only: still open for applications, and open to you (not internal-only)
    jobs["ok_open"] = jobs["still_open"].astype("boolean").fillna(True).astype(bool) if "still_open" in jobs else True
    if "ad_type" in jobs and not INCLUDE_INTERNAL:
        jobs["ok_eligible"] = ~jobs["ad_type"].fillna("").str.contains("internal|secondment", case=False)
    else:
        jobs["ok_eligible"] = True
    # Salary: checked when the pay is known; unknown pay passes, flagged as 'ask at interview'
    jobs["ok_salary"] = jobs["pay_min"].isna() | (jobs["pay_min"] >= SALARY_FLOOR)
    jobs["ok_skills"] = (jobs["skill_score"] >= MIN_SCORE) & (jobs["n_have"] >= MIN_SKILLS_MATCHED)

    # Never apply twice: leave out jobs already in data/applications.csv, flag look-alikes
    log = load_log()
    jobs = match_applications(jobs, log)
    jobs["ok_not_applied"] = jobs["applied_on"] == ""
    print(f"Applications in your log: {len(log)}")

    tests = ["ok_recent", "ok_open", "ok_eligible", "ok_level", "ok_salary", "ok_years", "ok_language",
             "ok_skills", "ok_not_applied"]
    jobs["shortlist"] = jobs[tests].all(axis=1)

    print("How many jobs pass each test:")
    for test in tests:
        print(f"  {test:<12} {jobs[test].sum():>4} of {len(jobs)}")
    print(f"  {'ALL TESTS':<12} {jobs['shortlist'].sum():>4}")

    recent = jobs[jobs["ok_recent"]]
    print(f"\nWhy recent jobs were left out (a job can fail more than one test):")
    for test in tests[1:]:
        print(f"  failed {test:<12} {(~recent[test]).sum():>4}")

    shortlist = jobs[jobs["shortlist"]].sort_values(["skill_score", "n_have"], ascending=False)
    print(f"\nSHORTLIST ({len(shortlist)} jobs, best match first):")
    if shortlist.empty:
        print("  none today - see 'near misses' below")
    for _, j in shortlist.iterrows():
        print(f"\n  {j['company']} | {j['title']} | {j['days_old']} days old")
        if j["possible_repeat"]:
            print(f"    CHECK: looks like a job you already applied to: {j['possible_repeat']}")
        if j["source"] == "hse":
            print(f"    {j['grade']} (EUR {j['pay_min']:,.0f}-{j['pay_max']:,.0f}) | {j['ad_type']} | "
                  f"closes {j['closing_date']} | job spec read: {j['has_job_spec']}")
        if j["source"] != "hse":
            pay = (f"{j['pay_min']:,.0f}-{j['pay_max']:,.0f} (from the ad)" if pd.notna(j["pay_min"])
                   else f"not stated - check it is at least {SALARY_FLOOR:,.0f} before applying")
            print(f"    pay: {pay}")
        print(f"    score {j['skill_score']:.0%} ({j['n_have']} of {j['n_asked']} skills)"
              f" | years asked: {int(j['years_required']) if pd.notna(j['years_required']) else '-'}")
        print(f"    you have: {j['skills_you_have']}")
        if j["skills_missing"]:
            print(f"    missing:  {j['skills_missing']}")
        print(f"    {j['url']}")

    jobs["n_failed"] = (~jobs[tests]).sum(axis=1)
    near = jobs[jobs["ok_recent"] & (jobs["n_failed"] == 1)].sort_values(
        ["n_have", "skill_score"], ascending=False).head(10)
    print("\nNEAR MISSES (recent, failed exactly ONE test, most skills matched first):")
    for _, j in near.iterrows():
        failed = [t.replace("ok_", "") for t in tests if not j[t]][0]
        detail = {"open": "closing date passed", "eligible": "internal-only",
                  "not_applied": f"you applied on {j['applied_on']}",
                  "salary": f"starts at {j['pay_min']:,.0f}" if pd.notna(j.get("pay_min")) else "",
                  "years": f"asks {int(j['years_required']) if pd.notna(j['years_required']) else '?'} yrs",
                  "language": j["languages_required"], "level": "senior title",
                  "skills": f"{j['n_have']} of {j['n_asked']} skills"}.get(failed, "")
        print(f"  {j['company']} | {j['title']} | failed: {failed} ({detail})")

    unscored = jobs[jobs["ok_recent"] & jobs["ok_level"] & jobs["ok_years"] & jobs["ok_language"] & (jobs["n_asked"] == 0)]
    print(f"\nNO SKILLS RECOGNISED ({len(unscored)} recent jobs - check these by eye, or add skills to skills_vocab.csv):")
    for _, j in unscored.head(10).iterrows():
        print(f"  {j['company']} | {j['title']} | {j['url']}")

    print("\nYears of experience asked for (recent jobs at your level, no language barrier):")
    pool = jobs[jobs["ok_recent"] & jobs["ok_level"] & jobs["ok_language"]]
    print(pool["years_required"].value_counts(dropna=False).sort_index().rename("jobs").to_string())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    jobs.drop(columns=["description", "core_text"]).to_csv(OUT, index=False)
    print(f"\nSaved all {len(jobs):,} scored jobs to {OUT} (open it in Excel to explore)")


if __name__ == "__main__":
    main()
