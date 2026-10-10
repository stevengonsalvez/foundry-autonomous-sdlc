"""Engine user isolation: creation, fallback, tree hand-over, shared binary, link inventory."""

from __future__ import annotations

import os
import pwd
from pathlib import Path
from types import SimpleNamespace

from sdlc_agents.coder import sandbox
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.ports import CommandResult


def _entry(uid: int = 1001) -> SimpleNamespace:
    return SimpleNamespace(pw_uid=uid, pw_gid=uid, pw_dir="/home/agyuser")


def test_engine_user_is_created_once_when_running_as_root() -> None:
    users: dict[str, SimpleNamespace] = {}
    calls: list[list[str]] = []

    def run(cmd: list[str], **_: object) -> CommandResult:
        calls.append(cmd)
        users["agyuser"] = _entry()
        return CommandResult(0, "")

    def getpwnam(name: str) -> SimpleNamespace:
        return users[name]

    user = sandbox.ensure_agy_user(run=run, getpwnam=getpwnam, euid=lambda: 0)  # type: ignore[arg-type]
    assert user == RunAs("agyuser", 1001, 1001, Path("/home/agyuser"))
    assert calls == [["useradd", "-m", "-s", "/bin/bash", "agyuser"]]
    assert sandbox.ensure_agy_user(run=run, getpwnam=getpwnam, euid=lambda: 0) == user  # type: ignore[arg-type]
    assert len(calls) == 1


def test_no_engine_user_without_root_or_when_useradd_fails() -> None:
    def missing(name: str) -> pwd.struct_passwd:
        raise KeyError(name)

    assert sandbox.ensure_agy_user(euid=lambda: 1000) is None
    assert sandbox.ensure_agy_user(run=lambda cmd, **_: CommandResult(1, "useradd: not found"), getpwnam=missing,
                                   euid=lambda: 0) is None
    assert sandbox.ensure_agy_user(run=lambda cmd, **_: CommandResult(0, ""), getpwnam=missing,
                                   euid=lambda: 0) is None


def test_give_tree_hands_over_everything_but_git(tmp_path: Path) -> None:
    for rel in ("app/src/a.ts", ".git/config", "app/node_modules/x/index.js", "README.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    (tmp_path / "app/link").symlink_to("/etc")
    chowned: list[str] = []
    sandbox.give_tree(tmp_path, RunAs("agyuser", 1001, 1001, Path("/h")),
                      chown=lambda path, uid, gid: chowned.append(os.path.relpath(path, tmp_path)))
    assert sorted(chowned) == ["README.md", "app", "app/link", "app/node_modules", "app/node_modules/x",
                               "app/node_modules/x/index.js", "app/src", "app/src/a.ts"]


def test_agy_is_installed_per_user_into_its_local_bin(tmp_path: Path) -> None:
    source = tmp_path / "agy"
    source.write_bytes(b"binary")
    user = RunAs("agyuser", os.getuid(), os.getgid(), tmp_path / "home/agyuser")
    dest = sandbox.install_user_binary(source, user)
    assert dest == user.home / ".local/bin/agy"
    assert dest.read_bytes() == b"binary"
    assert os.stat(dest).st_mode & 0o777 == 0o700
    assert dest.stat().st_uid == user.uid
    mtime = dest.stat().st_mtime_ns
    sandbox.install_user_binary(source, user)
    assert dest.stat().st_mtime_ns == mtime


def test_user_env_is_built_from_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("IDENTITY_HEADER", "secret")
    monkeypatch.setenv("LANG", "C.UTF-8")
    env = sandbox.user_env(RunAs("agyuser", 1001, 1001, Path("/home/agyuser")), Path("/opt/node/bin"))
    assert env["HOME"] == "/home/agyuser"
    assert env["PATH"] == "/opt/node/bin:/home/agyuser/.local/bin:/usr/local/bin:/usr/bin:/bin"
    assert env["LANG"] == "C.UTF-8"
    assert "IDENTITY_HEADER" not in env


def test_symlink_inventory_skips_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/link").symlink_to("/x")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/dirlink").symlink_to("/etc")
    (tmp_path / "app/filelink").symlink_to("../README.md")
    assert sandbox.symlinks(tmp_path) == {"app/dirlink": "/etc", "app/filelink": "../README.md"}


def test_leftover_engine_processes_are_killed_by_uid(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    for pid in ("101", "102", "self"):
        (proc / pid).mkdir(parents=True)
    killed: list[int] = []
    me = RunAs("agyuser", os.getuid(), os.getgid(), Path("/h"))
    assert sandbox.kill_user_processes(me, proc_root=proc, kill=lambda pid, sig: killed.append(pid)) == 2
    assert sorted(killed) == [101, 102]
    other = RunAs("agyuser", os.getuid() + 1, 0, Path("/h"))
    assert sandbox.kill_user_processes(other, proc_root=proc, kill=lambda pid, sig: killed.append(pid)) == 0
    assert sandbox.kill_user_processes(me, proc_root=tmp_path / "none") == 0
    assert sandbox.kill_user_processes(RunAs("root", 0, 0, Path("/")), proc_root=proc) == 0
