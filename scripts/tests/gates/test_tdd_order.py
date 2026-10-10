from __future__ import annotations

import subprocess
import sys
import time

import pytest
from conftest import REPO_ROOT, RUNNER_CMD, Repo

from scripts.gates import tdd_order
from scripts.gates.common import EXIT_ERROR, GateError

BRANCH = "agent/issue-12"
RED_ASSERT = {"app/core/parcel.test.ts": "it fail parses\n"}
GREEN_TEST = {"app/core/parcel.test.ts": "it pass parses\n"}
IMPL = {"app/core/src/parcel.ts": "export const parse = () => 1\n"}


def gate(repo: Repo, **kwargs: object) -> tdd_order.GateResult:
    params = {"base": "main", "head": "HEAD", "branch": BRANCH, "test_cmd": RUNNER_CMD}
    return tdd_order.evaluate(repo.path, **{**params, **kwargs})


class TestClassification:
    @pytest.mark.parametrize(
        "path",
        [
            "app/core/src/parcel.test.ts",
            "app/web/src/App.test.tsx",
            "app/api/server.spec.ts",
            "app/e2e/home.ts",
            "app/e2e/nested/deep/flow.ts",
            "app/api/tests/helpers.ts",
            "tests/helpers.ts",
            "app/core/__fixtures__/shipments.json",
            "root.test.ts",
        ],
    )
    def test_test_paths(self, path: str) -> None:
        assert tdd_order.is_test_path(path)

    @pytest.mark.parametrize(
        "path",
        [
            "app/core/src/parcel.ts",
            "app/core/src/test.ts",
            "app/core/src/parcel.test.js",
            "app/core/src/parcel.test.ts.bak",
            "app/core/Parcel.TEST.ts",
            "app/api/mytests/helpers.ts",
            "app/e2e",
            "app/e2e-config.ts",
            "package.json",
        ],
    )
    def test_non_test_paths(self, path: str) -> None:
        assert not tdd_order.is_test_path(path)


class TestNonAgentBranch:
    def test_passes_without_touching_git(self, tmp_path) -> None:
        result = tdd_order.evaluate(tmp_path, "nope", "nope", "feature/x")
        assert (result.passed, result.note) == (True, "not-agent-branch")

    def test_agent_prefix_is_case_insensitive(self, agent_repo: Repo) -> None:
        agent_repo.commit(IMPL, "feat: impl first")
        assert not gate(agent_repo, branch="Agent/issue-12").passed


class TestTestsFirst:
    def test_red_then_green_passes(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: parcel parsing")
        agent_repo.commit(IMPL, "feat: parcel parsing")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (True, "tests-first")
        assert "red: " in "\n".join(result.report)

    def test_red_check_runs_in_a_clean_worktree_at_the_leading_tip(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: parcel parsing")
        agent_repo.commit(IMPL, "feat: parcel parsing")
        # The implementation exists in the checkout but not at the leading tip.
        cmd = f"pwd; test ! -e app/core/src/parcel.ts && {RUNNER_CMD}"
        result = gate(agent_repo, test_cmd=cmd)
        assert result.passed
        assert str(agent_repo.path) not in "\n".join(result.report)
        assert agent_repo.worktree_count() == 1
        assert agent_repo.git("status", "--porcelain") == ""

    def test_later_test_only_commit_after_implementation_is_allowed(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: first")
        agent_repo.commit(IMPL, "feat: impl")
        agent_repo.commit({"app/core/more.test.ts": "it pass more\n"}, "test: more coverage")
        assert gate(agent_repo).note == "tests-first"

    def test_red_is_taken_at_the_tip_of_the_leading_run(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/a.test.ts": "it pass a\n"}, "test: green helper test")
        agent_repo.commit({"app/core/b.test.ts": "it fail b\n"}, "test: the red one")
        agent_repo.commit(IMPL, "feat: impl")
        assert gate(agent_repo).passed

    def test_leading_run_that_turns_green_again_fails(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/b.test.ts": "it fail b\n"}, "test: red")
        agent_repo.commit({"app/core/b.test.ts": "it pass b\n"}, "test: soften the test")
        agent_repo.commit(IMPL, "feat: impl")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "tests-not-red")


class TestTestsStayFrozenAfterRed:
    """The tests that were red must be the tests that later go green."""

    def test_flipping_the_red_test_alongside_the_implementation_is_rejected(
        self, agent_repo: Repo
    ) -> None:
        agent_repo.commit(RED_ASSERT, "test: red")
        agent_repo.commit({**GREEN_TEST, **IMPL}, "feat: impl and soften the test")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "tests-modified-after-red")
        assert "app/core/parcel.test.ts" in "\n".join(result.report)

    def test_deleting_the_red_test_in_a_trailing_commit_is_rejected(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: red")
        agent_repo.commit(IMPL, "feat: impl")
        agent_repo.commit({"app/core/parcel.test.ts": None}, "test: remove")
        assert gate(agent_repo).note == "tests-modified-after-red"

    def test_editing_a_test_that_predates_the_branch_is_rejected(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: red")
        agent_repo.commit(IMPL, "feat: impl")
        agent_repo.commit({"app/core/existing.test.ts": "it pass edited\n"}, "test: tweak")
        assert gate(agent_repo).note == "tests-modified-after-red"

    def test_renaming_a_test_after_red_is_rejected(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: red")
        agent_repo.commit(IMPL, "feat: impl")
        agent_repo.git("mv", "app/core/parcel.test.ts", "app/core/moved.test.ts")
        agent_repo.git("commit", "-q", "-m", "test: move")
        assert gate(agent_repo).note == "tests-modified-after-red"

    def test_adding_new_test_files_after_red_is_allowed(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: red")
        agent_repo.commit({**IMPL, "app/core/extra.test.ts": "it pass extra\n"}, "feat: impl")
        assert gate(agent_repo).note == "tests-first"

    def test_edit_that_is_undone_before_head_is_fine(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: red")
        agent_repo.commit(GREEN_TEST, "test: soften")
        agent_repo.commit(RED_ASSERT, "test: restore")
        agent_repo.commit(IMPL, "feat: impl")
        assert gate(agent_repo).note == "tests-first"


class TestOrderingViolations:
    def test_first_commit_is_implementation(self, agent_repo: Repo) -> None:
        agent_repo.commit(IMPL, "feat: impl first")
        agent_repo.commit(RED_ASSERT, "test: afterwards")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "first-commit-not-test-only")

    def test_mixed_test_and_source_commit_is_not_test_only(self, agent_repo: Repo) -> None:
        agent_repo.commit({**RED_ASSERT, **IMPL}, "feat: tests and impl together")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "first-commit-not-test-only")

    def test_rename_of_source_into_test_dir_still_touches_source(self, agent_repo: Repo) -> None:
        (agent_repo.path / "app/core/tests").mkdir()
        agent_repo.git("mv", "app/core/src/existing.ts", "app/core/tests/existing.ts")
        agent_repo.git("commit", "-q", "-m", "test: move")
        assert gate(agent_repo).note == "first-commit-not-test-only"

    def test_rename_of_test_out_of_test_dir_is_not_test_only(self, agent_repo: Repo) -> None:
        agent_repo.git("mv", "app/core/existing.test.ts", "app/core/src/existing_check.ts")
        agent_repo.git("commit", "-q", "-m", "test: rename")
        assert gate(agent_repo).note == "first-commit-not-test-only"

    def test_rename_between_test_paths_is_test_only(self, agent_repo: Repo) -> None:
        agent_repo.git("mv", "app/core/existing.test.ts", "app/core/renamed.test.ts")
        agent_repo.git("commit", "-q", "-m", "test: rename")
        assert gate(agent_repo).note == "test-only"


class TestRedEvidence:
    def test_tests_already_green_is_not_red(self, agent_repo: Repo) -> None:
        agent_repo.commit(GREEN_TEST, "test: parcel parsing")
        agent_repo.commit(IMPL, "feat: parcel parsing")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "tests-not-red")
        assert "passed before any implementation" in "\n".join(result.report)

    def test_load_error_only_is_not_red(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/parcel.test.ts": "needs app/core/src/parcel.ts\n"}, "test: x")
        agent_repo.commit(IMPL, "feat: parcel")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "tests-not-red")
        assert "failed to load" in "\n".join(result.report)

    def test_load_error_next_to_a_real_failure_is_red(self, agent_repo: Repo) -> None:
        files = {"app/core/a.test.ts": "needs app/core/src/parcel.ts\n", **RED_ASSERT}
        agent_repo.commit(files, "test: x")
        agent_repo.commit(IMPL, "feat: parcel")
        assert gate(agent_repo).passed

    def test_nonzero_exit_without_a_failed_test_summary_is_not_red(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        agent_repo.commit(IMPL, "feat: parcel")
        cmd = f"{sys.executable} -c 'import sys; print(\"boom\"); sys.exit(3)'"
        assert gate(agent_repo, test_cmd=cmd).note == "tests-not-red"

    def test_summary_alone_does_not_make_green_exit_red(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        agent_repo.commit(IMPL, "feat: parcel")
        cmd = "echo '      Tests  2 failed | 1 passed (3)'; exit 0"
        assert gate(agent_repo, test_cmd=cmd).note == "tests-not-red"

    def test_timeout_is_not_red(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        agent_repo.commit(IMPL, "feat: parcel")
        started = time.monotonic()
        # A grandchild that keeps the output pipe open must not stall the gate.
        result = gate(agent_repo, test_cmd="sleep 30 & sleep 30", timeout_s=1)
        assert time.monotonic() - started < 10
        assert (result.passed, result.note) == (False, "tests-not-red")
        assert "timed out" in "\n".join(result.report)

    def test_setup_cmd_runs_in_the_worktree_before_the_tests(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        agent_repo.commit(IMPL, "feat: parcel")
        result = gate(
            agent_repo, setup_cmd="touch installed", test_cmd=f"test -f installed && {RUNNER_CMD}"
        )
        assert result.passed

    def test_failing_setup_cmd_is_an_error(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        agent_repo.commit(IMPL, "feat: parcel")
        with pytest.raises(GateError, match="setup command exited 7"):
            gate(agent_repo, setup_cmd="exit 7")
        assert agent_repo.worktree_count() == 1

    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            ("      Tests  1 failed | 3 passed (4)\n", (1, 0)),
            (
                " Test Files  1 failed | 14 passed (15)\n      Tests  1 failed | 152 passed (153)",
                (1, 1),
            ),
            (" Test Files  1 failed | 14 passed (15)\n      Tests  152 passed (152)\n", (0, 1)),
            (" Test Files  2 failed | 1 passed (3)\n      Tests  5 failed (5)\n", (5, 2)),
            ("\x1b[31m Tests \x1b[0m", (0, 0)),
            ("Tests:       2 failed, 4 passed, 6 total\n", (2, 0)),
            ("Test Suites: 1 failed, 1 total\nTests:       0 total\n", (0, 1)),
            ("      Tests  no tests\n", (0, 0)),
            ("", (0, 0)),
            ("Tests  9 failed\n Test Files  1 failed (1)\n      Tests  no tests\n", (0, 1)),
        ],
    )
    def test_summary_parsing(self, output: str, expected: tuple[int, int]) -> None:
        assert tdd_order.parse_failed_tests(output) == expected


class TestTestOnlyBranches:
    def test_maintenance_branch_passes_without_running_tests(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/existing.test.ts": "it pass updated\n"}, "test: repair")
        result = gate(agent_repo, test_cmd="touch ran-the-tests")
        assert (result.passed, result.note) == (True, "test-only")
        assert not (agent_repo.path / "ran-the-tests").exists()

    def test_deleted_test_alone_is_test_only(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/existing.test.ts": None}, "test: remove obsolete test")
        assert gate(agent_repo).note == "test-only"

    def test_deleting_a_test_is_not_red_evidence(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/existing.test.ts": None}, "test: delete")
        agent_repo.commit(IMPL, "feat: impl")
        assert gate(agent_repo).note == "tests-not-red"


class TestHistoryShape:
    def test_merge_commit_is_rejected(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        agent_repo.git("checkout", "-q", "main")
        agent_repo.commit({"CHANGELOG.md": "x\n"}, "docs: main moves on")
        agent_repo.git("checkout", "-q", BRANCH)
        agent_repo.git("merge", "-q", "--no-ff", "-m", "merge main", "main")
        agent_repo.commit(IMPL, "feat: impl")
        # base is the old fork point so the merge sits inside the range
        result = gate(agent_repo, base=agent_repo.sha("main~1"))
        assert (result.passed, result.note) == (False, "merge-commit")

    def test_empty_commit_is_rejected(self, agent_repo: Repo) -> None:
        agent_repo.commit({}, "test: nothing")
        agent_repo.commit(RED_ASSERT, "test: real")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "empty-commit")

    def test_empty_commit_among_implementation_is_rejected(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: real")
        agent_repo.commit({}, "chore: retrigger ci")
        assert gate(agent_repo).note == "empty-commit"

    def test_base_ahead_of_head_uses_the_merge_base(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: parcel parsing")
        agent_repo.commit(IMPL, "feat: parcel parsing")
        agent_repo.git("checkout", "-q", "main")
        agent_repo.commit({"src_on_main.txt": "x\n"}, "feat: unrelated work lands on main")
        agent_repo.git("checkout", "-q", BRANCH)
        result = gate(agent_repo)
        assert result.passed
        assert "unrelated work" not in "\n".join(result.report)

    def test_control_characters_in_a_subject_do_not_break_parsing(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: red \x01 with a control character")
        agent_repo.commit(IMPL, "feat: impl")
        assert gate(agent_repo).note == "tests-first"

    def test_no_commits_between_base_and_head(self, agent_repo: Repo) -> None:
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "no-commits")

    def test_head_behind_base_has_no_commits(self, agent_repo: Repo) -> None:
        agent_repo.git("checkout", "-q", "main")
        agent_repo.commit({"x.txt": "x\n"}, "feat: main moves")
        agent_repo.git("checkout", "-q", BRANCH)
        assert gate(agent_repo).note == "no-commits"

    def test_unrelated_histories_are_an_error(self, agent_repo: Repo) -> None:
        agent_repo.git("checkout", "-q", "--orphan", "orphan")
        agent_repo.commit({"x.txt": "x\n"}, "init")
        with pytest.raises(GateError, match="no merge base"):
            gate(agent_repo, base="main")


class TestCli:
    def run(self, repo: Repo, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "scripts.gates.tdd_order", "--repo", str(repo.path), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_pass_prints_report_and_final_result_line(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        agent_repo.commit(IMPL, "feat: x")
        proc = self.run(agent_repo, "--base", "main", "--branch", BRANCH, "--test-cmd", RUNNER_CMD)
        assert proc.returncode == 0, proc.stderr
        assert "test: x" in proc.stdout
        assert proc.stdout.splitlines()[-1] == "RESULT=pass"

    def test_fail_exits_one(self, agent_repo: Repo) -> None:
        agent_repo.commit(IMPL, "feat: first")
        proc = self.run(agent_repo, "--base", "main", "--branch", BRANCH, "--test-cmd", RUNNER_CMD)
        assert proc.returncode == 1
        assert proc.stdout.splitlines()[-1] == "RESULT=fail"
        assert "NOTE=first-commit-not-test-only" in proc.stdout

    def test_unresolvable_base_fails_closed(self, agent_repo: Repo) -> None:
        agent_repo.commit(RED_ASSERT, "test: x")
        proc = self.run(agent_repo, "--base", "no-such-ref", "--branch", BRANCH)
        assert proc.returncode == EXIT_ERROR
        assert proc.stdout.splitlines()[-1] == "RESULT=fail"

    def test_non_agent_branch_passes(self, repo: Repo) -> None:
        proc = self.run(repo, "--base", "main", "--branch", "main")
        assert proc.returncode == 0
        assert "NOTE=not-agent-branch" in proc.stdout
