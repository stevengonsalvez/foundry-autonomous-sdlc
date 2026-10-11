from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import REPO_ROOT, Repo

from scripts.gates import agent_scope
from scripts.gates.common import EXIT_ERROR, Change, GateError

BRANCH = "agent/issue-12"


def gate(repo: Repo, **kwargs: str) -> agent_scope.GateResult:
    params = {"base": "main", "head": "HEAD", "branch": BRANCH}
    return agent_scope.evaluate(repo.path, **{**params, **kwargs})


def offenders(result: agent_scope.GateResult) -> str:
    return "\n".join(result.report)


class TestInScope:
    def test_changes_under_app_pass(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/src/new.ts": "x\n", "app/core/existing.test.ts": None}, "x")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (True, "in-scope")

    def test_branch_without_changes_passes(self, agent_repo: Repo) -> None:
        assert gate(agent_repo).note == "no-changes"

    def test_non_agent_branch_is_not_checked(self, repo: Repo) -> None:
        repo.branch("feature/docs")
        repo.commit({"README.md": "changed\n"}, "docs: x")
        result = gate(repo, branch="feature/docs")
        assert (result.passed, result.note) == (True, "not-agent-branch")

    def test_mode_change_under_app_is_allowed(self, agent_repo: Repo) -> None:
        (agent_repo.path / "app/runner.py").chmod(0o755)
        agent_repo.git("add", "app/runner.py")
        agent_repo.git("commit", "-q", "-m", "chore: chmod")
        assert gate(agent_repo).passed

    def test_change_reverted_within_the_branch_leaves_nothing_out_of_scope(
        self, agent_repo: Repo
    ) -> None:
        agent_repo.commit({"README.md": "tampered\n"}, "oops")
        agent_repo.commit({"README.md": "demo\n"}, "revert oops")
        agent_repo.commit({"app/core/src/x.ts": "x\n"}, "feat: x")
        assert gate(agent_repo).passed


class TestOutOfScope:
    def test_file_outside_app_fails_and_is_listed(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/src/x.ts": "x\n", ".github/workflows/ci.yml": "x\n"}, "x")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "out-of-scope")
        assert ".github/workflows/ci.yml" in offenders(result)
        assert "app/core/src/x.ts'" not in offenders(result)

    def test_deletion_outside_app(self, agent_repo: Repo) -> None:
        agent_repo.commit({"README.md": None}, "x")
        assert "'README.md': outside app/ [D]" in offenders(gate(agent_repo))

    def test_rename_out_of_app_lists_the_destination(self, agent_repo: Repo) -> None:
        agent_repo.git("mv", "app/core/src/existing.ts", "scripts_existing.ts")
        agent_repo.git("commit", "-q", "-m", "refactor: move")
        result = gate(agent_repo)
        assert not result.passed
        assert "scripts_existing.ts" in offenders(result)

    def test_rename_into_app_lists_the_source(self, agent_repo: Repo) -> None:
        agent_repo.git("mv", "README.md", "app/README.md")
        agent_repo.git("commit", "-q", "-m", "docs: move")
        result = gate(agent_repo)
        assert not result.passed
        assert "'README.md'" in offenders(result)

    def test_mode_change_outside_app(self, agent_repo: Repo) -> None:
        (agent_repo.path / "README.md").chmod(0o755)
        agent_repo.git("add", "README.md")
        agent_repo.git("commit", "-q", "-m", "chore: chmod")
        assert "'README.md'" in offenders(gate(agent_repo))

    def test_symlink_inside_app_is_rejected(self, agent_repo: Repo) -> None:
        os.symlink("../../.github", agent_repo.path / "app/escape")
        agent_repo.git("add", "app/escape")
        agent_repo.git("commit", "-q", "-m", "feat: link")
        result = gate(agent_repo)
        assert "'app/escape': symlink or submodule [A]" in offenders(result)

    def test_symlink_outside_app_is_rejected(self, agent_repo: Repo) -> None:
        os.symlink("app", agent_repo.path / "linked")
        agent_repo.git("add", "linked")
        agent_repo.git("commit", "-q", "-m", "feat: link")
        assert not gate(agent_repo).passed

    @pytest.mark.parametrize(
        "path", ["App/x.ts", "APP/x.ts", "app.txt", "application/x.ts", "appx"]
    )
    def test_lookalike_paths_are_outside_app(self, agent_repo: Repo, path: str) -> None:
        agent_repo.commit_index_paths({path: "x\n"}, "feat: lookalike")
        result = gate(agent_repo)
        assert not result.passed
        assert repr(path) in offenders(result)

    @pytest.mark.parametrize(
        ("path", "reason"),
        [
            ("app/../.github/ci.yml", "path traversal"),
            ("../outside", "path traversal"),
            ("app/./x.ts", "path traversal"),
            ("app//x.ts", "path traversal"),
            ("app\\..\\x", "backslash in path"),
            ("app/.git/hooks/pre-commit", "git metadata path"),
            ("app/.GIT/config", "git metadata path"),
            ("/app/x.ts", "path traversal"),
            ("app", "outside app/"),
        ],
    )
    def test_hostile_paths(self, path: str, reason: str) -> None:
        change = Change("A", "000000", "100644", path)
        assert agent_scope.violation(change) == reason


class TestProtectedConfiguration:
    @pytest.mark.parametrize(
        "path",
        [
            "app/package.json",
            "app/web/package.json",
            "app/core/src/package.json",
            "app/package-lock.json",
            "app/vitest.config.ts",
            "app/web/vitest.config.ts",
            "app/web/vite.config.ts",
            "app/e2e/playwright.config.ts",
            "app/e2e/playwright.smoke.config.ts",
            "app/e2e/playwright.other.config.mjs",
            "app/web/playwright.component.config.ts",
            "app/e2e/smoke/site.spec.ts",
            "app/e2e/smoke/helpers/wait.ts",
            "app/e2e/smoke/new.spec.ts",
            "app/eslint.config.js",
            "app/tsconfig.base.json",
            "app/web/tsconfig.json",
            "app/coverage/coverage-summary.json",
        ],
    )
    def test_harness_files_are_protected(self, path: str) -> None:
        assert agent_scope.violation(Change("M", "100644", "100644", path)) == (
            "protected test or build configuration"
        )

    @pytest.mark.parametrize(
        "path",
        [
            "app/core/src/parcel.ts",
            "app/web/src/App.tsx",
            "app/api/tests/parcel.test.ts",
            "app/e2e/tests/home.spec.ts",
            "app/e2e/smokeish/home.spec.ts",
            "app/e2e/tests/playwright.notes.ts",
            "app/contracts/carrier.openapi.yaml",
        ],
    )
    def test_ordinary_files_are_not(self, path: str) -> None:
        assert agent_scope.violation(Change("M", "100644", "100644", path)) is None

    def test_weakening_the_smoke_gate_fails_the_gate(self, agent_repo: Repo) -> None:
        agent_repo.commit(
            {
                "app/e2e/smoke/site.spec.ts": "// no checks\n",
                "app/e2e/playwright.smoke.config.ts": "export default {};\n",
                "app/core/src/ok.ts": "x\n",
            },
            "test: soften smoke",
        )
        result = gate(agent_repo)
        assert not result.passed
        report = offenders(result)
        assert (
            "'app/e2e/playwright.smoke.config.ts': protected test or build configuration" in report
        )
        assert "'app/e2e/smoke/site.spec.ts': protected test or build configuration" in report
        assert "app/core/src/ok.ts" not in report

    def test_editing_the_test_script_fails_the_gate(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/package.json": '{"scripts": {"test": "true"}}\n'}, "chore: x")
        result = gate(agent_repo)
        assert not result.passed
        assert "'app/package.json': protected test or build configuration [A]" in offenders(result)


class TestBaseHandling:
    def test_main_moving_ahead_is_not_attributed_to_the_branch(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/src/x.ts": "x\n"}, "feat: x")
        agent_repo.git("checkout", "-q", "main")
        agent_repo.commit({"docs/new.md": "x\n"}, "docs: lands on main")
        agent_repo.git("checkout", "-q", BRANCH)
        assert gate(agent_repo).passed

    def test_merging_main_into_the_branch_is_not_attributed_to_the_branch(
        self, agent_repo: Repo
    ) -> None:
        agent_repo.commit({"app/core/src/x.ts": "x\n"}, "feat: x")
        agent_repo.git("checkout", "-q", "main")
        agent_repo.commit({"docs/new.md": "x\n"}, "docs: lands on main")
        agent_repo.git("checkout", "-q", BRANCH)
        agent_repo.git("merge", "-q", "--no-ff", "-m", "merge main", "main")
        assert gate(agent_repo).passed

    def test_unresolvable_ref_is_an_error(self, agent_repo: Repo) -> None:
        with pytest.raises(GateError, match="cannot resolve"):
            gate(agent_repo, base="nope")


class TestCli:
    def run(self, repo: Repo, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "scripts.gates.agent_scope", "--repo", str(repo.path), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_pass(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/src/x.ts": "x\n"}, "feat: x")
        proc = self.run(agent_repo, "--base", "main", "--branch", BRANCH)
        assert proc.returncode == 0
        assert proc.stdout.splitlines()[-1] == "RESULT=pass"

    def test_fail_lists_offenders_and_exits_one(self, agent_repo: Repo) -> None:
        agent_repo.commit({"LICENSE": "x\n"}, "chore: x")
        proc = self.run(agent_repo, "--base", "main", "--branch", BRANCH)
        assert proc.returncode == 1
        assert "'LICENSE': outside app/" in proc.stdout
        assert proc.stdout.splitlines()[-1] == "RESULT=fail"

    def test_bad_ref_fails_closed(self, agent_repo: Repo) -> None:
        proc = self.run(agent_repo, "--base", "nope", "--branch", BRANCH)
        assert proc.returncode == EXIT_ERROR
        assert proc.stdout.splitlines()[-1] == "RESULT=fail"
