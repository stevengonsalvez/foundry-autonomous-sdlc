"""Engine user isolation: creation, fallback, tree hand-over, shared binary, link inventory."""

from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_user_env_is_built_from_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("IDENTITY_HEADER", "secret")
    monkeypatch.setenv("LANG", "C.UTF-8")
    env = sandbox.user_env(RunAs("agyuser", 1001, 1001, Path("/home/agyuser")), Path("/opt/node/bin"))
    assert env["HOME"] == "/home/agyuser"
    assert env["PATH"] == "/opt/node/bin:/opt/agy/bin:/usr/local/bin:/usr/bin:/bin"
    assert env["LANG"] == "C.UTF-8"
    assert "IDENTITY_HEADER" not in env


def test_symlink_inventory_skips_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/link").symlink_to("/x")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/dirlink").symlink_to("/etc")
    (tmp_path / "app/filelink").symlink_to("../README.md")
    assert sandbox.symlinks(tmp_path) == {"app/dirlink": "/etc", "app/filelink": "../README.md"}


def test_engine_user_processes_are_found_by_uid(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    for pid in ("101", "102", "self"):
        (proc / pid).mkdir(parents=True)
    me = RunAs("agyuser", os.getuid(), os.getgid(), Path("/h"))
    assert sorted(sandbox.user_pids(me, proc_root=proc)) == [101, 102]
    assert sandbox.user_pids(RunAs("x", os.getuid() + 1, 0, Path("/h")), proc_root=proc) == []
    assert sandbox.user_pids(me, proc_root=tmp_path / "none") == []


def _victim(tmp_path: Path) -> Path:
    victim = tmp_path / "root-owned" / "shadow"
    victim.parent.mkdir()
    victim.write_text("ROOT DATA\n")
    return victim


def test_agy_binary_goes_to_a_root_owned_dir_never_into_the_user_home(tmp_path: Path) -> None:
    victim = _victim(tmp_path)
    user = RunAs("agyuser", os.getuid(), os.getgid(), tmp_path / "home/agyuser")
    (user.home / ".local/bin").mkdir(parents=True)
    (user.home / ".local/bin/agy.tmp").symlink_to(victim)        # planted by an earlier job
    (user.home / ".local/bin/agy").symlink_to(victim)
    source = tmp_path / "agy"
    source.write_bytes(b"binary")
    dest = sandbox.install_agy_binary(source, tmp_path / "opt/agy")
    assert dest == tmp_path / "opt/agy/bin/agy"
    assert dest.read_bytes() == b"binary"
    assert stat.S_IMODE(dest.stat().st_mode) == 0o755
    assert victim.read_text() == "ROOT DATA\n"
    assert sandbox.install_agy_binary(source, tmp_path / "opt/agy") == dest


def test_private_file_write_never_follows_links_in_the_user_home(tmp_path: Path) -> None:
    victim = _victim(tmp_path)
    home = tmp_path / "home/agyuser"
    home.mkdir(parents=True)
    owner = (os.getuid(), os.getgid())
    (home / ".gemini").symlink_to(victim.parent)                 # directory link
    with pytest.raises(sandbox.UnsafePathError):
        sandbox.write_private_file(home, ".gemini/antigravity-cli/token", b"secret", owner=owner)
    assert sorted(p.name for p in victim.parent.iterdir()) == ["shadow"]
    (home / ".gemini").unlink()
    (home / ".gemini/antigravity-cli").mkdir(parents=True)
    (home / ".gemini/antigravity-cli/token").symlink_to(victim)   # file link
    path = sandbox.write_private_file(home, ".gemini/antigravity-cli/token", b"secret", owner=owner)
    assert victim.read_text() == "ROOT DATA\n"
    assert not path.is_symlink()
    assert path.read_bytes() == b"secret"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_safe_read_refuses_links_fifos_and_huge_files(tmp_path: Path) -> None:
    victim = _victim(tmp_path)
    (tmp_path / "link.json").symlink_to(victim)
    os.mkfifo(tmp_path / "pipe.json")
    (tmp_path / "big.json").write_bytes(b"x" * 2048)
    (tmp_path / "ok.json").write_text("{}")
    assert sandbox.safe_read(tmp_path / "ok.json", max_bytes=100) == b"{}"
    for name in ("link.json", "pipe.json", "big.json", "missing.json"):
        with pytest.raises(sandbox.UnsafePathError):
            sandbox.safe_read(tmp_path / name, max_bytes=1024)


def test_reap_kills_until_the_user_has_no_processes_left(tmp_path: Path) -> None:
    rounds = [[201, 202], [203], []]                              # a fork appeared during the first pass
    killed: list[int] = []
    user = RunAs("agyuser", 1001, 1001, Path("/h"))
    left = sandbox.reap_user(user, list_pids=lambda u: rounds.pop(0), kill=lambda pid, sig: killed.append(pid))
    assert left == 0
    assert killed == [201, 202, 203]
    endless = sandbox.reap_user(user, list_pids=lambda u: [999], kill=lambda pid, sig: None, max_rounds=3)
    assert endless == 1
    assert sandbox.reap_user(RunAs("root", 0, 0, Path("/")), list_pids=lambda u: [1]) == 0


def test_safe_read_can_take_the_tail_of_a_big_file(tmp_path: Path) -> None:
    (tmp_path / "big.log").write_bytes(b"x" * 5000 + b"END")
    assert sandbox.safe_read(tmp_path / "big.log", max_bytes=10, tail=True) == b"xxxxxxxEND"


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    (root / "app/api").mkdir(parents=True)
    (root / "app/web/node_modules/pkg").mkdir(parents=True)
    (root / "app/web/node_modules/.bin").mkdir()
    (root / "app/web/node_modules/.bin/vitest").symlink_to("../pkg/cli.js")       # npm's own, stays inside
    return root


def test_inventory_finds_nested_repos_and_links_that_leave_the_checkout(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "app/api/node_modules").symlink_to("../../.git")                     # H1: link named node_modules
    (root / "app/web/node_modules/evil").symlink_to("/etc")                       # depth 1 inside node_modules
    (root / "app/inner/.git").mkdir(parents=True)                                 # C1: nested repository
    (root / "app/web/src").mkdir()
    (root / "app/web/src/.git").write_text("gitdir: /tmp/elsewhere\n")             # a gitfile counts too
    inv = sandbox.inventory(root, owner_uid=os.getuid())
    assert sorted(inv.nested_git) == ["app/inner/.git", "app/web/src/.git"]
    assert sorted(inv.escaping) == ["app/web/node_modules/evil"]
    assert inv.symlinks["app/api/node_modules"] == "../../.git"
    assert "app/web/node_modules/.bin/vitest" not in inv.escaping


def test_node_modules_owned_by_someone_else_is_walked_fully(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "app/web/node_modules/pkg/deep").mkdir()
    (root / "app/web/node_modules/pkg/deep/escape").symlink_to("/etc")
    assert sandbox.inventory(root, owner_uid=os.getuid()).escaping == []          # owned: only depth 1 checked
    assert sandbox.inventory(root, owner_uid=os.getuid() + 1).escaping == ["app/web/node_modules/pkg/deep/escape"]


def test_engine_user_gets_empty_shell_startup_files(tmp_path: Path) -> None:
    user = RunAs("agyuser", os.getuid(), os.getgid(), tmp_path / "agyuser")
    user.home.mkdir()
    (user.home / ".profile").symlink_to(tmp_path / "elsewhere")         # never followed
    sandbox.ensure_shell_files(user)
    for name in (".bashrc", ".profile"):
        path = user.home / name
        assert path.is_file() and not path.is_symlink()
        assert path.read_bytes() == b""
        assert path.stat().st_uid == user.uid
    assert not (tmp_path / "elsewhere").exists()
