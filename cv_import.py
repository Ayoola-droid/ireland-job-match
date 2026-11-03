"""Turn a Word CV (.docx) into cv_master.json, the file the rest of the app works from.

How it reads the CV (no AI needed):
  - the first line is your name; the lines before the first section heading are your contact details
  - section headings such as "Profile", "Skills", "Experience", "Education", "Projects", "Certificates"
    decide where the lines that follow go
  - a line such as "Job title | Employer | Jan 2020 - May 2022" starts a new role, and the bullet
    points under it become that role's bullets
  - short lines in a table (a skills grid) become skills
Then every sentence is tagged with the skills it shows (from skills_vocab.csv), so the CV
tailoring and the cover letters can pick the right evidence for each job.

CVs come in many layouts, so ALWAYS check the result in the app ("My CV" tab) and fix
anything that landed in the wrong place. Run on its own:  python cv_import.py my_cv.docx
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

MASTER = Path("cv_master.json")
BACKUP = Path("cv_master.backup.json")
VOCAB = Path("skills_vocab.csv")

# Words that mark a section heading, and the section they start
SECTIONS = {
    "summary": r"summary|profile|about me|objective|personal statement|introduction",
    "skills": r"skills|competenc|technical|tools|strengths|expertise",
    "experience": r"experience|employment|work history|career|professional background|positions",
    "projects": r"projects?|portfolio",
    "education": r"education|qualifications?|academic|training and education",
    "certificates": r"certific|courses?|training|licen[cs]es|accreditation",
    "ignore": r"references?|interests|hobbies|languages|volunteer\w* interests|referees",
}
MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATE = re.compile(rf"\b({MONTH}\s*)?(19|20)\d\d\b|\bpresent\b|\bcurrent\b|\bnow\b", re.I)
DEGREE = re.compile(r"\b(msc|bsc|ba|ma|mba|phd|pgdip|hdip|diploma|degree|bachelor|master|doctor|university|"
                    r"college|school|institute|leaving cert|qqi|level \d)\b", re.I)
DEGREES = {d.lower(): d for d in ["MSc", "BSc", "BA", "MA", "MBA", "PhD", "PgDip", "HDip", "BEng", "MEng"]}
STUDY = re.compile(r"\b(academic|msc|bsc|pgdip|university|college|student|thesis|coursework|TUS)\b", re.I)


def guess_kind(heading):
    """'study' for academic work (MSc projects, coursework), otherwise 'job'."""
    return "study" if STUDY.search(heading or "") else "job"


# ---------- 1. read the Word file, in the order the lines appear -------------------
def read_lines(path):
    """Every paragraph of the document (also those inside tables and content boxes), in order,
    as dicts: text, style, bullet (is it a list item?), table (is it inside a table?)."""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    doc = Document(path)
    lines, previous = [], None
    for p in doc.element.body.iter(qn("w:p")):
        para = Paragraph(p, doc)
        text = re.sub(r"\s+", " ", para.text).strip()
        if not text or text == previous:  # skip blanks and copies (text boxes are stored twice)
            continue
        previous = text
        style = para.style.name if para.style is not None else ""
        has_numbering = p.pPr is not None and p.pPr.numPr is not None
        lines.append({"text": text, "style": style,
                      "bullet": has_numbering or "list" in style.lower() or text[:1] in "•-–▪●*",
                      "table": any(a.tag == qn("w:tc") for a in p.iterancestors())})
    return lines


# ---------- 2. small helpers ---------------------------------------------------
def section_of(line):
    """The section a heading line starts, or None if it is not a heading."""
    text = line["text"].strip(" :").lower()
    if len(text.split()) > 5 or "|" in text or DATE.search(text):
        return None
    for name, pattern in SECTIONS.items():
        if re.search(rf"^(\w+\s)?({pattern})", text):
            return name
    return None


def is_entry_heading(line):
    """A line that starts a new role, degree or project, e.g. 'Data Analyst | NCDC | 2019 - 2021'."""
    if line["bullet"] and not line["style"].lower().startswith("heading"):
        return False
    text = line["text"]
    return ("|" in text and len(text) < 200) or (bool(DATE.search(text)) and len(text) < 120
                                                 and not text.endswith("."))


def tidy_case(part):
    """'CUSTOMER ASSISTANT' or 'bUSINESS ANALYTICS' -> 'Customer Assistant'; short acronyms stay."""
    def word(w):
        if len(w) <= 4 and w.isupper():
            return w
        letters = [c for c in w if c.isalpha()]
        if letters and (w.isupper() or (letters[0].islower() and any(c.isupper() for c in letters[1:]))):
            return w.capitalize()
        return w
    if part.isupper() and len(part.split()) > 1:  # a whole phrase in capitals
        part = part.title().replace(" Of ", " of ").replace(" And ", " and ").replace(" For ", " for ")
    words = [DEGREES.get(w.lower().strip("(),"), None) or word(w) for w in part.split()]
    return " ".join(words)


def clean_bullet(text):
    return re.sub(r"^[•\-–▪●*]\s*", "", text).strip()


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if len(s.strip()) > 3]


def heading_of(text):
    """Make a role heading look like 'Title | Employer, Place | Dates'."""
    parts = [tidy_case(p.strip(" -–")) for p in re.split(r"\s*\|\s*", text) if p.strip(" -–")]
    return " | ".join(parts)


# ---------- 3. sort the lines into the CV's sections --------------------------------
def parse_lines(lines):
    cv = {"name": "", "contact": [], "summary": [], "skills": [], "projects": [], "experience": [],
          "education": [], "certificates": []}
    if not lines:
        return cv
    cv["name"] = tidy_case(lines[0]["text"])
    section, entry = "contact", None

    def close_entry():
        nonlocal entry
        if entry is None:
            return
        kind, heading, bullets = entry
        if kind == "education":
            cv["education"].append(heading + (" | " + "; ".join(bullets) if bullets else ""))
        elif kind == "projects":
            title, _, rest = heading.partition(" | ")
            cv["projects"].append({"title": title, "tools": rest, "bullet": " ".join(bullets), "tags": []})
        else:
            cv["experience"].append({"heading": heading, "kind": kind,
                                     "bullets": [{"text": b, "tags": []} for b in bullets]})
        entry = None

    for line in lines[1:]:
        text = line["text"]
        new_section = section_of(line)
        if new_section:
            close_entry()
            section = new_section
            continue
        if section == "contact":
            if is_entry_heading(line) and DATE.search(text) and "@" not in text:
                section = "experience"  # no headings at all: the roles start here
            else:
                cv["contact"] += [p.strip() for p in re.split(r"\s*[|•·]\s*", text) if p.strip()]
                continue
        if line["table"] and len(text.split()) <= 4 and not is_entry_heading(line):
            close_entry()  # a grid of short phrases in a table = a skills list
            cv["skills"] += [s.strip() for s in re.split(r"[,;•|]", text) if s.strip()]
            continue
        if section == "ignore":
            continue
        if is_entry_heading(line) and section in ("experience", "education", "projects", "certificates",
                                                   "skills", "summary"):
            close_entry()
            if section == "education" and DEGREE.search(text):
                kind = "education"
            elif section == "projects" and not DATE.search(text):
                kind = "projects"
            else:
                section = "experience" if section in ("certificates", "skills", "summary") else section
                kind = guess_kind(text)
            entry = (kind, heading_of(text), [])
            continue
        if entry is not None:
            entry[2].append(clean_bullet(text))
            continue
        if section == "summary":
            cv["summary"] += [{"text": s, "tags": [], "always": False} for s in split_sentences(clean_bullet(text))]
        elif section == "skills":
            cv["skills"] += [s.strip() for s in re.split(r"[,;•|]", clean_bullet(text)) if s.strip()]
        elif section == "certificates":
            if not re.fullmatch(r"https?://\S+", text):
                cv["certificates"].append(clean_bullet(text))
        elif section == "education":
            cv["education"].append(clean_bullet(text))
        elif section == "projects":
            if re.fullmatch(r"https?://\S+", text):
                cv["contact"].append(text)  # a portfolio link: keep it with the contact details
            else:
                cv["projects"].append({"title": clean_bullet(text)[:80], "tools": "", "bullet": clean_bullet(text),
                                       "tags": []})
    close_entry()
    cv["contact"] = list(dict.fromkeys(cv["contact"]))
    if cv["summary"]:
        cv["summary"][0]["always"] = True  # the opening sentence always goes on the CV
    cv["skills"] = list(dict.fromkeys(cv["skills"]))  # remove repeats, keep the order
    return cv


# ---------- 4. tag every sentence with the skills it shows -------------------------
def tags_for(text, vocab):
    found = []
    for _, row in vocab.iterrows():
        flags = 0 if row["case_sensitive"] == "yes" else re.IGNORECASE
        if re.search(row["pattern"], text, flags):
            found.append(row["skill"])
    return found


def auto_tag(cv, vocab, keep_existing=True):
    """Fill in empty tag lists (or all of them when keep_existing=False), and link each CV skill
    to the skills list. Hand-made tags are kept, so re-tagging never undoes your choices."""
    def fill(item, text):
        if not (keep_existing and item.get("tags")):
            item["tags"] = tags_for(text, vocab)
    for s in cv.get("summary", []):
        fill(s, s["text"])
    for p in cv.get("projects", []):
        fill(p, f"{p['title']} {p.get('tools', '')} {p['bullet']}")
    for role in cv.get("experience", []):
        for b in role["bullets"]:
            fill(b, b["text"])
    skill_tags = cv.get("skill_tags", {}) if keep_existing else {}
    cv["skill_tags"] = {s: skill_tags.get(s) or tags_for(s, vocab) for s in cv.get("skills", [])}
    return cv


def cv_text(cv):
    """All the words in the CV, for finding which skills you have. Certificates are left out:
    a short course alone doesn't mean you can claim the skill (tick it yourself if it does)."""
    parts = [s["text"] for s in cv.get("summary", [])] + cv.get("skills", [])
    parts += [f"{p['title']} {p.get('tools', '')} {p['bullet']}" for p in cv.get("projects", [])]
    parts += [r["heading"] + " " + " ".join(b["text"] for b in r["bullets"]) for r in cv.get("experience", [])]
    return " \n ".join(parts + cv.get("education", []))


def skills_found(cv, vocab):
    """Names of the skills in skills_vocab.csv that your CV mentions."""
    return tags_for(cv_text(cv), vocab)


def complete(cv, github_user=""):
    """Add the settings the other scripts expect, with sensible defaults."""
    cv.setdefault("_note", "Your master CV. Only TRUE statements go here: the app chooses and reorders them "
                           "for each job but never invents new ones. Edit it in the app's 'My CV' tab.")
    cv.setdefault("max_projects", 3)
    cv.setdefault("max_bullets_per_role", 3)
    cv.setdefault("portfolio_github_user", github_user)
    cv.setdefault("portfolio_ignore", {})
    for key in ("contact", "summary", "skills", "projects", "experience", "education", "certificates"):
        cv.setdefault(key, [])
    cv.setdefault("skill_tags", {})
    return cv


def import_docx(path, vocab=None):
    vocab = pd.read_csv(VOCAB) if vocab is None else vocab
    return complete(auto_tag(parse_lines(read_lines(path)), vocab))


def save(cv):
    """Save cv_master.json, keeping the previous version as cv_master.backup.json."""
    if MASTER.exists():
        BACKUP.write_text(MASTER.read_text(encoding="utf-8"), encoding="utf-8")
    MASTER.write_text(json.dumps(cv, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python cv_import.py my_cv.docx")
    cv = import_docx(sys.argv[1])
    print(f"Name: {cv['name']}\nContact: {cv['contact']}")
    print(f"{len(cv['summary'])} summary sentences, {len(cv['skills'])} skills, {len(cv['experience'])} roles "
          f"({sum(len(r['bullets']) for r in cv['experience'])} bullets), {len(cv['projects'])} projects, "
          f"{len(cv['education'])} education lines, {len(cv['certificates'])} certificates")
    for r in cv["experience"]:
        print(f"  [{r['kind']}] {r['heading']}  ({len(r['bullets'])} bullets)")
    if input(f"Save as {MASTER}? Your current file is kept as {BACKUP}. [y/N] ").strip().lower() == "y":
        save(cv)
        print("Saved. Check it in the app's 'My CV' tab.")


if __name__ == "__main__":
    main()
