"""
GitPort over the git CLI.

The PAT reaches git only through GIT_ASKPASS on the network commands (clone, fetch, ls-remote,
push): a token-free script in a fresh root-only directory (0700), deleted right after the call,
reads the token from an environment variable set on that one git process. It is never in argv,
the remote URL, .git/config, local git commands or the environment of test and engine commands.
Engines can write .git/config, so network commands first check that it is byte-identical to the
clone's, and fsmonitor and hooks are forced off on every call. Host and system git config are
ignored so a developer's credential helper or signing setup cannot leak in or change behaviour.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from sdlc_agents.coder import scope, shell
from sdlc_agents.ports import OWNER, CommandResult, GitError

NEUTRAL_AUTHOR = ("foundry-autonomous-sdlc", "noreply@users.noreply.github.com")
GIT_TIMEOUT_S = 600
TOKEN_VAR = "SDLC_GIT_TOKEN"  # noqa: S105  the variable name, not a value
ASKPASS_SCRIPT = f"""#!/bin/sh
case "$1" in
  Username*) printf '%s\\n' x-access-token ;;
  *) printf '%s\\n' "${TOKEN_VAR}" ;;
esac
"""
_NETWORK = frozenset({"clone", "fetch", "ls-remote", "push"})


def resolve_author(owner_user_id: int | None) -> tuple[str, str]:
    """The owner's GitHub noreply address when the numeric user id is known, else a neutral one."""
    if owner_user_id is None:
        return NEUTRAL_AUTHOR
    return NEUTRAL_AUTHOR[0], f"{owner_user_id}+{OWNER}@users.noreply.github.com"


class SubprocessGit:
    def __init__(self, *, author: tuple[str, str], remote_base: str = "https://github.com/",
                 cancel: threading.Event | None = None):
        self._author = author
        self._remote_base = remote_base
        self._cancel = cancel
        self._token = ""
        self._config_digest = ""
        self.workdir = Path(".")

    # -- GitPort ---------------------------------------------------------------------------

    def clone(self, repo: str, dest: str, *, token: str) -> None:
        self._token = token
        self.workdir = Path(dest)
        self.workdir.parent.mkdir(parents=True, exist_ok=True)
        self._git("clone", "--quiet", f"{self._remote_base}{repo}.git", str(self.workdir), cwd=self.workdir.parent)
        self._config_digest = self._digest_config()

    def checkout_new_branch(self, name: str, *, base: str) -> None:
        self._git("checkout", "--quiet", "--no-track", "-B", name, f"origin/{base}")

    def checkout_existing_branch(self, name: str) -> None:
        self._git("fetch", "--quiet", "origin", f"+refs/heads/{name}:refs/remotes/origin/{name}")
        self._git("checkout", "--quiet", "--no-track", "-B", name, f"origin/{name}")

    def write_files(self, files: dict[str, str]) -> None:
        for rel, content in files.items():
            if not scope.is_safe_relative(rel):
                raise GitError(f"unsafe path {rel!r}")
            target = self.workdir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    def changed_paths(self) -> list[str]:
        out = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all")
        entries = out.split("\0")
        paths: list[str] = []
        i = 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            paths.append(entry[3:])
            if entry[0] in "RC":   # rename/copy: the next entry is the source path
                paths.append(entries[i])
                i += 1
        return paths

    def revert_paths(self, paths: list[str]) -> None:
        tracked = set(self._git("ls-files", "-z", "--", *paths).split("\0")) if paths else set()
        head = set(self._git("ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *paths).split("\0")) \
            if paths else set()
        for path in paths:
            if path in head:
                self._git("restore", "--source=HEAD", "--staged", "--worktree", "--", path)
            else:
                if path in tracked:
                    self._git("rm", "--cached", "--quiet", "--", path)
                (self.workdir / path).unlink(missing_ok=True)

    def commit_all(self, message: str) -> str:
        self._git("add", "--all")
        if not self._git("diff", "--cached", "--name-only").strip():
            raise GitError("nothing to commit")
        self._git("commit", "--quiet", "--no-verify", "-m", message)
        return self.head_sha()

    def push(self, branch: str, *, force: bool = False) -> None:
        self._git("push", "--quiet", *(["--force-with-lease"] if force else []), "origin", f"HEAD:refs/heads/{branch}")

    def head_sha(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def run(self, cmd: list[str] | str, *, timeout_s: int) -> CommandResult:
        """Run a non-git command in the checkout without the token in its environment."""
        return shell.run(cmd, cwd=self.workdir, timeout_s=timeout_s, cancel=self._cancel)

    # -- extras the coder runner needs -----------------------------------------------------

    def remote_has_branch(self, name: str) -> bool:
        return bool(self._git("ls-remote", "--heads", "origin", f"refs/heads/{name}").strip())

    def commits_since(self, base: str) -> list[tuple[str, str]]:
        out = self._git("log", "--reverse", "--format=%H%x1f%s", f"origin/{base}..HEAD")
        return [tuple(line.split("\x1f", 1)) for line in out.splitlines() if line]  # type: ignore[misc]

    def files_in_commit(self, sha: str) -> list[str]:
        out = self._git("diff-tree", "--no-commit-id", "--root", "-r", "-z", "--name-only", sha)
        return [p for p in out.split("\0") if p]

    def metadata_digest(self) -> str:
        """Fingerprint of .git/config and .git/hooks, the parts of .git that can run code or redirect git."""
        digest = hashlib.sha256((self.workdir / ".git" / "config").read_bytes())
        hooks = self.workdir / ".git" / "hooks"
        for path in sorted(hooks.rglob("*")) if hooks.is_dir() else []:
            digest.update(f"{path.relative_to(hooks)}:{path.lstat().st_mode}".encode())
            if path.is_file() and not path.is_symlink():
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def tracked_files(self) -> list[str]:
        return [p for p in self._git("ls-files", "-z").split("\0") if p]

    def current_branch(self) -> str:
        return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()

    def reset_soft(self, sha: str) -> None:
        self._git("reset", "--quiet", "--soft", sha)

    def changed_since(self, sha: str) -> list[str]:
        """Every path that differs from `sha`: committed, staged, unstaged or new (ignored files excluded)."""
        self._git("add", "--all")
        return [p for p in self._git("diff", "--cached", "--no-renames", "-z", "--name-only", sha).split("\0") if p]

    def clean_ignored(self, subdir: str) -> None:
        """Delete gitignored files (node_modules, caches) so nothing an engine hid there survives."""
        self._git("clean", "-ffdqX", "--", subdir)

    # -- internals -------------------------------------------------------------------------

    def _digest_config(self) -> str:
        return hashlib.sha256((self.workdir / ".git" / "config").read_bytes()).hexdigest()

    def _git_env(self) -> dict[str, str]:
        config = [("commit.gpgsign", "false"), ("credential.helper", ""), ("core.hooksPath", os.devnull),
                  ("core.fsmonitor", "false")]
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != TOKEN_VAR}
        env.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": self._author[0], "GIT_AUTHOR_EMAIL": self._author[1],
            "GIT_COMMITTER_NAME": self._author[0], "GIT_COMMITTER_EMAIL": self._author[1],
            "GIT_CONFIG_COUNT": str(len(config)),
        })
        for i, (key, value) in enumerate(config):
            env[f"GIT_CONFIG_KEY_{i}"] = key
            env[f"GIT_CONFIG_VALUE_{i}"] = value
        return env

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        network = args[0] in _NETWORK
        if network and self._config_digest and self._digest_config() != self._config_digest:
            raise GitError("the checkout's .git/config changed since clone; refusing to send credentials")
        env = self._git_env()
        askpass_dir = None
        if network and self._token:
            askpass_dir = tempfile.mkdtemp(prefix="sdlc-askpass-")   # 0700, owned by this (root) process
            script = os.path.join(askpass_dir, "askpass")
            fd = os.open(script, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
            with os.fdopen(fd, "w") as fh:
                fh.write(ASKPASS_SCRIPT)
            env.update({"GIT_ASKPASS": script, TOKEN_VAR: self._token})
        # stdout only: porcelain parsing must not see stderr warnings.
        try:
            proc = subprocess.run(["git", *args], cwd=cwd or self.workdir, env=env,  # noqa: S603, S607
                                  capture_output=True, text=True, timeout=GIT_TIMEOUT_S, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise GitError(f"git {args[0]} timed out after {GIT_TIMEOUT_S}s") from None
        finally:
            if askpass_dir is not None:
                shutil.rmtree(askpass_dir, ignore_errors=True)
        if proc.returncode != 0:
            detail = (proc.stderr + proc.stdout).strip()[-2000:]
            raise GitError(f"git {args[0]} failed ({proc.returncode}): {detail}")
        return proc.stdout
