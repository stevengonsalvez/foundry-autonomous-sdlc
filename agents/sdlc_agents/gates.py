"""
Pre-merge verification (docs/architecture.md, "Gates"; decision D4: the third enforcement layer).

The orchestrator merges only when, on the PR head sha: all six required checks are `success`, an
owner-authored review marker approves exactly that sha, the PR and its issue are owner-authored,
the object's cost is under the cap, the branch is agent/* or the PR is labelled for test repair, and
every file the PR changes is under app/. The last rule covers every PR, not only agent/* branches:
for pull_request events GitHub runs the workflow files from the PR head, so a PR that edits
.github/ could weaken the very checks that gate it. Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sdlc_agents.ports import OWNER, CheckRun, Comment, Issue, PullRequest
from sdlc_agents.sanitise import parse_json_strict

REQUIRED_CHECKS = ("test", "coverage", "e2e", "gitleaks", "tdd-order", "agent-scope")
MAINTENANCE_LABEL = "maintenance:test-repair"
AGENT_PR_LABEL = "agent:pr"
AGENT_BRANCH_PREFIX = "agent/"
PENDING, MISSING, SUCCESS = "pending", "missing", "success"

REVIEW_MARKER_PREFIX = "<!-- sdlc-review:v1 "
_REVIEW_RE = re.compile(r"<!-- sdlc-review:v1 (\{[^\n]*?\}) -->")


def check_summary(runs: Iterable[CheckRun], pr_number: int | None = None) -> dict[str, str]:
    """Each required check's state on one sha: success, a failing conclusion, pending or missing.

    With several runs of the same name (re-runs) the latest completion wins and any run still in
    progress makes the check pending. Given a PR number, runs GitHub ties to that PR are the only
    ones counted when there are any: a fork PR on the same sha (whose runs GitHub does not tie to
    a base-repo PR) cannot then override them.
    """
    runs = list(runs)
    if pr_number is not None and any(pr_number in r.pull_requests for r in runs):
        runs = [r for r in runs if pr_number in r.pull_requests]
    result: dict[str, str] = {}
    latest: dict[str, str] = {}
    for run in runs:
        if run.name not in REQUIRED_CHECKS:
            continue
        if run.status != "completed":
            result[run.name] = PENDING
            continue
        if result.get(run.name) == PENDING:
            continue
        stamp = run.completed_at or ""
        if run.name not in latest or stamp >= latest[run.name]:
            latest[run.name] = stamp
            result[run.name] = run.conclusion or "unknown"
    return {name: result.get(name, MISSING) for name in REQUIRED_CHECKS}


def failed(summary: Mapping[str, str]) -> list[str]:
    return [n for n, s in summary.items() if s not in (SUCCESS, PENDING, MISSING)]


def waiting(summary: Mapping[str, str]) -> list[str]:
    return [n for n, s in summary.items() if s in (PENDING, MISSING)]


def all_green(summary: Mapping[str, str]) -> bool:
    return all(summary.get(name) == SUCCESS for name in REQUIRED_CHECKS)


# ---------------------------------------------------------------------------
# Review marker
# ---------------------------------------------------------------------------

def render_review_marker(verdict: str, head: str) -> str:
    """`<!-- sdlc-review:v1 {"verdict":"approve","head":"<sha>"} -->`, key order as in the docs."""
    if verdict not in ("approve", "request-changes") or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError(f"bad review marker values: {verdict!r} {head!r}")
    return f'{REVIEW_MARKER_PREFIX}{{"verdict":"{verdict}","head":"{head}"}} -->'


def latest_review(comments: Iterable[Comment]) -> tuple[str, str] | None:
    """(verdict, head) from the newest owner-authored review marker, None if there is none."""
    found: tuple[str, str] | None = None
    for comment in comments:
        if comment.author != OWNER or not comment.body.startswith(REVIEW_MARKER_PREFIX):
            continue
        match = _REVIEW_RE.match(comment.body)
        if not match:
            continue
        try:
            data = parse_json_strict(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("verdict"), str) and isinstance(data.get("head"), str):
            found = (data["verdict"], data["head"])
    return found


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def outside_app(files: Iterable[str]) -> list[str]:
    """Changed paths that are not plain paths under app/ (sorted, de-duplicated)."""
    bad = set()
    for path in files:
        parts = PurePosixPath(path).parts
        if not parts or parts[0] != "app" or ".." in parts or path.startswith("/"):
            bad.add(path)
    return sorted(bad)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, str] = field(default_factory=dict)
    scope_violation: bool = False   # files outside app/: retrying cannot help, escalate at once


def verify_merge(
    *,
    pr: PullRequest,
    issue: Issue | None,
    check_runs: Iterable[CheckRun],
    pr_comments: Iterable[Comment],
    pr_files: Iterable[str],
    object_usd: float,
    usd_cap: float,
) -> GateResult:
    """Every reason the PR must not be merged now; passed only when there are none."""
    reasons: list[str] = []
    checks = check_summary(check_runs, pr.number)
    for name, state in checks.items():
        if state != SUCCESS:
            reasons.append(f"check {name} is {state} on {pr.head_sha[:7]}")

    review = latest_review(pr_comments)
    if review is None:
        reasons.append("no review marker")
    elif review[1] != pr.head_sha:
        reasons.append(f"review marker is for {review[1][:7]}, head is {pr.head_sha[:7]}")
    elif review[0] != "approve":
        reasons.append(f"review verdict is {review[0]}")

    if pr.author != OWNER:
        reasons.append(f"PR author {pr.author} is not the owner")
    if issue is not None and issue.author != OWNER:
        reasons.append(f"issue author {issue.author} is not the owner")
    if object_usd >= usd_cap:
        reasons.append(f"cost {object_usd:.4f} USD is at or over the {usd_cap:.2f} USD cap")
    if not (pr.head_ref.startswith(AGENT_BRANCH_PREFIX) or MAINTENANCE_LABEL in pr.labels):
        reasons.append(f"branch {pr.head_ref} is not agent/* and the PR is not labelled {MAINTENANCE_LABEL}")
    if pr.base_ref != "main":
        reasons.append(f"base is {pr.base_ref}, not main")
    if pr.state != "open" or pr.merged:
        reasons.append("PR is not open")
    outside = outside_app(pr_files)
    if outside:
        shown = ", ".join(outside[:5]) + (f" and {len(outside) - 5} more" if len(outside) > 5 else "")
        reasons.append(f"PR changes files outside app/: {shown}")
    return GateResult(passed=not reasons, reasons=reasons, checks=checks, scope_violation=bool(outside))
