"""Builders for real temporary git repositories used by the gate tests."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# Stands in for `npm test`: prints a vitest style summary. A test file holds lines
# `it pass NAME` / `it fail NAME` and optional `needs PATH` (a missing PATH is a load error).
FAKE_RUNNER = """\
import pathlib
import sys

files_failed = files_passed = tests_failed = tests_passed = 0
for path in sorted(pathlib.Path("app").rglob("*.test.ts")):
    lines = path.read_text().splitlines()
    needs = [ln.split(None, 1)[1] for ln in lines if ln.startswith("needs ")]
    missing = [n for n in needs if not pathlib.Path(n).exists()]
    if missing:
        print(f"FAIL  {path} [ {path} ]")
        print(f'Error: Failed to resolve import "{missing[0]}"')
        files_failed += 1
        continue
    cases = [ln.split() for ln in lines if ln.startswith("it ")]
    failing = [c for c in cases if c[1] == "fail"]
    for case in failing:
        print(f"FAIL  {path} > {case[2]}")
        print("AssertionError: expected 1 to be 2")
    tests_failed += len(failing)
    tests_passed += len(cases) - len(failing)
    if failing:
        files_failed += 1
    else:
        files_passed += 1


def summary(label, failed, passed):
    parts = [f"{n} {word}" for n, word in ((failed, "failed"), (passed, "passed")) if n]
    return f"{label}  " + (" | ".join(parts) + f" ({failed + passed})" if parts else "no tests")


print(summary(" Test Files", files_failed, files_passed))
print(summary("      Tests", tests_failed, tests_passed))
sys.exit(1 if files_failed else 0)
"""

# Stands in for `vitest run --reporter=json`: same report shape, driven by test file lines
# `it pass NAME`, `it fail NAME`, `it error NAME MESSAGE...` (throws MESSAGE instead of failing
# an assertion) and `needs PATH` (a missing PATH is a file level load error).
FAKE_VITEST = r"""
import json
import pathlib
import sys

out = next(a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--outputFile.json="))
if pathlib.Path("app/e2e/crash").exists():
    sys.exit(2)
results = []
for path in sorted(pathlib.Path("app").rglob("*.test.ts")):
    entry = {"name": str(path.resolve()), "status": "passed", "message": "", "assertionResults": []}
    lines = path.read_text().splitlines()
    for line in lines:
        if line.startswith("needs ") and not pathlib.Path(line.split(None, 1)[1]).exists():
            target = line.split(None, 1)[1]
            entry["status"] = "failed"
            entry["message"] = f'Error: Failed to resolve import "{target}" from "{path}".\n at x'
    if not entry["message"]:
        for line in lines:
            if not line.startswith("it "):
                continue
            parts = line.split(None, 3)
            kind, name = parts[1], parts[2]
            if kind == "pass":
                messages = []
            elif kind == "fail":
                messages = ["AssertionError: expected 1 to be 2\n    at x"]
            else:
                messages = [parts[3] + "\n    at x"]
            status = "failed" if messages else "passed"
            entry["status"] = "failed" if messages else entry["status"]
            entry["assertionResults"].append(
                {"fullName": name, "title": name, "status": status, "failureMessages": messages}
            )
    results.append(entry)
pathlib.Path(out).write_text(json.dumps({"testResults": results}))
failed = sum(a["status"] == "failed" for r in results for a in r["assertionResults"])
print(f"      Tests  {failed} failed")
sys.exit(1 if any(r["status"] == "failed" for r in results) else 0)
"""
RUNNER_CMD = f"{shlex.quote(sys.executable)} app/runner.py"
JSON_CMD = f"{shlex.quote(sys.executable)} app/vitest_fake.py --outputFile.json={{report}}"


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    def git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
        return proc.stdout.strip()

    def commit(self, files: dict[str, str | None], message: str) -> str:
        """Write files (None deletes) and commit them."""
        for rel, content in files.items():
            target = self.path / rel
            if content is None:
                self.git("rm", "-q", "--", rel)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            self.git("add", "--", rel)
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.sha()

    def commit_index_paths(self, files: dict[str, str], message: str) -> str:
        """Commit paths straight into the index, bypassing the (case-insensitive) filesystem."""
        for rel, content in files.items():
            blob = subprocess.run(
                ["git", "-C", str(self.path), "hash-object", "-w", "--stdin"],
                input=content,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.git("update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}")
        self.git("commit", "-q", "-m", message)
        return self.sha()

    def sha(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref)

    def branch(self, name: str, start: str = "main") -> None:
        self.git("checkout", "-q", "-b", name, start)

    def worktree_count(self) -> int:
        return len(self.git("worktree", "list", "--porcelain").split("\n\n"))


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for name, value in {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def make_repo(tmp_path: Path) -> Iterator[Callable[[], Repo]]:
    counter = iter(range(1000))

    def build() -> Repo:
        path = tmp_path / f"repo{next(counter)}"
        path.mkdir()
        repo = Repo(path)
        repo.git("init", "-q", "-b", "main")
        repo.git("config", "commit.gpgsign", "false")
        repo.commit(
            {
                "README.md": "demo\n",
                "app/runner.py": FAKE_RUNNER,
                "app/vitest_fake.py": FAKE_VITEST,
                "app/core/src/existing.ts": "export const one = 1\n",
                "app/core/existing.test.ts": "it pass existing\n",
            },
            "chore: base",
        )
        return repo

    yield build


@pytest.fixture
def repo(make_repo: Callable[[], Repo]) -> Repo:
    return make_repo()


@pytest.fixture
def agent_repo(repo: Repo) -> Repo:
    """Base repo with the checkout moved to a new `agent/issue-12` branch."""
    repo.branch("agent/issue-12")
    return repo
