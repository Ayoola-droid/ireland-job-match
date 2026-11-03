"""Make a tailored CV (Word) and an evidence checklist for one shortlisted job.

Reads cv_master.json (your true CV content, tagged with skills) and the
shortlist in data/processed/jobs_ranked.csv. For the job you pick it:
  - keeps the summary sentences, projects and bullet points most relevant
    to the skills that job asks for, and lists matching skills first
  - never writes new claims: it only chooses and reorders what is in cv_master.json
  - OPTIONAL: asks the AI model chosen in ai_settings.json to reword the chosen
    bullets in the ad's language; each rewording is checked (no new numbers, no
    new skills) and shown next to your original for you to accept or reject
  - writes output/CV_<company>_<job id>.docx and output/NOTES_<company>_<job id>.md
    (the ad's requirements, your best evidence for each, and the gaps)
"""
import json
import re
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor, Inches

from settings import setting

MASTER = Path("cv_master.json")
VOCAB = Path("skills_vocab.csv")
RANKED = Path("data/processed/jobs_ranked.csv")
JOB_FILES = [Path("data/processed/jobs_greenhouse.csv"), Path("data/processed/jobs_hse.csv")]
OUT_DIR = Path("output")
ACCENT = RGBColor(0x1F, 0x5C, 0x7A)

STOPWORDS = set("""about above after again against their there these those which while with within without would
could should other where when what your yours have having this that from into they them then than also will shall
must able ability experience working work role team teams including including such using across more most very""".split())


def words(text):
    return {w for w in re.findall(r"[a-z]{5,}", str(text).lower()) if w not in STOPWORDS}


def tags_in(text, vocab):
    """Skills from skills_vocab.csv that appear in a piece of text."""
    found = set()
    for _, row in vocab.iterrows():
        flags = 0 if row["case_sensitive"] == "yes" else re.IGNORECASE
        if re.search(row["pattern"], str(text), flags):
            found.add(row["skill"])
    return found


def relevance(item_text, item_tags, job_tags, job_words, weights):
    tag_score = sum(weights.get(t, 1) for t in item_tags if t in job_tags)
    word_score = min(len(words(item_text) & job_words), 6) * 0.25
    return tag_score + word_score


def requirements(text):
    """Pull out requirement-like sentences from the ad (bullets, 'must', 'experience', ...)."""
    pieces = re.split(r"\s*•\s*|\n+|(?<=[.!?])\s+", str(text))
    admin = re.compile(r"closing date|incremental credit|criteria listed below|eligib|garda vetting|"
                       r"terms and conditions|superannuation|annual leave|compensation|without regard|"
                       r"protected by law|equal opportunit|on the basis of merit|discharge of the office|"
                       r"holding the office|good character|state of health|requisite knowledge|"
                       r"application form|by email|microsoft word|own work|\bsubmit|applications? (?:must|will)|"
                       r"shortlist|canvassing|curriculum vitae|\bCVs?\b|interview", re.I)
    keep = re.compile(r"\bexperience (?:in|with|of|applying|working|using|across|of)|\byears\b|ability to|"
                      r"\bskills\b|proficien|knowledge of|demonstrat|qualification|\bdegree\b|\bmust\b", re.I)
    seen, out = set(), []
    for p in pieces:
        p = p.strip()
        if 40 <= len(p) <= 400 and keep.search(p) and not admin.search(p) and p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out[:12]


def pick_job(ranked):
    shortlist = ranked[ranked["shortlist"]].reset_index(drop=True)
    if shortlist.empty:
        raise SystemExit("No shortlisted jobs. Run score_jobs.py and add_sponsors.py first.")
    print("Shortlisted jobs:")
    for i, j in shortlist.iterrows():
        print(f"  {i + 1}. {j['company']} | {j['title']} | score {j['skill_score']:.0%}")
    choice = input("\nNumber of the job to tailor for (Enter = 1): ").strip() or "1"
    return shortlist.iloc[int(choice) - 1]


def add_heading(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text.upper())
    run.bold, run.font.size, run.font.color.rgb = True, Pt(11), ACCENT
    return p


def add_bullet(doc, text):
    p = doc.add_paragraph(text, style="List Bullet")
    p.paragraph_format.space_after = Pt(1)
    return p


NUMBER = re.compile(r"\d[\d,.]*\d|\d")


def reword_prompt(bullets, job, reqs):
    numbered = "\n".join(f"{i + 1}. {b}" for i, b in enumerate(bullets))
    req_text = "\n".join(f"- {r}" for r in reqs[:8]) or "- (use the job title)"
    return f"""Reword each CV bullet point below so it uses the language of this job ad where that is TRUE to the original.

JOB: {job['title']} at {job['company']}
REQUIREMENTS FROM THE AD:
{req_text}

BULLETS:
{numbered}

RULES - follow all of them:
1. Keep the meaning of each bullet. Do not add any skill, tool, number, employer, result or responsibility that is not in that bullet.
2. Keep every number exactly as written.
3. Start with a strong past-tense verb. Maximum 35 words per bullet. {setting("writing_english", "UK/Irish English")}.
4. If a bullet cannot honestly be brought closer to the ad, return it unchanged.
5. Reply with exactly {len(bullets)} lines, numbered 1. to {len(bullets)}., and nothing else."""


def check_rewording(original, new, vocab, allowed_tags=()):
    """Warnings if a reworded bullet adds numbers or skills that the original doesn't have.
    allowed_tags: the skills this bullet is tagged with in cv_master.json (those may be named)."""
    warnings = []
    added_numbers = set(NUMBER.findall(new)) - set(NUMBER.findall(original))
    if added_numbers:
        warnings.append(f"new number(s): {', '.join(sorted(added_numbers))}")
    added_skills = tags_in(new, vocab) - tags_in(original, vocab) - set(allowed_tags)
    if added_skills:
        warnings.append(f"new skill(s): {', '.join(sorted(added_skills))}")
    if len(new.split()) > 1.4 * len(original.split()) + 5:
        warnings.append("much longer than the original")
    return warnings


def propose_rewordings(bullets, job, reqs, vocab, tag_lookup):
    """Ask the AI to reword each bullet; return one proposal per bullet (nothing is applied yet).
    A proposal is blocked if it adds numbers or skills the original doesn't have."""
    from local_ai import ask_model  # only needed when you choose to reword
    reply = ask_model(reword_prompt(bullets, job, reqs), max_tokens=1200)
    proposed = {int(n): t.strip() for n, t in re.findall(r"^\s*(\d+)[.)]\s*(.+)$", reply, re.M)}
    proposals = []
    for i, original in enumerate(bullets, 1):
        new = proposed.get(i, "").strip("*").strip()
        if not new or new == original:
            proposals.append({"original": original, "new": "", "warnings": [], "blocked": False})
            continue
        # Proofread the rewording (fixes 'myskills'-type joins; spelling issues become warnings)
        from proofread import known_words, proofread
        new, fixes, spelling = proofread(new, known_words(original, " ".join(bullets), " ".join(reqs), job["title"]))
        warnings = check_rewording(original, new, vocab, tag_lookup.get(original, ()))
        warnings += [f"fixed: {f}" for f in fixes] + [f"spelling: {f}" for f in spelling]
        blocked = any(w.startswith(("new number", "new skill")) for w in warnings)
        proposals.append({"original": original, "new": new, "warnings": warnings, "blocked": blocked})
    return proposals


def apply_rewordings(content, proposals, accepted):
    """Swap in the accepted rewordings (accepted = set of bullet numbers, from 1) and build the log."""
    final, log = [], []
    for i, p in enumerate(proposals, 1):
        use = bool(p["new"]) and not p["blocked"] and i in accepted
        final.append(p["new"] if use else p["original"])
        if not p["new"]:
            log.append(f"### Bullet {i}: kept (no change proposed)\n- {p['original']}\n")
        else:
            status = "ACCEPTED" if use else ("REJECTED automatically" if p["blocked"] else "kept original")
            warn = f" (warnings: {'; '.join(p['warnings'])})" if p["warnings"] else ""
            log.append(f"### Bullet {i}: {status}{warn}\n- Original: {p['original']}\n- Reworded: {p['new']}\n")
    n_projects = len(content["projects"])
    content = dict(content)
    content["projects"] = [dict(p, bullet=final[i]) for i, p in enumerate(content["projects"])]
    pos, experience = n_projects, []
    for heading, bs in content["experience"]:
        experience.append((heading, final[pos: pos + len(bs)]))
        pos += len(bs)
    content["experience"] = experience
    return content, log


def job_context(job):
    """The full ad text of a shortlisted job, and the skills it matched or missed."""
    jobs = pd.concat([pd.read_csv(p) for p in JOB_FILES if p.exists()], ignore_index=True)
    match = jobs[(jobs["source"] == job["source"]) & (jobs["job_id"].astype(str) == str(job["job_id"]))]
    description = match["description"].iloc[0] if len(match) else ""
    return {"description": description,
            "job_tags": set(str(job["skills_you_have"]).split(", ")) - {"nan", ""},
            "missing": set(str(job["skills_missing"]).split(", ")) - {"nan", ""},
            "job_words": words(job["title"] + " " + description)}


def select_content(master, vocab, job, ctx):
    """Choose and order the true CV pieces most relevant to this job."""
    weights = dict(zip(vocab["skill"], vocab["weight"]))
    rel = lambda text, tags: relevance(text, tags, ctx["job_tags"], ctx["job_words"], weights)

    # 1. Summary: the 'always' sentences plus the most relevant others, in their original order
    summary = master["summary"]
    scored = sorted([s for s in summary if not s.get("always")], key=lambda s: -rel(s["text"], s["tags"]))
    chosen = {id(s) for s in summary if s.get("always")} | {id(s) for s in scored[:2] if rel(s["text"], s["tags"]) > 0}

    # 2. Skills: those the job asks for first
    skill_tags = master["skill_tags"]
    skills = sorted(master["skills"],
                    key=lambda s: -sum(weights.get(t, 1) for t in skill_tags.get(s, []) if t in ctx["job_tags"]))

    # 3. Projects: the most relevant ones
    projects = sorted(master["projects"], key=lambda p: -rel(p["bullet"], p["tags"]))[: master["max_projects"]]

    # 4. Experience: every role kept in date order; most relevant bullets first, trimmed
    experience = []
    for role in master["experience"]:
        bullets = sorted(role["bullets"], key=lambda b: -rel(b["text"], b["tags"]))
        experience.append((role["heading"], [b["text"] for b in bullets[: master["max_bullets_per_role"]]]))

    return {"summary_text": " ".join(s["text"] for s in summary if id(s) in chosen),
            "summary_used": len(chosen), "summary_total": len(summary),
            "skills": skills, "matched_skills": {s for s in skills if set(skill_tags.get(s, [])) & ctx["job_tags"]},
            "projects": projects, "experience": experience}


def bullets_of(content):
    return [p["bullet"] for p in content["projects"]] + [b for _, bs in content["experience"] for b in bs]


def tag_lookup_of(master):
    lookup = {p["bullet"]: p["tags"] for p in master["projects"]}
    lookup.update({b["text"]: b["tags"] for r in master["experience"] for b in r["bullets"]})
    return lookup


def write_documents(master, vocab, job, ctx, content, reword_log=None):
    """Save the tailored CV (.docx), the evidence checklist (.md) and any rewording log. Returns their paths."""
    weights = dict(zip(vocab["skill"], vocab["weight"]))
    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(0.6)
        section.left_margin = section.right_margin = Inches(0.7)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10.5)
    normal.paragraph_format.space_after = Pt(2)

    name = doc.add_paragraph()
    run = name.add_run(master["name"])
    run.bold, run.font.size, run.font.color.rgb = True, Pt(20), ACCENT
    half = (len(master["contact"]) + 1) // 2  # contact details on two tidy lines
    for part in (master["contact"][:half], master["contact"][half:]):
        line = doc.add_paragraph(" | ".join(part))
        line.paragraph_format.space_after = Pt(0)
        line.runs[0].font.size = Pt(9)

    add_heading(doc, "Professional summary")
    doc.add_paragraph(content["summary_text"])

    add_heading(doc, "Skills")
    p = doc.add_paragraph()
    for i, s in enumerate(content["skills"]):
        r = p.add_run(s + ("" if i == len(content["skills"]) - 1 else "  •  "))
        r.bold = s in content["matched_skills"]

    add_heading(doc, "Projects")
    for proj in content["projects"]:
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(3)
        h.add_run(proj["title"]).bold = True
        h.add_run(f" | {proj['tools']}")
        add_bullet(doc, proj["bullet"])

    add_heading(doc, "Experience")
    for heading, bullets in content["experience"]:
        h = doc.add_paragraph()
        h.paragraph_format.space_before = Pt(3)
        h.add_run(heading).bold = True
        for b in bullets:
            add_bullet(doc, b)

    if master.get("certificates"):
        add_heading(doc, "Certificates")
        doc.add_paragraph("  •  ".join(master["certificates"]))

    add_heading(doc, "Education")
    for e in master["education"]:
        add_bullet(doc, e)

    OUT_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", f"{job['company']}_{job['job_id']}").strip("_")
    paths = {"cv": OUT_DIR / f"CV_{slug}.docx", "notes": OUT_DIR / f"NOTES_{slug}.md"}
    doc.save(paths["cv"])

    # ---- Evidence checklist ---------------------------------------------------
    evidence_pool = ([(p["title"], p["bullet"], set(p["tags"])) for p in master["projects"]] +
                     [(h, b["text"], set(b["tags"])) for r in master["experience"] for h in [r["heading"].split(" | ")[0]]
                      for b in r["bullets"]])
    lines = [f"# {job['company']} | {job['title']}", "",
             f"- Link: {job['url']}",
             f"- Skill score: {job['skill_score']:.0%} | sponsor: {job.get('sponsor_level', '?')}",
             f"- Skills matched: {', '.join(sorted(ctx['job_tags'])) or '-'}",
             f"- Skills the ad mentions that you don't have: {', '.join(sorted(ctx['missing'])) or 'none'}", "",
             "## Requirements in the ad, and your best evidence", ""]
    for req in requirements(ctx["description"]):
        req_tags = tags_in(req, vocab)
        best = max(evidence_pool, key=lambda e: sum(weights.get(t, 1) for t in e[2] & req_tags)
                   + len(words(e[1]) & words(req)) * 0.25)
        strength = sum(weights.get(t, 1) for t in best[2] & req_tags) + len(words(best[1]) & words(req)) * 0.25
        if strength >= 1:
            label = "STRONG" if strength >= 3 else "SOME"
            lines += [f"- **Requirement:** {req}", f"  - **{label}:** {best[0]}: {best[1]}", ""]
        else:
            lines += [f"- **Requirement:** {req}", "  - **NO CLEAR MATCH in your CV:** write your own example, "
                      "or treat this as a gap", ""]
    lines += ["## Before you send it",
              "- Read the CV against the ad: the script only chooses and reorders your own sentences.",
              "- Address the missing skills honestly (e.g. 'used CRM tools in sales; learning Salesforce').",
              "- Check the pay is at least EUR 40,904, and the closing date."]
    paths["notes"].write_text("\n".join(lines), encoding="utf-8")

    if reword_log:
        paths["reword"] = OUT_DIR / f"REWORD_{slug}.md"
        paths["reword"].write_text(f"# AI rewording log: {job['company']} | {job['title']}\n\n"
                                   + "\n".join(reword_log), encoding="utf-8")
    return paths


def main():
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    vocab = pd.read_csv(VOCAB)
    job = pick_job(pd.read_csv(RANKED))
    ctx = job_context(job)
    content = select_content(master, vocab, job, ctx)

    # Optional: AI rewording of the chosen bullets, each one accepted or rejected by you
    reword_log = []
    if input("\nReword the chosen bullets with the AI model? (y/N): ").strip().lower() == "y":
        from local_ai import describe
        bullets = bullets_of(content)
        print(f"\nAsking {describe()} to reword {len(bullets)} bullets...")
        proposals = propose_rewordings(bullets, job, requirements(ctx["description"]), vocab, tag_lookup_of(master))
        accepted = set()
        for i, p in enumerate(proposals, 1):
            if not p["new"]:
                continue
            print(f"\n--- Bullet {i} of {len(proposals)} ---\nORIGINAL: {p['original']}\nREWORDED: {p['new']}")
            for w in p["warnings"]:
                print(f"  ! {w}")
            if p["blocked"]:
                print("  -> Rejected automatically: the rewording changes the facts. Original kept.")
            elif input("Use the reworded version? (y = yes, Enter = keep original): ").strip().lower() == "y":
                accepted.add(i)
        content, reword_log = apply_rewordings(content, proposals, accepted)

    paths = write_documents(master, vocab, job, ctx, content, reword_log)
    if reword_log:
        n = sum("ACCEPTED" in entry for entry in reword_log)
        print(f"Reworded bullets accepted: {n} of {len(reword_log)} (see {paths['reword']})")
    print(f"\nTailored for: {job['company']} | {job['title']}")
    print(f"Summary sentences used: {content['summary_used']} of {content['summary_total']}")
    print(f"Skills listed first (bold): {', '.join(s for s in content['skills'] if s in content['matched_skills']) or 'none'}")
    print(f"Projects chosen: {', '.join(p['title'] for p in content['projects'])}")
    print(f"\nSaved {paths['cv']}\nSaved {paths['notes']}  (open it to see requirement-by-requirement evidence)")


if __name__ == "__main__":
    main()
