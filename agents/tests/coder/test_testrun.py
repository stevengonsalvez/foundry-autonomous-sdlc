"""Red and green are decided from the vitest JSON report, never from the exit code alone."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from sdlc_agents.coder import shell
from sdlc_agents.coder.testrun import TestRunner, parse_vitest_json, with_json_reporter

ROOT = "/home/session/work/checkout"


def _assertion(name: str, status: str, msg: str = "") -> dict:
    return {"fullName": name, "title": name, "status": status, "failureMessages": [msg] if msg else []}


def _file(path: str, status: str, assertions: list[dict], message: str = "") -> dict:
    return {"name": f"{ROOT}/{path}", "status": status, "message": message, "assertionResults": assertions}


def _report(*files: dict) -> str:
    failed = sum(1 for f in files for a in f["assertionResults"] if a["status"] == "failed")
    passed = sum(1 for f in files for a in f["assertionResults"] if a["status"] == "passed")
    return json.dumps({"numTotalTests": failed + passed, "numFailedTests": failed, "numPassedTests": passed,
                       "success": failed == 0 and all(f["status"] == "passed" for f in files),
                       "testResults": list(files)})


NEW = "app/api/tests/parcel.test.ts"
OLD = "app/core/tests/core.test.ts"


def test_failed_assertion_in_the_new_test_file_is_red() -> None:
    report = parse_vitest_json(_report(
        _file(NEW, "failed", [_assertion("shows eta", "failed", "expected null to be '2026-10-12'")]),
        _file(OLD, "passed", [_assertion("validates", "passed")]),
    ))
    assert report.is_red_for([NEW])
    assert not report.green
    assert report.summary() == "2 tests: 1 failed, 1 passed, 0 files failed to load"
    assert "expected null" in report.failure_excerpt()


def test_import_error_is_not_red_even_with_a_failed_assertion_elsewhere() -> None:
    report = parse_vitest_json(_report(
        _file(NEW, "failed", [], message="Error: Failed to load url ../src/eta (resolved id: ../src/eta)"),
        _file(OLD, "failed", [_assertion("validates", "failed", "boom")]),
    ))
    assert report.load_errors == (f"{ROOT}/{NEW}",)
    assert not report.is_red_for([NEW])
    assert "Failed to load url" in report.failure_excerpt()


def test_failure_only_in_an_unrelated_file_is_not_red_for_the_new_tests() -> None:
    report = parse_vitest_json(_report(
        _file(NEW, "passed", [_assertion("shows eta", "passed")]),
        _file(OLD, "failed", [_assertion("validates", "failed", "boom")]),
    ))
    assert not report.is_red_for([NEW])


def test_a_new_suite_vitest_did_not_collect_is_not_red() -> None:
    report = parse_vitest_json(_report(_file(OLD, "failed", [_assertion("validates", "failed", "boom")])))
    assert not report.is_red_for([NEW, OLD])
    assert report.is_red_for([OLD, "app/api/tests/__fixtures__/data.json"])


def test_green_needs_tests_and_no_failures() -> None:
    assert parse_vitest_json(_report(_file(NEW, "passed", [_assertion("a", "passed")]))).green
    assert not parse_vitest_json(_report()).green


def test_garbage_report_is_neither_red_nor_green() -> None:
    for text in ("", "not json", "[]", json.dumps({"testResults": "x"})):
        report = parse_vitest_json(text)
        assert not report.parsed
        assert not report.green
        assert not report.is_red_for([NEW])
        assert report.summary() == "no test report"


def test_json_reporter_args_go_after_a_double_dash_for_npm_only() -> None:
    assert with_json_reporter("npm test", "/r.json") == \
        "npm test -- --reporter=default --reporter=json --outputFile.json=/r.json"
    assert with_json_reporter("npx vitest run", "/r.json") == \
        "npx vitest run --reporter=default --reporter=json --outputFile.json=/r.json"


def test_runner_reads_the_report_file_and_deletes_a_stale_one(tmp_path: Path) -> None:
    script = tmp_path / "fake.py"
    script.write_text(
        "import sys, pathlib\n"
        "out = [a for a in sys.argv if a.startswith('--outputFile.json=')][0].split('=', 1)[1]\n"
        f"pathlib.Path(out).write_text({_report(_file(NEW, 'passed', [_assertion('a', 'passed')]))!r})\n"
        "print('ran ok')\n"
    )
    report_path = tmp_path / "report.json"
    runner = TestRunner(test_cmd=f"{sys.executable} {script}", cwd=tmp_path, report_path=report_path, env=None)
    outcome = runner.run(timeout_s=30)
    assert outcome.green
    assert "ran ok" in outcome.output

    report_path.write_text(_report(_file(NEW, "passed", [_assertion("a", "passed")])))
    broken = TestRunner(test_cmd=f"{sys.executable} -c 'raise SystemExit(1)'", cwd=tmp_path,
                        report_path=report_path, env=None)
    outcome = broken.run(timeout_s=30)
    assert not outcome.green
    assert outcome.report.summary() == "no test report"


def test_shell_times_out_and_kills_the_process_group(tmp_path: Path) -> None:
    started = time.monotonic()
    result = shell.run([sys.executable, "-c", "import time; print('x', flush=True); time.sleep(30)"],
                       cwd=tmp_path, timeout_s=1)
    assert result.returncode == shell.TIMEOUT_RC
    assert "timed out" in result.output
    assert time.monotonic() - started < 10


def test_shell_cancel_stops_a_running_command(tmp_path: Path) -> None:
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    result = shell.run("sleep 30", cwd=tmp_path, timeout_s=60, cancel=cancel)
    assert result.returncode == shell.CANCELLED_RC


def test_shell_keeps_the_tail_of_huge_output(tmp_path: Path) -> None:
    result = shell.run([sys.executable, "-c", "print('a' * 5000 + 'END')"], cwd=tmp_path, timeout_s=30,
                       max_output=100)
    assert result.output.endswith("END\n")
    assert len(result.output) < 200


def test_shell_reports_a_missing_binary_as_a_failed_command(tmp_path: Path) -> None:
    result = shell.run(["definitely-not-a-binary-xyz"], cwd=tmp_path, timeout_s=5)
    assert result.returncode == 127
    assert "definitely-not-a-binary-xyz" in result.output


def test_protected_suites_must_run_and_pass_every_assertion() -> None:
    report = parse_vitest_json(_report(
        _file(NEW, "passed", [_assertion("a", "passed"), _assertion("b", "passed")]),
        _file(OLD, "passed", [_assertion("c", "passed")]),
    ))
    assert report.suites_passed([NEW, OLD, "app/web/tests/helper.ts"])
    assert not report.suites_passed(["app/web/tests/missing.test.ts"])
    skipped = parse_vitest_json(_report(_file(NEW, "passed", [_assertion("a", "passed"), _assertion("b", "skipped")])))
    assert not skipped.suites_passed([NEW])
    empty = parse_vitest_json(_report(_file(NEW, "passed", [])))
    assert not empty.suites_passed([NEW])


def test_failing_paths_are_repo_relative() -> None:
    report = parse_vitest_json(_report(
        _file(NEW, "failed", [_assertion("a", "failed", "x")]),
        _file(OLD, "passed", [_assertion("c", "passed")]),
    ))
    assert report.failing_paths(ROOT) == [NEW]


def test_json_reporter_quotes_the_path_and_reuses_an_existing_separator() -> None:
    assert with_json_reporter("npm test -- --run", "/a b/r.json") == \
        "npm test -- --run --reporter=default --reporter=json '--outputFile.json=/a b/r.json'"


def test_shell_kills_detached_children_when_the_command_exits(tmp_path: Path) -> None:
    marker = tmp_path / "late"
    script = f"(sleep 1; touch {marker}) > /dev/null 2>&1 &\necho started\n"
    result = shell.run(["sh", "-c", script], cwd=tmp_path, timeout_s=10)
    assert result.returncode == 0
    time.sleep(1.5)
    assert not marker.exists()


def test_shell_aborts_as_soon_as_the_output_matches(tmp_path: Path) -> None:
    started = time.monotonic()
    script = ("import time\nprint('Authentication required. Please visit the URL to log in:', flush=True)\n"
              "time.sleep(30)\n")
    result = shell.run([sys.executable, "-c", script], cwd=tmp_path, timeout_s=60,
                       abort_on=lambda text: "login wall" if "Authentication required" in text else None)
    assert result.returncode == shell.ABORTED_RC
    assert "[aborted: login wall]" in result.output
    assert time.monotonic() - started < 10
