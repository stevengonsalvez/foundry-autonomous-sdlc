from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO_ROOT


def entry(covered: int, total: int) -> dict:
    return {"lines": {"total": total, "covered": covered, "skipped": 0, "pct": 0}}


def write_summary(path: Path, files: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    total_c = sum(f["lines"]["covered"] for f in files.values())
    total_t = sum(f["lines"]["total"] for f in files.values())
    path.write_text(json.dumps({"total": entry(total_c, total_t), **files}))


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.gates.coverage_report", "--root", str(root), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def app(tmp_path: Path) -> Path:
    return tmp_path / "app"


def test_merged_summary_is_grouped_by_workspace(app: Path) -> None:
    write_summary(
        app / "coverage" / "coverage-summary.json",
        {
            str(app / "core/src/a.ts"): entry(90, 100),
            str(app / "core/src/b.ts"): entry(10, 10),
            str(app / "api/src/c.ts"): entry(80, 100),
        },
    )
    proc = run(app)
    assert proc.returncode == 0, proc.stderr
    assert "core" in proc.stdout and "100/110" in proc.stdout
    assert "api" in proc.stdout and "80/100" in proc.stdout
    assert "TOTAL" in proc.stdout and "180/210" in proc.stdout


def test_per_workspace_summaries_are_combined(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(95, 100)})
    write_summary(app / "web/coverage/coverage-summary.json", {"b.tsx": entry(85, 100)})
    proc = run(app)
    assert proc.returncode == 0
    assert "180/200" in proc.stdout


def test_below_threshold_fails(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(79, 100)})
    proc = run(app)
    assert proc.returncode == 1
    assert "BELOW THRESHOLD" in proc.stdout


def test_exactly_at_threshold_passes(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(80, 100)})
    assert run(app).returncode == 0


def test_threshold_is_configurable(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(85, 100)})
    assert run(app, "--min", "90").returncode == 1


def test_a_strong_workspace_cannot_hide_a_collapse_in_the_total(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(1000, 1000)})
    write_summary(app / "web/coverage/coverage-summary.json", {"b.tsx": entry(0, 100)})
    proc = run(app)
    assert proc.returncode == 0  # the gate is the total, as the architecture defines it
    assert "0.00%" in proc.stdout  # but the weak workspace is visible in the table


def test_no_summary_is_an_error_not_a_pass(app: Path) -> None:
    app.mkdir()
    proc = run(app)
    assert proc.returncode == 2
    assert "did test:coverage run" in proc.stderr


def test_zero_measured_lines_fails(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {})
    assert run(app).returncode == 1


def test_step_summary_is_written(
    app: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(90, 100)})
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert run(app).returncode == 0
    assert "### Line coverage" in target.read_text()


def test_a_required_workspace_without_data_is_an_error(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(95, 100)})
    proc = run(app, "--require-workspaces", "core,web")
    assert proc.returncode == 2
    assert "web" in proc.stderr


def test_required_workspaces_present_passes(app: Path) -> None:
    write_summary(app / "core/coverage/coverage-summary.json", {"a.ts": entry(95, 100)})
    write_summary(app / "web/coverage/coverage-summary.json", {"b.tsx": entry(85, 100)})
    assert run(app, "--require-workspaces", "core,web").returncode == 0
