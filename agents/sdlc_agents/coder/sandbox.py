"""
Isolation for the agy engine inside the hosted sandbox (decision D10).

The coder process runs as root and holds the PAT and the managed identity. When it can, it runs
agy as an unprivileged user that owns only the working tree: not .git, not node_modules, not the
coder's $HOME. When the user cannot be created, agy runs as the coder's own user with a scrubbed
environment, and the job log records that.
"""

from __future__ import annotations

import contextlib
import os
import pwd
import shutil
import signal
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sdlc_agents.coder import shell
from sdlc_agents.ports import CommandResult

AGY_USER = "agyuser"
_ENV_PASSTHROUGH = ("LANG", "LC_ALL", "TERM", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
                    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
PRIVILEGED_WORK_ROOT = Path("/srv/sdlc-work")
AGY_DIR = Path("/opt/agy")    # root-owned, like /opt/node: the engine user runs it, cannot change it
ENGINE_SKIP_DIRS = (".git",)


@dataclass(frozen=True)
class RunAs:
    name: str
    uid: int
    gid: int
    home: Path


def ensure_agy_user(*, run: Callable[..., CommandResult] = shell.run,
                    getpwnam: Callable[[str], pwd.struct_passwd] = pwd.getpwnam,
                    euid: Callable[[], int] = os.geteuid) -> RunAs | None:
    """The unprivileged engine user, created on first use. None when not root or creation fails."""
    if euid() != 0:
        return None
    try:
        entry = getpwnam(AGY_USER)
    except KeyError:
        result = run(["useradd", "-m", "-s", "/bin/bash", AGY_USER], cwd="/", timeout_s=60)
        if result.returncode != 0:
            return None
        try:
            entry = getpwnam(AGY_USER)
        except KeyError:
            return None
    return RunAs(AGY_USER, entry.pw_uid, entry.pw_gid, Path(entry.pw_dir))


def user_pids(user: RunAs, *, proc_root: Path = Path("/proc")) -> list[int]:
    pids: list[int] = []
    for entry in proc_root.glob("[0-9]*") if proc_root.is_dir() else []:
        try:
            if entry.stat().st_uid == user.uid:
                pids.append(int(entry.name))
        except (OSError, ValueError):
            continue
    return pids


def reap_user(user: RunAs, *, list_pids: Callable[[RunAs], list[int]] = user_pids,
              kill: Callable[[int, int], None] = os.kill, max_rounds: int = 50) -> int:
    """SIGKILL every process of the engine user, repeating until none is left (a fork can land mid-pass).

    Called before anything root does to the user-owned tree (scans, hand-over, reads, pushes), so the
    tree cannot change under root. Returns how many processes survived (0 on success); never touches root.
    """
    if user.uid == 0:
        return 0
    for _ in range(max_rounds):
        pids = list_pids(user)
        if not pids:
            return 0
        for pid in pids:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                kill(pid, signal.SIGKILL)
    return len(list_pids(user))


def give_tree(root: Path, user: RunAs, *, chown: Callable[[str, int, int], None] = os.lchown) -> None:
    """Hand the working tree to the engine user. .git and the top directory stay with root (so the user
    cannot swap .git out); links are not followed."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ENGINE_SKIP_DIRS]
        for name in (*dirnames, *filenames):
            chown(os.path.join(dirpath, name), user.uid, user.gid)


class UnsafePathError(RuntimeError):
    pass


def install_agy_binary(source: Path, dest_root: Path = AGY_DIR) -> Path:
    """Install agy in a root-owned directory the engine user can execute from but not write to.

    Never into the user's home: root writing there could be steered by links the user planted.
    """
    dest = dest_root / "bin" / "agy"
    if dest.is_file() and not dest.is_symlink() and dest.stat().st_size == source.stat().st_size:
        return dest
    dest.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".agy-")
    with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
        shutil.copyfileobj(src, out)
        os.fchmod(out.fileno(), 0o755)
    os.replace(tmp, dest)
    return dest


def write_private_file(base: Path, rel: str, data: bytes, *, owner: tuple[int, int]) -> Path:
    """Write `base/rel` (0600, dirs 0700, all owned by `owner`) without following any link.

    Every directory is opened relative to its verified parent with O_NOFOLLOW, and an existing file
    or link at the target is unlinked and recreated with O_EXCL, so a link planted by the engine user
    can neither redirect the write nor have root change permissions on a file it points to.
    """
    parts = rel.split("/")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(base, flags)
    except OSError as exc:
        raise UnsafePathError(f"{base}: {exc}") from None
    try:
        for part in parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, 0o700, dir_fd=fd)
            try:
                child = os.open(part, flags, dir_fd=fd)
            except OSError as exc:
                raise UnsafePathError(f"{rel}: {part} is not a plain directory ({exc})") from None
            os.close(fd)
            fd = child
            os.fchown(fd, *owner)
            os.fchmod(fd, 0o700)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(parts[-1], dir_fd=fd)
        out = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            os.fchmod(out, 0o600)
            os.fchown(out, *owner)
            os.write(out, data)
        finally:
            os.close(out)
    finally:
        os.close(fd)
    return base / rel


def safe_read(path: Path, *, max_bytes: int) -> bytes:
    """Read a file in a tree another user controls: regular files only, links refused, never blocking."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise UnsafePathError(f"{path}: {exc}") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafePathError(f"{path} is not a regular file")
        if info.st_size > max_bytes:
            raise UnsafePathError(f"{path} is larger than {max_bytes} bytes")
        with os.fdopen(os.dup(fd), "rb") as fh:
            return fh.read(max_bytes)
    finally:
        os.close(fd)


def user_env(user: RunAs, node_bin: Path) -> dict[str, str]:
    """The complete environment for install, tests and agy as the engine user: built from nothing."""
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update({"HOME": str(user.home), "CI": "1", "NO_COLOR": "1",
                "PATH": f"{node_bin}:{AGY_DIR}/bin:/usr/local/bin:/usr/bin:/bin"})
    return env


def symlinks(root: Path) -> dict[str, str]:
    """Every symlink under `root` and its target; used to spot links untrusted code created.

    .git is checked by digest instead, and node_modules is skipped: npm creates links there, git
    ignores it, `git clean -X` removes it without following links, and no root write goes there.
    """
    found: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        for name in (*dirnames, *filenames):
            path = os.path.join(dirpath, name)
            if stat.S_ISLNK(os.lstat(path).st_mode):
                found[os.path.relpath(path, root)] = os.readlink(path)
    return found
