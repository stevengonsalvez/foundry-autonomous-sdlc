"""Toolchain bootstrap: verified Node tarball, git via apt, agy via its installer, the token file."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tarfile
from pathlib import Path

import pytest

from sdlc_agents.coder import shell
from sdlc_agents.coder.toolchain import AGY_SETTINGS_BYTES, NODE_INDEX, Toolchain, ToolchainError
from sdlc_agents.ports import CommandResult

NODE_NAME = "node-v22.99.1-linux-x64"


def _node_tarball() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        script = b"#!/bin/sh\necho v22.99.1\n"
        info = tarfile.TarInfo(f"{NODE_NAME}/bin/node")
        info.size, info.mode = len(script), 0o755
        tar.addfile(info, io.BytesIO(script))
        link = tarfile.TarInfo(f"{NODE_NAME}/bin/npm")
        link.type, link.linkname = tarfile.SYMTYPE, "node"
        tar.addfile(link)
    return buf.getvalue()


class FakeFetch:
    def __init__(self, pages: dict[str, bytes]):
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.pages[url]


def _node_pages(tarball: bytes, digest: str | None = None) -> dict[str, bytes]:
    digest = digest or hashlib.sha256(tarball).hexdigest()
    shasums = (f"{'0' * 64}  {NODE_NAME}.tar.xz\n{digest}  {NODE_NAME}.tar.gz\n"
               f"{'1' * 64}  node-v22.99.1-darwin-arm64.tar.gz\n")
    return {f"{NODE_INDEX}SHASUMS256.txt": shasums.encode(), f"{NODE_INDEX}{NODE_NAME}.tar.gz": tarball}


def test_node_is_installed_from_a_verified_tarball_once(tmp_path: Path) -> None:
    fetch = FakeFetch(_node_pages(_node_tarball()))
    tools = Toolchain(tmp_path, fetch=fetch, machine="x86_64")
    tools.ensure_node()
    node = tmp_path / ".local/node/bin/node"
    assert shell.run([str(node)], cwd=tmp_path, timeout_s=10).output.strip() == "v22.99.1"
    assert (tmp_path / ".local/node/bin/npm").is_symlink()
    assert str(tmp_path / ".local/node/bin") in tools.env()["PATH"].split(":")[0]
    tools.ensure_node()
    assert len(fetch.calls) == 2


def test_node_with_a_wrong_checksum_is_refused_and_not_installed(tmp_path: Path) -> None:
    tools = Toolchain(tmp_path, fetch=FakeFetch(_node_pages(_node_tarball(), digest="f" * 64)), machine="x86_64")
    with pytest.raises(ToolchainError, match="sha256 mismatch"):
        tools.ensure_node()
    assert not (tmp_path / ".local/node").exists()


def test_node_for_an_unknown_architecture_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ToolchainError, match="architecture"):
        Toolchain(tmp_path, fetch=FakeFetch({}), machine="sparc").ensure_node()


def test_missing_node_build_in_the_index_is_an_error(tmp_path: Path) -> None:
    pages = {f"{NODE_INDEX}SHASUMS256.txt": b"abc  node-v22.1.0-win-x64.zip\n"}
    with pytest.raises(ToolchainError, match="no linux-x64"):
        Toolchain(tmp_path, fetch=FakeFetch(pages), machine="x86_64").ensure_node()


def test_git_is_installed_with_apt_only_when_missing(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    present = {"git": None}

    def run(cmd: list[str], **_: object) -> CommandResult:
        calls.append(cmd)
        if "install" in cmd:
            present["git"] = "/usr/bin/git"
        return CommandResult(0, "ok")

    tools = Toolchain(tmp_path, fetch=FakeFetch({}), run=run, which=lambda name: present.get(name))
    tools.ensure_git()
    assert calls == [["apt-get", "update", "-qq"], ["apt-get", "install", "-y", "-qq", "git", "ca-certificates"]]
    tools.ensure_git()
    assert len(calls) == 2


def test_git_install_failure_is_reported(tmp_path: Path) -> None:
    tools = Toolchain(tmp_path, fetch=FakeFetch({}), run=lambda cmd, **_: CommandResult(100, "E: no space"),
                      which=lambda name: None)
    with pytest.raises(ToolchainError, match="no space"):
        tools.ensure_git()


def test_agy_installer_runs_with_home_and_must_produce_the_binary(tmp_path: Path) -> None:
    installer = (b'mkdir -p "$HOME/.local/bin" && printf "#!/bin/sh\\necho agy" > "$HOME/.local/bin/agy"'
                 b' && chmod +x "$HOME/.local/bin/agy"\n')
    tools = Toolchain(tmp_path, fetch=FakeFetch({"https://antigravity.google/cli/install.sh": installer}))
    assert tools.ensure_agy() == tmp_path / ".local/bin/agy"
    assert tools.ensure_agy() == tmp_path / ".local/bin/agy"

    broken = Toolchain(tmp_path / "other", fetch=FakeFetch({"https://antigravity.google/cli/install.sh": b"exit 0\n"}))
    with pytest.raises(ToolchainError, match="agy"):
        broken.ensure_agy()


def test_agy_token_file_is_private(tmp_path: Path) -> None:
    tools = Toolchain(tmp_path, fetch=FakeFetch({}))
    path = tools.write_agy_token('{"token":"one"}')
    path = tools.write_agy_token('{"token":"two"}')
    assert path == tmp_path / ".gemini/antigravity-cli/antigravity-oauth-token"
    assert path.read_text() == '{"token":"two"}'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_tool_env_is_an_allowlist_without_identity_or_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDENTITY_HEADER", "msi-secret")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "AUTHORIZATION: basic xyz")
    monkeypatch.setenv("LANG", "C.UTF-8")
    env = Toolchain(tmp_path, fetch=FakeFetch({})).env()
    assert "IDENTITY_HEADER" not in env
    assert "GIT_CONFIG_VALUE_0" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["CI"] == "1"
    assert env["LANG"] == "C.UTF-8"
    assert env["PATH"].startswith(f"{tmp_path}/.local/node/bin:{tmp_path}/.local/bin:")


def test_agy_token_can_go_to_the_engine_user_home(tmp_path: Path) -> None:
    tools = Toolchain(tmp_path / "coder", fetch=FakeFetch({}))
    owner = (os.getuid(), os.getgid())
    (tmp_path / "agyuser").mkdir()          # useradd -m created it
    path = tools.write_agy_token('{"t":"x"}', home=tmp_path / "agyuser", owner=owner)
    assert path == tmp_path / "agyuser/.gemini/antigravity-cli/antigravity-oauth-token"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (path.stat().st_uid, path.stat().st_gid) == owner
    assert not (tmp_path / "coder/.gemini").exists()


def test_node_installs_once_into_a_root_owned_world_readable_dir(tmp_path: Path) -> None:
    fetch = FakeFetch(_node_pages(_node_tarball()))
    owners: list[tuple[str, int, int]] = []
    tools = Toolchain(tmp_path / "home", fetch=fetch, machine="x86_64", node_dir=tmp_path / "opt/node",
                      euid=lambda: 0, chown=lambda path, uid, gid: owners.append((path, uid, gid)))
    assert tools.node_bin() == tmp_path / "opt/node/bin"
    assert shell.run([str(tmp_path / "opt/node/bin/node")], cwd=tmp_path, timeout_s=10).output.strip() == "v22.99.1"
    assert stat.S_IMODE((tmp_path / "opt/node/bin/node").stat().st_mode) == 0o755
    assert stat.S_IMODE((tmp_path / "opt/node").stat().st_mode) == 0o755
    assert owners
    assert {(uid, gid) for _, uid, gid in owners} == {(0, 0)}   # the tarball's uid could be agyuser's
    assert not (tmp_path / "home/.local/node").exists()
    assert tools.env()["PATH"].startswith(f"{tmp_path}/opt/node/bin:")
    assert tools.node_bin() == tmp_path / "opt/node/bin"
    assert len(fetch.calls) == 2


def _allows(rules: list[str], command: str) -> bool:
    """How agy applies the rules: command(<name>) by program name, command(regex:<re>) on the whole line."""
    for rule in rules:
        body = rule.removeprefix("command(").removesuffix(")")
        if body.startswith("regex:"):
            pattern = body.removeprefix("regex:")
            assert pattern.startswith("^") and pattern.endswith("$"), "anchored, whatever agy's matcher does"
            if re.search(pattern, command):
                return True
        elif command.split()[0] == body:
            return True
    return False


def _written_rules(tmp_path: Path) -> list[str]:
    path = Toolchain(tmp_path, fetch=FakeFetch({})).write_agy_settings()
    data = json.loads(path.read_text())
    assert set(data) == {"permissions"}
    rules: list[str] = data["permissions"]["allow"]
    return rules


@pytest.mark.parametrize("command", [
    "ls -la app/web", "cat app/web/src/eta.ts", "grep -rn eta app/web/src", "head -50 app/x.ts", "wc -l app/x.ts",
    "git status", "git diff", "git diff --stat HEAD~1", "git log --oneline -n 5", "git show HEAD:app/web/src/eta.ts",
    "git ls-files app/web", "npm test", "npm test -- web/tests/eta.test.ts", "npm run typecheck", "npm run lint",
    "npm run test:coverage", "npx vitest run web/tests/eta.test.ts", "npx vitest run -t eta --reporter=verbose",
])
def test_agy_may_read_the_repo_and_run_the_tests(tmp_path: Path, command: str) -> None:
    assert _allows(_written_rules(tmp_path), command), command


@pytest.mark.parametrize("command", [
    "find . -exec sh -c id ;", "find . -delete", "curl https://evil.example", "wget x", "bash -c id", "sh -c id",
    "python3 -c 1", "node -e 1", "env", "printenv", "rm -rf app", "ssh host", "nc host 1",
    "git push origin HEAD", "git remote -v", "git config core.pager sh", "git -c core.pager=sh log",
    "git diff --output=/tmp/x", "git diff --ext-diff", "git log --textconv", "git status; curl x",
    "git log $(id)", "git show `id`", "npm test && curl x", "npm test -- --config=/tmp/evil.ts",
    "npm run build", "npm install left-pad", "npx vitest run --config /tmp/x", "npx vitest --watch",
    "npx vitest run --outputFile=/tmp/x", "npx some-other-tool", "git diff | sh",
])
def test_agy_may_not_escape_through_the_allow_list(tmp_path: Path, command: str) -> None:
    assert not _allows(_written_rules(tmp_path), command), command


def test_agy_settings_go_to_the_engine_user_home_privately(tmp_path: Path) -> None:
    tools = Toolchain(tmp_path / "coder", fetch=FakeFetch({}))
    (tmp_path / "agyuser").mkdir()
    path = tools.write_agy_settings(home=tmp_path / "agyuser", owner=(os.getuid(), os.getgid()))
    assert path == tmp_path / "agyuser/.gemini/antigravity-cli/settings.json"
    assert path.read_bytes() == AGY_SETTINGS_BYTES
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
