"""Red evidence read from the vitest JSON report: only assertion failures count."""

from __future__ import annotations

import pytest
from conftest import JSON_CMD, RUNNER_CMD, Repo

from scripts.gates import tdd_order

BRANCH = "agent/issue-12"
IMPL = {"app/core/src/parcel.ts": "export const parse = () => 1\n"}
PARCEL = "app/core/parcel.test.ts"


def gate(repo: Repo, **kwargs: object) -> tdd_order.GateResult:
    params = {"base": "main", "head": "HEAD", "branch": BRANCH, "test_cmd": JSON_CMD}
    return tdd_order.evaluate(repo.path, **{**params, **kwargs})


def red_commit(repo: Repo, body: str, path: str = PARCEL) -> None:
    repo.commit({path: body}, "test: red")
    repo.commit(IMPL, "feat: impl")


def text(result: tdd_order.GateResult) -> str:
    return "\n".join(result.report)


class TestValidRed:
    def test_an_assertion_failure_is_red(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it fail parses\n")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (True, "tests-first")
        assert "red: 1 valid assertion failure(s)" in text(result)

    def test_valid_failure_next_to_passing_tests_is_red(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it pass a\nit fail b\nit pass c\n")
        assert gate(agent_repo).passed

    def test_an_edited_existing_test_counts_as_changed(self, agent_repo: Repo) -> None:
        agent_repo.commit({"app/core/existing.test.ts": "it fail existing\n"}, "test: tighten")
        agent_repo.commit(IMPL, "feat: impl")
        assert gate(agent_repo).passed

    def test_the_report_file_is_not_left_in_the_checkout(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it fail parses\n")
        gate(agent_repo)
        assert agent_repo.git("status", "--porcelain") == ""


class TestInvalidRed:
    def test_reference_error_is_not_red(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it error parses ReferenceError: expect is not defined\n")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "tests-invalid-red")
        assert PARCEL in text(result)
        assert "parses" in text(result)
        assert "ReferenceError: expect is not defined" in text(result)

    @pytest.mark.parametrize(
        "message",
        [
            "ReferenceError: foo is not defined",
            "TypeError: parse is not a function",
            "TypeError: Cannot read properties of undefined (reading 'x')",
            "SyntaxError: Unexpected token '}'",
            "Error: Cannot find module './missing'",
            "Error: Failed to resolve import './missing' from 'x.ts'",
            "SyntaxError: The requested module './a.js' does not provide an export named 'b'",
            "Error: something wrapped: x is not a function",
        ],
    )
    def test_invalid_error_kinds(self, agent_repo: Repo, message: str) -> None:
        red_commit(agent_repo, f"it error parses {message}\n")
        assert gate(agent_repo).note == "tests-invalid-red"

    @pytest.mark.parametrize(
        "message",
        [
            "AssertionError: expected 2 to be 3",
            "TestingLibraryElementError: Unable to find an element with the text: Track",
            "Error: Test timed out in 5000ms.",
            "AssertionError: expected [ 'ReferenceError' ] to deeply equal []",
        ],
    )
    def test_other_failures_are_valid(self, agent_repo: Repo, message: str) -> None:
        red_commit(agent_repo, f"it error parses {message}\n")
        assert gate(agent_repo).passed

    def test_one_invalid_failure_spoils_a_valid_one(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it fail good\nit error bad ReferenceError: expect is not defined\n")
        result = gate(agent_repo)
        assert result.note == "tests-invalid-red"
        assert "bad" in text(result)
        assert "good" not in text(result).split("invalid red evidence")[1]

    def test_file_that_fails_to_load_is_invalid(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "needs app/core/src/parcel.ts\n")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "tests-invalid-red")
        assert "Failed to resolve import" in text(result)

    def test_load_error_in_one_file_spoils_a_valid_failure_in_another(
        self, agent_repo: Repo
    ) -> None:
        agent_repo.commit(
            {PARCEL: "it fail good\n", "app/core/other.test.ts": "needs app/core/src/other.ts\n"},
            "test: red",
        )
        agent_repo.commit(IMPL, "feat: impl")
        result = gate(agent_repo)
        assert result.note == "tests-invalid-red"
        assert "app/core/other.test.ts" in text(result)

    def test_report_shows_the_first_error_line_only(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it error parses ReferenceError: nope\n")
        report = text(gate(agent_repo))
        assert "ReferenceError: nope" in report
        assert "at x" not in report


class TestScopeOfTheClassification:
    """Only tests added or changed by the leading test-only commits are judged."""

    def legacy_repo(self, make_repo, body: str) -> Repo:
        repo = make_repo()
        repo.commit({"app/core/legacy.test.ts": body}, "test: legacy")
        repo.branch(BRANCH)
        return repo

    def test_invalid_failure_in_an_untouched_file_is_ignored(self, make_repo) -> None:
        repo = self.legacy_repo(make_repo, "it error legacy TypeError: boom\n")
        red_commit(repo, "it fail parses\n")
        assert gate(repo).passed

    def test_valid_failure_only_in_an_untouched_file_is_not_red(self, make_repo) -> None:
        repo = self.legacy_repo(make_repo, "it fail legacy\n")
        red_commit(repo, "it pass parses\n")
        result = gate(repo)
        assert (result.passed, result.note) == (False, "tests-not-red")
        assert "not in the tests this branch added or changed" in text(result)

    def test_deleted_test_file_is_not_part_of_the_changed_set(self, make_repo) -> None:
        repo = self.legacy_repo(make_repo, "it fail legacy\n")
        repo.commit({"app/core/legacy.test.ts": None}, "test: drop legacy")
        repo.commit(IMPL, "feat: impl")
        assert gate(repo).note == "tests-not-red"

    def test_changes_from_every_leading_commit_count(self, agent_repo: Repo) -> None:
        agent_repo.commit({PARCEL: "it fail good\n"}, "test: first")
        agent_repo.commit(
            {"app/core/b.test.ts": "it error bad ReferenceError: x\n"}, "test: second"
        )
        agent_repo.commit(IMPL, "feat: impl")
        assert gate(agent_repo).note == "tests-invalid-red"


class TestRunnerProblems:
    def test_green_run_is_not_red(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it pass parses\n")
        assert gate(agent_repo).note == "tests-not-red"

    def test_missing_report_is_not_red(self, agent_repo: Repo) -> None:
        agent_repo.commit({PARCEL: "it fail parses\n", "app/e2e/crash": "x\n"}, "test: red")
        agent_repo.commit(IMPL, "feat: impl")
        result = gate(agent_repo)
        assert (result.passed, result.note) == (False, "tests-not-red")
        assert "no JSON report" in text(result)

    def test_garbage_report_is_not_red(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it fail parses\n")
        cmd = "echo 'not json' > {report}; exit 1"
        result = gate(agent_repo, test_cmd=cmd)
        assert (result.passed, result.note) == (False, "tests-not-red")
        assert "unreadable JSON report" in text(result)

    def test_command_without_the_placeholder_uses_the_summary_line(self, agent_repo: Repo) -> None:
        red_commit(agent_repo, "it fail parses\n")
        assert gate(agent_repo, test_cmd=RUNNER_CMD).note == "tests-first"


class TestDefaults:
    def test_default_command_asks_vitest_for_a_json_report(self) -> None:
        assert "{report}" in tdd_order.DEFAULT_TEST_CMD
        assert "--reporter=json" in tdd_order.DEFAULT_TEST_CMD
        assert "--reporter=default" in tdd_order.DEFAULT_TEST_CMD
