"""
Isolation for the agy engine inside the hosted sandbox (decision D10).

The coder process runs as root and holds the PAT and the managed identity. When it can, it runs
agy as an unprivileged user that owns only the working tree: not .git, not node_modules, not the
coder's $HOME. When the user cannot be created, agy runs as the coder's own user with a scrubbed
environment, and the job log records that.
"""

from __future__ import annotations

import os
import pwd
import shutil
import signal
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sdlc_agents.coder import shell
from sdlc_agents.ports import CommandResult

AGY_USER = "agyuser"
_ENV_PASSTHROUGH = ("LANG", "LC_ALL", "TERM", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
                    "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
PRIVILEGED_WORK_ROOT = Path("/srv/sdlc-work")
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


def kill_user_processes(user: RunAs, *, proc_root: Path = Path("/proc"),
                        kill: Callable[[int, int], None] = os.kill) -> int:
    """SIGKILL every process the engine user still has (daemons that left agy's process group)."""
    if user.uid == 0:
        return 0   # never root: that would take the coder itself down
    killed = 0
    for entry in proc_root.glob("[0-9]*") if proc_root.is_dir() else []:
        try:
            if entry.stat().st_uid != user.uid:
                continue
            kill(int(entry.name), signal.SIGKILL)
            killed += 1
        except (OSError, ValueError):
            continue
    return killed


def give_tree(root: Path, user: RunAs, *, chown: Callable[[str, int, int], None] = os.lchown) -> None:
    """Hand the working tree to the engine user. .git and the top directory stay with root (so the user
    cannot swap .git out); links are not followed."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ENGINE_SKIP_DIRS]
        for name in (*dirnames, *filenames):
            chown(os.path.join(dirpath, name), user.uid, user.gid)


def install_user_binary(source: Path, user: RunAs) -> Path:
    """Install agy for the engine user in its own ~/.local/bin (the coder's $HOME is not traversable for it)."""
    dest = user.home / ".local" / "bin" / "agy"
    if not dest.exists() or dest.stat().st_size != source.stat().st_size:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp")
        shutil.copyfile(source, tmp)
        os.chmod(tmp, 0o700)
        os.lchown(tmp, user.uid, user.gid)
        os.replace(tmp, dest)
    for directory in (dest.parent, dest.parent.parent):
        os.lchown(directory, user.uid, user.gid)
    return dest


def user_env(user: RunAs, node_bin: Path) -> dict[str, str]:
    """The complete environment for install, tests and agy as the engine user: built from nothing."""
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    env.update({"HOME": str(user.home), "CI": "1", "NO_COLOR": "1",
                "PATH": f"{node_bin}:{user.home}/.local/bin:/usr/local/bin:/usr/bin:/bin"})
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
