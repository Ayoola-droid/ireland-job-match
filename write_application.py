"""Write a cover letter or HSE-style competency answers with the AI model on YOUR laptop.

Uses LM Studio's local server (nothing leaves your computer). The model is given
ONLY numbered evidence from cv_master.json and must cite it, e.g. [P2] or [E5].
Three automatic checks then look for the usual AI mistakes:
  1. sentences with no citation (possible invented claims)
  2. skills you marked 'no' in skills_vocab.csv (e.g. Salesforce)
  3. numbers that don't appear in your evidence (invented statistics)
Output: output/COVER_<company>_<id>.md (with citations and the check report)
        output/COVER_<company>_<id>.docx (clean text, citations removed, to edit and send)
Always read and edit the result yourself before sending it.
"""
import json
import re
from pathlib import Path

import pandas as pd
from docx import Document
from docx.shared import Pt

from local_ai import ask_model, describe
from cv_import import guess_kind
from settings import setting
from proofread import known_words, proofread
from tailor_cv import JOB_FILES, MASTER, RANKED, VOCAB, pick_job, relevance, requirements, words

# ---- Settings you can change ------------------------------------------------
# (which AI model to use, and its temperature, are set in ai_settings.json)
MAX_EVIDENCE = 12           # how many CV pieces the model may use
MAX_WORDS = 300
# -----------------------------------------------------------------------------

OUT_DIR = Path("output")
# Opening and closing sentences ("I am applying for...", "I would welcome...") need no citation
COURTESY = re.compile(r"\b(apply|applying|welcome|discuss|look forward|thank|opportunity to|"
                      r"transfer\w*|carr(?:y|ies) over|equip\w*|prepared me|shows? (?:that )?I can|keen to)\b", re.I)


def evidence_meta(master):
    """What each evidence id is: a job (with role and employer), university study, a personal
    portfolio project, the profile summary, or a certificate."""
    meta, n = {}, 0
    for i, p in enumerate(master["projects"]):
        meta[f"P{i + 1}"] = {"kind": "project", "text": f"{p['title']}: {p['bullet']}", "tags": p["tags"]}
    for role in master["experience"]:
        parts = [x.strip() for x in role["heading"].split("|")]
        title, place, dates = (parts + ["", "", ""])[:3]
        # each role says whether it was a job or study (set in the app's CV editor); older files are guessed
        kind = role.get("kind") or guess_kind(role["heading"])
        org = place.split(",")[0].strip()
        for b in role["bullets"]:
            n += 1
            meta[f"E{n}"] = {"kind": kind, "role": title, "org": org, "place": place, "dates": dates,
                             "text": b["text"], "tags": b["tags"]}
    for i, s in enumerate(master["summary"]):
        meta[f"S{i + 1}"] = {"kind": "summary", "text": s["text"], "tags": s["tags"]}
    for i, c in enumerate(master.get("certificates", [])):
        meta[f"C{i + 1}"] = {"kind": "certificate", "text": c, "tags": []}
    return meta


def label(pid, m):
    """How an evidence item is presented to the AI, so it can't mistake a project for a job."""
    if m["kind"] == "project":
        return (f"PERSONAL PORTFOLIO PROJECT (done on my own with public data; NOT a job, NOT an employer) - "
                f"{m['text']}")
    if m["kind"] == "job":
        return f"JOB as {m['role']} at {m['place']} ({m['dates']}) - {m['text']}"
    if m["kind"] == "study":
        return f"UNIVERSITY STUDY: {m['role']} at {m['place']} ({m['dates']}) - {m['text']}"
    if m["kind"] == "certificate":
        return f"CERTIFICATE (a training course, not work experience) - {m['text']}"
    return f"PROFILE SUMMARY - {m['text']}"


def evidence_list(master, job_tags, job_words, weights):
    """Number the most relevant CV pieces (P = project, E = job or study, S = summary, C = certificate),
    each labelled with what it is."""
    meta = evidence_meta(master)
    pieces = [(pid, label(pid, m), m["tags"]) for pid, m in meta.items()]
    ranked = sorted(pieces, key=lambda p: -relevance(meta[p[0]]["text"], p[2], job_tags, job_words, weights))
    return ranked[:MAX_EVIDENCE]


def build_prompt(mode, job, reqs, evidence, missing, name="me"):
    evidence_text = "\n".join(f"[{pid}] {text}" for pid, text, _ in evidence)
    req_text = "\n".join(f"- {r}" for r in reqs) or "- (none extracted; use the job title)"
    rules = f"""RULES - follow all of them:
1. Use ONLY facts from the EVIDENCE list. Do not add any skill, tool, number, employer or achievement that is not in it.
2. After every sentence that states a fact about me, put the evidence id(s) in square brackets, e.g. [P2] or [E3][S1].
3. I do NOT have these skills, so never claim them: {', '.join(missing) or 'none listed'}. If the job needs one, you may say I am keen to learn it.
4. Plain, confident {setting("writing_english", "UK/Irish English")}. No clichés such as "I am writing to express my interest" or "passionate".
5. Keep numbers exactly as written in the evidence.
6. Where I lack direct experience of something the job asks for, make the strongest TRUE case from transferable
   experience: name the closest real example from the evidence and say plainly how it carries over
   (e.g. "Although I haven't used X, at Y I did Z, which ..."). Never present a transferable example as direct experience.
7. Each evidence item says what it is. Only JOB items are employment. A PERSONAL PORTFOLIO PROJECT is something I did on
   my own with public data: write "In a personal portfolio project, I analysed <organisation>'s public data ..." and
   NEVER say I worked at, for or with that organisation, or that it was my role. UNIVERSITY STUDY happened during my studies.
8. Name the job title and employer exactly as written in the item you cite. Never move an example from one job to another.
9. Do not invent what the work "involved" (teams, vendors, budgets, segments) beyond the evidence text."""
    if mode == "cover":
        task = (f"Write a cover letter (maximum {MAX_WORDS} words) from {name} for the job below. "
                "Three or four short paragraphs: why this role, two or three pieces of evidence that match the "
                "requirements, and a short close. Do not include addresses or a date.")
    else:
        task = ("For each REQUIREMENT below, write the strongest honest competency answer of 120-180 words in "
                "STAR form (Situation, Task, Action, Result), as asked in HSE application forms.\n"
                "Format each answer as:\n**<the requirement>**\nType: Direct  (or)  Type: Transferable\n<the answer>\n"
                "Use 'Direct' when the evidence shows I have done this exact kind of work. Use 'Transferable' when "
                "you build the answer from a different real situation in the evidence whose skills carry over: "
                "choose the closest one, describe what I actually did, then explain in one or two sentences why it "
                "shows I can meet the requirement. Use an example only once if you can; vary them across answers.\n"
                "Write each answer as flowing STAR prose, not a list of CV bullets: Situation (where and when, one "
                "sentence), Task (what was needed), Action (what I did, the longest part, using 'I'), Result (the "
                "outcome from the evidence, with its numbers if any). Example shape, NOT content to copy: "
                "'In my role as <job title> at <employer> [E1], <situation>. I needed to <task>. I <actions> [E1]. "
                "As a result, <result> [E1].' For a project: 'In a personal portfolio project [P1], ...'")
    return (f"{task}\n\nJOB: {job['title']} at {job['company']}\n\nREQUIREMENTS FROM THE AD:\n{req_text}\n\n"
            f"EVIDENCE (the only facts you may use):\n{evidence_text}\n\n{rules}")


EMPLOYMENT_WORDS = re.compile(r"^\s*(?:At|For)\s+[A-Z]|\bworked (?:at|for|with)\b|\bemployed\b|"
                              r"\bmy (?:role|job|position|time) (?:at|with|as)\b|\bwhile (?:at|working)\b", re.I)


def context_warnings(text, meta):
    """Catch two mistakes: a portfolio project written as if it were a job, and an example
    moved to the wrong employer or role."""
    warnings = []
    jobs = {pid: m for pid, m in meta.items() if m["kind"] in ("job", "study")}
    known_orgs = {m["org"] for m in jobs.values() if m["org"]}
    known_roles = {m["role"] for m in jobs.values() if m["role"]}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        cited = re.findall(r"\[([PESC]\d+)\]", sentence)
        if not cited:
            continue
        if any(meta.get(c, {}).get("kind") == "project" for c in cited) and EMPLOYMENT_WORDS.search(sentence):
            warnings.append(f"Describes a portfolio project as if it were a job: \"{sentence.strip()[:120]}\"")
        cited_jobs = [jobs[c] for c in cited if c in jobs]
        if cited_jobs:
            named_orgs = {o for o in known_orgs if o.lower() in sentence.lower()}
            named_roles = {r for r in known_roles if r.lower() in sentence.lower()}
            wrong = (named_orgs - {j["org"] for j in cited_jobs}) | (named_roles - {j["role"] for j in cited_jobs})
            if wrong:
                source = "; ".join(sorted({f"{j['role']} at {j['org']}" for j in cited_jobs}))
                warnings.append(f"Names {', '.join(sorted(wrong))}, but the cited example is from {source}: "
                                f"\"{sentence.strip()[:120]}\"")
    return warnings


def check(text, evidence, vocab, meta=None):
    """Return a list of warnings about possible invented content."""
    warnings = []
    # Bold lines repeat the ad's requirement, and 'Type:' lines are labels: neither is a claim about me
    text = "\n".join(line for line in text.split("\n")
                     if not line.strip().startswith("**") and not line.strip().lower().startswith("type:"))
    # A citation written after the full stop ("...sales. [E11]") belongs to that sentence
    text = re.sub(r"([.!?])[ \t]*((?:\[[PESC]\d+\])+)", r" \2\1", text)
    ids = {pid for pid, _, _ in evidence}
    if meta:
        warnings += context_warnings(text, meta)
    cited = set(re.findall(r"\[([PESC]\d+)\]", text))
    for bad in sorted(cited - ids):
        warnings.append(f"Cites [{bad}], which is not in the evidence list")
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        s = sentence.strip()
        if (len(s.split()) >= 8 and not re.search(r"\[[PESC]\d+\]", s)
                and re.search(r"\b(I|my|me)\b", s) and not s.startswith("**")
                and not COURTESY.search(s)):
            warnings.append(f"No citation: \"{s[:120]}\"")
    # Skills you don't have may only appear in an honest sentence ("I haven't used X", "keen to learn X")
    honest = re.compile(r"learn|training|certificate|keen|develop|haven't|have not|not used|although|"
                        r"transfer|carr(?:y|ies) over", re.I)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if honest.search(sentence):
            continue
        for _, row in vocab[vocab["i_have_it"] == "no"].iterrows():
            flags = 0 if row["case_sensitive"] == "yes" else re.IGNORECASE
            if re.search(row["pattern"], sentence, flags):
                warnings.append(f"Claims '{row['skill']}' (marked as a skill you don't have): \"{sentence.strip()[:120]}\"")
    evidence_numbers = set(re.findall(r"\d[\d,.]*\d|\d", " ".join(t for _, t, _ in evidence)))
    for num in set(re.findall(r"\d[\d,.]*\d|\d", re.sub(r"\[[PESC]\d+\]", "", text))):
        if num not in evidence_numbers and len(num.strip(".,")) > 1:
            warnings.append(f"Number '{num}' does not appear in your evidence")
    return warnings


def write_document(job, mode):
    """Write a cover letter (mode 'cover') or competency answers (mode 'hse') for one shortlisted job.
    Returns the text, the check warnings, the answer types and the saved file paths."""
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    vocab = pd.read_csv(VOCAB)
    weights = dict(zip(vocab["skill"], vocab["weight"]))
    jobs = pd.concat([pd.read_csv(p) for p in JOB_FILES if p.exists()], ignore_index=True)
    match = jobs[(jobs["source"] == job["source"]) & (jobs["job_id"].astype(str) == str(job["job_id"]))]
    description = match["description"].iloc[0] if len(match) else ""
    job_tags = set(str(job["skills_you_have"]).split(", ")) - {"nan", ""}
    missing = sorted(set(str(job["skills_missing"]).split(", ")) - {"nan", ""})
    evidence = evidence_list(master, job_tags, words(job["title"] + " " + description), weights)
    reqs = requirements(description)[:6 if mode == "hse" else 12]

    text = ask_model(build_prompt(mode, job, reqs, evidence, missing, master.get("name") or "me"))
    # Proofread first (fixes 'myskills' etc.), then run the fact checks on the corrected text
    known = known_words(json.dumps(master), description, job["title"], job["company"], " ".join(vocab["skill"]))
    text, fixes, spelling = proofread(text, known)
    warnings = check(text, evidence, vocab, evidence_meta(master))
    types = [t.lower() for t in re.findall(r"Type:\s*(Direct|Transferable)", text, re.I)]

    OUT_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{job['company']}_{job['job_id']}").strip("_")
    prefix = "COVER" if mode == "cover" else "ANSWERS"
    paths = {"md": OUT_DIR / f"{prefix}_{slug}.md", "docx": OUT_DIR / f"{prefix}_{slug}.docx"}
    md = [f"# {prefix.title()}: {job['company']} | {job['title']}", "", text, "", "## Automatic checks", ""]
    md += [f"- {w}" for w in warnings] or ["- No problems found (still read it yourself)."]
    md += ["", "## Proofreading", ""] + [f"- Fixed: {f}" for f in fixes] + [f"- Check: {f}" for f in spelling]
    if not fixes and not spelling:
        md.append("- No spelling or spacing problems found.")
    md += ["", "## Evidence the model was given", ""] + [f"- [{pid}] {t}" for pid, t, _ in evidence]
    paths["md"].write_text("\n".join(md), encoding="utf-8")

    doc = Document()
    doc.styles["Normal"].font.name, doc.styles["Normal"].font.size = "Calibri", Pt(11)
    for para in re.sub(r"\s*\[[PESC]\d+\]", "", text).split("\n"):
        if para.strip():
            doc.add_paragraph(para.replace("**", "").strip())
    doc.save(paths["docx"])
    return {"text": text, "warnings": warnings, "types": types, "paths": paths,
            "fixes": fixes, "spelling": spelling}


def main():
    job = pick_job(pd.read_csv(RANKED))
    mode = "hse" if input("1 = cover letter, 2 = competency answers (HSE style) [1]: ").strip() == "2" else "cover"
    print(f"\nAsking {describe()} ...")
    result = write_document(job, mode)

    print("\n" + result["text"] + "\n")
    if mode == "hse":
        print(f"Answers: {result['types'].count('direct')} direct, {result['types'].count('transferable')} "
              "transferable (be ready to explain transferable examples at interview)")
    print(f"Proofreading: {len(result['fixes'])} fix(es) made, {len(result['spelling'])} word(s) to check")
    for f in result["fixes"]:
        print("  fixed:", f)
    for f in result["spelling"]:
        print("  check:", f)
    print(f"Automatic checks: {len(result['warnings'])} warning(s)")
    for w in result["warnings"]:
        print("  !", w)
    print(f"\nSaved {result['paths']['md']} (with citations and checks)")
    print(f"Saved {result['paths']['docx']} (clean copy to edit)")


if __name__ == "__main__":
    main()
