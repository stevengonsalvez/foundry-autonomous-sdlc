"""Wrapper for GitGuardian ggshield that handles API quota exhaustion gracefully.

When ggshield fails with quota exhaustion ('no more API calls available'),
this wrapper emits a GitHub Actions ::warning:: and job summary line and exits 0,
preventing false-positive CI failures while keeping real findings (exit code 1)
and gitleaks enforcing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

QUOTA_ERROR_SUBSTRING = "no more API calls available"


def run_ggshield(args: list[str]) -> int:
    api_key = os.environ.get("GITGUARDIAN_API_KEY", "").strip()
    if not api_key:
        print(
            "::warning::GITGUARDIAN_API_KEY not set — add it via "
            "'gh secret set GITGUARDIAN_API_KEY' to enable ggshield."
        )
        return 0

    executable = shutil.which("ggshield")
    cmd = [executable, *args] if executable else [sys.executable, "-m", "ggshield", *args]

    proc = subprocess.run(cmd, capture_output=True, text=True)

    if proc.stdout:
        sys.stdout.write(proc.stdout)
        sys.stdout.flush()
    if proc.stderr:
        sys.stderr.write(proc.stderr)
        sys.stderr.flush()

    if proc.returncode == 0:
        return 0

    combined_output = f"{proc.stdout}\n{proc.stderr}"
    if QUOTA_ERROR_SUBSTRING in combined_output:
        warning_msg = (
            "GitGuardian API quota exhausted (no more API calls available). "
            "Scan skipped; required Gitleaks secret gate remains active."
        )
        print(f"::warning::{warning_msg}")

        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_file:
            summary_path = Path(summary_file)
            summary_text = (
                "### GitGuardian Secret Scan\n\n"
                "> [!WARNING]\n"
                "> **GitGuardian API quota exhausted**: no more API calls available.\n"
                "> Scan was skipped. Required `gitleaks` gate remains active and enforcing.\n\n"
            )
            try:
                with summary_path.open("a", encoding="utf-8") as f:
                    f.write(summary_text)
            except OSError as err:
                sys.stderr.write(f"Failed to write GITHUB_STEP_SUMMARY: {err}\n")

        return 0

    return proc.returncode


def main() -> None:
    sys.exit(run_ggshield(sys.argv[1:]))


if __name__ == "__main__":
    main()
