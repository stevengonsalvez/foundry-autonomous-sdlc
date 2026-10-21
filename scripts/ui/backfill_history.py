"""Backfill release screenshots across historical git tags (every v* tag by default).

For each tag:
1. Checks out / archives the tag into an isolated temporary workspace.
2. Builds app/web with npm ci and npm run build.
3. If building fails, records 'not reproducible: <reason>' in manifest.
4. If building succeeds, captures every state in scripts/ui/states.json that the tag's app
   has (states it lacks are skipped, not failed) at desktop (1280) and mobile (390) using the
   CURRENT capture.mjs, so every release is rendered by the same code.
5. Validates artifacts as untrusted data using validate_artifact.py.
6. Records which states changed versus the previous release in each manifest (`changes`).
7. Stores artifacts on the pr-screenshots branch under releases/<tag>/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ui.release_changes import annotate_release  # noqa: E402
from scripts.ui.validate_artifact import validate_artifact_dir  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent
CAPTURE_SCRIPT = SCRIPTS_DIR / "capture.mjs"
BRANCH_NAME = "pr-screenshots"
TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_semver_tag(tag: str) -> tuple[int, ...]:
    """Parse vMAJOR.MINOR.PATCH into a tuple for sorting."""
    m = TAG_RE.match(tag)
    if m:
        return tuple(int(x) for x in m.groups())
    return (999, 999, 999)


def list_version_tags(max_tag: str | None = None) -> list[str]:
    """List all git tags starting with 'v', sorted in semver order."""
    res = subprocess.run(
        ["git", "tag", "-l", "v*"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tags = [t.strip() for t in res.stdout.splitlines() if t.strip() and TAG_RE.match(t.strip())]
    tags.sort(key=parse_semver_tag)
    if max_tag:
        max_tuple = parse_semver_tag(max_tag)
        tags = [t for t in tags if parse_semver_tag(t) <= max_tuple]
    return tags


def get_tag_commit_sha(tag: str) -> str:
    """Get the commit SHA for a git tag."""
    res = subprocess.run(
        ["git", "rev-list", "-n", "1", tag],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def capture_tag(tag: str, dest_dir: Path) -> dict[str, Any]:
    """Build and capture screenshots for a single tag in an isolated temp directory."""
    commit_sha = get_tag_commit_sha(tag)
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"backfill-{tag}-") as td:
        temp_dir = Path(td)
        app_dir = temp_dir / "app"

        # Export archive of the tag to avoid dirtying local git state
        p_git = subprocess.Popen(
            ["git", "archive", tag],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        p_tar = subprocess.Popen(
            ["tar", "-x", "-C", str(temp_dir)],
            stdin=p_git.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if p_git.stdout:
            p_git.stdout.close()
        _, tar_err = p_tar.communicate()
        _, git_err = p_git.communicate()

        if p_git.returncode != 0 or p_tar.returncode != 0:
            err_msg = (git_err.decode(errors="replace") or tar_err.decode(errors="replace")).strip()
            manifest = {
                "version": 1,
                "tag": tag,
                "commit_sha": commit_sha,
                "reproducible": False,
                "reason": f"git archive failed: {err_msg}",
                "screenshots": [],
            }
            (dest_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            return manifest

        # 1. Install dependencies
        ci_res = subprocess.run(["npm", "ci"], cwd=app_dir, capture_output=True, text=True)
        if ci_res.returncode != 0:
            manifest = {
                "version": 1,
                "tag": tag,
                "commit_sha": commit_sha,
                "reproducible": False,
                "reason": f"npm ci failed: {ci_res.stderr.strip()[:300]}",
                "screenshots": [],
            }
            (dest_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            return manifest

        # 2. Build web application
        build_res = subprocess.run(
            ["npm", "run", "build", "--workspace", "@parcel/web"],
            cwd=app_dir,
            capture_output=True,
            text=True,
        )
        if build_res.returncode != 0:
            manifest = {
                "version": 1,
                "tag": tag,
                "commit_sha": commit_sha,
                "reproducible": False,
                "reason": f"build failed: {build_res.stderr.strip()[:300]}",
                "screenshots": [],
            }
            (dest_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            return manifest

        dist_dir = app_dir / "web" / "dist"
        if not dist_dir.exists() or not (dist_dir / "index.html").exists():
            manifest = {
                "version": 1,
                "tag": tag,
                "commit_sha": commit_sha,
                "reproducible": False,
                "reason": "dist/index.html not generated by build",
                "screenshots": [],
            }
            (dest_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            return manifest

        # 3. Capture screenshots using capture.mjs
        env = os.environ.copy()
        capture_cmd = [
            "node",
            str(CAPTURE_SCRIPT),
            "--dist",
            str(dist_dir),
            "--out-dir",
            str(dest_dir),
            "--head-sha",
            commit_sha,
            "--skip-build",
        ]
        cap_res = subprocess.run(
            capture_cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True
        )
        if cap_res.returncode != 0:
            manifest = {
                "version": 1,
                "tag": tag,
                "commit_sha": commit_sha,
                "reproducible": False,
                "reason": f"capture failed: {cap_res.stderr.strip()[:300]}",
                "screenshots": [],
            }
            (dest_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            return manifest

        # 4. Validate artifact
        val_res = validate_artifact_dir(dest_dir)
        if not val_res.valid:
            manifest = {
                "version": 1,
                "tag": tag,
                "commit_sha": commit_sha,
                "reproducible": False,
                "reason": f"artifact validation failed: {'; '.join(val_res.errors)}",
                "screenshots": [],
            }
            (dest_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            return manifest

        # Load and enhance manifest
        manifest_file = dest_dir / "manifest.json"
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        manifest_data["tag"] = tag
        manifest_data["reproducible"] = True
        manifest_data["commit_sha"] = commit_sha
        manifest_file.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")
        return manifest_data


def get_remote_url() -> str:
    """Get the real origin remote URL."""
    res = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    url = res.stdout.strip()
    if not url:
        repo = os.getenv("GITHUB_REPOSITORY", "stevengonsalvez/foundry-autonomous-sdlc")
        url = f"https://github.com/{repo}.git"
    return url


def overlay_release(src: Path, dst: Path) -> None:
    """Copy a captured release over its stored directory without deleting what is there.

    Files from earlier captures (for example home-desktop.png, linked from the README) stay
    until nothing references them; the new manifest decides what the history page shows.
    """
    shutil.copytree(src, dst, dirs_exist_ok=True)


def commit_to_pr_screenshots_branch(
    releases_dir: Path,
    tags: list[str],
    *,
    push: bool = False,
) -> None:
    """Commit release screenshot captures to the orphan pr-screenshots branch."""
    with tempfile.TemporaryDirectory(prefix="pr-screenshots-worktree-") as wt_dir:
        wt_path = Path(wt_dir)

        # Check if remote branch exists
        ls_res = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", BRANCH_NAME],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        has_remote = BRANCH_NAME in ls_res.stdout

        if has_remote:
            subprocess.run(
                ["git", "fetch", "origin", f"{BRANCH_NAME}:{BRANCH_NAME}"],
                cwd=REPO_ROOT,
                check=True,
            )
            subprocess.run(
                ["git", "worktree", "add", str(wt_path), BRANCH_NAME],
                cwd=REPO_ROOT,
                check=True,
            )
        else:
            # Create orphan branch in temporary directory pointing to real remote
            subprocess.run(["git", "init"], cwd=wt_path, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", get_remote_url()],
                cwd=wt_path,
                check=True,
            )
            subprocess.run(
                ["git", "checkout", "--orphan", BRANCH_NAME],
                cwd=wt_path,
                check=True,
            )

        try:
            wt_releases = wt_path / "releases"
            wt_releases.mkdir(parents=True, exist_ok=True)

            changed = False
            for tag in tags:
                src_tag_dir = releases_dir / tag
                if not src_tag_dir.exists():
                    continue
                overlay_release(src_tag_dir, wt_releases / tag)
                changed = True

            if changed:
                subprocess.run(["git", "add", "releases"], cwd=wt_path, check=True)
                diff_check = subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    cwd=wt_path,
                )
                if diff_check.returncode != 0:
                    tag_list_str = ", ".join(tags)
                    commit_msg = (
                        f"chore(history): backfill screenshots for releases ({tag_list_str})"
                    )
                    subprocess.run(
                        ["git", "commit", "-S", "-m", commit_msg],
                        cwd=wt_path,
                        check=True,
                    )
                    if push:
                        subprocess.run(
                            ["git", "push", "origin", BRANCH_NAME],
                            cwd=wt_path,
                            check=True,
                        )
                        print(f"Pushed backfilled releases to origin/{BRANCH_NAME}")
        finally:
            if has_remote:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(wt_path)],
                    cwd=REPO_ROOT,
                    check=False,
                )


def run_backfill(
    *,
    tags: list[str] | None = None,
    max_tag: str | None = None,
    output_dir: Path | None = None,
    push: bool = False,
    update_local_history: bool = True,
) -> dict[str, Any]:
    """Execute the backfill process across tags."""
    if tags is None:
        tags = list_version_tags(max_tag=max_tag)

    if not tags:
        print("No matching tags found for backfill.")
        return {}

    print(f"Starting backfill for {len(tags)} tags: {', '.join(tags)}")
    temp_releases = output_dir or Path(tempfile.mkdtemp(prefix="backfill-releases-"))

    results: dict[str, Any] = {}
    for tag in tags:
        print(f"--- Processing {tag} ---")
        dest_dir = temp_releases / tag
        manifest = capture_tag(tag, dest_dir)
        results[tag] = manifest
        if manifest.get("reproducible"):
            count = len(manifest.get("screenshots", []))
            print(f"Successfully captured {tag}: {count} screenshots.")
        else:
            print(f"Tag {tag} recorded as not reproducible: {manifest.get('reason')}")

    # Pixel-diff each release against the one before it (oldest first)
    for tag in tags:
        try:
            changes = annotate_release(temp_releases, tag)
        except Exception as exc:
            print(f"Notice: could not record changes for {tag}: {exc}")
            continue
        if changes is not None:
            counts: dict[str, int] = {}
            for st in changes["states"].values():
                counts[st["status"]] = counts.get(st["status"], 0) + 1
            print(f"{tag}: changes vs {changes['vs']}: {counts}")

    # Copy into history/screenshots/ if requested
    if update_local_history:
        history_screenshots = REPO_ROOT / "history" / "screenshots"
        history_screenshots.mkdir(parents=True, exist_ok=True)
        for tag in tags:
            src = temp_releases / tag
            dst = history_screenshots / tag
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
        print(f"Updated local history screenshots at {history_screenshots}")

    # Commit to pr-screenshots branch
    try:
        commit_to_pr_screenshots_branch(temp_releases, tags, push=push)
    except Exception as exc:
        print(f"Notice: pr-screenshots branch update: {exc}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill release screenshots across historical git tags."
    )
    parser.add_argument(
        "--tags",
        nargs="*",
        help="Explicit list of tags to process (default: every v* tag)",
    )
    parser.add_argument(
        "--max-tag",
        default=None,
        help="Maximum tag to include (default: no limit)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Output directory to store captured releases",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push commit to origin/pr-screenshots",
    )
    parser.add_argument(
        "--no-local-history",
        action="store_true",
        help="Do not copy into history/screenshots/",
    )
    args = parser.parse_args()

    run_backfill(
        tags=args.tags,
        max_tag=args.max_tag,
        output_dir=args.out_dir,
        push=args.push,
        update_local_history=not args.no_local_history,
    )


if __name__ == "__main__":
    main()
