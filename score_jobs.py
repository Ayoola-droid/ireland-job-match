"""Score each job against your skills and build a shortlist.

Reads every job file in JOB_FILES (from the fetch_*.py scripts, plus jobs you added yourself) and
skills_vocab.csv (your editable skills list). For each job it finds:
  - which skills the ad asks for, how important each one is (under "Minimum requirements",
    or only "Nice to have"), and how many of those you have (skill score)
  - any must-have skill you don't have (the ok_essentials test)
  - the highest "X years" of experience the ad mentions
  - any non-English language the ad requires
  - whether the title is senior/manager level
Writes every job with its scores to data/processed/jobs_scored.csv.
"""
import re
from datetime import datetime
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

SOURCES = {"greenhouse": Path("data/processed/jobs_boards.csv"),  # all company career boards (setting name kept)
           "hse": Path("data/processed/jobs_hse.csv"),
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
CLOSING_HOUR = 12  # applications close at this hour on the closing date (HSE: 12:00 noon)

# ---- Essential vs nice-to-have skills ----------------------------------------
# A skill under "Minimum requirements" counts more than one under "Nice to have".
IMPORTANCE = {"essential": 2.0, "normal": 1.0, "desirable": 0.5}
# Short ads (e.g. Jooble snippets) name only a few skills, so 2 out of 2 would look like 100%.
# Each score is worked out as if the ad might ask for one more technical skill you haven't seen
# (weight 3): long ads hardly change, short ones can't reach 100% on a handful of words.
UNSEEN_WEIGHT = 3

# Headings that start each part of an ad. They are matched only when they start with a capital
# letter and the next item follows straight after, so a sentence such as "if you meet the
# minimum requirements to apply" is not taken for a heading.
ESSENTIAL_HEADINGS = [
    r"minimum (?:requirements|qualifications)", r"basic qualifications",
    r"required (?:skills|qualifications|experience)", r"(?:key |core |essential |job )?requirements",
    r"essential(?: criteria| skills| experience)?", r"post specific requirements", r"eligibility criteria",
    r"skills, competencies and/or knowledge", r"what you(?:'|’)?ll (?:need|bring)(?: to (?:thrive|succeed))?",
    r"what you will (?:need|bring)", r"what we(?:'|’)?re looking for", r"what we are looking for",
    r"who you are", r"about you", r"you (?:have|bring|will have)", r"must[- ]haves?",
    r"qualifications(?: and experience)?", r"skills (?:and|&) experience", r"your (?:experience|profile|skills)",
    r"what (?:skills )?(?:do i|will i|do you|will you) need\??"]
DESIRABLE_HEADINGS = [
    r"preferred (?:requirements|qualifications|skills|experience)", r"nice[- ]to[- ]haves?",
    r"bonus (?:points|skills)(?: and attributes)?(?: if)?", r"desirable(?: criteria| skills| requirements| experience)?",
    r"it(?:'|’)?s a (?:plus|bonus)(?: if)?", r"it would be (?:great|nice|a plus)(?: if)?", r"pluses",
    r"extra credit", r"even better(?: if)?", r"additional skills", r"good to have"]
OTHER_HEADINGS = [  # these end the requirements: the duties, the pay
    r"about the (?:role|job|position)", r"how to apply",
    r"(?:key |principal )?(?:duties|responsibilities)(?: and responsibilities)?", r"what you(?:'|’)?ll do",
    r"what you will do", r"what will (?:i|you) be doing\??", r"the role", r"in this role", r"purpose of the post",
    r"remuneration", r"salary", r"working hours"]
# The employer selling itself: the company, its benefits and its parent company ("When you join
# Salesforce..." in Intercom's ads). Skills named here are not asked of you, so they don't count at all.
COMPANY_HEADINGS = [
    r"about (?:us|the (?:team|company))", r"about [A-Z]\w+", r"benefits", r"what we offer", r"perks",
    r"why (?:join|work)", r"our (?:benefits|commitment|values|mission|culture)",
    r"equal (?:employment )?opportunit\w+", r"when you join", r"unleash your potential", r"life at [A-Z]\w+"]
# Words next to a skill that say how much it matters ("SQL is a plus", "Python required")
DESIRABLE_CUE = re.compile(r"\bplus\b|\bbonus\b|nice[- ]to[- ]have|\bpreferred\b|\bpreferabl\w*|\bdesirabl\w*"
                           r"|\badvantage\w*|\bbeneficial\b|\bideally\b|\bwould be great\b|\bnot (?:required|essential)\b",
                           re.IGNORECASE)
# "Salesforce (or similar CRM)", "SAP or equivalent", "e.g. AWS": the ad accepts other tools, so not a strict must-have
ALTERNATIVE_CUE = re.compile(r"\bor (?:a |any )?(?:similar|equivalent|comparable|other)\b|\be\.g\.|\bsuch as\b"
                             r"|\bfor (?:example|instance)\b|\betc\b",
                             re.IGNORECASE)
ESSENTIAL_CUE = re.compile(r"\bmust\b|\brequired\b|\bessential\b|\bmandatory\b|\bextensive\b|\bsignificant experience\b",
                           re.IGNORECASE)
CUE_BEFORE, CUE_AFTER = 40, 60  # how many characters either side of the skill to look at


def _heading_regex(phrases):
    return re.compile(r"(?i:\b(?:" + "|".join(phrases) + r"))(?:\s*\([^)]{0,40}\))?\s*[:\-–—]?"
                      r"(?=\s*(?:[A-Z0-9•·▪*\-]|\n|$))")


HEADINGS = [(kind, _heading_regex(phrases)) for kind, phrases in
            [("essential", ESSENTIAL_HEADINGS), ("desirable", DESIRABLE_HEADINGS), ("normal", OTHER_HEADINGS),
             ("company", COMPANY_HEADINGS)]]


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def is_heading(sentence):
    """A short sentence that is one of the requirement headings ("What skills do I need?")."""
    return len(sentence) <= 60 and any(rx.match(sentence) for _, rx in HEADINGS)


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
            # short sentences ("Python.") are always kept: too short to be boilerplate. Headings such as
            # "What skills do I need?" repeat in every ad too, but are kept: they show what is essential
            cores[idx] = " ".join(s for s in sentences if len(s) <= 20 or counts[s] < limit or is_heading(s))
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


def compile_vocab(vocab):
    """Prepare each skill's search pattern once, instead of once per job (much faster)."""
    return [(row["skill"], re.compile(row["pattern"], 0 if row["case_sensitive"] == "yes" else re.IGNORECASE),
             row["i_have_it"] == "yes", row["weight"]) for _, row in vocab.iterrows()]


def find_skills(text, vocab):
    """Return the skills in the ad you have, the ones you don't, and their weights.
    `vocab` is the skills table, or the result of compile_vocab(skills table)."""
    if isinstance(vocab, pd.DataFrame):
        vocab = compile_vocab(vocab)
    have, missing, w_have, w_missing = [], [], 0, 0
    for skill, pattern, i_have_it, weight in vocab:
        if pattern.search(text):
            if i_have_it:
                have.append(skill)
                w_have += weight
            else:
                missing.append(skill)
                w_missing += weight
    return have, missing, w_have, w_missing


def requirement_sections(text):
    """Split an ad into parts by its headings. Returns [(start, end, kind)], where kind is
    'essential' (Minimum requirements, Who you are...), 'desirable' (Nice to have, Preferred...),
    'company' (About us, benefits: not about you) or 'normal' (everything else: the intro, the duties)."""
    # Where two headings match the same words, the longest wins ("About the role" over "About the"),
    # then the order of HEADINGS ("About you" is a requirement, not the company's "About Stripe")
    priority = {kind: i for i, (kind, _) in enumerate(HEADINGS)}
    marks = sorted(((m.start(), m.end(), kind) for kind, rx in HEADINGS for m in rx.finditer(text)
                    if m.group(0)[0].isupper()), key=lambda h: (h[0], -h[1], priority[h[2]]))
    headings = []
    for start, end, kind in marks:  # "Preferred requirements" also contains "requirements": keep the first
        if not headings or start >= headings[-1][1]:
            headings.append((start, end, kind))
    sections, pos, kind = [], 0, "normal"
    for start, end, next_kind in headings:
        sections.append((pos, start, kind))
        pos, kind = end, next_kind
    sections.append((pos, len(text), kind))
    return [s for s in sections if s[1] > s[0]]


def importance_at(text, start, end, sections):
    """How much one mention of a skill matters: its section first, then the words around it
    in the same sentence or list item ('...is a plus' makes it desirable, '...required' essential)."""
    kind = next((k for s, e, k in sections if s <= start < e), "normal")
    if kind == "company":
        return "company"
    before = re.split(r"[.!?;\n•]", text[max(0, start - CUE_BEFORE):start])[-1]
    after = re.split(r"[.!?;\n•]", text[end:end + CUE_AFTER])[0]
    nearby = before + " " + after
    if DESIRABLE_CUE.search(nearby):
        return "desirable"
    if ALTERNATIVE_CUE.search(nearby):
        return "normal"
    if kind == "normal" and ESSENTIAL_CUE.search(nearby):
        return "essential"
    return kind


def rate_skills(text, vocab):
    """Like find_skills, but also says how important each skill is in this ad.
    A skill mentioned several times takes its most important mention.
    Returns {skill: (importance, you_have_it, weight)}."""
    if isinstance(vocab, pd.DataFrame):
        vocab = compile_vocab(vocab)
    sections = requirement_sections(text)
    rank = {"desirable": 0, "normal": 1, "essential": 2}
    found = {}
    for skill, pattern, i_have_it, weight in vocab:
        levels = [level for m in pattern.finditer(text)
                  if (level := importance_at(text, m.start(), m.end(), sections)) != "company"]
        if levels:
            found[skill] = (max(levels, key=rank.get), i_have_it, weight)
    return found


def score_from_rated(found):
    """Weighted share of the ad's skills you have: weight (3 technical, 1 general) times importance
    (essential 2, normal 1, nice to have 0.5), with one unseen technical skill added (UNSEEN_WEIGHT)."""
    w_have = sum(w * IMPORTANCE[imp] for imp, have, w in found.values() if have)
    w_all = sum(w * IMPORTANCE[imp] for imp, have, w in found.values())
    return round(w_have / (w_all + UNSEEN_WEIGHT), 2) if w_all else float("nan")


def still_open(jobs, now=None):
    """Is each job still taking applications right now? Worked out from the closing date every time
    you score, not when the jobs were fetched, so a job that closed since then drops off.
    The closing day itself counts until CLOSING_HOUR (HSE campaigns close at 12:00 noon).
    Jobs with no closing date (most company boards) count as open."""
    now = now or datetime.now()
    if "closing_date" not in jobs:
        return pd.Series(True, index=jobs.index)
    closing = pd.to_datetime(jobs["closing_date"], errors="coerce")
    deadline = closing + pd.Timedelta(hours=CLOSING_HOUR)
    return (closing.isna() | (deadline > now)).astype(bool)


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

    compiled = compile_vocab(vocab)
    rated = jobs.apply(lambda j: rate_skills(j["title"] + "\n" + j["core_text"], compiled), axis=1)
    jobs["skills_you_have"] = [", ".join(s for s, (_, have, _) in r.items() if have) for r in rated]
    jobs["skills_missing"] = [", ".join(s for s, (_, have, _) in r.items() if not have) for r in rated]
    jobs["essentials_you_have"] = [", ".join(s for s, (imp, have, _) in r.items() if have and imp == "essential")
                                   for r in rated]
    jobs["essentials_missing"] = [", ".join(s for s, (imp, have, _) in r.items() if not have and imp == "essential")
                                  for r in rated]
    jobs["nice_to_have"] = [", ".join(s for s, (imp, _, _) in r.items() if imp == "desirable") for r in rated]
    jobs["n_have"] = [sum(have for _, have, _ in r.values()) for r in rated]
    jobs["n_asked"] = [len(r) for r in rated]
    # The old score (every skill counts the same) is kept for comparison
    jobs["skill_score_simple"] = [round(sum(w for _, h, w in r.values() if h) / sum(w for _, _, w in r.values()), 2)
                                  if r else float("nan") for r in rated]
    # Weighted score: technical skills (3) count more than general ones (1), essential ones (x2) more than
    # nice-to-haves (x0.5), and short ads can't reach 100% on a few words (see UNSEEN_WEIGHT)
    jobs["skill_score"] = [score_from_rated(r) for r in rated]

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
    if found.any():
        jobs.loc[found, "pay_min"] = from_text[found].str[0].astype(float)
        jobs.loc[found, "pay_max"] = from_text[found].str[1].astype(float)
        jobs.loc[found, "pay_source"] = "ad text"
    print("Where the pay figure came from:", jobs["pay_source"].value_counts().to_dict(), "\n")
    jobs["recent"] = (jobs["days_old"] <= DAYS) | (jobs["source"] == "manual")  # you chose these yourself

    # Each test on its own column, so you can see WHY a job was left out
    jobs["ok_recent"] = jobs["recent"]
    jobs["ok_level"] = ~jobs["senior"]
    jobs["ok_years"] = jobs["years_required"].isna() | (jobs["years_required"] <= MAX_YEARS)
    jobs["ok_language"] = jobs["languages_required"] == ""
    # HSE only: still open for applications, and open to you (not internal-only)
    jobs["ok_open"] = still_open(jobs)
    if "ad_type" in jobs and not INCLUDE_INTERNAL:
        jobs["ok_eligible"] = ~jobs["ad_type"].fillna("").str.contains("internal|secondment", case=False)
    else:
        jobs["ok_eligible"] = True
    # Salary: checked when the pay is known; unknown pay passes, flagged as 'ask at interview'
    jobs["ok_salary"] = jobs["pay_min"].isna() | (jobs["pay_min"] >= SALARY_FLOOR)
    jobs["ok_skills"] = (jobs["skill_score"] >= MIN_SCORE) & (jobs["n_have"] >= MIN_SKILLS_MATCHED)
    # Must-haves: an ad that lists a skill you don't have under its essential requirements is left out
    # (it shows as a near miss, so you can still decide for yourself)
    jobs["ok_essentials"] = jobs["essentials_missing"] == ""

    # Never apply twice: leave out jobs already in data/applications.csv, flag look-alikes
    log = load_log()
    jobs = match_applications(jobs, log)
    jobs["ok_not_applied"] = jobs["applied_on"] == ""
    print(f"Applications in your log: {len(log)}")

    tests = ["ok_recent", "ok_open", "ok_eligible", "ok_level", "ok_salary", "ok_years", "ok_language",
             "ok_skills", "ok_essentials", "ok_not_applied"]
    jobs["shortlist"] = jobs[tests].all(axis=1)

    print("How many jobs pass each test:")
    for test in tests:
        print(f"  {test:<15} {jobs[test].sum():>4} of {len(jobs)}")
    print(f"  {'ALL TESTS':<15} {jobs['shortlist'].sum():>4}")

    recent = jobs[jobs["ok_recent"]]
    print(f"\nWhy recent jobs were left out (a job can fail more than one test):")
    for test in tests[1:]:
        print(f"  failed {test:<15} {(~recent[test]).sum():>4}")

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
        if j["essentials_you_have"]:
            print(f"    must-haves you have: {j['essentials_you_have']}")
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
                  "skills": f"{j['n_have']} of {j['n_asked']} skills",
                  "essentials": f"must have {j['essentials_missing']}"}.get(failed, "")
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
