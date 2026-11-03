"""Keep the projects in cv_master.json up to date with your GitHub portfolio.

Checks every public repository of the GitHub user in cv_master.json and reports:
  NEW      a repository that isn't in your CV yet: drafts a project entry from its
           README (title, tools, first key finding, skills) and asks before adding it
  UPDATED  a repository in your CV that has changed since the last sync: shows the
           README's key findings next to your current CV bullet so you can refresh it
Nothing is changed without your 'y'. Before any change, cv_master.json is backed up
to cv_master.backup.json. Repositories listed under portfolio_ignore are skipped.
"""
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from tailor_cv import MASTER, VOCAB, tags_in

STATE = Path("data/portfolio_sync.json")  # when each repository was last seen
BACKUP = Path("cv_master.backup.json")
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "ireland-job-match"}


def get_repos(user):
    url = f"https://api.github.com/users/{user}/repos?per_page=100&sort=pushed"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return [r for r in response.json() if not r["fork"] and not r["archived"]]


def get_readme(user, repo):
    url = f"https://raw.githubusercontent.com/{user}/{repo}/HEAD/README.md"
    response = requests.get(url, timeout=30)
    return response.text if response.status_code == 200 else ""


def plain(text):
    """Remove Markdown formatting: **bold**, [links](...), `code`."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[*`_]", "", text).strip()


def key_findings(readme):
    """The numbered or bulleted items under a 'Key findings' heading."""
    section = re.search(r"#+\s*Key findings[^\n]*\n(.*?)(?=\n#+\s|\Z)", readme, re.S | re.I)
    if not section:
        return []
    items = re.findall(r"^\s*(?:\d+\.|[-*])\s+(.+)$", section.group(1), re.M)
    return [plain(i) for i in items]


def draft_project(repo, readme, vocab):
    title = re.search(r"^#\s+(.+)$", readme, re.M)
    tools = re.search(r"\*\*Tools:\*\*\s*(.+)", readme)
    findings = key_findings(readme)
    have = set(vocab.loc[vocab["i_have_it"] == "yes", "skill"])
    return {
        "title": plain(title.group(1)) if title else repo["name"],
        "tools": plain(tools.group(1)) if tools else (repo.get("language") or ""),
        "bullet": findings[0] if findings else (repo.get("description") or "WRITE A ONE-LINE RESULT WITH A NUMBER"),
        "tags": sorted(tags_in(readme, vocab) & have),
        "repo": repo["name"],
    }


def scan_portfolio():
    """Check GitHub without changing anything. Returns (results, new_state).
    Each result: {"kind": NEW / UPDATED / ok / skip, "repo": name, "pushed": date, ...}"""
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    vocab = pd.read_csv(VOCAB)
    user = master.get("portfolio_github_user", "")
    ignore = master.get("portfolio_ignore", {})
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    in_cv = {p.get("repo"): p for p in master["projects"] if p.get("repo")}
    results, new_state = [], dict(state)
    for repo in get_repos(user):
        name, pushed = repo["name"], repo["pushed_at"]
        new_state[name] = pushed
        if name in ignore:
            results.append({"kind": "skip", "repo": name, "pushed": pushed, "reason": ignore[name]})
        elif name not in in_cv:
            results.append({"kind": "NEW", "repo": name, "pushed": pushed,
                            "draft": draft_project(repo, get_readme(user, name), vocab)})
        elif state.get(name) and pushed > state[name]:
            results.append({"kind": "UPDATED", "repo": name, "pushed": pushed, "last_sync": state[name],
                            "current_bullet": in_cv[name]["bullet"],
                            "findings": key_findings(get_readme(user, name))})
        else:
            results.append({"kind": "ok", "repo": name, "pushed": pushed, "first_sync": not state.get(name)})
    return results, new_state


def _save_master(master):
    shutil.copy(MASTER, BACKUP)
    MASTER.write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")


def add_project(draft):
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    master["projects"].append(draft)
    _save_master(master)


def ignore_repo(name, reason):
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    master.setdefault("portfolio_ignore", {})[name] = reason
    _save_master(master)


def update_bullet(repo_name, bullet):
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    for p in master["projects"]:
        if p.get("repo") == repo_name:
            p["bullet"] = bullet
    _save_master(master)


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main():
    results, new_state = scan_portfolio()
    print(f"{len(results)} public repositories checked\n")
    for r in results:
        if r["kind"] == "skip":
            print(f"  skip     {r['repo']} ({r['reason']})")
        elif r["kind"] == "ok":
            print(f"  ok       {r['repo']}" + ("  (first sync: baseline saved)" if r["first_sync"] else ""))
        elif r["kind"] == "NEW":
            print(f"\nNEW      {r['repo']}  (last updated {r['pushed'][:10]})")
            print(json.dumps(r["draft"], ensure_ascii=False, indent=2))
            if input("Add this project to cv_master.json? Check the bullet is true first (y/N): ").strip().lower() == "y":
                add_project(r["draft"])
                print(f"  added (previous version saved in {BACKUP}) - edit the wording if needed")
            else:
                reason = input("Ignore this repository in future? Type a reason, or Enter to ask again next time: ").strip()
                if reason:
                    ignore_repo(r["repo"], reason)
        elif r["kind"] == "UPDATED":
            print(f"\nUPDATED  {r['repo']}  (changed {r['pushed'][:10]}, last sync {r['last_sync'][:10]})")
            print(f"  Your CV bullet now: {r['current_bullet']}")
            if r["findings"]:
                print("  Key findings in the README now:")
                for i, f in enumerate(r["findings"], 1):
                    print(f"    {i}. {f}")
                pick = input("  Number of a finding to use as the new CV bullet (Enter = keep yours): ").strip()
                if pick.isdigit() and 1 <= int(pick) <= len(r["findings"]):
                    update_bullet(r["repo"], r["findings"][int(pick) - 1])
                    print("  bullet updated")
    save_state(new_state)
    print(f"\nSync finished {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Run it after you update a project.")


if __name__ == "__main__":
    main()
