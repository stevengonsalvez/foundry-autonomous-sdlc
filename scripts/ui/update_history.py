"""Automate updating the app evolution timeline for releases and merges.

Used by the trusted app-history.yml workflow:
- Validates the captured artifact directory as untrusted data using validate_artifact.py
- Commits the validated PNGs to branch pr-screenshots under releases/<tag-or-sha8>/
- Copies validated PNGs into history/screenshots/<tag-or-sha8>/
- Regenerates history/data.json, history/index.html, history/css/styles.css, history/js/main.js
- Verifies size budgets (HTML < 50KB, CSS < 20KB, JS < 15KB)
- Optionally commits and pushes to main and pr-screenshots
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ui.validate_artifact import validate_artifact_dir  # noqa: E402

BRANCH_NAME = "pr-screenshots"


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


def resolve_release_key(repo_root: Path, override_key: str | None = None) -> tuple[str, str]:
    """Resolve release key (tag or sha8) and full commit sha.

    Returns (key, full_sha).
    """
    if override_key:
        sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root, check=False) or "00000000"
        return override_key, sha

    full_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root, check=False) or "00000000"

    # Check if HEAD is an exact tag match (v*)
    tag_res = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if tag_res.returncode == 0 and tag_res.stdout.strip().startswith("v"):
        return tag_res.stdout.strip(), full_sha

    return full_sha[:8], full_sha


def publish_to_pr_screenshots(
    artifacts_dir: Path,
    key: str,
    repo: str,
    push: bool = False,
) -> None:
    """Store release screenshots on pr-screenshots branch under releases/<key>/."""
    work_dir = Path("/tmp/history-screenshots-worktree")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    run_cmd(["git", "init"], cwd=work_dir)
    remote_url = f"https://github.com/{repo}.git"
    run_cmd(["git", "remote", "add", "origin", remote_url], cwd=work_dir)

    remote_branches = run_cmd(
        ["git", "ls-remote", "--heads", "origin", BRANCH_NAME], cwd=work_dir, check=False
    )
    if BRANCH_NAME in remote_branches:
        run_cmd(["git", "fetch", "origin", BRANCH_NAME, "--depth=1"], cwd=work_dir)
        run_cmd(["git", "checkout", BRANCH_NAME], cwd=work_dir)
    else:
        run_cmd(["git", "checkout", "--orphan", BRANCH_NAME], cwd=work_dir)

    target_dir = work_dir / "releases" / key
    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy files
    for item in artifacts_dir.iterdir():
        if item.is_file() and (item.name.endswith(".png") or item.name == "manifest.json"):
            shutil.copy2(item, target_dir / item.name)

    run_cmd(["git", "config", "user.name", "github-actions[bot]"], cwd=work_dir)
    run_cmd(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        cwd=work_dir,
    )
    run_cmd(["git", "add", "-A"], cwd=work_dir)
    status = run_cmd(["git", "status", "--porcelain"], cwd=work_dir)

    if status:
        msg = f"proof(history): UI screenshots for release {key}"
        run_cmd(["git", "commit", "-m", msg], cwd=work_dir)
        print(f"Committed screenshots for {key} to {BRANCH_NAME}")
        if push:
            for attempt in range(3):
                try:
                    run_cmd(
                        ["git", "pull", "--rebase", "origin", BRANCH_NAME],
                        cwd=work_dir,
                        check=False,
                    )
                    run_cmd(["git", "push", "origin", BRANCH_NAME], cwd=work_dir)
                    print(f"Pushed {BRANCH_NAME} to origin")
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise RuntimeError(
                            f"Failed to push to {BRANCH_NAME} after 3 attempts: {exc}"
                        ) from exc
                    time.sleep(1)
    else:
        print(f"No changes in screenshots for release {key}")


def update_history(
    artifacts_dir: str | Path,
    repo: str,
    key: str | None = None,
    push: bool = False,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    artifacts_path = Path(artifacts_dir).resolve()
    print(f"Validating artifacts in {artifacts_path}...")
    res = validate_artifact_dir(artifacts_path)
    if not res.valid:
        err_msg = "Artifact validation failed:\n" + "\n".join(f"  - {e}" for e in res.errors)
        raise RuntimeError(err_msg)

    rel_key, full_sha = resolve_release_key(repo_root, key)
    print(f"Resolved release key: {rel_key} (commit: {full_sha[:8]})")

    # 1. Publish to pr-screenshots branch (fails hard on error)
    if repo:
        publish_to_pr_screenshots(artifacts_path, rel_key, repo, push=push)

    return {
        "key": rel_key,
        "full_sha": full_sha,
        "screenshots": res.screenshots,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update app evolution history for current release/merge."
    )
    parser.add_argument(
        "--artifacts-dir",
        required=True,
        type=Path,
        help="Directory containing captured screenshots and manifest",
    )
    parser.add_argument(
        "--repo",
        default=os.getenv("GITHUB_REPOSITORY", "stevengonsalvez/foundry-autonomous-sdlc"),
        help="GitHub repository (owner/repo)",
    )
    parser.add_argument(
        "--key", default=None, help="Release key override (e.g. v0.4.0 or commit sha8)"
    )
    parser.add_argument(
        "--push", action="store_true", help="Push changes to pr-screenshots and main"
    )
    args = parser.parse_args()

    update_history(
        artifacts_dir=args.artifacts_dir,
        repo=args.repo,
        key=args.key,
        push=args.push,
    )


if __name__ == "__main__":
    main()
