r"""Automate publishing release screenshots to the pr-screenshots branch.

Used by the trusted app-history.yml workflow:
- Validates the captured artifact directory as untrusted data using validate_artifact.py
- Commits the validated PNGs to branch pr-screenshots under releases/<key>/
- Verifies key against allowlist (^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$|^[0-9a-f]{8}$)
- Pushes to pr-screenshots with jittered retry backoff
"""

from __future__ import annotations

import argparse
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ui.validate_artifact import validate_artifact_dir  # noqa: E402

BRANCH_NAME = "pr-screenshots"
TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
RELEASE_KEY_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$|^[0-9a-f]{8}$")


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


def parse_semver_tag(tag: str) -> tuple[int, ...]:
    """Parse vMAJOR.MINOR.PATCH into a tuple for sorting."""
    m = TAG_RE.match(tag)
    if m:
        return tuple(int(x) for x in m.groups())
    return (999, 999, 999)


def resolve_release_key(repo_root: Path, override_key: str | None = None) -> tuple[str, str]:
    """Resolve release key (tag or sha8) and full commit sha.

    Returns (key, full_sha).
    """
    if override_key:
        if not RELEASE_KEY_RE.match(override_key):
            raise ValueError(
                f"Invalid release key override '{override_key}': "
                "must match semver tag or 8-char SHA"
            )
        sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root, check=False) or "00000000"
        return override_key, sha

    full_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root, check=False) or "00000000"

    # Check if HEAD has matching semver tags (v*), ignoring any prod/ tags
    tag_res = subprocess.run(
        ["git", "tag", "--points-at", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if tag_res.returncode == 0:
        matching_tags = [
            t.strip()
            for t in tag_res.stdout.splitlines()
            if TAG_RE.match(t.strip())
        ]
        if matching_tags:
            matching_tags.sort(key=parse_semver_tag)
            return matching_tags[-1], full_sha

    short_sha = full_sha[:8]
    if not re.match(r"^[0-9a-f]{8}$", short_sha):
        raise ValueError(f"Invalid commit SHA resolved: '{short_sha}'")
    return short_sha, full_sha


def publish_to_pr_screenshots(
    artifacts_dir: Path,
    key: str,
    repo: str,
    push: bool = False,
) -> None:
    """Store release screenshots on pr-screenshots branch under releases/<key>/."""
    work_dir = Path(tempfile.mkdtemp(dir=os.environ.get("RUNNER_TEMP")))

    try:
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
            msg = f"proof(history): UI screenshots for release {key}"
            run_cmd(["git", "commit", "-m", msg], cwd=work_dir)
            print(f"Committed screenshots for {key} to {BRANCH_NAME}")
            if push:
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
                            if BRANCH_NAME in remote_branches:
                                raise RuntimeError(
                                    f"git pull --rebase failed: {pull_res.stderr.strip()}"
                                )
                        run_cmd(["git", "push", "origin", BRANCH_NAME], cwd=work_dir)
                        print(f"Pushed {BRANCH_NAME} to origin")
                        break
                    except Exception as exc:
                        run_cmd(["git", "rebase", "--abort"], cwd=work_dir, check=False)
                        if attempt == 2:
                            raise RuntimeError(
                                f"Failed to push to {BRANCH_NAME} after 3 attempts: {exc}"
                            ) from exc
                        backoff = (2**attempt) + random.uniform(0.1, 0.5)
                        time.sleep(backoff)
        else:
            print(f"No changes in screenshots for release {key}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


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
        "--push", action="store_true", help="Push changes to pr-screenshots"
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
