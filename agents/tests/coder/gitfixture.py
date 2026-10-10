"""Builds a real bare 'GitHub' remote in a temp dir, isolated from the developer's git config."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sdlc_agents.ports import REPO

ISOLATED_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "owner", "GIT_AUTHOR_EMAIL": "owner@example.com",
    "GIT_COMMITTER_NAME": "owner", "GIT_COMMITTER_EMAIL": "owner@example.com",
}


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, **ISOLATED_ENV}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,  # noqa: S603, S607
                          text=True).stdout


Commits = dict[str, str] | list[tuple[str, dict[str, str]]]   # one "feat: work on" commit, or (message, files)s


def make_remote(root: Path, files: dict[str, str], branches: dict[str, Commits] | None = None) -> str:
    """Create root/<REPO>.git seeded with `files` on main. Returns the remote base URL for SubprocessGit."""
    bare = root / f"{REPO}.git"
    bare.mkdir(parents=True)
    git(bare, "init", "--bare", "-q", "-b", "main")
    seed = root / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    _write(seed, files)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "chore: seed")
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "origin", "main")
    for branch, commits in (branches or {}).items():
        git(seed, "checkout", "-q", "-b", branch, "main")
        for message, extra in commits if isinstance(commits, list) else [(f"feat: work on {branch}", commits)]:
            _write(seed, extra)
            git(seed, "add", "-A")
            git(seed, "commit", "-q", "-m", message)
        git(seed, "push", "-q", "origin", branch)
        git(seed, "checkout", "-q", "main")
    return f"{root.as_uri()}/"


def remote_log(root: Path, branch: str) -> list[str]:
    """Subjects of commits on `branch` not on main, oldest first."""
    bare = root / f"{REPO}.git"
    out = git(bare, "log", "--reverse", "--format=%s", f"main..{branch}")
    return out.splitlines()


def remote_file(root: Path, branch: str, path: str) -> str:
    return git(root / f"{REPO}.git", "show", f"{branch}:{path}")


def _write(base: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
