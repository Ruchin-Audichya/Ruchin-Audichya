#!/usr/bin/env python3
"""Refresh the dynamic parts of the profile README.

Runs daily in GitHub Actions. Uses only the standard library and the public GitHub API
(authenticated with the workflow's GITHUB_TOKEN when available). It writes:

- the "Recently active" projects table          (<!--START:projects--> … <!--END:projects-->)
- the recent public activity feed                (<!--START:activity--> … <!--END:activity-->)
- a quick stats line                             (<!--START:stats--> … <!--END:stats-->)
- assets/languages.svg, a language bar chart made from the primary languages of owned repos

Files are rewritten only when their content changes, so quiet days produce no commit.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError

USERNAME = "Ruchin-Audichya"
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
LANG_SVG = ROOT / "assets" / "languages.svg"

# Repos that are shown elsewhere in the README or aren't projects.
SKIP_REPOS = {USERNAME.lower(), "medifastrx-bot", "profile"}
MAX_PROJECTS = 5
MAX_ACTIVITY = 6

LANG_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5", "Java": "#b07219",
    "C++": "#f34b7d", "C": "#555555", "HTML": "#e34c26", "CSS": "#663399", "Kotlin": "#A97BFF",
    "Dart": "#00B4AB", "Go": "#00ADD8", "Rust": "#dea584", "Shell": "#89e051", "Jupyter Notebook": "#DA5B0B",
    "Vue": "#41b883", "Svelte": "#ff3e00", "PHP": "#4F5D95", "Swift": "#F05138",
}


# ───────────────────────────── GitHub API ─────────────────────────────

def api(path: str):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{USERNAME}-profile-readme", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def load_data() -> dict:
    """Fetch live data, or read a fixture file when PROFILE_FIXTURE is set (for local testing)."""
    fixture = os.environ.get("PROFILE_FIXTURE")
    if fixture:
        return json.loads(Path(fixture).read_text(encoding="utf-8"))
    return {
        "user": api(f"/users/{USERNAME}"),
        "repos": api(f"/users/{USERNAME}/repos?per_page=100&sort=pushed&type=owner"),
        "events": api(f"/users/{USERNAME}/events/public?per_page=50"),
    }


# ───────────────────────────── Formatting ─────────────────────────────

def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def ago(when: dt.datetime, now: dt.datetime) -> str:
    days = (now.date() - when.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years > 1 else ''} ago"


def repo_link(full_name: str) -> str:
    owner, _, name = full_name.partition("/")
    label = name if owner.lower() == USERNAME.lower() else full_name
    return f"[{label}](https://github.com/{full_name})"


def owned_projects(repos: list[dict]) -> list[dict]:
    return [r for r in repos if not r.get("fork") and not r.get("archived") and not r.get("private") and r["name"].lower() not in SKIP_REPOS]


def projects_section(repos: list[dict], now: dt.datetime) -> str:
    rows = ["| Project | What it is | Built with | Updated |", "| --- | --- | --- | --- |"]
    for r in owned_projects(repos)[:MAX_PROJECTS]:
        desc = (r.get("description") or "").strip().replace("|", "\\|") or "—"
        if len(desc) > 90:
            desc = desc[:87].rstrip() + "…"
        stars = f" ⭐ {r['stargazers_count']}" if r.get("stargazers_count") else ""
        rows.append(f"| [**{r['name']}**]({r['html_url']}){stars} | {desc} | {r.get('language') or '—'} | {ago(parse_time(r['pushed_at']), now)} |")
    return "\n".join(rows)


def describe(event: dict) -> str | None:
    kind = event.get("type", "")
    repo = repo_link(event.get("repo", {}).get("name", "unknown/repo"))
    p = event.get("payload", {}) or {}
    if kind == "PushEvent":
        branch = (p.get("ref") or "").removeprefix("refs/heads/")
        return f"🚀 Pushed to {repo}" + (f" · `{branch}`" if branch and branch not in ("main", "master") else "")
    if kind == "PullRequestEvent":
        pr = p.get("pull_request", {}) or {}
        action = "Merged" if p.get("action") == "closed" and pr.get("merged") else (p.get("action") or "updated").capitalize()
        title = escape(pr.get("title") or "")
        return f"🔀 {action} PR #{pr.get('number', p.get('number', '?'))} in {repo}" + (f": {title}" if title else "")
    if kind == "IssuesEvent":
        issue = p.get("issue", {}) or {}
        return f"🐛 {(p.get('action') or 'updated').capitalize()} issue #{issue.get('number', '?')} in {repo}"
    if kind == "CreateEvent":
        if p.get("ref_type") == "repository":
            return f"✨ Created {repo}"
        return None  # new branches and tags are noise
    if kind == "ReleaseEvent":
        rel = p.get("release", {}) or {}
        return f"📦 Released {escape(rel.get('tag_name') or '')} of {repo}"
    # Stars and forks of other people's repositories aren't shown: the feed is about own work.
    if kind == "PublicEvent":
        return f"🌍 Made {repo} public"
    return None


def activity_section(events: list[dict], now: dt.datetime) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for e in events:
        text = describe(e)
        if not text or text in seen:  # collapse repeated pushes to the same repo
            continue
        seen.add(text)
        lines.append(f"- {text} <sub>{ago(parse_time(e['created_at']), now)}</sub>")
        if len(lines) >= MAX_ACTIVITY:
            break
    return "\n".join(lines) or "- 🌙 Quiet for now. Something is cooking."


def stats_section(user: dict, repos: list[dict]) -> str:
    owned = [r for r in repos if not r.get("fork")]
    stars = sum(r.get("stargazers_count", 0) for r in owned)

    def badge(label: str, value: int, color: str) -> str:
        return f"![{label}](https://img.shields.io/badge/{label.replace(' ', '%20')}-{value}-{color}?style=flat-square)"

    return " ".join([
        badge("Public repos", user.get("public_repos", len(owned)), "0ea5e9"),
        badge("Stars earned", stars, "f59e0b"),
        badge("Followers", user.get("followers", 0), "10b981"),
    ])


def languages_svg(repos: list[dict]) -> str:
    counts = Counter(r["language"] for r in repos if not r.get("fork") and r.get("language"))
    top = counts.most_common(6)
    total = sum(n for _, n in top) or 1
    width, bar_y, bar_h = 480, 38, 10
    parts, x = [], 0.0
    for lang, n in top:
        w = width * n / total
        parts.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{w:.1f}" height="{bar_h}" fill="{LANG_COLORS.get(lang, "#8b949e")}"/>')
        x += w
    legend = []
    for i, (lang, n) in enumerate(top):
        cx, cy = (i % 3) * 160, 74 + (i // 3) * 24
        legend.append(
            f'<circle cx="{cx + 6}" cy="{cy - 4}" r="5" fill="{LANG_COLORS.get(lang, "#8b949e")}"/>'
            f'<text x="{cx + 18}" y="{cy}">{escape(lang)} <tspan fill-opacity=".6">{round(100 * n / total)}%</tspan></text>'
        )
    height = 74 + ((len(top) + 2) // 3) * 24
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Most used languages">
<style>text{{font:500 13px -apple-system,'Segoe UI',Helvetica,Arial,sans-serif;fill:#8b949e}}.t{{font-weight:700;font-size:14px}}</style>
<text class="t" x="0" y="18">Most used languages</text>
<clipPath id="r"><rect x="0" y="{bar_y}" width="{width}" height="{bar_h}" rx="5"/></clipPath>
<g clip-path="url(#r)">{''.join(parts)}</g>
{''.join(legend)}
</svg>
"""


# ───────────────────────────── README plumbing ─────────────────────────────

def replace_section(text: str, name: str, content: str) -> str:
    pattern = re.compile(rf"(<!--START:{name}-->)(.*?)(<!--END:{name}-->)", re.S)
    if not pattern.search(text):
        raise ValueError(f"Missing <!--START:{name}--> / <!--END:{name}--> markers in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", text, count=1)


def write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def main() -> int:
    try:
        data = load_data()
    except (HTTPError, URLError, TimeoutError) as err:
        print(f"GitHub API unavailable ({err}); leaving README unchanged.")
        return 0
    if not isinstance(data.get("repos"), list) or not isinstance(data.get("events"), list):
        print("Unexpected API response; leaving README unchanged.")
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    readme = README.read_text(encoding="utf-8")
    readme = replace_section(readme, "projects", projects_section(data["repos"], now))
    readme = replace_section(readme, "activity", activity_section(data["events"], now))
    readme = replace_section(readme, "stats", stats_section(data["user"], data["repos"]))

    changed = write_if_changed(README, readme)
    changed |= write_if_changed(LANG_SVG, languages_svg(data["repos"]))
    print("Updated." if changed else "No changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
