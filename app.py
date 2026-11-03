"""Job Match: the whole pipeline behind buttons, for anyone's job search.

Start it by double-clicking start_app.bat (or: python -m streamlit run app.py).
It opens in your web browser at http://localhost:8501 and runs only on your computer.

Tabs:
  1. My CV        upload a Word CV, edit every part of it, choose your skills, link your GitHub portfolio
  2. Find jobs    where to search, pay, visa sponsorship, which career boards, then run the pipeline
  3. Shortlist    tailored CV with page preview, cover letter, competency answers, "I've applied"
  4. Applications the log of everything you applied to
"""
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT = Path(__file__).resolve().parent
os.chdir(PROJECT)  # every script uses paths relative to the project folder

import cv_import  # noqa: E402  (these must come after chdir)
import settings  # noqa: E402

S = settings.load()
APP_NAME = S.get("app_name", "Job Match")
SPONSORSHIP = bool(S.get("check_sponsorship", True))
CURRENCY = S.get("currency", "€")
MASTER = Path("cv_master.json")
VOCAB = Path("skills_vocab.csv")
COMPANIES = Path("companies.csv")

st.set_page_config(page_title=APP_NAME, page_icon="🔎", layout="wide")

# Atmosphere and one orchestrated entrance: layered background, staggered reveal of the header.
st.markdown("""
<style>
.stApp {
  background:
    radial-gradient(1200px 500px at 85% -10%, rgba(11,122,92,0.10), transparent 60%),
    radial-gradient(900px 400px at -10% 110%, rgba(46,94,138,0.08), transparent 60%),
    repeating-linear-gradient(0deg, rgba(15,42,46,0.025) 0 1px, transparent 1px 28px),
    #F2F4EF;
}
@keyframes rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
.hero { animation: rise .6s ease-out both; margin: 0.2rem 0 1.4rem; }
.hero .eyebrow { font-family: 'JetBrains Mono', monospace; font-size: .78rem; letter-spacing: .14em;
  text-transform: uppercase; color: #0B7A5C; animation: rise .6s ease-out .05s both; }
.hero h1 { font-family: 'Bricolage Grotesque', sans-serif; font-weight: 800; font-size: 3.6rem; line-height: 1;
  margin: .3rem 0 .4rem; color: #0F2A2E; animation: rise .6s ease-out .12s both; }
.hero p { font-weight: 300; font-size: 1.15rem; max-width: 46rem; color: #3A5357; animation: rise .6s ease-out .2s both; }
.stats { display: flex; gap: .8rem; flex-wrap: wrap; margin-top: 1rem; }
.stat { background: #0F2A2E; color: #E8EFE9; border-radius: .4rem; padding: .7rem 1rem; min-width: 9rem;
  animation: rise .6s ease-out both; }
.stat:nth-child(1) { animation-delay: .28s } .stat:nth-child(2) { animation-delay: .36s }
.stat:nth-child(3) { animation-delay: .44s } .stat:nth-child(4) { animation-delay: .52s }
.stat b { display: block; font-family: 'Bricolage Grotesque', sans-serif; font-weight: 800; font-size: 2rem;
  color: #7FD8B6; line-height: 1.1; }
.stat span { font-size: .8rem; letter-spacing: .04em; opacity: .85; }
</style>
""", unsafe_allow_html=True)


# ---------- helpers ------------------------------------------------------------
def run_scripts(*names):
    """Run pipeline scripts one after another, showing their output. Stops at the first error."""
    for name in names:
        with st.spinner(f"Running {name} ..."):
            result = subprocess.run([sys.executable, name], capture_output=True, text=True,
                                    cwd=PROJECT, encoding="utf-8", errors="replace")
        ok = result.returncode == 0
        with st.expander(f"{'✅' if ok else '❌'} {name}", expanded=not ok):
            st.code((result.stdout + result.stderr)[-6000:] or "(no output)")
        if not ok:
            st.error(f"{name} stopped with an error (details above).")
            return False
    return True


def fetch_scripts():
    """The job sources switched on in the settings."""
    return [f for f, key in [("fetch_greenhouse.py", "use_greenhouse"), ("fetch_hse.py", "use_hse")]
            if S.get(key, True)]


def read_csv(path):
    path = Path(path)
    return pd.read_csv(path) if path.exists() else None


def download(path, label):
    path = Path(path)
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, key=f"dl-{path.name}")


def load_cv():
    return json.loads(MASTER.read_text(encoding="utf-8")) if MASTER.exists() else None


def money(value):
    return f"{CURRENCY}{value:,.0f}"


PAPER_CSS = """
<style>
  body { margin: 0; background: transparent; }
  .paper { background: #fff; width: 794px; max-width: calc(100% - 24px); margin: 8px auto 24px; box-sizing: border-box;
           padding: 48px 60px; border-radius: 6px; box-shadow: 0 1px 3px rgba(15,42,46,.15), 0 10px 30px rgba(15,42,46,.10);
           font-family: Calibri, Carlito, 'IBM Plex Sans', sans-serif; font-size: 10.5pt; line-height: 1.35; color: #1b1b1b; }
  .paper p { margin: 0 0 3px; }
  .paper p.name { font-size: 20pt; font-weight: 700; color: #1F5C7A; margin-bottom: 4px; }
  .paper p.contact { font-size: 9pt; color: #444; margin: 0; }
  .paper p.section { font-size: 11pt; font-weight: 700; color: #1F5C7A; margin: 12px 0 3px; letter-spacing: .02em; }
  .paper ul { margin: 2px 0 4px 18px; padding: 0; }
  .paper li { margin: 0 0 2px; }
  .paper.letter { font-size: 11pt; line-height: 1.5; }
  .paper.letter p { margin: 0 0 10px; }
</style>
"""


def preview_docx(path, letter=False, height=820):
    """Show a Word file as a page inside the app (like a job site's 'review your CV' step)."""
    import mammoth
    import streamlit.components.v1 as components
    with open(path, "rb") as f:
        html = mammoth.convert_to_html(f).value
    if not letter:  # recreate the CV's look: big name, contact lines, coloured section headings
        html = re.sub(r"^<p><strong>(.*?)</strong></p>", r'<p class="name">\1</p>', html, count=1)
        html = re.sub(r'(?<=</p>)<p>([^<]*\|[^<]*)</p>', r'<p class="contact">\1</p>', html, count=2)
        html = re.sub(r"<p><strong>([A-Z][A-Z &/]+)</strong></p>", r'<p class="section">\1</p>', html)
    components.html(PAPER_CSS + f'<div class="paper{" letter" if letter else ""}">{html}</div>',
                    height=height, scrolling=True)


def slug_of(job):
    return re.sub(r"[^A-Za-z0-9]+", "_", f"{job['company']}_{job['job_id']}").strip("_")


# ---------- CV editor helpers ------------------------------------------------------
def tags_text(tags):
    return ", ".join(tags or [])


def tags_list(text):
    return [t.strip() for t in str(text or "").split(",") if t.strip()]


def lines_of(text):
    return [line.strip() for line in str(text or "").splitlines() if line.strip()]


def split_heading(heading):
    """'Title | Employer, Place | Dates' -> (title, employer, dates)."""
    parts = [p.strip() for p in heading.split("|")]
    dates = parts.pop() if len(parts) > 1 and cv_import.DATE.search(parts[-1]) else ""
    return (parts[0] if parts else ""), " | ".join(parts[1:]), dates


def draft_cv():
    """A working copy of the CV for the editor, with a fixed id on every role so that adding or
    removing one doesn't mix up the boxes on screen. Saved back without the ids."""
    if "cv_draft" not in st.session_state:
        cv = cv_import.complete(load_cv() or {"name": ""})
        for role in cv["experience"]:
            role["_id"] = uuid.uuid4().hex[:8]
            role.setdefault("kind", cv_import.guess_kind(role["heading"]))
        st.session_state["cv_draft"] = cv
    return st.session_state["cv_draft"]


def reset_draft():
    st.session_state.pop("cv_draft", None)


def clean_table(df, text_column):
    """Rows of an edited table, without the empty ones."""
    return [r for r in df.fillna("").to_dict("records") if str(r.get(text_column, "")).strip()]


def pattern_for(skill):
    """A search pattern that finds the skill as whole words, e.g. 'wound care' -> \\bwound care\\b."""
    return r"\b" + re.escape(str(skill).strip().lower()).replace("\\ ", " ") + r"\b"


def check_patterns(vocab):
    """Fill in a search pattern for new skills, and report patterns that aren't valid."""
    problems = []
    for i, row in vocab.iterrows():
        if not str(row["pattern"] or "").strip():
            vocab.at[i, "pattern"] = pattern_for(row["skill"])
        try:
            re.compile(vocab.at[i, "pattern"])
        except re.error as error:
            problems.append(f"{row['skill']}: {error}")
    return problems


# ---------- sidebar: which AI brain --------------------------------------------
ai = json.loads(Path("ai_settings.json").read_text(encoding="utf-8"))
with st.sidebar:
    st.header("AI model")
    names = list(ai["profiles"])
    choice = st.selectbox("Brain used for writing", names, index=names.index(ai["active"]),
                          format_func=lambda n: f"{n}: {ai['profiles'][n]['description']}")
    if choice != ai["active"]:
        ai["active"] = choice
        Path("ai_settings.json").write_text(json.dumps(ai, indent=2), encoding="utf-8")
        st.rerun()
    profile = ai["profiles"][choice]
    if profile.get("sends_data_off_device"):
        st.warning("This model sends your CV evidence to an outside company.")
        if profile.get("api_key_env") and not os.environ.get(profile["api_key_env"]):
            st.error(f"No API key found in {profile['api_key_env']}.")
    else:
        st.success("Private: runs on this computer.")
    st.caption("Change models or add cloud profiles in ai_settings.json.")


def hero_stats():
    """Headline numbers for the header (only from files that exist)."""
    stats = []
    ranked = Path("data/processed/jobs_ranked.csv")
    if ranked.exists():
        r = pd.read_csv(ranked)
        stats += [(len(r), "jobs checked"), (int(r["shortlist"].sum()), "on your shortlist")]
        if SPONSORSHIP and "sponsor_level" in r:
            stats.append((int((r["shortlist"] & (r["sponsor_level"] == "strong")).sum()),
                          "shortlisted at strong sponsors"))
    log = Path("data/applications.csv")
    if log.exists():
        stats.append((int((pd.read_csv(log, dtype=str)["job_id"].fillna("") != "").sum()), "applications logged"))
    return "".join(f'<div class="stat"><b>{n}</b><span>{label}</span></div>' for n, label in stats)


eyebrow = "Visa-aware job search" if SPONSORSHIP else "Your job search"
tagline = ("Jobs you qualify for, at employers with a record of sponsoring work permits, with a tailored CV "
           "and honest application documents for each." if SPONSORSHIP else
           "Jobs you qualify for, ranked by how well your CV matches, with a tailored CV and honest "
           "application documents for each.")
st.markdown(f"""
<div class="hero">
  <div class="eyebrow">{eyebrow} · {S.get("location_label", "")}</div>
  <h1>{APP_NAME}</h1>
  <p>{tagline}</p>
  <div class="stats">{hero_stats()}</div>
</div>
""", unsafe_allow_html=True)
if not MASTER.exists():
    st.info("👋 **Start here:** upload your CV in **1. My CV**. Everything else is built from it.")

tab_cv, tab_find, tab_short, tab_apps = st.tabs(
    ["1. My CV", "2. Find jobs", "3. Shortlist & documents", "4. My applications"])

# ---------- 1. My CV --------------------------------------------------------------
with tab_cv:
    vocab = pd.read_csv(VOCAB)
    with st.expander("📤 Start from a Word CV (.docx)", expanded=not MASTER.exists()):
        st.caption("The app reads your CV's sections, roles and bullet points. CVs come in many layouts, "
                   "so check every part below after importing and fix anything in the wrong place.")
        upload = st.file_uploader("Your CV as a Word file", type=["docx"])
        if upload is not None:
            imported = cv_import.import_docx(upload, vocab)
            st.markdown(f"**Found:** {imported['name'] or '(no name)'} · {len(imported['summary'])} summary "
                        f"sentences · {len(imported['skills'])} skills · {len(imported['experience'])} roles "
                        f"({sum(len(r['bullets']) for r in imported['experience'])} bullet points) · "
                        f"{len(imported['projects'])} projects · {len(imported['education'])} education lines · "
                        f"{len(imported['certificates'])} certificates")
            for r in imported["experience"]:
                st.caption(f"{'🎓' if r['kind'] == 'study' else '💼'} {r['heading']} ({len(r['bullets'])} bullets)")
            if MASTER.exists():
                st.warning("This replaces the CV the app has now (it is kept as cv_master.backup.json).")
            if st.button("Use this as my CV", type="primary"):
                old = load_cv() or {}
                for key in ("portfolio_github_user", "portfolio_ignore", "max_projects", "max_bullets_per_role"):
                    if key in old:
                        imported[key] = old[key]
                cv_import.save(imported)
                reset_draft()
                st.success("Saved. Now check each part below, then tick your skills in 'Skills list'.")
                st.rerun()
        if not MASTER.exists() and st.button("…or start with an empty CV and type it in"):
            cv_import.save(cv_import.complete({"name": ""}))
            reset_draft()
            st.rerun()

    if MASTER.exists():
        cv = draft_cv()
        st.subheader("Edit my CV")
        st.caption("Only true statements: the app picks and reorders these for each job but never adds new ones. "
                   "The **skills shown** column links each line to your skills list; leave it empty and the "
                   "app fills it in when you save.")
        part_about, part_exp, part_proj, part_edu, part_skills = st.tabs(
            ["About me", "Experience", "Projects & portfolio", "Education & certificates", "Skills list"])

        with part_about:
            name = st.text_input("Full name", cv["name"])
            contact = st.text_area("Contact details (one per line: town, phone, email, LinkedIn…)",
                                   "\n".join(cv["contact"]), height=130)
            st.markdown("**Profile summary**: one sentence per row. Tick *always* for sentences that go on every CV.")
            summary_df = st.data_editor(
                pd.DataFrame([{"text": s["text"], "always": bool(s.get("always")), "skills shown": tags_text(s["tags"])}
                              for s in cv["summary"]], columns=["text", "always", "skills shown"]),
                num_rows="dynamic", use_container_width=True, key="ed-summary",
                column_config={"text": st.column_config.TextColumn(width="large"),
                               "always": st.column_config.CheckboxColumn(width="small")})
            skills_text = st.text_area("Skills section of the CV (one per line, as you want them printed)",
                                       "\n".join(cv["skills"]), height=200)

        with part_exp:
            st.caption("Jobs, internships, volunteering and study with real tasks. Mark study as 🎓 so the AI never "
                       "calls it a job. One bullet point per row.")
            roles_out = []
            for i, role in enumerate(cv["experience"]):
                rid = role["_id"]
                title, employer, dates = split_heading(role["heading"])
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([3, 3, 2, 1.4])
                    title = c1.text_input("Role", title, key=f"t-{rid}")
                    employer = c2.text_input("Employer / place", employer, key=f"e-{rid}")
                    dates = c3.text_input("Dates", dates, key=f"d-{rid}")
                    kind = c4.selectbox("Type", ["job", "study"], index=1 if role.get("kind") == "study" else 0,
                                        key=f"k-{rid}", format_func=lambda k: "💼 job" if k == "job" else "🎓 study")
                    bullets_df = st.data_editor(
                        pd.DataFrame([{"text": b["text"], "skills shown": tags_text(b["tags"])} for b in role["bullets"]],
                                     columns=["text", "skills shown"]),
                        num_rows="dynamic", use_container_width=True, key=f"b-{rid}",
                        column_config={"text": st.column_config.TextColumn("bullet point", width="large")})
                    m1, m2, _ = st.columns([1, 1, 6])
                    if m1.button("↑ Move up", key=f"up-{rid}", disabled=i == 0):
                        cv["experience"][i - 1], cv["experience"][i] = cv["experience"][i], cv["experience"][i - 1]
                        st.rerun()
                    if m2.button("🗑 Remove", key=f"rm-{rid}"):
                        cv["experience"].pop(i)
                        st.rerun()
                roles_out.append({"heading": " | ".join(p for p in (title.strip(), employer.strip(), dates.strip()) if p),
                                  "kind": kind,
                                  "bullets": [{"text": r["text"].strip(), "tags": tags_list(r["skills shown"])}
                                              for r in clean_table(bullets_df, "text")]})
            if st.button("➕ Add a role"):
                cv["experience"].append({"heading": "", "kind": "job", "bullets": [], "_id": uuid.uuid4().hex[:8]})
                st.rerun()
            max_bullets = st.number_input("Bullet points per role on a tailored CV", 1, 8,
                                          int(cv.get("max_bullets_per_role", 3)))

        with part_proj:
            st.caption("Personal or portfolio projects (the AI always calls these projects, never jobs). "
                       "Add the GitHub repo name to keep a project in step with GitHub.")
            projects_df = st.data_editor(
                pd.DataFrame([{"title": p["title"], "tools": p.get("tools", ""), "bullet": p["bullet"],
                               "repo": p.get("repo", ""), "skills shown": tags_text(p["tags"])} for p in cv["projects"]],
                             columns=["title", "tools", "bullet", "repo", "skills shown"]),
                num_rows="dynamic", use_container_width=True, key="ed-projects",
                column_config={"bullet": st.column_config.TextColumn("one-sentence result", width="large"),
                               "repo": st.column_config.TextColumn("GitHub repo", width="small")})
            p1, p2 = st.columns(2)
            github_user = p1.text_input("GitHub username (for the portfolio check)", cv.get("portfolio_github_user", ""))
            max_projects = p2.number_input("Projects on a tailored CV", 0, 8, int(cv.get("max_projects", 3)))

            st.markdown("**Keep projects in step with GitHub**")
            st.caption("Save your username first. New repos are offered as draft projects; updated ones offer the "
                       "key findings from their README as a new bullet.")
            import sync_portfolio as sp
            if st.button("🔄 Check GitHub for new or updated projects", disabled=not cv.get("portfolio_github_user")):
                try:
                    st.session_state["portfolio"] = sp.scan_portfolio()
                except Exception as error:  # e.g. no internet
                    st.error(f"Could not check GitHub: {error}")
            scan = st.session_state.get("portfolio")
            if scan:
                results, new_state = scan
                for r in results:
                    if r["kind"] == "NEW":
                        with st.container(border=True):
                            st.markdown(f"**NEW: {r['repo']}** (updated {r['pushed'][:10]})")
                            st.json(r["draft"])
                            a, b = st.columns(2)
                            if a.button("Add to my CV", key=f"add-{r['repo']}"):
                                sp.add_project(r["draft"])
                                reset_draft()
                                st.success("Added. Edit its wording in the table above.")
                            reason = b.text_input("…or ignore it from now on, because:", key=f"ign-{r['repo']}")
                            if reason and b.button("Ignore", key=f"ignb-{r['repo']}"):
                                sp.ignore_repo(r["repo"], reason)
                                reset_draft()
                                st.success("Will be skipped from now on.")
                    elif r["kind"] == "UPDATED":
                        with st.container(border=True):
                            st.markdown(f"**UPDATED: {r['repo']}** (changed {r['pushed'][:10]})")
                            st.markdown(f"Your CV bullet now: {r['current_bullet']}")
                            if r["findings"]:
                                new = st.radio("Key findings in the README now", r["findings"], key=f"f-{r['repo']}")
                                if st.button("Use as my CV bullet", key=f"use-{r['repo']}"):
                                    sp.update_bullet(r["repo"], new)
                                    reset_draft()
                                    st.success("Bullet updated.")
                    else:
                        st.caption(f"{r['kind']}: {r['repo']}" + (f" ({r.get('reason')})" if r.get("reason") else ""))
                if st.button("Mark this check as done"):
                    sp.save_state(new_state)
                    st.session_state.pop("portfolio")
                    st.success("Saved. Next check will only show changes after today.")

        with part_edu:
            education_text = st.text_area("Education (one qualification per line)", "\n".join(cv["education"]),
                                          height=150)
            certificates_text = st.text_area("Certificates and courses (one per line)",
                                             "\n".join(cv["certificates"]), height=120)

        with part_skills:
            st.caption("These are the skills the app looks for in job ads. Tick the ones you really have: jobs are "
                       "scored on them, and the AI is told never to claim the unticked ones. Weight 3 = core or "
                       "technical skill, 1 = general skill. Add rows for skills in your field; leave the pattern "
                       "empty and the app makes one (patterns are regular expressions, e.g. `excel|spreadsheet`).")
            found = set(cv_import.skills_found(cv, vocab))
            table = vocab.assign(i_have_it=vocab["i_have_it"].eq("yes"), case_sensitive=vocab["case_sensitive"].eq("yes"))
            table.insert(1, "in my CV", table["skill"].isin(found))
            edited_vocab = st.data_editor(
                table, num_rows="dynamic", use_container_width=True, key="ed-vocab", disabled=["in my CV"],
                column_config={"i_have_it": st.column_config.CheckboxColumn("I have it"),
                               "in my CV": st.column_config.CheckboxColumn("found in my CV"),
                               "weight": st.column_config.SelectboxColumn(options=[1, 2, 3], width="small"),
                               "case_sensitive": st.column_config.CheckboxColumn("match capitals", width="small"),
                               "pattern": st.column_config.TextColumn(width="medium")})
            unlinked = [k for k in cv["skills"] if not cv_import.tags_for(k, vocab)]
            if unlinked:
                st.markdown(f"**{len(unlinked)} skills on your CV aren't in this list yet:** {', '.join(unlinked)}")
                if st.button("➕ Add them to the list (ticked, weight 1)",
                             help="Then jobs asking for them count as a match. Raise the weight of core skills to 3."):
                    new_rows = pd.DataFrame({"skill": unlinked, "pattern": [pattern_for(k) for k in unlinked],
                                             "i_have_it": "yes", "case_sensitive": "no", "weight": 1})
                    pd.concat([vocab, new_rows], ignore_index=True).to_csv(VOCAB, index=False)
                    st.rerun()
            v1, v2 = st.columns(2)
            if v1.button("✔ Tick exactly the skills found in my CV",
                         help="Unticks the rest. Then add any you have that your CV doesn't mention."):
                new = vocab.copy()
                new["i_have_it"] = new["skill"].isin(found).map({True: "yes", False: "no"})
                new.to_csv(VOCAB, index=False)
                st.success(f"Ticked {len(found)} skills: {', '.join(sorted(found)) or 'none'}.")
                st.rerun()
            if v2.button("💾 Save skills list"):
                out = edited_vocab.drop(columns=["in my CV"]).dropna(subset=["skill"])
                out = out[out["skill"].astype(str).str.strip() != ""].copy()
                out["i_have_it"] = out["i_have_it"].fillna(False).map({True: "yes", False: "no"})
                out["case_sensitive"] = out["case_sensitive"].fillna(False).map({True: "yes", False: "no"})
                out["weight"] = out["weight"].fillna(1).astype(int)
                problems = check_patterns(out)
                if problems:
                    st.error("Fix these patterns first: " + "; ".join(problems))
                else:
                    out.to_csv(VOCAB, index=False)
                    st.success(f"Saved {len(out)} skills ({(out['i_have_it'] == 'yes').sum()} ticked). "
                               "Click 'Score & rank' on the Find jobs tab to use them.")

        st.divider()
        if st.button("💾 Save my CV", type="primary", help="Saves the first four parts (the skills list has its own button)"):
            new_cv = {k: v for k, v in cv.items() if k != "experience"}
            new_cv.update({
                "name": name.strip(), "contact": lines_of(contact),
                "summary": [{"text": r["text"].strip(), "tags": tags_list(r["skills shown"]), "always": bool(r["always"])}
                            for r in clean_table(summary_df, "text")],
                "skills": lines_of(skills_text),
                "experience": [r for r in roles_out if r["heading"] or r["bullets"]],
                "projects": [{"title": r["title"].strip(), "tools": r["tools"].strip(), "bullet": r["bullet"].strip(),
                              "tags": tags_list(r["skills shown"]), **({"repo": r["repo"].strip()} if r["repo"].strip() else {})}
                             for r in clean_table(projects_df, "title")],
                "education": lines_of(education_text), "certificates": lines_of(certificates_text),
                "portfolio_github_user": github_user.strip(), "max_projects": int(max_projects),
                "max_bullets_per_role": int(max_bullets)})
            cv_import.save(cv_import.auto_tag(new_cv, vocab))
            reset_draft()
            st.success("CV saved (the previous version is in cv_master.backup.json). Make a tailored CV on the "
                       "Shortlist tab to see it.")
            st.rerun()

# ---------- 2. Find jobs ---------------------------------------------------------
with tab_find:
    st.subheader("Your search")
    with st.expander("Where, what pay, and do you need a visa?", expanded=not MASTER.exists()):
        w1, w2 = st.columns(2)
        location_words = w1.text_input("Places to search (separate with |)",
                                       S.get("location_words", "ireland|dublin|cork|galway|limerick|waterford"),
                                       help="A job is kept if its location contains any of these, e.g. "
                                            "london|manchester|remote")
        location_label = w2.text_input("Name of your search area (shown in the header)", S.get("location_label", "Ireland"))
        x1, x2, x3 = st.columns(3)
        currency = x1.selectbox("Currency in job ads", ["€", "£", "$"], index=["€", "£", "$"].index(CURRENCY))
        english = x2.selectbox("Write in", ["UK/Irish English", "US English", "Australian English", "Canadian English"],
                               index=["UK/Irish English", "US English", "Australian English", "Canadian English"]
                               .index(S.get("writing_english", "UK/Irish English"))
                               if S.get("writing_english", "UK/Irish English") in
                               ["UK/Irish English", "US English", "Australian English", "Canadian English"] else 0)
        app_name = x3.text_input("App name", APP_NAME)
        sponsorship = st.checkbox("I need visa sponsorship: rank employers by work permits issued (Ireland's DETE list)",
                                  SPONSORSHIP, help="Untick if you can already work where you are searching.")
        st.markdown("**Job sources**")
        y1, y2 = st.columns(2)
        use_greenhouse = y1.checkbox("Company career boards (Greenhouse, list below)", bool(S.get("use_greenhouse", True)))
        use_hse = y2.checkbox("HSE: Ireland's health service", bool(S.get("use_hse", True)))
        st.caption("Career boards: find a company's board token in its jobs page address, "
                   "boards.greenhouse.io/**token**. Add a row per company.")
        companies_df = st.data_editor(pd.read_csv(COMPANIES).fillna(""), num_rows="dynamic", use_container_width=True,
                                      key="ed-companies",
                                      column_config={"ats": st.column_config.SelectboxColumn(options=["greenhouse"])})

    c1, c2, c3 = st.columns(3)
    days = c1.select_slider("Jobs posted in the last…", options=[1, 3, 7, 14, 30, 60, 90],
                            value=S.get("days", 30), format_func=lambda d: f"{d} day{'s' if d > 1 else ''}")
    floor = c2.number_input(f"Salary floor ({CURRENCY} a year, 0 = none)", 0, 500000, int(S.get("salary_floor", 0)),
                            step=500, help="In Ireland, €40,904 is the Critical Skills Employment Permit minimum "
                                           "with a relevant degree")
    min_score = c3.slider("Minimum skill match", 0.3, 1.0, float(S.get("min_score", 0.6)), 0.05, format="%.2f")
    c4, c5, c6 = st.columns(3)
    max_years = c4.slider("Most years of experience asked", 0, 15, int(S.get("max_years", 4)))
    min_skills = c5.slider("At least this many matching skills", 1, 8, int(S.get("min_skills_matched", 3)))
    internal = c6.checkbox("Include HSE internal-only jobs", bool(S.get("include_internal", False)),
                           help="Tick only if you work for the HSE or a Section 38 agency")
    if st.button("💾 Save settings"):
        companies_out = companies_df[companies_df["board_token"].astype(str).str.strip() != ""].copy()
        companies_out["ats"] = companies_out["ats"].replace("", "greenhouse")
        companies_out.to_csv(COMPANIES, index=False)
        settings.save({"days": days, "salary_floor": floor, "min_score": min_score, "max_years": max_years,
                       "min_skills_matched": min_skills, "include_internal": internal,
                       "location_words": location_words.strip(" |") or "ireland", "location_label": location_label,
                       "currency": currency, "writing_english": english, "app_name": app_name or "Job Match",
                       "check_sponsorship": sponsorship, "use_greenhouse": use_greenhouse, "use_hse": use_hse})
        st.success("Saved. Click 'Run everything' (new places or sources) or 'Score & rank' to apply them.")
        st.rerun()

    st.subheader("Run the pipeline")
    if not fetch_scripts():
        st.warning("Switch on at least one job source above.")
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("▶ Run everything", type="primary", help="Fetch new jobs, then score and rank them"):
        run_scripts(*fetch_scripts(), "score_jobs.py", "add_sponsors.py")
    if b2.button("Fetch new jobs"):
        run_scripts(*fetch_scripts())
    if b3.button("Score & rank"):
        run_scripts("score_jobs.py", "add_sponsors.py")
    if SPONSORSHIP and b4.button("Update sponsor list", help="After downloading a new month of the DETE file into data/raw/"):
        run_scripts("clean_sponsors.py")

    scored = read_csv("data/processed/jobs_scored.csv")
    if scored is not None:
        tests = [c for c in scored.columns if c.startswith("ok_")]
        st.caption(f"Last scoring: {len(scored)} jobs, {int(scored['shortlist'].sum())} on the shortlist")
        passing = pd.DataFrame({"test": [f"{i}. {t.replace('ok_', '')}" for i, t in enumerate(tests, 1)],
                                "jobs passing": [int(scored[t].sum()) for t in tests]})
        st.bar_chart(passing, x="test", y="jobs passing", horizontal=True)

# ---------- 3. Shortlist & documents ----------------------------------------------
with tab_short:
    ranked = read_csv("data/processed/jobs_ranked.csv")
    if not MASTER.exists():
        st.info("Add your CV in '1. My CV' first.")
    elif ranked is None or not ranked["shortlist"].any():
        st.info("No shortlist yet. Go to '2. Find jobs' and click 'Run everything'.")
    else:
        short = ranked[ranked["shortlist"]].reset_index(drop=True)
        columns = ["company", "title", "days_old", "skill_score"] + (["sponsor_level"] if SPONSORSHIP else [])
        show = short[columns].copy()
        show["skill_score"] = (show["skill_score"] * 100).round()
        show["pay"] = short.apply(lambda j: f"{money(j['pay_min'])}–{money(j['pay_max'])}" if pd.notna(j.get("pay_min"))
                                  else "not stated", axis=1)
        show["url"] = short["url"]
        st.dataframe(show, hide_index=True, use_container_width=True,
                     column_config={"url": st.column_config.LinkColumn("ad", display_text="open"),
                                    "skill_score": st.column_config.ProgressColumn("skill match", min_value=0,
                                                                                   max_value=100, format="%d%%"),
                                    "days_old": st.column_config.NumberColumn("days old", width="small"),
                                    "sponsor_level": st.column_config.TextColumn("sponsor", width="small"),
                                    "company": st.column_config.TextColumn(width="small"),
                                    "pay": st.column_config.TextColumn(width="medium")})
        pick = st.selectbox("Choose a job", range(len(short)),
                            format_func=lambda i: f"{short.loc[i, 'company']} | {short.loc[i, 'title']}")
        job = short.loc[pick]
        slug = slug_of(job)
        d1, d2 = st.columns(2)
        d1.markdown(f"**You have:** {job['skills_you_have']}")
        d2.markdown(f"**Missing:** {job['skills_missing'] if pd.notna(job['skills_missing']) else 'nothing'}")

        st.divider()
        st.subheader("Tailored CV")
        import tailor_cv
        reword = st.checkbox("Suggest AI rewording of the chosen bullets (you approve each one)")
        if st.button("📄 Make tailored CV"):
            master = json.loads(tailor_cv.MASTER.read_text(encoding="utf-8"))
            vocab = pd.read_csv(tailor_cv.VOCAB)
            ctx = tailor_cv.job_context(job)
            content = tailor_cv.select_content(master, vocab, job, ctx)
            if reword:
                try:
                    with st.spinner("Asking the AI model to reword your bullets (a minute or two on a laptop)…"):
                        proposals = tailor_cv.propose_rewordings(tailor_cv.bullets_of(content), job,
                                                                 tailor_cv.requirements(ctx["description"]), vocab,
                                                                 tailor_cv.tag_lookup_of(master))
                    st.session_state["reword"] = {"slug": slug, "content": content, "ctx": ctx,
                                                  "proposals": proposals}
                except SystemExit as error:  # local_ai stops with a message if the model can't be reached
                    st.error(str(error))
            else:
                tailor_cv.write_documents(master, vocab, job, ctx, content)
                st.session_state.pop("reword", None)
                st.success("CV and evidence checklist saved in the output folder.")

        pending = st.session_state.get("reword")
        if pending and pending["slug"] == slug:
            st.markdown("**Review the rewordings.** Rejected ones changed the facts and can't be used.")
            accepted = set()
            for i, p in enumerate(pending["proposals"], 1):
                if not p["new"]:
                    continue
                with st.container(border=True):
                    st.markdown(f"**Original:** {p['original']}\n\n**Reworded:** {p['new']}")
                    for w in p["warnings"]:
                        st.caption(f"⚠ {w}")
                    if p["blocked"]:
                        st.error("Rejected automatically: changes the facts.")
                    elif st.checkbox("Use the reworded version", key=f"rw-{slug}-{i}"):
                        accepted.add(i)
            if st.button("✅ Build CV with my choices"):
                master = json.loads(tailor_cv.MASTER.read_text(encoding="utf-8"))
                vocab = pd.read_csv(tailor_cv.VOCAB)
                content, log = tailor_cv.apply_rewordings(pending["content"], pending["proposals"], accepted)
                tailor_cv.write_documents(master, vocab, job, pending["ctx"], content, log)
                st.session_state.pop("reword")
                st.success(f"CV saved with {len(accepted)} reworded bullet(s).")

        cv_file = Path(f"output/CV_{slug}.docx")
        if cv_file.exists():
            h1, h2 = st.columns([3, 1])
            h1.markdown(f"**CV** · `{cv_file.name}`")
            with h2:
                download(cv_file, "⬇ Download")
            preview_docx(cv_file)
            st.caption("To change the wording for every job, edit it in '1. My CV' and make the CV again. "
                       "For this job only, download it and edit it in Word.")
        notes = Path(f"output/NOTES_{slug}.md")
        if notes.exists():
            with st.expander("Evidence checklist: each requirement and your best evidence"):
                st.markdown(notes.read_text(encoding="utf-8"))

        st.divider()
        st.subheader("Cover letter and competency answers (AI)")
        import form_questions
        import write_application
        with st.expander("Questions to answer", expanded=True):
            st.caption("Taken from the job's application form when the app found one, otherwise from the ad's "
                       "requirements. Upload the form, or paste the questions yourself; leave a blank line "
                       "between questions.")
            form = st.file_uploader("The employer's application form (.docx)", type=["docx"], key=f"form-{slug}")
            if form is not None and st.session_state.get(f"form-read-{slug}") != form.file_id:
                content = form.read()
                found = form_questions.questions_from_docx(content)
                st.session_state[f"q-{slug}"] = "\n\n".join(found)
                st.session_state[f"no-ai-{slug}"] = form_questions.forbids_ai(content)
                st.session_state[f"form-read-{slug}"] = form.file_id
                st.caption(f"Found {len(found)} question(s) in the form.")
            if f"q-{slug}" not in st.session_state:
                st.session_state[f"q-{slug}"] = "\n\n".join(write_application.questions_for(
                    job, write_application.description_of(job)))
            questions_text = st.text_area("One question per paragraph", key=f"q-{slug}", height=220)
        questions = [q.strip() for q in re.split(r"\n\s*\n", questions_text) if q.strip()]
        no_ai = bool(st.session_state.get(f"no-ai-{slug}", str(job.get("form_no_ai", "")).lower() == "true"))
        if no_ai:
            st.error("**This employer's form says not to use AI to complete it** (the HSE's says: \"Your application "
                     "must be your own work … Do not use AI to complete the application form\"). AI answers are "
                     "switched off for this job. Use the answer plan instead: it picks the best examples from your "
                     "CV for each question, and you write the answers yourself.")
        w1, w2, w3 = st.columns(3)
        if w3.button("📝 Make answer plan (no AI)", disabled=not questions,
                     help="The best CV examples for each question, under Situation / Task / Action / Result"):
            st.session_state[f"plan-{slug}"] = write_application.answer_plan(job, questions)
        for col, mode, label in [(w1, "cover", "✉ Write cover letter"),
                                 (w2, "hse", f"🧩 Write answers to {len(questions)} question(s)")]:
            if col.button(label, disabled=(mode == "hse" and (not questions or no_ai))):
                try:
                    with st.spinner("Writing with the AI model (a minute or two per answer on a laptop)…"):
                        st.session_state[f"doc-{mode}"] = write_application.write_document(job, mode, questions)
                except SystemExit as error:  # local_ai stops with a message if the model can't be reached
                    st.error(str(error))
        plan = st.session_state.get(f"plan-{slug}")
        if plan:
            with st.container(border=True):
                h1, h2 = st.columns([3, 1])
                h1.markdown(f"**Answer plan** · `{plan[1].name}`")
                with h2:
                    download(plan[1], "⬇ Download")
                for q, examples in plan[0]:
                    st.markdown(f"**{q}**")
                    for e in examples:
                        st.caption(f"• {e}")
        for mode, prefix in [("cover", "COVER"), ("hse", "ANSWERS")]:
            res = st.session_state.get(f"doc-{mode}")
            if res and Path(res["paths"]["docx"]).stem.endswith(slug):
                with st.container(border=True):
                    h1, h2 = st.columns([3, 1])
                    h1.markdown(f"**{'Cover letter' if mode == 'cover' else 'Competency answers'}** · "
                                f"`{Path(res['paths']['docx']).name}`")
                    with h2:
                        download(res["paths"]["docx"], "⬇ Download")
                    preview_docx(res["paths"]["docx"], letter=True, height=520)
                    if res.get("fixes"):
                        st.info("Proofreading fixed: " + "; ".join(res["fixes"]))
                    for f in res.get("spelling", []):
                        st.caption(f"✎ Check: {f}")
                    if mode == "hse":
                        st.caption(f"{res['types'].count('direct')} direct, {res['types'].count('transferable')} "
                                   "transferable answers: be ready to explain transferable ones at interview")
                    for w in res["warnings"]:
                        st.warning(w)
                    if not res["warnings"]:
                        st.success("No problems found by the checks (still read it yourself).")
            if not (res and Path(res["paths"]["docx"]).stem.endswith(slug)):
                download(f"output/{prefix}_{slug}.docx", f"⬇ Download {prefix.lower()} (.docx)")

        st.divider()
        import track_applications as ta
        if st.button("✔ I've applied: log this job"):
            log, message = ta.log_job(ta.load_log(), job)
            ta.save_log(log)
            st.success(message + "  (It leaves the shortlist next time you score.)")

# ---------- 4. My applications ------------------------------------------------------
with tab_apps:
    import track_applications as ta
    log = ta.load_log()
    if log.empty:
        st.info("No applications logged yet. Use '✔ I've applied' on the Shortlist tab.")
    else:
        counts = log["status"].value_counts()
        cols = st.columns(len(ta.STATUSES))
        for col, status in zip(cols, ta.STATUSES):
            col.metric(status, int(counts.get(status, 0)))
        edited = st.data_editor(log, hide_index=True, use_container_width=True,
                                disabled=[c for c in log.columns if c not in ("status", "notes")],
                                column_config={"status": st.column_config.SelectboxColumn(options=ta.STATUSES),
                                               "url": st.column_config.LinkColumn(display_text="open")})
        if st.button("💾 Save changes"):
            changed = edited["status"] != log["status"]
            edited.loc[changed, "status_date"] = date.today().isoformat()
            ta.save_log(edited)
            st.success(f"Saved ({int(changed.sum())} status change(s)).")
