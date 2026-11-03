"""Ireland Job Match: the whole pipeline behind buttons.

Start it by double-clicking start_app.bat (or: python -m streamlit run app.py).
It opens in your web browser at http://localhost:8501 and runs only on your laptop.
"""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT = Path(__file__).resolve().parent
os.chdir(PROJECT)  # every script uses paths relative to the project folder

import settings  # noqa: E402  (must come after chdir)

st.set_page_config(page_title="Ireland Job Match", page_icon="🔎", layout="wide")

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


def read_csv(path):
    path = Path(path)
    return pd.read_csv(path) if path.exists() else None


def download(path, label):
    path = Path(path)
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, key=f"dl-{path.name}")


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
    import re
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
    import re
    return re.sub(r"[^A-Za-z0-9]+", "_", f"{job['company']}_{job['job_id']}").strip("_")


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
        st.success("Private: runs on this laptop.")
    st.caption("Change models or add cloud profiles in ai_settings.json.")

def hero_stats():
    """Four headline numbers for the header (only from files that exist)."""
    stats = []
    ranked = Path("data/processed/jobs_ranked.csv")
    if ranked.exists():
        r = pd.read_csv(ranked)
        stats += [(len(r), "jobs in Ireland checked"), (int(r["shortlist"].sum()), "on your shortlist"),
                  (int((r["shortlist"] & (r["sponsor_level"] == "strong")).sum()), "shortlisted at strong sponsors")]
    log = Path("data/applications.csv")
    if log.exists():
        stats.append((int((pd.read_csv(log, dtype=str)["job_id"].fillna("") != "").sum()), "applications logged"))
    return "".join(f'<div class="stat"><b>{n}</b><span>{label}</span></div>' for n, label in stats)


st.markdown(f"""
<div class="hero">
  <div class="eyebrow">Visa-aware job search · Ireland</div>
  <h1>Ireland Job Match</h1>
  <p>Jobs you qualify for, at employers with a record of sponsoring work permits, with a tailored CV
  and honest application documents for each.</p>
  <div class="stats">{hero_stats()}</div>
</div>
""", unsafe_allow_html=True)
tab_find, tab_short, tab_apps, tab_cv = st.tabs(
    ["1. Find jobs", "2. Shortlist & documents", "3. My applications", "4. Portfolio & CV"])

# ---------- 1. Find jobs ---------------------------------------------------------
with tab_find:
    s = settings.load()
    st.subheader("Search settings")
    c1, c2, c3 = st.columns(3)
    days = c1.select_slider("Jobs posted in the last…", options=[1, 3, 7, 14, 30, 60, 90],
                            value=s.get("days", 30), format_func=lambda d: f"{d} day{'s' if d > 1 else ''}")
    floor = c2.number_input("Salary floor (€ a year)", 0, 200000, int(s.get("salary_floor", 40904)), step=500,
                            help="€40,904 = Critical Skills Employment Permit minimum with a relevant degree")
    min_score = c3.slider("Minimum skill match", 0.3, 1.0, float(s.get("min_score", 0.6)), 0.05,
                          format="%.2f")
    c4, c5, c6 = st.columns(3)
    max_years = c4.slider("Most years of experience asked", 0, 10, int(s.get("max_years", 4)))
    min_skills = c5.slider("At least this many matching skills", 1, 8, int(s.get("min_skills_matched", 3)))
    internal = c6.checkbox("Include HSE internal-only jobs", bool(s.get("include_internal", False)),
                           help="Tick only if you work for the HSE or a Section 38 agency")
    if st.button("💾 Save settings"):
        settings.save({"days": days, "salary_floor": floor, "min_score": min_score, "max_years": max_years,
                       "min_skills_matched": min_skills, "include_internal": internal})
        st.success("Saved. Click 'Score & rank' to apply them.")

    st.subheader("Run the pipeline")
    b1, b2, b3, b4 = st.columns(4)
    if b1.button("▶ Run everything", type="primary", help="Fetch new jobs, then score and rank them"):
        run_scripts("fetch_greenhouse.py", "fetch_hse.py", "score_jobs.py", "add_sponsors.py")
    if b2.button("Fetch new jobs"):
        run_scripts("fetch_greenhouse.py", "fetch_hse.py")
    if b3.button("Score & rank"):
        run_scripts("score_jobs.py", "add_sponsors.py")
    if b4.button("Update sponsor list", help="After downloading a new month of the DETE file into data/raw/"):
        run_scripts("clean_sponsors.py")

    scored = read_csv("data/processed/jobs_scored.csv")
    if scored is not None:
        tests = [c for c in scored.columns if c.startswith("ok_")]
        st.caption(f"Last scoring: {len(scored)} jobs in Ireland, {int(scored['shortlist'].sum())} on the shortlist")
        passing = pd.DataFrame({"test": [f"{i}. {t.replace('ok_', '')}" for i, t in enumerate(tests, 1)],
                                "jobs passing": [int(scored[t].sum()) for t in tests]})
        st.bar_chart(passing, x="test", y="jobs passing", horizontal=True)

# ---------- 2. Shortlist & documents ----------------------------------------------
with tab_short:
    ranked = read_csv("data/processed/jobs_ranked.csv")
    if ranked is None or not ranked["shortlist"].any():
        st.info("No shortlist yet. Go to '1. Find jobs' and click 'Run everything'.")
    else:
        short = ranked[ranked["shortlist"]].reset_index(drop=True)
        show = short[["company", "title", "days_old", "skill_score", "sponsor_level"]].copy()
        show["skill_score"] = (show["skill_score"] * 100).round()
        show["pay"] = short.apply(lambda j: f"€{j['pay_min']:,.0f}–{j['pay_max']:,.0f}" if pd.notna(j.get("pay_min"))
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
            st.caption("To change the wording, edit cv_master.json and make the CV again, "
                       "or download it and edit it in Word.")
        notes = Path(f"output/NOTES_{slug}.md")
        if notes.exists():
            with st.expander("Evidence checklist: each requirement and your best evidence"):
                st.markdown(notes.read_text(encoding="utf-8"))

        st.divider()
        st.subheader("Cover letter and competency answers (AI)")
        import write_application
        w1, w2 = st.columns(2)
        for col, mode, label in [(w1, "cover", "✉ Write cover letter"), (w2, "hse", "🧩 Write competency answers")]:
            if col.button(label):
                try:
                    with st.spinner("Writing with the AI model (a minute or two on a laptop)…"):
                        st.session_state[f"doc-{mode}"] = write_application.write_document(job, mode)
                except SystemExit as error:  # local_ai stops with a message if the model can't be reached
                    st.error(str(error))
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

# ---------- 3. My applications ------------------------------------------------------
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

# ---------- 4. Portfolio & CV -------------------------------------------------------
with tab_cv:
    st.subheader("Keep your CV in step with GitHub")
    import sync_portfolio as sp
    if st.button("🔄 Check GitHub for new or updated projects"):
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
                        st.success("Added. Edit the wording in cv_master.json if needed.")
                    reason = b.text_input("…or ignore it from now on, because:", key=f"ign-{r['repo']}")
                    if reason and b.button("Ignore", key=f"ignb-{r['repo']}"):
                        sp.ignore_repo(r["repo"], reason)
                        st.success("Will be skipped from now on.")
            elif r["kind"] == "UPDATED":
                with st.container(border=True):
                    st.markdown(f"**UPDATED: {r['repo']}** (changed {r['pushed'][:10]})")
                    st.markdown(f"Your CV bullet now: {r['current_bullet']}")
                    if r["findings"]:
                        new = st.radio("Key findings in the README now", r["findings"], key=f"f-{r['repo']}")
                        if st.button("Use as my CV bullet", key=f"use-{r['repo']}"):
                            sp.update_bullet(r["repo"], new)
                            st.success("Bullet updated.")
            else:
                st.caption(f"{r['kind']}: {r['repo']}" + (f" ({r.get('reason')})" if r.get("reason") else ""))
        if st.button("Mark this check as done"):
            sp.save_state(new_state)
            st.session_state.pop("portfolio")
            st.success("Saved. Next check will only show changes after today.")

    st.subheader("Your CV content")
    master = json.loads(Path("cv_master.json").read_text(encoding="utf-8"))
    st.caption(f"{len(master['projects'])} projects, "
               f"{sum(len(r['bullets']) for r in master['experience'])} experience bullets, "
               f"{len(master['skills'])} skills. Edit cv_master.json in VS Code to change the wording.")
    st.dataframe(pd.DataFrame([{"project": p["title"], "repo": p.get("repo", ""), "bullet": p["bullet"]}
                               for p in master["projects"]]), hide_index=True, use_container_width=True)
