"""Dispatch pages.yml and wait for that run, so a deploy-branch change reaches the live site.

    python -m scripts.cd.pages_deploy --repo O/R [--ref main] [--timeout 900]

pages.yml renders the whole site from the deploy branch, so a dispatch after every push to that
branch is how a change gets published. The dispatch asks for `return_run_details`, so the
response names the run it created (REST API change of 2026-02-19: `workflow_run_id`, `run_url`,
`html_url`). Only when the response carries no run id is the run found by creation time.

A run that ends `cancelled` is not an error here: the `pages` concurrency group keeps only one
pending run, so a newer run can replace ours, and that run renders the same branch. What decides
success is the live check that follows (`verify_live`), which this script does not replace.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from datetime import datetime

from .ghcli import GhError, Runner, api_get, api_send, fail, gh

WORKFLOW = "pages.yml"
CLOCK_SLACK_S = 5


def epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()


def find_run(runs: list[dict[str, object]], not_before: float) -> dict[str, object] | None:
    """The earliest dispatched run created at or after `not_before`."""
    later = [r for r in runs if epoch(str(r["created_at"])) >= not_before]
    return min(later, key=lambda r: epoch(str(r["created_at"])), default=None)


def search_run(
    run: Runner,
    repo: str,
    dispatched: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    interval_s: float,
    find_timeout_s: float,
) -> dict[str, object]:
    """Fallback: the earliest dispatched pages run created right after `dispatched`."""
    listing = f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=20"
    while True:
        found = find_run(api_get(run, listing)["workflow_runs"], dispatched - CLOCK_SLACK_S)
        if found is not None:
            return found
        if clock() - dispatched > find_timeout_s:
            raise RuntimeError(f"no {WORKFLOW} run appeared within {find_timeout_s:.0f}s")
        sleep(interval_s)


def dispatch_and_wait(
    run: Runner,
    repo: str,
    *,
    ref: str = "main",
    timeout_s: float = 900,
    find_timeout_s: float = 180,
    interval_s: float = 10,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> str:
    """Returns the conclusion of the pages run. Raises when it fails or cannot be found."""
    dispatched = clock()
    response = api_send(
        run,
        "POST",
        f"repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
        {"ref": ref, "return_run_details": True},
    )
    named = response.get("workflow_run_id") if isinstance(response, dict) else None
    if isinstance(named, int) and not isinstance(named, bool):
        run_id, url = named, str(response.get("html_url") or f"run {named}")
    else:
        log("the dispatch response named no run, searching by creation time")
        found = search_run(run, repo, dispatched, clock, sleep, interval_s, find_timeout_s)
        run_id, url = found["id"], found["html_url"]
    log(f"waiting for {WORKFLOW} run {url}")

    deadline = clock() + timeout_s
    while True:
        current = api_get(run, f"repos/{repo}/actions/runs/{run_id}")
        if current["status"] == "completed":
            conclusion = str(current["conclusion"])
            if conclusion == "success":
                return conclusion
            if conclusion == "cancelled":
                log(f"warning: {url} was cancelled; relying on the live check")
                return conclusion
            raise RuntimeError(f"{WORKFLOW} run ended {conclusion}: {url}")
        if clock() > deadline:
            raise RuntimeError(f"{WORKFLOW} run did not finish within {timeout_s:.0f}s: {url}")
        sleep(interval_s)


def main(argv: list[str] | None = None, run: Runner = gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument("--ref", default="main")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        conclusion = dispatch_and_wait(run, args.repo, ref=args.ref, timeout_s=args.timeout)
    except (GhError, RuntimeError) as err:
        return fail(str(err))
    print(f"{WORKFLOW}: {conclusion}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
