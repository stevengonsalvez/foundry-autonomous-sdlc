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


def ensure_shell_files(user: RunAs) -> None:
    """Empty ~/.bashrc and ~/.profile: agy reads them at start, and a missing file stalled its first command."""
    for name in (".bashrc", ".profile"):
        write_private_file(user.home, name, b"", owner=(user.uid, user.gid))


def safe_read(path: Path, *, max_bytes: int, tail: bool = False) -> bytes:
    """Read a file in a tree another user controls: regular files only, links refused, never blocking.

    A file over `max_bytes` is refused, or with `tail` only its last `max_bytes` are read (logs).
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise UnsafePathError(f"{path}: {exc}") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UnsafePathError(f"{path} is not a regular file")
        if info.st_size > max_bytes and not tail:
            raise UnsafePathError(f"{path} is larger than {max_bytes} bytes")
        with os.fdopen(os.dup(fd), "rb") as fh:
            fh.seek(max(info.st_size - max_bytes, 0))
            return fh.read(max_bytes)
    finally:
        os.close(fd)


def user_env(user: RunAs, node_bin: Path) -> dict[str, str]:
    """The complete environment for install, tests and agy as the engine user: built from nothing."""
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update({"HOME": str(user.home), "CI": "1", "NO_COLOR": "1",
                "PATH": f"{node_bin}:{AGY_DIR}/bin:/usr/local/bin:/usr/bin:/bin"})
    return env


@dataclass(frozen=True)
class Inventory:
    symlinks: dict[str, str]      # every link not inside a node_modules directory -> its target
    nested_git: list[str]         # any .git file or directory below the checkout root
    escaping: list[str]           # links anywhere whose target is absolute, outside the checkout or in .git


def inventory(root: Path, *, owner_uid: int) -> Inventory:
    """Everything in the tree that could steer root: links, nested repositories, links leaving the tree.

    Each entry is lstat'ed before anything is pruned, so a link merely named node_modules is still seen.
    A node_modules is pruned only when it is a real directory owned by the engine user (npm put it
    there; git ignores it and `git clean -X` removes it without following links); its first level
    (@scope and .bin directories) is still checked for links that leave the checkout.

    Links inside node_modules (npm workspace links like @parcel/core -> ../../core, .bin entries) are
    judged by target only, so they are not reported as new; a link named node_modules is not inside.
    """
    links: dict[str, str] = {}
    nested: list[str] = []
    escaping: list[str] = []

    def visit(path: str) -> os.stat_result:
        info = os.lstat(path)
        rel = os.path.relpath(path, root)
        if os.path.basename(path) == ".git" and os.path.dirname(rel):
            nested.append(rel)
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            if "node_modules" not in Path(rel).parent.parts:
                links[rel] = target
            if not _link_stays_inside(root, rel, target):
                escaping.append(rel)
        return info

    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            visit(os.path.join(dirpath, name))
        keep: list[str] = []
        for name in dirnames:
            path = os.path.join(dirpath, name)
            info = visit(path)
            if stat.S_ISLNK(info.st_mode) or (name == ".git" and dirpath == str(root)):
                continue
            if name == ".git":
                continue   # reported as nested; never descended
            if name == "node_modules" and info.st_uid == owner_uid:
                _first_level(path, visit)
                continue
            keep.append(name)
        dirnames[:] = keep
    return Inventory(links, sorted(nested), sorted(escaping))


def _first_level(node_modules: str, visit: Callable[[str], os.stat_result]) -> None:
    for entry in os.scandir(node_modules):
        info = visit(entry.path)
        if (entry.name.startswith("@") or entry.name == ".bin") and stat.S_ISDIR(info.st_mode):
            for scoped in os.scandir(entry.path):
                visit(scoped.path)


def _link_stays_inside(root: Path, rel: str, target: str) -> bool:
    """Resolve without following anything: lexical normalisation, then an lstat walk that refuses links on the way.

    A target is allowed only when it is relative, lands inside the checkout, is not in any .git, and
    every existing component on the way is a real directory or file (missing components are fine,
    a dangling link inside the tree cannot reach outside).
    """
    if os.path.isabs(target):
        return False
    resolved = os.path.normpath(os.path.join(os.path.dirname(rel), target))
    if resolved == ".":
        return True
    parts = Path(resolved).parts
    if parts[0] == ".." or ".git" in parts:
        return False
    current = str(root)
    for part in parts:
        current = os.path.join(current, part)
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                return False
        except FileNotFoundError:
            return True
    return True


def symlinks(root: Path) -> dict[str, str]:
    return inventory(root, owner_uid=os.getuid()).symlinks
