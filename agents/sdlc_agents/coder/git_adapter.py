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
                 cancel: threading.Event | None = None, askpass_dir: Path | None = None):
        self._author = author
        self._askpass_parent = str(askpass_dir) if askpass_dir else None   # must allow exec: not a noexec /tmp
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
            target = scope.contained_path(self.workdir, rel)   # no link in any existing component
            if target is None:
                raise GitError(f"unsafe path {rel!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if scope.contained_path(self.workdir, rel) != target:
                raise GitError(f"unsafe path {rel!r}")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)

    def changed_paths(self) -> list[str]:
        out = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all")
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
                target = scope.contained_path(self.workdir, path)
                if target is not None and target.is_dir():
                    shutil.rmtree(target)   # a nested repository staged as a gitlink
                elif target is not None:
                    target.unlink(missing_ok=True)
                elif os.path.islink(self.workdir / path):
                    os.unlink(self.workdir / path)   # the link itself, never what it points to

    def commit_all(self, message: str) -> str:
        self._stage_all()
        if not self._git("diff", "--cached", "--ignore-submodules=dirty", "--name-only").strip():
            raise GitError("nothing to commit")
        self._git("commit", "--quiet", "--no-verify", "-m", message)
        return self.head_sha()

    def push(self, branch: str, *, sha: str | None = None, force: bool = False) -> None:
        """Push `sha` (default HEAD). With `sha`, HEAD must still be exactly that commit, so nothing that ran
        after the last scope check can change what leaves the sandbox."""
        if sha is not None and self.head_sha() != sha:
            raise GitError(f"HEAD moved since {sha[:12]} was verified; refusing to push")
        source = sha or "HEAD"
        self._git("push", "--quiet", *(["--force-with-lease"] if force else []), "origin",
                  f"{source}:refs/heads/{branch}")

    def head_sha(self) -> str:
        return self._git("rev-parse", "HEAD").strip()

    def run(self, cmd: list[str] | str, *, timeout_s: int) -> CommandResult:
        """Run a non-git command in the checkout without the token in its environment."""
        return shell.run(cmd, cwd=self.workdir, timeout_s=timeout_s, cancel=self._cancel)

    # -- extras the coder runner needs -----------------------------------------------------

    def remote_has_branch(self, name: str) -> bool:
        return bool(self._git("ls-remote", "--heads", "origin", f"refs/heads/{name}").strip())

    def commits_since(self, base: str) -> list[tuple[str, str]]:
        out = self._git("log", "--reverse", "--topo-order", "--format=%H%x1f%s", f"origin/{base}..HEAD")
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
        self._stage_all()
        return [p for p in self._git("diff", "--cached", "--no-renames", "--ignore-submodules=dirty", "-z",
                                      "--name-only", sha).split("\0") if p]

    def _stage_all(self) -> None:
        """`git add --all`, except index entries that are gitlinks: re-adding one makes git ask the nested
        repository for its state, which runs that repository's own config (a clean filter) as root."""
        gitlinks = [path for mode, path in self._index_modes() if mode == "160000"]
        excludes = [f":(exclude,literal){path}" for path in gitlinks]
        self._git("add", "--all", "--", ".", *excludes)

    def _index_modes(self, *paths: str) -> list[tuple[str, str]]:
        entries = []
        for entry in self._git("ls-files", "-s", "-z", "--", *paths).split("\0"):
            meta, _, path = entry.partition("\t")
            if path:
                entries.append((meta.split(" ")[0], path))
        return entries

    def special_paths_since(self, sha: str) -> list[str]:
        """Changed paths staged as gitlinks (160000) or symlinks (120000): never allowed from an engine.

        Modes come from the index (`ls-files -s`), never from a diff: a diff against a gitlink asks the
        nested repository for its state, which runs that repository's own config (filters) as root.
        """
        changed = self.changed_since(sha)
        if not changed:
            return []
        return [path for mode, path in self._index_modes(*changed) if mode in ("160000", "120000")]

    def rev_parse(self, ref: str) -> str:
        return self._git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()

    def merge_origin(self, base: str) -> list[str]:
        """Merge origin/<base> into HEAD as a real merge commit (never a fast-forward, rebase or force).
        Returns the conflicted paths: [] when the merge went through (and is committed), else the tree holds
        the half-done merge with conflict markers for the caller to commit and resolve."""
        try:
            self._git("merge", "--quiet", "--no-ff", "--no-edit", f"origin/{base}")
            return []
        except GitError:
            unmerged = sorted({p for p in self._git("diff", "--name-only", "--diff-filter=U", "-z").split("\0") if p})
            if not unmerged:
                raise
            return unmerged

    def commit_merge(self, parents: tuple[str, ...], message: str) -> str:
        """One commit holding the working tree and exactly these parents; HEAD (and the index) move onto it."""
        self._stage_all()
        tree = self._git("write-tree").strip()
        args = [arg for parent in parents for arg in ("-p", parent)]
        sha = self._git("commit-tree", tree, *args, "-m", message).strip()
        self._git("reset", "--quiet", "--soft", sha)
        return sha

    def diff_paths(self, old: str, new: str) -> list[str]:
        out = self._git("diff", "--no-renames", "--ignore-submodules=dirty", "-z", "--name-only", old, new)
        return [p for p in out.split("\0") if p]

    def special_paths_between(self, old: str, new: str) -> list[str]:
        return _special(self._git("diff", "--no-renames", "--raw", "-z", old, new))

    def special_paths_in_commit(self, sha: str) -> list[str]:
        return _special(self._git("diff-tree", "--no-commit-id", "--root", "-r", "--raw", "-z", sha))

    def clean_ignored(self, subdir: str) -> None:
        """Delete gitignored files (node_modules, caches) so nothing an engine hid there survives."""
        self._git("clean", "-ffdqX", "--", subdir)

    # -- internals -------------------------------------------------------------------------

    def _digest_config(self) -> str:
        return hashlib.sha256((self.workdir / ".git" / "config").read_bytes()).hexdigest()

    def _git_env(self) -> dict[str, str]:
        # Nothing in the working tree may make root's git run a command: no hooks, no fsmonitor, no
        # attributes file, no recursion into nested repositories (whose own config could define filters).
        config = [("commit.gpgsign", "false"), ("credential.helper", ""), ("core.hooksPath", os.devnull),
                  ("core.fsmonitor", "false"), ("core.attributesFile", os.devnull),
                  ("diff.ignoreSubmodules", "all"), ("submodule.recurse", "false"),
                  ("status.submoduleSummary", "false")]
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != TOKEN_VAR}
        env.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
            "GIT_ATTR_NOSYSTEM": "1",
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
            # 0700, owned by this (root) process
            askpass_dir = tempfile.mkdtemp(prefix="sdlc-askpass-", dir=self._askpass_parent)
            script = os.path.join(askpass_dir, "askpass")
            fd = os.open(script, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
            with os.fdopen(fd, "w") as fh:
                fh.write(ASKPASS_SCRIPT)
            env.update({"GIT_ASKPASS": script, TOKEN_VAR: self._token})
        # stdout only: porcelain parsing must not see stderr warnings.
        try:
            code, out, err = shell.capture(["git", *args], cwd=cwd or self.workdir, env=env, timeout_s=GIT_TIMEOUT_S)
        finally:
            if askpass_dir is not None:
                shutil.rmtree(askpass_dir, ignore_errors=True)
        if code == shell.TIMEOUT_RC:
            raise GitError(f"git {args[0]} timed out after {GIT_TIMEOUT_S}s")
        if code != 0:
            detail = (err + out).strip()[-2000:]
            raise GitError(f"git {args[0]} failed ({code}): {detail}")
        return out


def _special(raw: str) -> list[str]:
    """Paths whose new mode in `--raw -z` output is a gitlink or a symlink."""
    fields = raw.split("\0")
    found: list[str] = []
    i = 0
    while i + 1 < len(fields):
        meta, path = fields[i], fields[i + 1]
        i += 2
        parts = meta.lstrip(":").split()
        if len(parts) >= 2 and parts[1] in ("160000", "120000"):
            found.append(path)
    return found
