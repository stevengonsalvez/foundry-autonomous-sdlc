"""The `plan` job: decide what this CD run deploys, and read the facts later jobs need.

    python -m scripts.cd.plan resolve        # sha, version, pr, issue, includes, proceed
    python -m scripts.cd.plan failed-job     # first failed job among NEEDS_JSON

Everything attacker-influenced (PR title, body, branch name) is read here, inside Python, and only
digits, a 40 hex sha or a validated version string leave through the step outputs.
Inputs arrive through the environment: REPO, EVENT_NAME, SHA_INPUT, RUN_SHA, GH_TOKEN.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .deploy_state import Include
from .ghcli import GhError, Runner, api_get, fail, gh, set_output
from .soak import minutes_arg

JOB_ORDER = ("build", "stage", "smoke", "soak", "promote")
MAX_INCLUDES = 50
TAG_RETRIES = 5
TAG_RETRY_WAIT_S = 15

_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)", re.IGNORECASE)
_AGENT_BRANCH = re.compile(r"agent/issue-(\d+)(?:-r\d+)?")
_RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_SHA = re.compile(r"[0-9a-f]{40}")
_SHA_INPUT = re.compile(r"[0-9a-fA-F]{7,40}|main")


def parse_issue(body: str | None, branch: str | None) -> int | None:
    """The issue a PR closes: `Closes #N` in the body first, else the agent branch name."""
    match = _CLOSES.search(body or "")
    if match:
        return int(match.group(1))
    match = _AGENT_BRANCH.fullmatch(branch or "")
    return int(match.group(1)) if match else None


def pick_version(tags_at_sha: list[str], short: str) -> str:
    """The highest `vX.Y.Z` tag on the sha, else `main-<short sha>`."""
    found = [
        (tuple(int(n) for n in m.groups()), tag)
        for tag in tags_at_sha
        if (m := _RELEASE_TAG.fullmatch(tag))
    ]
    return max(found)[1] if found else f"main-{short}"


def select_pr(prs: list[dict[str, Any]], sha: str) -> dict[str, Any] | None:
    """The merged PR that produced `sha`: the one whose merge commit it is, else any merged PR."""
    merged = [pr for pr in prs if pr.get("merged_at")]
    exact = [pr for pr in merged if pr.get("merge_commit_sha") == sha]
    chosen = exact or merged
    return chosen[0] if chosen else None


def include_for(pr: dict[str, Any], sha: str) -> Include:
    issue = parse_issue(pr.get("body"), (pr.get("head") or {}).get("ref"))
    return Include(pr=int(pr["number"]), issue=issue, sha=sha)


def compute_includes(
    shas_newest_first: list[str], lookup: Callable[[str], dict[str, Any] | None]
) -> list[Include]:
    """One entry per merged PR among `shas` (first-parent merges since prod), oldest first."""
    includes = []
    for sha in reversed(shas_newest_first):
        pr = lookup(sha)
        if pr is not None:
            includes.append(include_for(pr, sha))
    return includes


def failed_job(needs: dict[str, Any]) -> str | None:
    """The first job, in pipeline order, whose result is `failure`."""
    for job in JOB_ORDER:
        if (needs.get(job) or {}).get("result") == "failure":
            return job
    return None


# ---- I/O -------------------------------------------------------------------------------------


def _pulls(run: Runner, repo: str, sha: str) -> list[dict[str, Any]]:
    result = api_get(run, f"repos/{repo}/commits/{sha}/pulls")
    return result if isinstance(result, list) else []


def tags_at(run: Runner, repo: str, sha: str) -> list[str]:
    tags = api_get(run, f"repos/{repo}/tags?per_page=100")
    return [t["name"] for t in tags if (t.get("commit") or {}).get("sha") == sha]


def prod_sha(run: Runner, repo: str) -> str | None:
    """The sha prod runs now, from deploy.json on the deploy branch (None before any release)."""
    try:
        doc = api_get(run, f"repos/{repo}/contents/deploy.json?ref=deploy")
    except GhError as err:
        if err.not_found:
            return None
        raise
    state = json.loads(base64.b64decode(doc["content"]))
    prod = state.get("prod")
    return prod["sha"] if prod and _SHA.fullmatch(prod.get("sha", "")) else None


def first_parent_shas(prod: str, sha: str) -> list[str]:
    """First-parent commits in `prod..sha`, newest first; `[sha]` when prod is not in this clone."""
    done = subprocess.run(
        ["git", "log", "--first-parent", "--format=%H", f"{prod}..{sha}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        return [sha]
    return done.stdout.split()[:MAX_INCLUDES]


def resolve_sha(run: Runner, repo: str, requested: str) -> str:
    if not _SHA_INPUT.fullmatch(requested):
        raise ValueError(f"not a commit sha or main: {requested!r}")
    sha = api_get(run, f"repos/{repo}/commits/{requested}")["sha"]
    if not _SHA.fullmatch(sha):
        raise ValueError(f"GitHub returned an unexpected sha: {sha!r}")
    return str(sha)


def is_on_main(run: Runner, repo: str, sha: str, head: str) -> bool:
    if sha == head:
        return True
    status = api_get(run, f"repos/{repo}/compare/{sha}...{head}")["status"]
    return status in ("ahead", "identical")


@dataclass(frozen=True)
class Plan:
    sha: str
    short: str
    version: str
    pr: int | None
    issue: int | None
    includes: list[Include]
    proceed: bool
    reason: str


def build_plan(
    run: Runner,
    *,
    repo: str,
    event: str,
    requested_sha: str,
    sleep: Callable[[float], None] = time.sleep,
    git_log: Callable[[str, str], list[str]] = first_parent_shas,
) -> Plan:
    head = resolve_sha(run, repo, "main")
    sha = resolve_sha(run, repo, requested_sha or "main")
    if not is_on_main(run, repo, sha, head):
        raise ValueError(f"{sha} is not on main: only commits on main are deployed")
    short = sha[:7]

    proceed, reason = True, "deploying"
    if event != "workflow_dispatch" and sha != head:
        proceed, reason = False, f"main has moved on to {head[:7]}; a newer run deploys it"

    prs = _pulls(run, repo, sha)
    pr = select_pr(prs, sha)
    issue = include_for(pr, sha).issue if pr else None

    tags = tags_at(run, repo, sha)
    for _ in range(TAG_RETRIES if sha == head and proceed else 0):
        if tags:
            break
        sleep(TAG_RETRY_WAIT_S)  # the orchestrator tags the merge commit just after the merge
        tags = tags_at(run, repo, sha)

    prod = prod_sha(run, repo)
    shas = git_log(prod, sha) if prod and prod != sha else [sha]
    cache = {sha: pr}

    def lookup(commit: str) -> dict[str, Any] | None:
        if commit not in cache:
            cache[commit] = select_pr(_pulls(run, repo, commit), commit)
        return cache[commit]

    includes = compute_includes(shas, lookup)
    return Plan(
        sha,
        short,
        pick_version(tags, short),
        pr["number"] if pr else None,
        issue,
        includes,
        proceed,
        reason,
    )


def site_url(repo: str) -> str:
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}"


def summary_lines(plan: Plan) -> list[str]:
    """Markdown for the run page; built only from validated values."""
    if not plan.proceed:
        return [f"CD skipped {plan.short}: {plan.reason}"]
    carried = ", ".join(f"#{i.pr}" for i in plan.includes) or "none"
    return [
        f"CD plan: deploying `{plan.version}` (`{plan.short}`), pull requests carried: {carried}"
    ]


def write_summary(plan: Plan) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(summary_lines(plan)) + "\n")


def cmd_resolve(run: Runner) -> int:
    repo = os.environ["REPO"]
    event = os.environ["EVENT_NAME"]
    requested = os.environ.get("SHA_INPUT") or os.environ.get("RUN_SHA") or ""
    try:
        minutes_arg(
            os.environ.get("SOAK_MINUTES") or "10"
        )  # a bad input fails here, not after staging
        plan = build_plan(run, repo=repo, event=event, requested_sha=requested)
    except (ValueError, GhError, argparse.ArgumentTypeError) as err:
        return fail(str(err))
    write_summary(plan)
    site = site_url(repo)
    set_output("sha", plan.sha)
    set_output("short", plan.short)
    set_output("version", plan.version)
    set_output("pr", plan.pr)
    set_output("issue", plan.issue)
    set_output("includes", json.dumps([i.as_dict() for i in plan.includes], separators=(",", ":")))
    set_output("proceed", str(plan.proceed).lower())
    set_output("reason", plan.reason)
    set_output("prod_url", f"{site}/")
    set_output("staging_url", f"{site}/staging/")
    return 0


def cmd_failed_job() -> int:
    needs = json.loads(os.environ["NEEDS_JSON"])
    job = failed_job(needs)
    if job is None:
        return fail("no job in needs failed")
    set_output("job", job)
    return 0


def main(argv: list[str] | None = None, run: Runner = gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("resolve", "failed-job"))
    args = parser.parse_args(argv)
    return cmd_resolve(run) if args.command == "resolve" else cmd_failed_job()


if __name__ == "__main__":
    sys.exit(main())
