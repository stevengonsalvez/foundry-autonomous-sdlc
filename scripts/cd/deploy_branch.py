"""The git side of CD: change the `deploy` branch and push it.

    python -m scripts.cd.deploy_branch stage    --artifact DIR --sha S --run-id N --run-url U ...
    python -m scripts.cd.deploy_branch promote  --sha S --run-id N --run-attempt A --run-url U
    python -m scripts.cd.deploy_branch rollback --sha S --run-id N --run-attempt A --run-url U \
        --reason JOB --promote-result failure

Each command clones the branch (creating it as an orphan when absent), applies one transition to
the tree and to deploy.json, commits as github-actions[bot] and pushes. A push that loses a race
starts over from a fresh clone, so two writers can never produce a merge conflict in deploy.json.
The remote comes from `--remote`, else from GITHUB_SERVER_URL and GITHUB_REPOSITORY; credentials
come from the git credential helper that `gh auth setup-git` installs, never from the URL.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import deploy_state as ds
from .ghcli import fail, optional_int, set_output, utc_now

BRANCH = "deploy"
STATE_FILE = "deploy.json"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
PUSH_ATTEMPTS = 6

Mutate = Callable[[Path, ds.State], ds.State]


class GitError(RuntimeError):
    pass


def git(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and done.returncode:
        raise GitError(f"git {' '.join(args[:3])} failed: {done.stderr.strip()[:400]}")
    return done


def remote_has_branch(remote: str) -> bool:
    done = git(["ls-remote", "--exit-code", "--heads", remote, f"refs/heads/{BRANCH}"], check=False)
    if done.returncode == 0:
        return True
    if done.returncode == 2:
        return False
    raise GitError(f"git ls-remote failed: {done.stderr.strip()[:400]}")


def checkout(remote: str, dest: Path) -> None:
    """A working copy of the deploy branch, or an empty orphan one when it does not exist."""
    if remote_has_branch(remote):
        git(
            [
                "clone",
                "--quiet",
                "--depth",
                "1",
                "--branch",
                BRANCH,
                "--single-branch",
                remote,
                str(dest),
            ]
        )
    else:
        git(["init", "--quiet", "--initial-branch", BRANCH, str(dest)])
        git(["remote", "add", "origin", remote], cwd=dest)
    git(["config", "user.name", BOT_NAME], cwd=dest)
    git(["config", "user.email", BOT_EMAIL], cwd=dest)
    git(["config", "commit.gpgsign", "false"], cwd=dest)


def commit_and_push(dest: Path, message: str) -> None:
    git(["add", "--all"], cwd=dest)
    if git(["diff", "--cached", "--quiet"], cwd=dest, check=False).returncode == 0:
        return
    git(["commit", "--quiet", "-m", message], cwd=dest)
    git(["push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"], cwd=dest)


def update(
    remote: str,
    mutate: Mutate,
    message: str,
    *,
    attempts: int = PUSH_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> ds.State:
    """Apply `mutate` to a fresh clone and push; a refused push starts over from a new clone."""
    last: GitError | None = None
    for attempt in range(attempts):
        with tempfile.TemporaryDirectory(prefix="deploy-wt-") as tmp:
            dest = Path(tmp) / "wt"
            checkout(remote, dest)
            state_path = dest / STATE_FILE
            state = ds.parse(state_path.read_text("utf-8") if state_path.exists() else "")
            new_state = mutate(dest, state)
            state_path.write_text(ds.dumps(new_state), encoding="utf-8")
            try:
                commit_and_push(dest, message)
            except GitError as err:
                last = err
            else:
                return new_state
        sleep(min(2**attempt, 10) + random.random())
    raise GitError(f"could not push {BRANCH} after {attempts} attempts: {last}")


# ---- tree operations -------------------------------------------------------------------------


def replace_tree(dest: Path, source: Path | None) -> None:
    """Make `dest` an exact copy of `source`, or remove it when there is no source."""
    if dest.exists():
        shutil.rmtree(dest)
    if source is not None:
        shutil.copytree(source, dest, symlinks=True)


_TEXT_ASSETS = {".html", ".js", ".mjs", ".css"}


def reachable_assets(tree: Path) -> set[Path]:
    """Paths (relative to assets/) of the files this build's own entry points lead to.

    Starts at index.html and follows every asset name that appears in a page, script or style it
    reaches. Files carried over from an older build are not named by this build, so they drop out.
    """
    assets = tree / "assets"
    index = tree / "index.html"
    if not assets.is_dir() or not index.is_file():
        return set()
    files = {p.relative_to(assets): p for p in assets.rglob("*") if p.is_file()}
    seen: set[Path] = set()
    queue = [index]
    while queue:
        text = queue.pop().read_text("utf-8", errors="ignore")
        for rel, path in files.items():
            if rel not in seen and rel.name in text:
                seen.add(rel)
                if rel.suffix in _TEXT_ASSETS:
                    queue.append(path)
    return seen


def replace_app_tree(dest: Path, source: Path | None) -> None:
    """Replace a served app tree, keeping the previous build's assets the new one lacks.

    Browsers holding the old index.html still ask for its hashed scripts for a while after a
    promote or rollback. One generation back is kept; what the old tree itself carried over from
    before that is dropped, so the folder cannot grow without bound.
    """
    carried: dict[Path, bytes] = {}
    if source is not None and dest.exists():
        carried = {rel: (dest / "assets" / rel).read_bytes() for rel in reachable_assets(dest)}
    replace_tree(dest, source)
    for rel, body in carried.items():
        target = dest / "assets" / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)


def reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ds.DeployStateError(f"artifact contains a symlink: {path.relative_to(root)}")


def read_build_json(directory: Path) -> dict[str, Any]:
    try:
        info = json.loads((directory / "build.json").read_text("utf-8"))
    except (OSError, ValueError) as err:
        raise ds.DeployStateError(f"{directory} has no readable build.json: {err}") from err
    if not isinstance(info, dict):
        raise ds.DeployStateError(f"{directory}/build.json is not an object")
    return info


# ---- transitions with their tree changes ------------------------------------------------------


def do_stage(
    root: Path, state: ds.State, *, artifact: Path, release_meta: dict[str, Any], now: str
) -> ds.State:
    if not (artifact / "index.html").is_file():
        raise ds.DeployStateError(f"{artifact} has no index.html")
    reject_symlinks(artifact)
    info = read_build_json(artifact)
    if info.get("sha") != release_meta["sha"]:
        raise ds.DeployStateError(
            f"artifact is build {info.get('sha')}, expected {release_meta['sha']}"
        )
    release = ds.Release(
        sha=info["sha"],
        short=info["short"],
        version=info["version"],
        built_at=info["built_at"],
        run_id=release_meta["run_id"],
        run_url=release_meta["run_url"],
        pr=release_meta["pr"],
        issue=release_meta["issue"],
        includes=tuple(release_meta["includes"]),
    )
    replace_tree(root / "staging", artifact)
    return ds.stage(state, release, now)


def do_promote(
    root: Path,
    state: ds.State,
    *,
    sha: str,
    run_id: int,
    run_attempt: int,
    run_url: str,
    now: str,
) -> ds.State:
    staging = state["staging"]
    if staging is None or staging["sha"] != sha:
        held = staging["sha"] if staging else "nothing"
        raise ds.DeployStateError(f"cannot promote {sha}: staging holds {held}")
    if read_build_json(root / "staging").get("sha") != sha:
        raise ds.DeployStateError("staging/ does not hold the build deploy.json says it does")
    if ds.is_prod(state, sha):
        tag = state["prod"]["tag"] or ""
    else:
        tag = ds.tag_name(now, staging["short"])
        prod = root / "prod"
        replace_tree(root / "prod-prev", prod if prod.exists() else None)
        replace_app_tree(prod, root / "staging")
    return ds.promote(
        state, sha=sha, run_id=run_id, run_attempt=run_attempt, run_url=run_url, now=now, tag=tag
    )


def do_rollback(
    root: Path,
    state: ds.State,
    *,
    subject: ds.Subject,
    run_id: int,
    run_attempt: int,
    promote_failed: bool,
    run_url: str,
    reason: str,
    now: str,
) -> ds.State:
    overwritten = ds.prod_overwritten_by(state, subject.sha, run_id, run_attempt, promote_failed)
    new = ds.rollback(
        state,
        subject=subject,
        run_id=run_id,
        run_attempt=run_attempt,
        promote_failed=promote_failed,
        run_url=run_url,
        reason=reason,
        now=now,
    )
    if overwritten:
        previous = root / "prod-prev"
        if (new["prod"] is None) == previous.exists():
            raise ds.DeployStateError("prod-prev/ and previous_prod in deploy.json disagree")
        replace_app_tree(root / "prod", previous if previous.exists() else None)
        replace_tree(previous, None)
    prod = root / "prod"
    if (new["prod"] is None) == prod.exists():
        raise ds.DeployStateError("prod/ and prod in deploy.json disagree")
    replace_tree(root / "staging", prod if prod.exists() else None)
    return new


# ---- command line -----------------------------------------------------------------------------


def default_remote() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ['GITHUB_REPOSITORY']}.git"


def load_includes(env_name: str) -> list[ds.Include]:
    raw = json.loads(os.environ.get(env_name) or "[]")
    return [ds.Include(pr=i["pr"], issue=i["issue"], sha=i["sha"]) for i in raw]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("stage", "promote", "rollback"))
    parser.add_argument("--remote")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, default=1)
    parser.add_argument(
        "--promote-result",
        default="",
        help="result of the promote job of this attempt; prod is rolled back only after `failure`",
    )
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--pr", type=optional_int, default=None)
    parser.add_argument("--issue", type=optional_int, default=None)
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--reason", default="")
    parser.add_argument(
        "--includes-env",
        default="CD_INCLUDES",
        help="environment variable holding the includes JSON",
    )
    args = parser.parse_args(argv)
    remote = args.remote or default_remote()
    now = utc_now()
    subject = ds.Subject(args.sha, args.version or None, args.pr, args.issue)
    outcome: dict[str, Any] = {}

    def mutate(root: Path, state: ds.State) -> ds.State:
        if args.command == "stage":
            if args.artifact is None:
                raise ds.DeployStateError("--artifact is required")
            meta = {
                "sha": args.sha,
                "run_id": args.run_id,
                "run_url": args.run_url,
                "pr": args.pr,
                "issue": args.issue,
                "includes": load_includes(args.includes_env),
            }
            return do_stage(root, state, artifact=args.artifact, release_meta=meta, now=now)
        if args.command == "promote":
            new = do_promote(
                root,
                state,
                sha=args.sha,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                run_url=args.run_url,
                now=now,
            )
            outcome.update(
                tag=new["prod"]["tag"],
                version=new["prod"]["version"],
                includes=json.dumps(new["prod"]["includes"], separators=(",", ":")),
            )
            return new
        if args.command == "rollback":
            promote_failed = args.promote_result == "failure"
            overwritten = ds.prod_overwritten_by(
                state, args.sha, args.run_id, args.run_attempt, promote_failed
            )
            new = do_rollback(
                root,
                state,
                subject=subject,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                promote_failed=promote_failed,
                run_url=args.run_url,
                reason=args.reason,
                now=now,
            )
            prod = new["prod"]
            outcome.update(
                prod_overwritten=str(overwritten).lower(),
                restored_sha=prod["sha"] if prod else "",
                restored_version=prod["version"] if prod else "",
            )
            return new
        raise AssertionError(args.command)

    short = args.sha[:7]
    messages = {
        "stage": f"cd: stage {short} ({args.version or 'build'})",
        "promote": f"cd: promote {short} to prod",
        "rollback": f"cd: roll back {short} ({args.reason})",
    }
    try:
        update(remote, mutate, messages[args.command])
    except (GitError, ds.DeployStateError) as err:
        return fail(str(err))
    for key, value in outcome.items():
        set_output(key, value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
