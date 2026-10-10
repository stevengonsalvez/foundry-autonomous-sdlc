"""Collect the proof for the final report into docs/evidence.md, straight from GitHub.

For every owner-authored issue and every maintenance PR it records the stage timeline, the pull
request, the commit order (tests before implementation), the six CI checks on the head commit, the
review verdict, the merge, the release and the cost, plus the totals and gate pass rates from the
metrics branch. Read only: it never writes to GitHub.

Usage: python scripts/collect_evidence.py [--out docs/evidence.md]
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO = "stevengonsalvez/foundry-autonomous-sdlc"
OWNER = "stevengonsalvez"
ROOT = Path(__file__).resolve().parent.parent
GATES = ("test", "coverage", "e2e", "gitleaks", "tdd-order", "agent-scope")
STATE = re.compile(r"<!-- sdlc-state:v1\s*(.*?)-->", re.DOTALL)
REVIEW = re.compile(r"<!-- sdlc-review:v1 (\{.*?\}) -->")
Api = Callable[[str], object]


def gh_api(path: str) -> object:
    done = subprocess.run(["gh", "api", "--paginate", "--slurp", path], capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(f"gh api {path}: {done.stderr.strip()[:200]}")
    pages = json.loads(done.stdout)
    if pages and isinstance(pages[0], list):
        return [item for page in pages for item in page]
    return pages[0] if len(pages) == 1 else pages


def is_test_path(path: str) -> bool:
    return bool(re.search(r"(\.test\.tsx?$|\.spec\.ts$|/tests/|^app/e2e/|/__fixtures__/)", path))


def state_of(comments: list[dict]) -> dict | None:
    for comment in comments:
        if comment["user"]["login"] == OWNER and (m := STATE.search(comment["body"])):
            return json.loads(m.group(1))
    return None


def commit_rows(api: Api, pr: int) -> list[dict]:
    rows = []
    for c in api(f"repos/{REPO}/pulls/{pr}/commits"):  # type: ignore[union-attr]
        detail = api(f"repos/{REPO}/commits/{c['sha']}")
        files = [f["filename"] for f in detail["files"]]  # type: ignore[index]
        rows.append({"sha": c["sha"][:10], "subject": c["commit"]["message"].splitlines()[0],
                     "kind": "test-only" if files and all(is_test_path(f) for f in files) else "implementation",
                     "files": len(files), "signed": c["commit"].get("verification", {}).get("verified", False)})
    return rows


def tests_first(rows: list[dict]) -> bool:
    kinds = [r["kind"] for r in rows]
    return bool(kinds) and kinds[0] == "test-only" and "implementation" in kinds


def check_rows(api: Api, sha: str) -> dict[str, str]:
    runs = api(f"repos/{REPO}/commits/{sha}/check-runs")
    runs = runs["check_runs"] if isinstance(runs, dict) else runs  # type: ignore[index]
    return {r["name"]: r["conclusion"] or r["status"] for r in runs}  # type: ignore[union-attr]


def review_verdict(comments: list[dict], head: str) -> str:
    for comment in reversed(comments):
        m = REVIEW.search(comment["body"]) if comment["user"]["login"] == OWNER else None
        if m and json.loads(m.group(1)).get("head") == head:
            return json.loads(m.group(1)).get("verdict", "?")
    return "none for this head"


def render_item(title: str, issue: dict, state: dict | None, pr: dict | None, commits: list[dict],
                checks: dict[str, str], verdict: str) -> str:
    out = [f"### {title}", "", f"Issue: [#{issue['number']}](https://github.com/{REPO}/issues/{issue['number']}) "
           f"state `{issue['state']}`, labels {', '.join('`'+x['name']+'`' for x in issue['labels']) or 'none'}", ""]
    if state:
        stages = " ▶ ".join(s["stage"].replace("stage:", "") for s in state.get("stages", []))
        cost = state.get("cost", {})
        out += [f"Timeline: {stages}", f"Quality score: {state.get('quality', {}).get('score')}, "
                f"engine: {state.get('coder', {}).get('engine') if state.get('coder') else 'n/a'}, "
                f"cost: {cost.get('usd', 0):.4f} USD", ""]
        if state.get("escalation"):
            out += [f"Escalation: `{state['escalation']['label']}`: {'; '.join(state['escalation']['reasons'])}", ""]
    if pr:
        merged = pr.get("merged_at")
        out += [f"Pull request: [#{pr['number']}]({pr['html_url']}) {'merged ' + merged if merged else pr['state']}, "
                f"merge commit `{(pr.get('merge_commit_sha') or '')[:10]}`", ""]
        out += ["| commit | kind | files | signed | subject |", "|---|---|---|---|---|"]
        out += [f"| `{c['sha']}` | {c['kind']} | {c['files']} | {c['signed']} | {c['subject']} |" for c in commits]
        out += ["", f"Tests first: **{'yes' if tests_first(commits) else 'no'}**", ""]
        out += ["| check | result |", "|---|---|"] + [f"| {g} | {checks.get(g, 'missing')} |" for g in GATES]
        out += ["", f"Review agent verdict for the head commit: **{verdict}**", ""]
    release = (state or {}).get("release")
    if release:
        out += [f"Release: [{release['tag']}]({release['url']})", ""]
    return "\n".join(out)


def build(api: Api = gh_api) -> str:
    issues = [i for i in api(f"repos/{REPO}/issues?state=all&per_page=100")  # type: ignore[union-attr]
              if "pull_request" not in i and i["user"]["login"] == OWNER]
    sections = ["# Evidence", "", "Generated by `scripts/collect_evidence.py` from the live repository.", ""]
    for issue in sorted(issues, key=lambda i: i["number"]):
        comments = api(f"repos/{REPO}/issues/{issue['number']}/comments")
        state = state_of(comments)  # type: ignore[arg-type]
        pr = commits = checks = None
        verdict = "n/a"
        if state and state.get("pr"):
            pr = api(f"repos/{REPO}/pulls/{state['pr']['number']}")
            commits = commit_rows(api, pr["number"])  # type: ignore[index]
            checks = check_rows(api, pr["head"]["sha"])  # type: ignore[index]
            verdict = review_verdict(api(f"repos/{REPO}/issues/{pr['number']}/comments"), pr["head"]["sha"])  # type: ignore[arg-type,index]
        scenario = (state or {}).get("scenario", "?")
        sections.append(render_item(f"Scenario {scenario}: {issue['title']}", issue, state, pr, commits or [],
                                    checks or {}, verdict))
    try:
        blob = api(f"repos/{REPO}/contents/metrics.json?ref=metrics")
        metrics = json.loads(base64.b64decode(blob["content"]))  # type: ignore[index]
        sections += ["## Totals", "", "```json", json.dumps(metrics["totals"], indent=2), "```", "",
                     "## Gate pass rates", "", "```json", json.dumps(metrics["gate_pass_rates"], indent=2), "```", ""]
    except RuntimeError:
        sections += ["## Totals", "", "No metrics.json on the metrics branch yet.", ""]
    return "\n".join(sections)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "evidence.md")
    args = parser.parse_args(argv)
    args.out.write_text(build() + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
