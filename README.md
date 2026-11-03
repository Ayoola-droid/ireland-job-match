# Ireland Job Match: finding jobs I qualify for, at employers that sponsor visas

**Business question:** Of the jobs advertised in Ireland right now, which ones match my skills, pay at least the Critical Skills Employment Permit minimum (€40,904), and are at employers with a record of sponsoring work permits?

**Data:**
- [DETE employment permits issued to companies 2026](https://enterprise.gov.ie/en/publications/employment-permit-statistics-2026.html), Department of Enterprise, Tourism and Employment (Jan–Sep 2026, published monthly)
- Live job ads from company career boards: the free public job feeds of [Greenhouse](https://developers.greenhouse.io/job-board.html), Lever, Ashby and Workable (no key needed), plus companies' own careers pages
- Live HSE job ads from [about.hse.ie](https://about.hse.ie/jobs/job-search/) (public pages; robots.txt allows the jobs section)
- Optional: [Jooble](https://ie.jooble.org/api/about) job-search API (free key) for small companies and recruiters, and any job ad you add by its link
- HSE consolidated pay scales by grade (June 2026), stored in `hse_grade_pay.csv`

**Tools:** Python 3.12 (pandas, requests, openpyxl, python-docx, Streamlit), regular expressions, a local or cloud AI model, Excel, Word

**Status:** In progress. The pipeline runs end to end behind a point-and-click app (import CV → fetch → score → sponsor check → tailored CV → cover letter and competency answers → application log). Next: weight the ad's essential criteria, add more job sources.

## Use it for your own job search

You don't need to be in data analytics or need a visa: the app is built from **your** CV.

1. Install it (see [Setup](#setup)) and double-click `start_app.bat` (or run `streamlit run app.py`). The app opens on a **❓ How to use** tab with these steps.
2. **1. My CV:** drop your CV (a Word file) in the green box. Later, drop in a newer CV and choose **Add only what's new** to keep your edits. Check each part (About me, Experience, Projects & portfolio, Education & certificates) and fix anything that landed in the wrong place, then click **Save my CV**.
3. **Skills list:** click **Add them to the list** to add your CV's own skills, then **Tick exactly the skills found in my CV** and add any others you have. Jobs are scored on these, and the AI is never allowed to claim the unticked ones.
4. **2. Find jobs → Your search:**
   - the places to search, e.g. `london|manchester|remote`
   - the currency and your salary floor (0 = none)
   - the English you write in
   - the company career boards to read: any company on Greenhouse, Lever, Ashby or Workable, or any careers page
   - with visa sponsorship on, **Find sponsors' career sites** checks which employers on the permit list have a public job board, so their vacancies are read directly
   - whether you need **visa sponsorship**. Untick it if you can already work there: jobs are then ranked by skill match only, and the Irish sponsor data isn't needed.
5. Click **Run everything**, then go to **3. Shortlist** to make a tailored CV, cover letter or competency answers for each job, and log each application. The questions come from the employer's application form (found automatically for HSE jobs, or upload any form).
   - Where a form says not to use AI (as HSE forms do), the app warns you and offers an **answer plan** instead: the best examples from your CV for each question, for you to write up.

All your settings are kept in `app_settings.json`, your skills in `skills_vocab.csv`, and your CV in `cv_master.json`, which never leaves your computer. For the AI writing, run a free local model in [LM Studio](https://lmstudio.ai/) or add a cloud profile in `ai_settings.json`. The HSE source and the DETE sponsor list are specific to Ireland; switch them off elsewhere.

## Key findings (first run, 1 November 2026)

1. **2,370 job ads → 268 in Ireland → 6 that pass every test.** Most Irish ads at the nine tech companies checked are for engineering or sales roles, or above my level (59 recent jobs failed on seniority, 88 on skills).
2. **Sponsorship is common but often one-off.** 7,741 employers received 29,989 permits from January to September 2026, but **58% received only one**. Only 541 received ten or more.
3. **Public health is a strong sponsor.** HSE entities hold 194 permits across 15 regional names, and hospital groups add more (University Limerick Hospitals Group 171, Cork University Hospital 165). Three of the six shortlisted jobs are HSE Grade VII posts starting at **€61,219**.
4. **Company boilerplate distorts keyword matching.** Up to **60%** of an ad's text (Intercom, HSE) is repeated "About us", benefits and terms text. Removing sentences that recur across a company's ads stopped false matches such as a recruiting role "requiring" customer-service software skills.
5. **Most ads don't state pay.** Only **17 of 237** tech-company ads in Ireland give a salary, so pay is flagged as "ask before applying" rather than assumed.
6. **A skill score can overstate fit.** An HSE Grade VII *Data & Digital Communications* post scored 77%, but the requirement-by-requirement checklist showed that its essential criteria are extensive CRM and Salesforce experience. Counting skills is not enough; which skills are *essential* matters.

## Skills demonstrated

- Working with REST APIs and public web pages responsibly (robots.txt checked, one request per second, dated raw copies)
- Data cleaning and reconciliation: the DETE file reconciles to its published totals for every month (29,989 permits)
- Rule-based text classification with regular expressions, tuned against real false positives
- Matching messy entity names (brand vs legal name) with a human-checked mapping file
- Building a multi-step pipeline where each step does one job and can be rerun on its own
- Privacy by design: personal names and contact details are never stored or committed
- Generating Word documents in code (python-docx) from structured, tagged content
- Guard-railed AI writing: every claim must cite CV evidence, and automatic checks catch invented numbers, unheld skills and projects passed off as jobs
- Reading semi-structured documents: turning any Word CV into tagged, editable data
- Designing a configurable tool that other people can set up for their own search without editing code

## Method

1. **Sponsor list** (`clean_sponsors.py`): load the DETE file, check that employers add up to the Total row for every month, drop the Total row, fill blanks with 0, and build a matching key (upper case, `&` → AND, no punctuation, legal endings such as LIMITED/DAC/PLC removed). Names that share a key are flagged, not merged.
2. **Jobs** (`fetch_boards.py`, `fetch_hse.py`, optionally `fetch_jooble.py`; fetched at the same time, and ads read on an earlier run are reused): download ads with full descriptions, keep Irish locations, and save dated raw copies. For HSE, read grade, advertisement type (who can apply), closing date, and the Word job specification where one is attached.
3. **Scoring** (`score_jobs.py`): remove company boilerplate, find skills from `skills_vocab.csv` in each ad, and compute a weighted skill score (technical skills weight 3, general skills weight 1). Then apply nine tests: recent, still open, open to me, right level, pay at or above €40,904, years of experience, language, skills, and not already applied to. Every test has its own column, so the output shows why a job was left out.
4. **Sponsor evidence** (`add_sponsors.py`): join jobs to the DETE list through `company_aliases.csv`, and rate each employer as *strong* (10+ permits across 6+ months), *some* or *not on list*.
5. **Tailored CV** (`tailor_cv.py`): my CV is stored as small, true, skill-tagged pieces in `cv_master.json`. For a chosen job, the script ranks each piece by the weight of its tags that the job asks for (plus shared words), then keeps the most relevant summary sentences, projects and bullets and lists matching skills first, in bold. It never writes new claims, only chooses and reorders. It also writes a checklist that pairs each requirement in the ad with my best evidence (STRONG, SOME or no clear match).
6. **Application log** (`track_applications.py`): records each application (date, CV file sent, status) in `data/applications.csv`. The scorer leaves out jobs already applied to (same source and job ID) and flags look-alikes: same company, and titles sharing 80%+ of their words once reference codes and re-post words such as *Amended* or *Phase 2* are removed. Look-alikes are flagged, not hidden, because a re-post can be a new vacancy.

### Judgement calls

- `MAX_YEARS = 4`: four years was the most common requirement among suitable jobs (5 of 22). I have about 6 years of work experience, 2–3 of them in data roles.
- HSE level and pay come from the **grade**, not the title (Grades III–VII suit my level; VIII and above are senior).
- Names sharing a matching key are added together when looking up a company. The one uncertain pair (two sole traders called John O'Sullivan) cannot affect results, because sole traders aren't advertising data jobs.
- `Intercom` maps to *Intercom R&D Unlimited Company*, not *Carrier Intercompany Lending DAC*, which a plain text search also finds.

## Data-quality log

| Issue | What I did |
|---|---|
| DETE file ends with a Total row | Reconciled every month to it (all match), then excluded it |
| 10 pairs of employers written two ways (e.g. "CLG" vs "Company Limited by Guarantee") | Flagged by matching key; added together at lookup |
| "Data" in a title caught engineering jobs | Replaced title keywords with skill scoring of the full ad |
| Company boilerplate inflated skill matches | Removed sentences found in 30%+ of a company's ads |
| "Regression" matched *regression testing* | Pattern now requires "linear/logistic regression" or "regression model" |
| HSE search returned nothing for page 0 | Pages are numbered from 1; the script reads the page count first and stops on an empty page |
| HSE titles starting "Grade VII…" were read as the Grade field | A label now counts only when it is alone on its line; checked against all 31 saved pages |
| Personal data: the DETE list includes individual sole traders, and HSE pages list recruiters' names, emails and phone numbers | Contact details are never stored; the `data/` folder is excluded from Git |

## How to rerun

The easiest way is the app: double-click `start_app.bat` and use the buttons. Each button runs the scripts below, which still work on their own (in VS Code, open each file and click ▶), in this order:

1. `clean_sponsors.py`: only when a new month of DETE data is published
2. `fetch_boards.py`, `fetch_hse.py` (and `fetch_jooble.py` if switched on): download today's jobs
3. `score_jobs.py`: its settings (time frame, years, salary floor, minimum score…) come from `app_settings.json`, which the app's sliders save
4. `add_sponsors.py`: writes `data/processed/jobs_ranked.csv`
5. `tailor_cv.py`: pick a shortlisted job; writes `output/CV_<company>_<id>.docx` and `output/NOTES_<company>_<id>.md`
6. `track_applications.py`: after applying, mark the job as applied; update statuses (interview, offer, rejected, no reply) as replies come in

## Setup

```powershell
git clone https://github.com/Ayoola-droid/ireland-job-match.git
cd ireland-job-match
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

Then double-click `start_app.bat` and upload your CV on the **My CV** tab (or copy `cv_master.example.json` to `cv_master.json` and edit it). `cv_master.json` is kept out of Git.

The data isn't in the repository. Only if you need Irish visa sponsorship: download *Employment permits issued to companies 2026* from the DETE link above into `data/raw/` and click **Update sponsor list**. Tested with Python 3.12.10, pandas 3.1.0, openpyxl 3.1.5 and requests 2.34.2.

## Scripts

| Script | What it does |
|---|---|
| `inspect_sponsors.py` | First look at the raw DETE file (sheets, header, Total row) |
| `clean_sponsors.py` | Reconciles and cleans the sponsor list → `data/processed/sponsors_2026.csv` |
| `find_sponsor.py` | Searches the sponsor list by name, to fill in `company_aliases.csv` |
| `fetch_boards.py` | Downloads ads from the boards in `companies.csv`, four at a time → `jobs_boards.csv` (`fetch_greenhouse.py` still works and runs it) |
| `ats_feeds.py` | Readers for each hiring system's public feed (Greenhouse, Lever, Ashby, Workable) and for careers pages |
| `find_sponsor_boards.py` | Checks which employers on the permit list have a public job board → `sponsor_boards.csv` |
| `download_hse_sample.py` | Saves one HSE page to inspect its structure (exploration step) |
| `fetch_hse.py` | Reads all HSE listings and job pages → `jobs_hse.csv` |
| `fetch_jooble.py` | Searches Jooble for your search words → `jobs_jooble.csv` (needs a free key in `JOOBLE_API_KEY`) |
| `job_from_url.py` | Reads one job ad from its web address (or pasted text) → `jobs_manual.csv` |
| `form_questions.py` | Finds the questions in an application form, and whether it forbids AI |
| `score_jobs.py` | Removes boilerplate, scores skills, applies the nine tests → `jobs_scored.csv` |
| `add_sponsors.py` | Adds sponsor evidence and ranks the shortlist → `jobs_ranked.csv` |
| `tailor_cv.py` | Builds a tailored Word CV and an evidence checklist for one shortlisted job → `output/` |
| `track_applications.py` | Logs applications and their status → `data/applications.csv` (private); used by `score_jobs.py` to skip jobs already applied to |
| `app.py` | The point-and-click app (Streamlit) that runs everything; `start_app.bat` opens it |
| `cv_import.py` | Reads a Word CV into `cv_master.json` and tags each line with the skills it shows |
| `write_application.py` | Writes a cover letter or STAR competency answers with the AI model, then checks them |
| `proofread.py` | Fixes joined words and spacing in AI text and flags spellings to check |
| `local_ai.py` | Sends prompts to the AI model chosen in `ai_settings.json` (local or cloud) |
| `sync_portfolio.py` | Compares your GitHub repos with the projects on your CV |
| `settings.py` | Reads and saves `app_settings.json` |

| Mapping file | What it holds (edit these, not the code) |
|---|---|
| `companies.csv` | Career boards to check |
| `skills_vocab.csv` | Skills, the words that reveal them, whether I have them, and their weight |
| `company_aliases.csv` | Brand name → legal name(s) on the DETE list, with notes |
| `hse_grade_pay.csv` | HSE pay range by grade and whether it suits my level |
| `cv_master.json` | My CV as skill-tagged pieces (private; edit it in the app, `cv_master.example.json` shows the layout) |
| `app_settings.json` | Search settings: places, currency, salary floor, sponsorship on/off, sources, scoring limits |
| `ai_settings.json` | AI model profiles (API keys stay in environment variables, never in this file) |

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). As a project convention, the `data` type marks changes to the mapping files above.

## Project structure

```
ireland-job-match/
├── app.py, start_app.bat    the app
├── *.py                     scripts (see table above)
├── *.csv, *_settings.json   mapping and settings files you can edit
├── .streamlit/, static/     app theme and bundled fonts
├── requirements.txt
└── data/                    not in Git
    ├── raw/                 DETE file, dated job downloads
    └── processed/           cleaned and scored tables
output/                      tailored CVs and notes (not in Git)
```
