#!/usr/bin/env python3
"""
Build GitHub Pulse SVGs from the authenticated GraphQL API so commits in
private repositories (and other non-public signals GitHub applies to the
contribution calendar) are included — the same source your profile graph uses
when logged in with a PAT that can read your account.

Requires env: GH_STATS_PAT (classic PAT: read:user, repo)
"""

from __future__ import annotations

import json
import os
import sys
import html
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GRAPHQL = "https://api.github.com/graphql"

# Radical-ish palette
BG = "#141321"
TEXT = "#e0e6ed"
MUTED = "#8b949e"
ACCENT = "#22d3ee"
ACCENT2 = "#a855f7"
ACCENT3 = "#ec4899"
HEAT = ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353")


def graphql(token: str, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {"query": query, "variables": variables or {}}
    data = json.dumps(payload).encode()
    req = Request(
        GRAPHQL,
        data=data,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "allwinromario-profile-readme-pulse",
        },
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode())
    if body.get("errors"):
        raise RuntimeError(json.dumps(body["errors"], indent=2))
    return body["data"]


def load_calendar_and_profile(token: str) -> tuple[dict[str, int], dict[str, Any]]:
    """Return (day -> contribution_count) for the default collection window and extra stats."""
    q = """
    query {
      viewer {
        login
        followers { totalCount }
        following { totalCount }
        repositories(ownerAffiliations: OWNER) { totalCount }
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
          totalIssueContributions
          totalPullRequestContributions
          totalPullRequestReviewContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
                color
              }
            }
          }
        }
      }
    }
    """
    data = graphql(token, q)
    viewer = data["viewer"]
    cal = viewer["contributionsCollection"]["contributionCalendar"]
    days: dict[str, int] = {}
    for w in cal.get("weeks") or []:
        for d in w.get("contributionDays") or []:
            days[d["date"]] = int(d.get("contributionCount") or 0)
    extra = {
        "login": viewer["login"],
        "followers": viewer["followers"]["totalCount"],
        "following": viewer["following"]["totalCount"],
        "repos_owned": viewer["repositories"]["totalCount"],
        "total_commit_contributions": viewer["contributionsCollection"]["totalCommitContributions"],
        "restricted": viewer["contributionsCollection"].get("restrictedContributionsCount") or 0,
        "calendar_total": cal.get("totalContributions"),
        "issue": viewer["contributionsCollection"]["totalIssueContributions"],
        "pr": viewer["contributionsCollection"]["totalPullRequestContributions"],
        "review": viewer["contributionsCollection"]["totalPullRequestReviewContributions"],
        "weeks_raw": cal.get("weeks") or [],
    }
    return days, extra


def load_repo_languages(token: str) -> list[tuple[str, int]]:
    """Aggregate language sizes across owned repos (public + private)."""
    lang_bytes: defaultdict[str, int] = defaultdict(int)
    cursor: str | None = None
    q = """
    query($cursor: String) {
      viewer {
        repositories(first: 100, after: $cursor, ownerAffiliations: OWNER) {
          pageInfo { hasNextPage endCursor }
          nodes {
            languages(first: 25, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name } }
            }
          }
        }
      }
    }
    """
    while True:
        data = graphql(token, q, {"cursor": cursor})
        conn = data["viewer"]["repositories"]
        for node in conn["nodes"]:
            for edge in node["languages"]["edges"]:
                lang_bytes[edge["node"]["name"]] += int(edge["size"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    ranked = sorted(lang_bytes.items(), key=lambda x: -x[1])
    return ranked


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def longest_and_current_streak(day_map: dict[str, int]) -> tuple[int, int]:
    """Interpret contribution days the same way as typical streak widgets: UTC dates."""
    if not day_map:
        return 0, 0
    have = {datetime.strptime(k, "%Y-%m-%d").date() for k, v in day_map.items() if v > 0}
    if not have:
        return 0, 0

    sorted_dates = sorted(have)
    longest = cur = 1
    for i in range(1, len(sorted_dates)):
        if sorted_dates[i] == sorted_dates[i - 1] + timedelta(days=1):
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 1

    t = today_utc()
    cur_streak = 0
    d = t
    if d not in have:
        d = t - timedelta(days=1)
    while d in have:
        cur_streak += 1
        d -= timedelta(days=1)
    return longest, cur_streak


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def svg_stats(extra: dict[str, Any]) -> str:
    login = esc(extra["login"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="495" height="195" viewBox="0 0 495 195">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{ACCENT}"/>
      <stop offset="1" stop-color="{ACCENT2}"/>
    </linearGradient>
  </defs>
  <rect fill="{BG}" width="495" height="195" rx="12"/>
  <text x="20" y="32" fill="url(#g)" font-family="ui-sans-serif,system-ui,sans-serif" font-size="14" font-weight="600">GitHub · {login}</text>
  <text x="20" y="52" fill="{MUTED}" font-family="ui-sans-serif,system-ui,sans-serif" font-size="11">Includes private contributions (authenticated API)</text>
  <g fill="{TEXT}" font-family="ui-monospace,Menlo,monospace" font-size="13">
    <text x="20" y="90"><tspan fill="{ACCENT}">●</tspan> Followers  <tspan fill="{ACCENT2}">{extra['followers']}</tspan></text>
    <text x="20" y="112"><tspan fill="{ACCENT}">●</tspan> Following  <tspan fill="{ACCENT2}">{extra['following']}</tspan></text>
    <text x="20" y="134"><tspan fill="{ACCENT}">●</tspan> Repos (owner)  <tspan fill="{ACCENT2}">{extra['repos_owned']}</tspan></text>
    <text x="20" y="156"><tspan fill="{ACCENT}">●</tspan> Commits (window)  <tspan fill="{ACCENT2}">{extra['total_commit_contributions']}</tspan></text>
    <text x="20" y="178"><tspan fill="{ACCENT}">●</tspan> Issues / PRs / Reviews  <tspan fill="{ACCENT2}">{extra['issue']} / {extra['pr']} / {extra['review']}</tspan></text>
  </g>
</svg>"""


def svg_streak(calendar_total: int | None, longest: int, current: int, restricted: int) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="495" height="195" viewBox="0 0 495 195">
  <defs>
    <linearGradient id="fire" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{ACCENT3}"/>
      <stop offset="1" stop-color="{ACCENT}"/>
    </linearGradient>
  </defs>
  <rect fill="{BG}" width="495" height="195" rx="12"/>
  <text x="20" y="34" fill="url(#fire)" font-family="ui-sans-serif,system-ui,sans-serif" font-size="15" font-weight="600">Contribution calendar</text>
  <text x="20" y="54" fill="{MUTED}" font-family="ui-sans-serif,system-ui,sans-serif" font-size="11">Streaks derived from the same days as your profile graph · UTC</text>
  <text x="24" y="105" fill="{TEXT}" font-family="ui-monospace,Menlo,monospace" font-size="36" font-weight="700">{current}</text>
  <text x="24" y="124" fill="{MUTED}" font-size="11" font-family="ui-sans-serif,system-ui,sans-serif">Current streak (days)</text>
  <text x="260" y="105" fill="{TEXT}" font-family="ui-monospace,Menlo,monospace" font-size="36" font-weight="700">{longest}</text>
  <text x="260" y="124" fill="{MUTED}" font-size="11" font-family="ui-sans-serif,system-ui,sans-serif">Longest streak (window)</text>
  <text x="24" y="170" fill="{ACCENT2}" font-family="ui-monospace,Menlo,monospace" font-size="15">Σ contributions (window): {calendar_total if calendar_total is not None else "—"}</text>
  <text x="280" y="170" fill="{MUTED}" font-size="11" font-family="ui-sans-serif,system-ui,sans-serif">Restricted days: {restricted}</text>
</svg>"""


def svg_langs(ranked: list[tuple[str, int]], top_n: int = 8) -> str:
    if not ranked:
        ranked = [("No data", 1)]
    top = ranked[:top_n]
    total = sum(b for _, b in top) or 1
    colors = ["#f97316", "#22d3ee", "#a855f7", "#ec4899", "#22c55e", "#eab308", "#6366f1", "#94a3b8", "#64748b"]
    bx0, bw, y0 = 180, 280, 68
    bar_h = 16
    gap = 10
    bars: list[str] = []
    for i, (name, nbytes) in enumerate(top):
        pct = nbytes / total
        w = max(2, int(bw * pct))
        y = y0 + i * (bar_h + gap)
        col = colors[i % len(colors)]
        bars.append(
            f'<rect x="{bx0}" y="{y}" width="{w}" height="{bar_h}" rx="4" fill="{col}" opacity="0.92"/>'
            f'<text x="20" y="{y + bar_h - 3}" fill="{TEXT}" font-size="12" font-family="ui-sans-serif,system-ui,sans-serif">'
            f'{esc(name)}</text>'
            f'<text x="470" y="{y + bar_h - 3}" text-anchor="end" fill="{MUTED}" font-size="11" font-family="ui-monospace,Menlo,monospace">'
            f'{100.0 * pct:.1f}%</text>'
        )
    bar_blk = "\n  ".join(bars)
    h = max(220, y0 + len(top) * (bar_h + gap) + 24)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="495" height="{h}" viewBox="0 0 495 {h}">
  <rect fill="{BG}" width="495" height="{h}" rx="12"/>
  <text x="20" y="30" fill="{ACCENT}" font-family="ui-sans-serif,system-ui,sans-serif" font-size="14" font-weight="600">Languages (owned repos)</text>
  <text x="20" y="48" fill="{MUTED}" font-family="ui-sans-serif,system-ui,sans-serif" font-size="11">Weighted by bytes · includes private repositories</text>
  {bar_blk}
</svg>"""


def svg_activity(day_map: dict[str, int], width: int = 800, height: int = 220) -> str:
    """Line chart of daily contributions over the window."""
    if not day_map:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect fill="{BG}" width="{width}" height="{height}" rx="12"/>
  <text x="20" y="100" fill="{MUTED}" font-size="13">No activity data</text>
</svg>"""
    items = sorted(((datetime.strptime(k, "%Y-%m-%d").date(), v) for k, v in day_map.items()), key=lambda x: x[0])
    vals = [v for _, v in items]
    mx = max(vals) if vals else 1
    pad_l, pad_r, pad_t, pad_b = 44, 20, 36, 28
    w = width - pad_l - pad_r
    hch = height - pad_t - pad_b
    n = len(items)
    pts: list[tuple[float, float]] = []
    for i, (_, v) in enumerate(items):
        x = pad_l + (i / max(1, n - 1)) * w
        y = pad_t + hch - (v / mx) * hch
        pts.append((x, y))
    line_pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    base_y = pad_t + hch
    if pts:
        fx, lx = pts[0][0], pts[-1][0]
        seg = " ".join(f"L {x:.2f},{y:.2f}" for x, y in pts)
        path_d = f"M {fx:.2f},{base_y:.2f} {seg} L {lx:.2f},{base_y:.2f} Z"
    else:
        path_d = ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ACCENT}" stop-opacity="0.35"/>
      <stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect fill="{BG}" width="{width}" height="{height}" rx="12"/>
  <text x="20" y="24" fill="{ACCENT2}" font-size="14" font-weight="600" font-family="ui-sans-serif,system-ui,sans-serif">Activity · rolling year (authenticated, incl. private)</text>
  <path d="{path_d}" fill="url(#area)"/>
  <polyline fill="none" stroke="{ACCENT}" stroke-width="2" points="{line_pts}"/>
  <text x="20" y="{height - 8}" fill="{MUTED}" font-size="10" font-family="ui-sans-serif,system-ui,sans-serif">Commits, PRs, issues, and reviews GitHub counts as contributions.</text>
</svg>"""


def svg_heatmap(weeks: list[dict[str, Any]], day_map: dict[str, int], max_weeks: int = 48) -> str:
    """Contribution grid from API weeks (columns = weeks, rows = Sun–Sat)."""
    if not weeks:
        return f'<svg xmlns="http://www.w3.org/2000/svg" width="780" height="128"><rect fill="{BG}" width="780" height="128" rx="12"/></svg>'
    wks = weeks[-max_weeks:]
    max_c = max(day_map.values() or [0]) or 1
    cells: list[str] = []
    for wi, week in enumerate(wks):
        for di, day in enumerate(week.get("contributionDays") or []):
            c = int(day.get("contributionCount") or 0)
            level = 0 if c == 0 else min(4, max(1, int(4 * c / max_c)))
            color = HEAT[level]
            cx = 20 + wi * 11
            cy = 44 + di * 11
            cells.append(f'<rect x="{cx}" y="{cy}" width="10" height="10" rx="2" fill="{color}"/>')
    grid = "\n  ".join(cells)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="780" height="128" viewBox="0 0 780 128">
  <rect fill="{BG}" width="780" height="128" rx="12"/>
  <text x="20" y="26" fill="{TEXT}" font-size="13" font-weight="600" font-family="ui-sans-serif,system-ui,sans-serif">Contribution heatmap · calendar weeks (authenticated)</text>
  <text x="20" y="118" fill="{MUTED}" font-size="10" font-family="ui-sans-serif,system-ui,sans-serif">Less</text>
  <g transform="translate(48,106)">{"".join(f'<rect x="{i*12}" y="0" width="10" height="10" rx="2" fill="{HEAT[i]}"/>' for i in range(5))}</g>
  <text x="115" y="118" fill="{MUTED}" font-size="10">More</text>
  {grid}
</svg>"""


def main() -> int:
    token = os.environ.get("GH_STATS_PAT", "").strip()
    if not token:
        print("GH_STATS_PAT is not set; cannot fetch private-inclusive metrics.", file=sys.stderr)
        return 1
    out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "github-pulse")
    os.makedirs(out_dir, mode=0o755, exist_ok=True)

    try:
        day_map, extra = load_calendar_and_profile(token)
        longest, current = longest_and_current_streak(day_map)
        langs = load_repo_languages(token)
    except (HTTPError, URLError, RuntimeError, KeyError, ValueError) as e:
        print(f"API error: {e}", file=sys.stderr)
        return 1

    cal_total = extra.get("calendar_total")
    if cal_total is None and day_map:
        cal_total = sum(day_map.values())

    with open(os.path.join(out_dir, "stats.svg"), "w", encoding="utf-8") as f:
        f.write(svg_stats(extra))
    with open(os.path.join(out_dir, "streak.svg"), "w", encoding="utf-8") as f:
        f.write(svg_streak(cal_total, longest, current, int(extra.get("restricted") or 0)))
    with open(os.path.join(out_dir, "langs.svg"), "w", encoding="utf-8") as f:
        f.write(svg_langs(langs))
    with open(os.path.join(out_dir, "activity.svg"), "w", encoding="utf-8") as f:
        f.write(svg_activity(day_map))
    with open(os.path.join(out_dir, "heatmap.svg"), "w", encoding="utf-8") as f:
        f.write(svg_heatmap(extra.get("weeks_raw") or [], day_map))

    meta = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "login": extra["login"],
        "calendar_total": cal_total,
        "current_streak": current,
        "longest_streak": longest,
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("Wrote assets to", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
