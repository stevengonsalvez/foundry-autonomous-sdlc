"""Flag the ticket of a release that failed: a label and one comment per run, updated in place.

    python -m scripts.cd.flag_ticket --repo O/R --issue 12 --pr 13 --run-id 99 --run-url U \
        --reason smoke --version v0.4.0 --rollback-ok true --restored-version v0.3.1

The label goes on the issue, or on the PR when the release has no issue. With neither, nothing is
flagged (a commit pushed straight to main has no ticket) and the script says so.
"""

from __future__ import annotations

import argparse
import sys

from .comments import upsert_comment
from .ghcli import GhError, Runner, api_send, fail, gh, optional_int

LABEL = "escalated:deploy-failed"


def marker(run_id: int) -> str:
    return f"<!-- cd-rollback:{run_id} -->"


def build_comment(
    *,
    run_id: int,
    run_url: str,
    reason: str,
    version: str,
    rollback_ok: bool,
    restored_version: str,
) -> str:
    if rollback_ok:
        restored = f"restored to {restored_version}" if restored_version else "removed"
        outcome = f"Staging was {restored}. Nothing from this release reached prod."
    else:
        outcome = "The rollback itself did not finish: check the run before anything else."
    return (
        f"{marker(run_id)}\n"
        f"**Release failed: {version}**\n\n"
        f"The `{reason}` job failed. {outcome}\n\n"
        f"Run: {run_url}"
    )


def target(issue: int | None, pr: int | None) -> int | None:
    return issue if issue is not None else pr


def flag(
    run: Runner,
    *,
    repo: str,
    issue: int | None,
    pr: int | None,
    run_id: int,
    run_url: str,
    reason: str,
    version: str,
    rollback_ok: bool,
    restored_version: str,
) -> str:
    number = target(issue, pr)
    if number is None:
        return "no issue or pull request to flag"
    api_send(run, "POST", f"repos/{repo}/issues/{number}/labels", {"labels": [LABEL]})
    body = build_comment(
        run_id=run_id,
        run_url=run_url,
        reason=reason,
        version=version,
        rollback_ok=rollback_ok,
        restored_version=restored_version,
    )
    comment = upsert_comment(run, repo, number, marker(run_id), body)
    return f"#{number}: labelled {LABEL}, comment {comment}"


def main(argv: list[str] | None = None, run: Runner = gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=optional_int, default=None)
    parser.add_argument("--pr", type=optional_int, default=None)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--rollback-ok", choices=("true", "false"), default="true")
    parser.add_argument("--restored-version", default="")
    args = parser.parse_args(argv)
    try:
        message = flag(
            run,
            repo=args.repo,
            issue=args.issue,
            pr=args.pr,
            run_id=args.run_id,
            run_url=args.run_url,
            reason=args.reason,
            version=args.version,
            rollback_ok=args.rollback_ok == "true",
            restored_version=args.restored_version,
        )
    except (GhError, ValueError, KeyError) as err:
        return fail(str(err))
    print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
