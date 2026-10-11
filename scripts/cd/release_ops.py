"""GitHub-side release bookkeeping: deployments, the prod tag, and the "released" comments.

    python -m scripts.cd.release_ops deploy-start --repo R --env staging --sha S --log-url U \
        --env-url E [--state in_progress|success]
    python -m scripts.cd.release_ops deploy-mark --repo R --env staging --sha S --state failure
    python -m scripts.cd.release_ops create-tag --repo R --tag prod/20261011-093005-abc1234 --sha S
    python -m scripts.cd.release_ops comment-release --repo R --sha S --version V --run-url U \
        --soak-minutes 10 --pr 13 --issue 12

GitHub calls the production environment `production`; deploy.json calls it `prod`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .comments import upsert_comment
from .ghcli import GhError, Runner, api_get, api_send, fail, gh, optional_int, set_output

ENVIRONMENTS = ("staging", "production")
STATES = ("in_progress", "success", "failure", "inactive")
MAX_TICKETS = 40


def set_status(
    run: Runner, repo: str, deployment_id: int, state: str, log_url: str = "", env_url: str = ""
) -> None:
    body: dict[str, Any] = {"state": state, "auto_inactive": True}
    if log_url:
        body["log_url"] = log_url
    if env_url and state in ("in_progress", "success"):
        body["environment_url"] = env_url
    api_send(run, "POST", f"repos/{repo}/deployments/{deployment_id}/statuses", body)


def deploy_start(
    run: Runner, repo: str, env: str, sha: str, log_url: str, env_url: str, state: str
) -> int:
    """Create a deployment of `sha` and give it a first status."""
    created = api_send(
        run,
        "POST",
        f"repos/{repo}/deployments",
        {
            "ref": sha,
            "environment": env,
            "auto_merge": False,
            "required_contexts": [],
            "transient_environment": env == "staging",
            "production_environment": env == "production",
            "description": f"CD {env} {sha[:7]}",
        },
    )
    deployment_id = int(created["id"])
    set_status(run, repo, deployment_id, state, log_url, env_url)
    return deployment_id


def deploy_mark(
    run: Runner, repo: str, env: str, sha: str, state: str, log_url: str = "", env_url: str = ""
) -> int:
    """Give every deployment of `sha` in `env` a status. Returns how many were marked."""
    found = api_get(run, f"repos/{repo}/deployments?sha={sha}&environment={env}&per_page=30")
    for deployment in found:
        set_status(run, repo, int(deployment["id"]), state, log_url, env_url)
    return len(found)


def create_tag(run: Runner, repo: str, tag: str, sha: str) -> str:
    """A lightweight tag. Creating the same tag on the same sha again is fine."""
    try:
        api_send(run, "POST", f"repos/{repo}/git/refs", {"ref": f"refs/tags/{tag}", "sha": sha})
    except GhError as err:
        if not err.unprocessable:
            raise
        existing = api_get(run, f"repos/{repo}/git/ref/tags/{tag}")["object"]["sha"]
        if existing != sha:
            raise RuntimeError(f"tag {tag} already exists on {existing}, not {sha}") from err
        return "exists"
    return "created"


def release_comment(sha: str, version: str, run_url: str, soak_minutes: float) -> tuple[str, str]:
    marker = f"<!-- cd-release:{sha} -->"
    body = (
        f"{marker}\nReleased to prod: {version} (smoke and {soak_minutes:g} minute soak passed)\n\n"
        f"Run: {run_url}"
    )
    return marker, body


def ticket_numbers(pr: int | None, issue: int | None, includes: list[dict[str, Any]]) -> list[int]:
    """The PR and issue of this release first, then those of every build it carried along."""
    numbers: list[int] = []
    candidates = [pr, issue]
    for item in includes:
        candidates += [item.get("pr"), item.get("issue")]
    for number in candidates:
        if number is not None and number not in numbers:
            numbers.append(number)
    return numbers[:MAX_TICKETS]


def comment_release(
    run: Runner,
    repo: str,
    *,
    sha: str,
    version: str,
    run_url: str,
    soak_minutes: float,
    pr: int | None,
    issue: int | None,
    includes: list[dict[str, Any]],
) -> list[str]:
    marker, body = release_comment(sha, version, run_url, soak_minutes)
    results = []
    for number in ticket_numbers(pr, issue, includes):
        results.append(f"#{number}: {upsert_comment(run, repo, number, marker, body)}")
    return results


def main(argv: list[str] | None = None, run: Runner = gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("deploy-start", "deploy-mark", "create-tag", "comment-release"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--repo", required=True)
        cmd.add_argument("--sha", required=True)
        if name in ("deploy-start", "deploy-mark"):
            cmd.add_argument("--env", choices=ENVIRONMENTS, required=True)
            cmd.add_argument("--log-url", default="")
            cmd.add_argument("--env-url", default="")
        if name == "deploy-start":
            cmd.add_argument("--state", choices=("in_progress", "success"), default="in_progress")
        if name == "deploy-mark":
            cmd.add_argument("--state", choices=("failure", "inactive", "success"), required=True)
        if name == "create-tag":
            cmd.add_argument("--tag", required=True)
        if name == "comment-release":
            cmd.add_argument("--version", required=True)
            cmd.add_argument("--run-url", required=True)
            cmd.add_argument("--soak-minutes", type=float, default=10)
            cmd.add_argument("--pr", type=optional_int, default=None)
            cmd.add_argument("--issue", type=optional_int, default=None)
            cmd.add_argument("--includes-env", default="CD_INCLUDES")
    args = parser.parse_args(argv)
    try:
        if args.command == "deploy-start":
            deployment = deploy_start(
                run, args.repo, args.env, args.sha, args.log_url, args.env_url, args.state
            )
            set_output("deployment_id", deployment)
        elif args.command == "deploy-mark":
            marked = deploy_mark(
                run, args.repo, args.env, args.sha, args.state, args.log_url, args.env_url
            )
            print(f"{args.env} {args.sha[:7]}: {marked} deployment(s) marked {args.state}")
        elif args.command == "create-tag":
            print(f"tag {args.tag}: {create_tag(run, args.repo, args.tag, args.sha)}")
        else:
            includes = json.loads(os.environ.get(args.includes_env) or "[]")
            for line in comment_release(
                run,
                args.repo,
                sha=args.sha,
                version=args.version,
                run_url=args.run_url,
                soak_minutes=args.soak_minutes,
                pr=args.pr,
                issue=args.issue,
                includes=includes,
            ):
                print(line)
    except (GhError, RuntimeError, ValueError) as err:
        return fail(str(err))
    return 0


if __name__ == "__main__":
    sys.exit(main())
