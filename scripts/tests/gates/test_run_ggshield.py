from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.gates.run_ggshield import (
    QUOTA_ERROR_SUBSTRING,
    run_ggshield,
)


class TestRunGGShield:
    def test_quota_exhaustion_emits_warning_writes_summary_and_exits_0(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        summary_file = tmp_path / "step_summary.md"
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        mock_proc = MagicMock(
            returncode=128,
            stdout="",
            stderr="Error: Could not perform the requested action: no more API calls available.\n",
        )

        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 0
        mock_run.assert_called_once()
        captured = capsys.readouterr()
        assert "::warning::" in captured.out
        assert QUOTA_ERROR_SUBSTRING in captured.out or "quota" in captured.out.lower()

        # Check job summary was written
        assert summary_file.exists()
        summary_content = summary_file.read_text(encoding="utf-8")
        assert "GitGuardian" in summary_content
        assert "quota" in summary_content.lower()

    def test_quota_exhaustion_without_trailing_period_exits_0(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        summary_file = tmp_path / "step_summary.md"
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        mock_proc = MagicMock(
            returncode=128,
            stdout="",
            stderr="Error: Could not perform the requested action: no more API calls available\n",
        )

        with patch("subprocess.run", return_value=mock_proc):
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 0
        captured = capsys.readouterr()
        assert "::warning::" in captured.out

    def test_real_secrets_found_exits_code_1(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")

        mock_proc = MagicMock(
            returncode=1,
            stdout="Incident: Secret detected: Generic High Entropy Secret at line 42\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_proc):
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 1
        captured = capsys.readouterr()
        assert "Secret detected" in captured.out
        assert "::warning::" not in captured.out

    def test_finding_with_quota_phrase_in_stdout_and_stderr_exits_1(
        self, monkeypatch, capsys
    ) -> None:
        """Exit code 1 (findings) must never be swallowed even if quota phrase is present."""
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")

        mock_proc = MagicMock(
            returncode=1,
            stdout="Incident: Secret detected: line 10 # no more API calls available\n",
            stderr="Error: Could not perform the requested action: no more API calls available.\n",
        )

        with patch("subprocess.run", return_value=mock_proc):
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 1
        captured = capsys.readouterr()
        assert "::warning::" not in captured.out

    def test_finding_with_quota_phrase_in_stdout_only_exits_1(
        self, monkeypatch, capsys
    ) -> None:
        """Exit code 1 with quota phrase in scanned file stdout must exit 1."""
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")

        mock_proc = MagicMock(
            returncode=1,
            stdout="Incident: Secret detected in no more API calls available.py\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_proc):
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 1
        captured = capsys.readouterr()
        assert "::warning::" not in captured.out

    def test_quota_phrase_in_stdout_only_with_rc_128_exits_128(
        self, monkeypatch, capsys
    ) -> None:
        """Quota phrase in stdout only must not trigger bypass; must check stderr line."""
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")

        mock_proc = MagicMock(
            returncode=128,
            stdout="Scanning file: test_no more API calls available.py\n",
            stderr="Fatal: unrelated error occurred\n",
        )

        with patch("subprocess.run", return_value=mock_proc):
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 128
        captured = capsys.readouterr()
        assert "::warning::" not in captured.out

    def test_clean_scan_exits_0(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")

        mock_proc = MagicMock(
            returncode=0,
            stdout="No secrets found. 12 files scanned.\n",
            stderr="",
        )

        with patch("subprocess.run", return_value=mock_proc):
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 0
        captured = capsys.readouterr()
        assert "No secrets found" in captured.out
        assert "::warning::" not in captured.out

    def test_missing_api_key_emits_warning_and_exits_0(self, monkeypatch, capsys) -> None:
        monkeypatch.delenv("GITGUARDIAN_API_KEY", raising=False)

        with patch("subprocess.run") as mock_run:
            code = run_ggshield(["secret", "scan", "ci"])

        assert code == 0
        mock_run.assert_not_called()
        captured = capsys.readouterr()
        assert "::warning::GITGUARDIAN_API_KEY not set" in captured.out

    def test_unexpected_fatal_error_fails(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("GITGUARDIAN_API_KEY", "mock-key")

        mock_proc = MagicMock(
            returncode=2,
            stdout="",
            stderr="Error: Invalid command line option --unknown-flag\n",
        )

        with patch("subprocess.run", return_value=mock_proc):
            code = run_ggshield(["secret", "scan", "--unknown-flag"])

        assert code == 2
        captured = capsys.readouterr()
        assert "Invalid command line option" in captured.err
        assert "::warning::" not in captured.out
