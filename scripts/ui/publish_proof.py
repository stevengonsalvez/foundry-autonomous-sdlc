"""
Publish UI proof screenshots to the orphan branch pr-screenshots and comment on the PR.

Used by the trusted ui-proof.yml workflow:
- Validates the artifact as untrusted data using validate_artifact.py
- Commits the validated PNGs to branch pr-screenshots under pr-<number>/<head sha 8>/
- Prunes pr-screenshots directories of PRs closed more than 14 days ago
- Upserts the single PR comment with marker <!-- ui-proof:v1 -->
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.ui.validate_artifact import validate_artifact_dir

MARKER = "<!-- ui-proof:v1 -->"
BRANCH_NAME = "pr-screenshots"
PRUNE_DAYS = 14

FIXED_ROUTES = ("home", "parcel-found", "not-found", "invalid-input")
FIXED_VIEWPORTS = ("desktop", "mobile")
ROUTE_TITLES = {
    "home": "Home",
    "parcel-found": "Parcel Found",
    "not-found": "Not Found",
    "invalid-input": "Invalid Input",
}


def run_cmd(cmd: list[str], *, cwd: Path | str | None = None, check: bool = True) -> str:
    res = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            f"Command {cmd} failed with exit code {res.returncode}:\n"
            f"stdout: {res.stdout}\nstderr: {res.stderr}"
        )
    return res.stdout.strip()


def resolve_pr_number(
    head_sha: str,
    repo: str,
    pull_requests_json: str | None = None,
    head_repo: str | None = None,
    head_branch: str | None = None,
) -> int | None:
    if pull_requests_json:
        try:
            data = json.loads(pull_requests_json)
            if isinstance(data, list):
                matches: list[int] = []
                for pr in data:
                    if not isinstance(pr, dict):
                        continue
                    num = pr.get("number")
                    if not isinstance(num, int):
                        continue
                    pr_head = pr.get("head") or {}
                    if pr_head.get("sha") != head_sha:
                        continue
                    pr_head_repo = (pr_head.get("repo") or {}).get("full_name")
                    pr_head_ref = pr_head.get("ref")
                    if head_repo and pr_head_repo and pr_head_repo != head_repo:
                        continue
                    if head_branch and pr_head_ref and pr_head_ref != head_branch:
                        continue
                    matches.append(num)
                if len(matches) == 1:
                    return matches[0]
                if len(matches) > 1:
                    return None
        except Exception:
            pass

    # Fallback to GitHub API: pick only the PR whose head.repo.full_name and head.ref match the run
    try:
        out = run_cmd(
            ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/commits/{head_sha}/pulls"],
            check=False,
        )
        if out:
            pages = json.loads(out)
            pulls: list[Any] = []
            if isinstance(pages, list):
                for item in pages:
                    if isinstance(item, list):
                        pulls.extend(item)
                    elif isinstance(item, dict):
                        pulls.append(item)

            matches = []
            for pr in pulls:
                if not isinstance(pr, dict):
                    continue
                num = pr.get("number")
                if not isinstance(num, int):
                    continue
                pr_head = pr.get("head") or {}
                if pr_head.get("sha") != head_sha:
                    continue
                pr_head_repo = (pr_head.get("repo") or {}).get("full_name")
                pr_head_ref = pr_head.get("ref")
                if head_repo and pr_head_repo and pr_head_repo != head_repo:
                    continue
                if head_branch and pr_head_ref and pr_head_ref != head_branch:
                    continue
                matches.append(num)
            if len(matches) == 1:
                return matches[0]
    except Exception:
        pass

    return None


def format_pr_comment(
    repo: str,
    pr_number: int,
    head_sha: str,
    manifest_sha256: str,
    screenshots: list[dict[str, Any]],
) -> str:
    head_short = head_sha[:8]
    base_url = f"https://raw.githubusercontent.com/{repo}/{BRANCH_NAME}/pr-{pr_number}/{head_short}"

    by_route: dict[str, dict[str, str]] = {}
    for item in screenshots:
        route = item.get("route")
        viewport = item.get("viewport")
        filename = item.get("filename")
        if route in FIXED_ROUTES and viewport in FIXED_VIEWPORTS and filename:
            by_route.setdefault(route, {})[viewport] = filename

    table_rows = []
    capture_count = 0
    for route in FIXED_ROUTES:
        if route not in by_route:
            continue
        desktop_file = by_route[route].get("desktop")
        mobile_file = by_route[route].get("mobile")

        if desktop_file:
            desktop_cell = (
                f'<img src="{base_url}/{desktop_file}" alt="{route} desktop" width="320" />'
            )
            capture_count += 1
        else:
            desktop_cell = "-"

        if mobile_file:
            mobile_cell = f'<img src="{base_url}/{mobile_file}" alt="{route} mobile" width="160" />'
            capture_count += 1
        else:
            mobile_cell = "-"

        title = ROUTE_TITLES.get(route, route)
        table_rows.append(f"| **{title}** | {desktop_cell} | {mobile_cell} |")

    lines = [
        MARKER,
        f"### UI Screenshots for `{head_short}`",
        "",
        f"- Head commit: `{head_sha}`",
        f"- Manifest SHA-256: `{manifest_sha256}`",
        f"- Storage: [`{BRANCH_NAME}`](https://github.com/{repo}/tree/{BRANCH_NAME}/pr-{pr_number}/{head_short})",
        "",
        "<details open>",
        f"<summary><b>Screenshots ({capture_count} captures)</b></summary>",
        "",
        "| Route | Desktop (1280px) | Mobile (390px) |",
        "|---|---|---|",
        *table_rows,
        "",
        "</details>",
        "",
        "*(Advisory UI proof captured deterministically via Playwright)*",
    ]
    return "\n".join(lines)


def post_or_update_comment(repo: str, pr_number: int, body: str) -> None:
    comments_raw = run_cmd(
        [
            "gh",
            "api",
            f"repos/{repo}/issues/{pr_number}/comments",
            "--paginate",
            "--slurp",
        ]
    )
    pages = json.loads(comments_raw) if comments_raw else []
    comments: list[dict[str, Any]] = []
    if isinstance(pages, list):
        for p in pages:
            if isinstance(p, list):
                comments.extend(p)
            elif isinstance(p, dict):
                comments.append(p)

    existing_id = None
    for comment in comments:
        user = comment.get("user") or {}
        user_login = user.get("login")
        c_body = comment.get("body", "")
        if user_login == "github-actions[bot]" and c_body.startswith(MARKER):
            existing_id = comment.get("id")
            break

    if existing_id is not None:
        run_cmd(
            [
                "gh",
                "api",
                "-X",
                "PATCH",
                f"repos/{repo}/issues/comments/{existing_id}",
                "-f",
                f"body={body}",
            ]
        )
        print(f"Updated existing UI proof comment {existing_id} on PR #{pr_number}")
    else:
        run_cmd(
            [
                "gh",
                "api",
                "-X",
                "POST",
                f"repos/{repo}/issues/{pr_number}/comments",
                "-f",
                f"body={body}",
            ]
        )
        print(f"Posted new UI proof comment on PR #{pr_number}")


def prune_old_prs(worktree_dir: Path, repo: str) -> list[int]:
    pruned: list[int] = []
    now = datetime.datetime.now(datetime.UTC)

    for item in worktree_dir.iterdir():
        if not item.is_dir() or not item.name.startswith("pr-"):
            continue
        pr_num_str = item.name[3:]
        if not pr_num_str.isdigit():
            continue
        num = int(pr_num_str)

        try:
            pr_data_raw = run_cmd(
                [
                    "gh",
                    "pr",
                    "view",
                    str(num),
                    "--repo",
                    repo,
                    "--json",
                    "state,closedAt",
                ],
                check=False,
            )
            if not pr_data_raw:
                continue
            pr_info = json.loads(pr_data_raw)
            state = pr_info.get("state")
            closed_at_str = pr_info.get("closedAt")
            if state in ("CLOSED", "MERGED") and closed_at_str:
                closed_at = datetime.datetime.fromisoformat(closed_at_str.replace("Z", "+00:00"))
                if (now - closed_at).total_seconds() > PRUNE_DAYS * 86400:
                    shutil.rmtree(item)
                    pruned.append(num)
                    print(f"Pruned stale screenshots for closed PR #{num}")
        except Exception as exc:
            print(f"Notice: Could not check status for PR #{num}: {exc}", file=sys.stderr)

    return pruned


def publish(
    artifacts_dir: str | Path,
    head_sha: str,
    repo: str,
    pr_number: int | None = None,
    pull_requests_json: str | None = None,
    head_repo: str | None = None,
    head_branch: str | None = None,
) -> None:
    print(f"Validating artifacts in {artifacts_dir}...")
    res = validate_artifact_dir(artifacts_dir)
    if not res.valid:
        err_msg = "Artifact validation failed:\n" + "\n".join(f"  - {e}" for e in res.errors)
        raise RuntimeError(err_msg)

    if pr_number is None:
        pr_number = resolve_pr_number(
            head_sha=head_sha,
            repo=repo,
            pull_requests_json=pull_requests_json,
            head_repo=head_repo,
            head_branch=head_branch,
        )

    if pr_number is None:
        print(f"No open PR found for head sha {head_sha}. Nothing to publish.")
        return

    print(f"Publishing UI screenshots for PR #{pr_number} (head sha: {head_sha[:8]})...")

    work_dir = Path(tempfile.mkdtemp(dir=os.environ.get("RUNNER_TEMP")))

    published_manifest_sha256 = ""
    target_ref = f"refs/heads/{BRANCH_NAME}"

    try:
        # Initialize or clone pr-screenshots branch
        run_cmd(["git", "init"], cwd=work_dir)
        remote_url = f"https://github.com/{repo}.git"
        run_cmd(["git", "remote", "add", "origin", remote_url], cwd=work_dir)

        remote_branches = run_cmd(
            ["git", "ls-remote", "--heads", "origin", BRANCH_NAME],
            cwd=work_dir,
            check=False,
        )
        remote_heads = [
            line.split()[1]
            for line in remote_branches.splitlines()
            if len(line.split()) >= 2
        ]
        if target_ref in remote_heads:
            run_cmd(["git", "fetch", "origin", BRANCH_NAME, "--depth=1"], cwd=work_dir)
            run_cmd(["git", "checkout", BRANCH_NAME], cwd=work_dir)
        else:
            run_cmd(["git", "checkout", "--orphan", BRANCH_NAME], cwd=work_dir)

        target_dir = work_dir / f"pr-{pr_number}" / head_sha[:8]
        target_dir.mkdir(parents=True, exist_ok=True)

        # Copy verified PNGs
        artifacts_path = Path(artifacts_dir)
        for screenshot in res.screenshots:
            fn = screenshot["filename"]
            shutil.copy2(artifacts_path / fn, target_dir / fn)

        # Write rebuilt manifest containing only allowlisted keys
        rebuilt_manifest = {
            "version": 1,
            "screenshots": [
                {
                    "filename": s["filename"],
                    "route": s["route"],
                    "sha256": s["sha256"],
                    "size": s["size"],
                    "viewport": s["viewport"],
                }
                for s in res.screenshots
            ],
        }
        manifest_bytes = (
            json.dumps(rebuilt_manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        (target_dir / "manifest.json").write_bytes(manifest_bytes)
        published_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

        # Prune old PRs closed more than 14 days ago
        pruned = prune_old_prs(work_dir, repo)

        # Configure git committer
        run_cmd(["git", "config", "user.name", "github-actions[bot]"], cwd=work_dir)
        run_cmd(
            [
                "git",
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ],
            cwd=work_dir,
        )

        run_cmd(["git", "add", "-A"], cwd=work_dir)
        status = run_cmd(["git", "status", "--porcelain"], cwd=work_dir)

        if status:
            msg = f"proof: UI screenshots for PR #{pr_number} at {head_sha[:8]}"
            if pruned:
                msg += f" (pruned: {', '.join(f'#{n}' for n in pruned)})"
            run_cmd(["git", "commit", "-m", msg], cwd=work_dir)

            # Push with a loop of up to 3 attempts with rebase
            for attempt in range(3):
                try:
                    pull_res = subprocess.run(
                        ["git", "pull", "--rebase", "origin", BRANCH_NAME],
                        cwd=work_dir,
                        capture_output=True,
                        text=True,
                    )
                    if pull_res.returncode != 0:
                        run_cmd(["git", "rebase", "--abort"], cwd=work_dir, check=False)
                        if target_ref in remote_heads:
                            raise RuntimeError(
                                f"git pull --rebase failed: {pull_res.stderr.strip()}"
                            )
                    run_cmd(["git", "push", "origin", BRANCH_NAME], cwd=work_dir)
                    print(f"Pushed UI screenshots to branch {BRANCH_NAME}")
                    break
                except Exception as exc:
                    run_cmd(["git", "rebase", "--abort"], cwd=work_dir, check=False)
                    if attempt == 2:
                        raise RuntimeError(
                            f"Failed to push to {BRANCH_NAME} after 3 attempts: {exc}"
                        ) from exc
                    time.sleep(1)
        else:
            print("No changes to commit on pr-screenshots branch.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    # Upsert comment on the PR
    comment_body = format_pr_comment(
        repo=repo,
        pr_number=pr_number,
        head_sha=head_sha,
        manifest_sha256=published_manifest_sha256,
        screenshots=res.screenshots,
    )
    post_or_update_comment(repo, pr_number, comment_body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish validated UI screenshots.")
    parser.add_argument("--artifacts-dir", required=True, help="Directory of artifacts")
    parser.add_argument("--head-sha", required=True, help="Head commit sha")
    parser.add_argument("--repo", required=True, help="Repository owner/name")
    parser.add_argument("--pr-number", type=int, help="Pull request number")
    parser.add_argument("--pull-requests-json", help="JSON string of PRs from workflow event")
    parser.add_argument("--head-repo", help="Head repository full name")
    parser.add_argument("--head-branch", help="Head branch name")

    args = parser.parse_args()
    pull_requests_json = args.pull_requests_json or os.environ.get("PULL_REQUESTS_JSON")
    head_repo = args.head_repo or os.environ.get("HEAD_REPO")
    head_branch = args.head_branch or os.environ.get("HEAD_BRANCH")

    publish(
        artifacts_dir=args.artifacts_dir,
        head_sha=args.head_sha,
        repo=args.repo,
        pr_number=args.pr_number,
        pull_requests_json=pull_requests_json,
        head_repo=head_repo,
        head_branch=head_branch,
    )


if __name__ == "__main__":
    main()
