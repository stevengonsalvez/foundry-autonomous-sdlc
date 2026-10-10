"""Red and green are decided from the vitest JSON report, never from the exit code alone."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from sdlc_agents.coder import shell
from sdlc_agents.coder.testrun import TestRunner, is_valid_red, parse_vitest_json, with_json_reporter

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
        _file(OLD, "failed", [_assertion("validates", "failed", "AssertionError: expected 1 to be 2")]),
    ))
    assert report.load_errors == (f"{ROOT}/{NEW}",)
    assert not report.is_red_for([NEW])
    assert "Failed to load url" in report.failure_excerpt()


def test_failure_only_in_an_unrelated_file_is_not_red_for_the_new_tests() -> None:
    report = parse_vitest_json(_report(
        _file(NEW, "passed", [_assertion("shows eta", "passed")]),
        _file(OLD, "failed", [_assertion("validates", "failed", "AssertionError: expected 1 to be 2")]),
    ))
    assert not report.is_red_for([NEW])


def test_a_new_suite_vitest_did_not_collect_is_never_red() -> None:
    failing = _assertion("validates", "failed", "AssertionError: expected 1 to be 2")
    report = parse_vitest_json(_report(_file(OLD, "failed", [failing])))
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


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_runner_never_follows_a_planted_report(tmp_path: Path, kind: str) -> None:
    secret = tmp_path / "secret.json"
    secret.write_text(_report(_file(NEW, "passed", [_assertion("TOPSECRET", "passed")])))
    report_path = tmp_path / "report.json"
    plant = (f"import os; os.symlink({str(secret)!r}, {str(report_path)!r})" if kind == "symlink"
             else f"import os; os.mkfifo({str(report_path)!r})")
    script = tmp_path / "plant.py"
    script.write_text(plant + "\n")
    runner = TestRunner(test_cmd=f"{sys.executable} {script}", cwd=tmp_path, report_path=report_path, env=None)
    started = time.monotonic()
    outcome = runner.run(timeout_s=30)
    assert not outcome.green
    assert outcome.report.summary() == "no test report"
    assert "TOPSECRET" not in json.dumps(outcome.report.failure_excerpt())
    assert time.monotonic() - started < 10


# -- valid red: only assertion failures count ----------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
CHECKOUT = "/srv/sdlc-work/j-8-1/checkout"
DESIGNED = "app/web/tests/estimated-delivery.test.tsx"


def _fixture(name: str):  # type: ignore[no-untyped-def]
    return parse_vitest_json((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", ["valid_assertion.json", "valid_testing_library.json"])
def test_assertion_and_testing_library_failures_are_a_valid_red(name: str) -> None:
    verdict = _fixture(name).red_verdict([DESIGNED])
    assert verdict.kind == "red", verdict
    assert verdict.invalid == ()


@pytest.mark.parametrize(("name", "first_line"), [
    ("invalid_reference_error.json", "ReferenceError: expect is not defined"),
    ("mixed_valid_and_type_error.json", "TypeError: formatEta is not a function"),
    ("timeout.json", "Error: Test timed out in 5000ms."),
    ("load_error.json", 'Error: Failed to resolve import "../src/eta"'),
])
def test_broken_tests_are_invalid_not_red(name: str, first_line: str) -> None:
    verdict = _fixture(name).red_verdict([DESIGNED])
    assert verdict.kind == "invalid", verdict
    assert any(DESIGNED in line and first_line in line for line in verdict.invalid), verdict.invalid


def test_passing_or_uncollected_new_tests_are_not_a_red() -> None:
    passing = parse_vitest_json(_report(_file(NEW, "passed", [_assertion("a", "passed")])))
    assert passing.red_verdict([NEW]).kind == "not-red"
    missing = parse_vitest_json(_report(_file(OLD, "failed", [_assertion("x", "failed", "AssertionError: x")])))
    verdict = missing.red_verdict([NEW])
    assert verdict.kind == "invalid"                       # the designer put it where vitest does not look
    assert verdict.invalid == (f"{NEW}: not collected by vitest (check the file name and location)",)
    assert parse_vitest_json("garbage").red_verdict([NEW]).kind == "not-red"


@pytest.mark.parametrize(("message", "valid"), [
    ("AssertionError: expected 1 to be 2", True),
    ("Error: expect(received).toEqual(expected)\n\nExpected: 1\nReceived: 2", True),
    ("TestingLibraryElementError: Unable to find role=\"heading\"", True),
    ("ReferenceError: expect is not defined", False),
    ("TypeError: Cannot read properties of undefined (reading 'eta')", False),
    ("SyntaxError: Unexpected token '<'", False),
    ("Error: Cannot find module '../src/eta'", False),
    ("SyntaxError: The requested module './x' does not provide an export named 'eta'", False),
    ("Error: Test timed out in 5000ms.", False),
    ("Error: something odd", False),
])
def test_failure_classification(message: str, valid: bool) -> None:
    assert is_valid_red(message) is valid


def test_report_paths_are_never_resolved_on_the_filesystem(tmp_path: Path) -> None:
    secret_dir = tmp_path / "root-only"
    secret_dir.mkdir()
    checkout = tmp_path / "checkout"
    (checkout / "app").mkdir(parents=True)
    (checkout / "app/link").symlink_to(secret_dir)      # planted by the engine user
    name = f"{checkout}/app/link/x.test.ts"
    report = parse_vitest_json(_report({"name": name, "status": "failed", "message": "", "assertionResults": [
        _assertion("t", "failed", "AssertionError: expected 1 to be 2")]}))
    assert report.failing_tests(str(checkout))[0][0] == "app/link/x.test.ts"
    assert report.failing_paths(str(checkout)) == ["app/link/x.test.ts"]
    outside = parse_vitest_json(_report({"name": "/etc/x.test.ts", "status": "failed", "message": "",
                                         "assertionResults": [_assertion("t", "failed", "AssertionError: x")]}))
    assert outside.failing_paths(str(checkout)) == ["/etc/x.test.ts"]


def test_captured_commands_time_out_even_when_a_grandchild_holds_the_pipes(tmp_path: Path) -> None:
    # subprocess.run(timeout=...) kills only the child, then waits for EOF the grandchild never sends.
    started = time.monotonic()
    code, out, _err = shell.capture(["sh", "-c", "sleep 30 & echo started; sleep 30"], cwd=tmp_path, env=None,
                                    timeout_s=1)
    assert code == shell.TIMEOUT_RC
    assert "started" in out
    assert time.monotonic() - started < 10
    assert shell.capture(["sh", "-c", "echo ok; echo warn >&2"], cwd=tmp_path, env=None, timeout_s=10) == (
        0, "ok\n", "warn\n")


def _proc(root: Path, pid: int, pgrp: int, rss_kb: int, hwm_kb: int, comm: str = "node") -> None:
    d = root / str(pid)
    d.mkdir()
    (d / "stat").write_text(f"{pid} ({comm} worker) S 1 {pgrp} {pgrp} 0 -1 4194560 0 0\n")
    (d / "status").write_text(f"Name:\t{comm}\nVmHWM:\t  {hwm_kb} kB\nVmRSS:\t  {rss_kb} kB\n")


def test_group_memory_sums_current_rss_and_keeps_the_largest_peak(tmp_path: Path) -> None:
    _proc(tmp_path, 100, 100, rss_kb=50_000, hwm_kb=60_000, comm="npm")
    _proc(tmp_path, 101, 100, rss_kb=700_000, hwm_kb=900_000)
    _proc(tmp_path, 102, 555, rss_kb=9_999_999, hwm_kb=9_999_999)   # another group: not ours
    (tmp_path / "self").mkdir()
    assert shell.group_memory_kib(100, proc_root=tmp_path) == (750_000, 900_000)
    assert shell.group_memory_kib(100, proc_root=tmp_path / "missing") == (0, 0)


def test_the_last_run_reports_its_memory_peak_where_proc_exists(tmp_path: Path) -> None:
    shell.run([sys.executable, "-c", "x = bytearray(30_000_000); import time; time.sleep(1.5)"], cwd=tmp_path,
              timeout_s=30)
    peak = shell.take_memory()
    if Path("/proc/self/status").exists():
        assert peak is not None and peak.largest_kib >= 30_000
    else:
        assert peak is None
    assert shell.take_memory() is None          # taken once: a later step never reports a stale peak


def test_cgroup_memory_reports_limit_and_peak_when_present(tmp_path: Path) -> None:
    (tmp_path / "memory.max").write_text("4294967296\n")
    (tmp_path / "memory.peak").write_text("1073741824\n")
    assert shell.cgroup_memory(tmp_path) == "cgroup memory.max 4096 MiB, memory.peak 1024 MiB"
    (tmp_path / "memory.max").write_text("max\n")
    assert shell.cgroup_memory(tmp_path) == "cgroup memory.max max, memory.peak 1024 MiB"
    assert shell.cgroup_memory(tmp_path / "none") == ""
