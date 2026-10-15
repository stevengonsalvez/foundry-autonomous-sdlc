"""Guard rails for the UI proof workflows: baseline wiring and the trust boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_ci_captures_the_base_commit_best_effort_and_uploads_it() -> None:
    steps = _load("ci.yml")["jobs"]["ui-screenshots"]["steps"]
    by_name = {s.get("name"): s for s in steps}

    checkout = by_name["Check out the base commit"]
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert checkout["with"]["persist-credentials"] is False

    for name in ("Check out the base commit", "Build the base app", "Capture baseline screenshots"):
        assert by_name[name]["continue-on-error"] is True, f"{name} must never fail the PR"

    capture = by_name["Capture baseline screenshots"]["run"]
    assert "scripts/ui/capture.mjs" in capture
    assert "--out-dir ui-screenshots-base" in capture

    upload = by_name["Upload baseline UI screenshots artifact"]
    assert upload["with"]["name"] == "ui-screenshots-base"
    assert upload["with"]["if-no-files-found"] == "ignore"

    # the PR artifact is still mandatory and unchanged
    pr_upload = by_name["Upload UI screenshots artifact"]
    assert pr_upload["with"]["name"] == "ui-screenshots"
    assert pr_upload["with"]["if-no-files-found"] == "error"


def test_ui_proof_keeps_its_trust_boundary_and_permissions() -> None:
    wf = _load("ui-proof.yml")
    assert wf["permissions"] == {"contents": "write", "pull-requests": "write"}

    steps = wf["jobs"]["publish"]["steps"]
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["ref"] == "main"

    downloads = [s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact")]
    paths = {d["with"]["name"]: d["with"]["path"] for d in downloads}
    assert paths == {
        "ui-screenshots": "untrusted-screenshots",
        "ui-screenshots-base": "untrusted-screenshots-base",
    }
    base_dl = next(d for d in downloads if d["with"]["name"] == "ui-screenshots-base")
    assert "base_present" in base_dl["if"]

    publish = next(s for s in steps if s.get("name") == "Validate and publish screenshots")
    assert "python -m scripts.ui.publish_proof" in publish["run"]
    assert '--base-dir "$BASE_DIR"' in publish["run"]
