"""
Reconcile: rebuild what the events should say from GitHub, the source of truth.

Runs on every `reconcile` call and covers events the orchestrator never delivered (a ledger that was
down, a tick that crashed). Reads issues, state comments, PRs and commits, the CD record on branch
`deploy` and the orchestrator's `metrics.json`, and returns events for whatever differs from `doc`.
Only owner authored objects count, the same rule the orchestrator uses. Stdlib only.
"""

from __future__ import annotations

import json
from typing import Any

from sdlc_agents import state as sdlc_state
from sdlc_agents.ledger import events, model
from sdlc_agents.ports import OWNER, GitHubError, GitHubPort

CODER_LOG_MARKER = "<!-- sdlc-coder-log:v1"
MAINTENANCE_LABEL = "maintenance:test-repair"
DEPLOY_BRANCH = "deploy"
METRICS_BRANCH = "metrics"


def _first_line(message: str) -> str:
    return model.clean(message.splitlines()[0] if message else "", 160)


def build_ticket(
    github: GitHubPort, item: Any, previous: dict[str, Any] | None, now: str
) -> tuple[dict[str, Any] | None, str | None]:
    """The ticket for one issue or maintenance PR, and a problem note when its state comment is unreadable."""
    comments = github.list_comments(item.number)
    try:
        state_comment, st = sdlc_state.find(comments)
    except ValueError as exc:
        return None, f"#{item.number}: state comment unreadable: {model.clean(exc, 160)}"
    data = st.data if st else None
    coder_log = next((c for c in comments if c.author == OWNER and c.body.startswith(CODER_LOG_MARKER)), None)
    ids: dict[str, int] = {}
    if state_comment:
        ids["state"] = state_comment.id
    if coder_log:
        ids["coder_log"] = coder_log.id
    pr_number = ((data or {}).get("pr") or {}).get("number") or (item.number if item.is_pull_request else None)
    pr_info: dict[str, Any] | None = None
    commits: list[dict[str, Any]] = []
    if pr_number:
        try:
            pull = github.get_pull(int(pr_number))
            pr_info = {
                "number": pull.number,
                "title": pull.title,
                "branch": pull.head_ref,
                "head": pull.head_sha,
                "merge_sha": pull.merge_commit_sha,
            }
            same = previous and (previous.get("pr") or {}).get("head") == pull.head_sha and previous.get("commits")
            if same:
                commits = previous["commits"]
            else:
                commits = [
                    {
                        "sha": c.sha[:12],
                        "message": _first_line(c.message),
                        "kind": model.commit_kind(c.message),
                        "files": len(c.files),
                    }
                    for c in github.list_pull_commits(pull.number)
                ]
        except GitHubError:
            pr_info = None

    return model.ticket(
        number=item.number,
        kind="pr" if item.is_pull_request else "issue",
        title=item.title,
        author=item.author,
        opened_at=item.created_at,
        closed_at=item.closed_at,
        labels=item.labels,
        state_data=data,
        commits=commits,
        pr_info=pr_info,
        comment_ids=ids,
        comments=comments,
        updated_at=getattr(item, "updated_at", None),
    ), None


def reconcile(
    github: GitHubPort, doc: dict[str, Any], now: str, *, issue: int | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Events for every difference between GitHub and `doc`, plus problems worth recording."""
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    known = {t["issue"]: t for t in doc["tickets"]}
    archived = set(doc.get("archived_ids", []))
    ignored = 0
    for item in sorted(github.list_issues(state="all"), key=lambda i: i.number):
        if issue is not None and item.number != issue:
            continue
        # Agent PRs are driven through their issue; a PR is its own ticket when it is the maintenance flow's, or
        # when a release of it was rolled back (the CD workflow flags it, there being no issue to flag).
        if (
            item.is_pull_request
            and MAINTENANCE_LABEL not in item.labels
            and model.DEPLOY_FAILED_LABEL not in item.labels
            and item.number not in known  # a PR once flagged stays a ticket, so its recovery shows too
        ):
            continue
        if item.author != OWNER:
            ignored += 1
            continue
        if (
            item.state == "closed"
            and item.number not in known  # a merged PR whose flag CD took off must still update
            and not any(lbl.startswith(("stage:", "escalated:")) for lbl in item.labels)
        ):
            continue
        if item.number in archived:
            continue
        try:
            # One bad issue (an oversized state comment, an unknown stage) must not stop the others.
            ticket, problem = build_ticket(github, item, known.get(item.number), now)
            if problem:
                problems.append(problem)
                continue
            assert ticket is not None
            if known.get(item.number, {}).get("digest") != ticket["digest"]:
                out.append(
                    events.make(
                        "ticket.updated",
                        ticket["updated_at"],
                        {"ticket": ticket},
                        issue=item.number,
                        source="reconcile",
                    )
                )
        except Exception as exc:
            problems.append(f"#{item.number}: skipped: {type(exc).__name__}: {model.clean(exc, 160)}")
    doc["ledger"]["ignored"] = ignored
    if issue is None:
        out += _deploy_event(github, doc, now) + _metrics_event(github, doc, now)
    return out, problems


def _deploy_event(github: GitHubPort, doc: dict[str, Any], now: str) -> list[dict[str, Any]]:
    try:
        text = github.get_file("deploy.json", ref=DEPLOY_BRANCH)
    except GitHubError:
        return []
    if not text:
        return []
    try:
        deploy = json.loads(text)
    except ValueError:
        return []
    if deploy == doc.get("deploy"):
        return []
    history = deploy.get("history") or [{"at": now}]
    at = max(str(h.get("at", "")) for h in history) or now
    return [events.make("env.changed", at, {"deploy": deploy}, source="reconcile")]


def _metrics_event(github: GitHubPort, doc: dict[str, Any], now: str) -> list[dict[str, Any]]:
    try:
        text = github.get_file("metrics.json", ref=METRICS_BRANCH)
        totals = json.loads(text)["totals"] if text else None
        generated = json.loads(text)["generated_at"] if text else None
    except (GitHubError, ValueError, KeyError):
        return []
    if not totals:
        return []
    seen = doc["cost"].get("metrics") or {}
    if seen.get("generated_at") == generated:
        return []
    return [
        events.make(
            "metrics.observed",
            str(generated or now),
            {
                "usd": float(totals.get("usd", 0)),
                "orchestrator_usd": float(totals.get("orchestrator_usd", 0)),
                "issues": int(totals.get("issues", 0)),
                "generated_at": generated,
            },
            source="reconcile",
        )
    ]


def previous_commit_sha(doc: dict[str, Any], issue: int) -> str | None:
    t = next((x for x in doc["tickets"] if x["issue"] == issue), None)
    return ((t or {}).get("pr") or {}).get("head")
