"""
Toolchain bootstrap inside the hosted sandbox (Debian 12, root, no git or node; see docs/findings.md).

Everything installs under $HOME, which the platform persists across idle eviction, so a resumed
session finds the tools already there.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tarfile
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sdlc_agents.coder import sandbox, shell
from sdlc_agents.ports import CommandResult

NODE_INDEX = "https://nodejs.org/dist/latest-v22.x/"
AGY_INSTALLER = "https://antigravity.google/cli/install.sh"
NODE_DIR = Path("/opt/node")   # outside $HOME: the engine user cannot traverse the coder's home
AGY_AUTH_FILE = ".gemini/antigravity-cli/antigravity-oauth-token"
AGY_SETTINGS_FILE = ".gemini/antigravity-cli/settings.json"
# Headless agy denies every shell command not allowed here (antigravity.google/docs/cli/headless). This is
# guidance for the engine, not the security boundary (that is the engine user, its scrubbed environment and
# root's scans; see docs/runbook.md). Reading and running the tests only: no find (-exec is a shell), no
# network tools, shells, interpreters, env dumps, git writes or rm. Arguments are plain words that cannot
# start with a dash, plus an explicit list of harmless flags, so no --config, --exec, --output, -c,
# --ext-diff or --textconv, and no shell metacharacters. Patterns are anchored, so a substring matcher
# cannot widen them.
_WORD = r"[A-Za-z0-9._/:@,+%][A-Za-z0-9._/=:@,+%~-]*"
_GIT_FLAGS = r"--stat|--name-only|--name-status|--oneline|--cached|--staged|--no-color|-n|-p|-[0-9]+"
_VITEST_FLAGS = r"--run|--reporter=(default|verbose|dot)|-t|--no-color|--"


def _args(flags: str) -> str:
    return rf"( ({flags}|{_WORD}))*"


AGY_ALLOWED_COMMANDS = (
    "command(ls)", "command(cat)", "command(head)", "command(tail)", "command(wc)", "command(grep)",
    f"command(regex:^git (status|diff|log|show|ls-files){_args(_GIT_FLAGS)}$)",
    f"command(regex:^npm (test|run (lint|typecheck|test|test:coverage)){_args(_VITEST_FLAGS)}$)",
    f"command(regex:^npx vitest run{_args(_VITEST_FLAGS)}$)",
)
AGY_SETTINGS_BYTES = json.dumps({"permissions": {"allow": list(AGY_ALLOWED_COMMANDS)}}, indent=2).encode()
AGY_COMMANDS_HELP = ("ls, cat, head, tail, wc, grep; git status, diff, log, show, ls-files; npm test, "
                     "npm run lint, typecheck, test, test:coverage; npx vitest run (plain arguments only)")
_NODE_ARCH = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
# Environment passed to engines and test commands. Anything else (managed identity endpoints,
# Azure settings, git auth) stays out of reach of code the engine writes or runs.
_ENV_ALLOW = ("LANG", "LC_ALL", "TZ", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
              "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY")
_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class ToolchainError(RuntimeError):
    pass


def http_get(url: str, *, timeout_s: int = 300, max_bytes: int = 400 * 1024 * 1024) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        data: bytes = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ToolchainError(f"{url} is larger than {max_bytes} bytes")
    return data


Runner = Callable[..., CommandResult]


class Toolchain:
    def __init__(self, home: Path, *, fetch: Callable[[str], bytes] = http_get, run: Runner = shell.run,
                 which: Callable[[str], str | None] = shutil.which, machine: str | None = None,
                 node_dir: Path | None = None, euid: Callable[[], int] = os.geteuid,
                 chown: Callable[[str, int, int], None] = os.lchown):
        self.home = home
        self._node_dir = node_dir or home / ".local/node"
        self._euid = euid
        self._chown = chown
        self._fetch = fetch
        self._run = run
        self._which = which
        self._machine = machine or platform.machine()

    @property
    def node_dir(self) -> Path:
        return self._node_dir

    @property
    def agy_path(self) -> Path:
        return self.home / ".local/bin/agy"

    def env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
        env.update({
            "HOME": str(self.home), "CI": "1", "NO_COLOR": "1",
            "PATH": f"{self.node_dir}/bin:{self.home}/.local/bin:{_SYSTEM_PATH}",
        })
        return env

    def ensure_git(self) -> None:
        if self._which("git"):
            return
        env: dict[str, Any] = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        for cmd in (["apt-get", "update", "-qq"], ["apt-get", "install", "-y", "-qq", "git", "ca-certificates"]):
            result = self._run(cmd, cwd=self.home, env=env, timeout_s=600)
            if result.returncode != 0:
                raise ToolchainError(f"{' '.join(cmd)} failed: {result.output[-1000:]}")
        if not self._which("git"):
            raise ToolchainError("git still missing after apt-get install")

    def ensure_node(self) -> None:
        if (self.node_dir / "bin/node").exists():
            return
        arch = _NODE_ARCH.get(self._machine)
        if arch is None:
            raise ToolchainError(f"unsupported architecture {self._machine}")
        shasums = self._fetch(f"{NODE_INDEX}SHASUMS256.txt").decode()
        pattern = re.compile(rf"^([0-9a-f]{{64}})\s+(node-v22\.\d+\.\d+-linux-{arch})\.tar\.gz$", re.MULTILINE)
        match = pattern.search(shasums)
        if not match:
            raise ToolchainError(f"no linux-{arch} tarball in {NODE_INDEX}SHASUMS256.txt")
        expected, name = match.groups()
        tarball = self._fetch(f"{NODE_INDEX}{name}.tar.gz")
        actual = hashlib.sha256(tarball).hexdigest()
        if actual != expected:
            raise ToolchainError(f"sha256 mismatch for {name}.tar.gz: expected {expected}, got {actual}")
        self.node_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.node_dir.parent) as tmp:
            archive = Path(tmp) / "node.tar.gz"
            archive.write_bytes(tarball)
            with tarfile.open(archive) as tar:
                tar.extractall(tmp, filter="data")
            extracted = Path(tmp) / name
            if self._euid() == 0:
                # Extracting as root keeps the tarball's numeric owner, which may be the engine user's uid.
                for dirpath, dirnames, filenames in os.walk(extracted):
                    for entry in (dirpath, *(os.path.join(dirpath, n) for n in (*dirnames, *filenames))):
                        self._chown(entry, 0, 0)
            os.chmod(extracted, 0o755)  # noqa: S103  world-executable on purpose, root-owned and not writable
            os.replace(extracted, self.node_dir)

    def node_bin(self) -> Path:
        """node's bin directory, installed on first use. Root-owned and world-readable, so the engine
        user can run npm and vitest from it but never change it."""
        self.ensure_node()
        return self.node_dir / "bin"

    def ensure_agy(self) -> Path:
        if self.agy_path.exists():
            return self.agy_path
        script_dir = self.home / ".cache"
        script_dir.mkdir(parents=True, exist_ok=True)
        script = script_dir / "agy-install.sh"
        script.write_bytes(self._fetch(AGY_INSTALLER))
        result = self._run(["bash", str(script)], cwd=self.home, env=self.env(), timeout_s=900)
        if not self.agy_path.exists():
            raise ToolchainError(f"agy installer did not produce {self.agy_path}: {result.output[-1000:]}")
        return self.agy_path

    def write_agy_settings(self, *, home: Path | None = None, owner: tuple[int, int] | None = None) -> Path:
        """agy's permission allow-list, 0600 in agy's home (link-safe when that home belongs to another user)."""
        data = AGY_SETTINGS_BYTES
        if owner is not None:
            return sandbox.write_private_file(home or self.home, AGY_SETTINGS_FILE, data, owner=owner)
        path = (home or self.home) / AGY_SETTINGS_FILE
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(data)
        return path

    def write_agy_token(self, token: str, *, home: Path | None = None,
                        owner: tuple[int, int] | None = None) -> Path:
        """Write the agy token 0600 under `home` (default: the coder's), owned by `owner` when given."""
        if owner is not None:   # another user's home: never follow what that user may have planted there
            return sandbox.write_private_file(home or self.home, AGY_AUTH_FILE, token.encode(), owner=owner)
        path = (home or self.home) / AGY_AUTH_FILE
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(token)
        return path
