#!/usr/bin/env python3
"""Update dynamic sections in README.md for profile repo."""

from __future__ import annotations

import datetime as dt
import json
import urllib.request
from urllib.error import URLError
from pathlib import Path

README_PATH = Path("README.md")
USERNAME = "Ruchin-Audichya"
MAX_ITEMS = 7


def fetch_events(username: str, limit: int = 20) -> list[dict]:
    url = f"https://api.github.com/users/{username}/events/public"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{username}-readme-updater",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))[:limit]


def format_event(event: dict) -> str | None:
    event_type = event.get("type", "")
    repo = event.get("repo", {}).get("name", "unknown/repo")
    payload = event.get("payload", {})

    if event_type == "PushEvent":
        commits = payload.get("commits", [])
        count = len(commits)
        branch = payload.get("ref", "refs/heads/main").split("/")[-1]
        return f"- 🚀 Pushed **{count} commit(s)** to `{repo}` on `{branch}`"
    if event_type == "PullRequestEvent":
        action = payload.get("action", "updated")
        pr = payload.get("pull_request", {}).get("number", "?")
        return f"- 🔃 {action.title()} PR **#{pr}** in `{repo}`"
    if event_type == "IssuesEvent":
        action = payload.get("action", "updated")
        issue = payload.get("issue", {}).get("number", "?")
        return f"- 🐛 {action.title()} issue **#{issue}** in `{repo}`"
    if event_type == "WatchEvent":
        return f"- ⭐ Starred `{repo}`"
    if event_type == "ForkEvent":
        return f"- 🍴 Forked `{repo}`"
    if event_type == "CreateEvent":
        ref_type = payload.get("ref_type", "resource")
        ref = payload.get("ref", "")
        extra = f" `{ref}`" if ref else ""
        return f"- 🛠️ Created {ref_type}{extra} in `{repo}`"

    return f"- 📌 {event_type.replace('Event', '')} in `{repo}`"


def replace_section(text: str, start: str, end: str, content: str) -> str:
    start_idx = text.find(start)
    end_idx = text.find(end)
    if start_idx == -1 or end_idx == -1 or start_idx > end_idx:
        raise ValueError(f"Could not locate section markers: {start} / {end}")
    end_idx += len(end)
    before = text[: start_idx + len(start)]
    after = text[end_idx - len(end) :]
    return f"{before}\n{content}\n{after}"


def main() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    try:
        events = fetch_events(USERNAME)
    except URLError:
        events = []
    activity_lines: list[str] = []
    for event in events:
        line = format_event(event)
        if line:
            activity_lines.append(line)
        if len(activity_lines) >= MAX_ITEMS:
            break

    if not activity_lines:
        activity_lines = ["- 🌙 No recent public activity found yet."]

    now = dt.datetime.now(dt.timezone.utc)
    metadata = "\n".join(
        [
            f"- Last README refresh: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "- Time zone: UTC",
            "- Automation: GitHub Actions + Python",
        ]
    )

    readme = replace_section(
        readme,
        "<!--START_SECTION:activity-->",
        "<!--END_SECTION:activity-->",
        "\n".join(activity_lines),
    )
    readme = replace_section(
        readme,
        "<!--START_SECTION:metadata-->",
        "<!--END_SECTION:metadata-->",
        metadata,
    )

    README_PATH.write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
