"""Static checks on the deployment workflows: the rules that cannot be exercised without GitHub."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ROOT / ".github" / "workflows"
CD = yaml.safe_load((WORKFLOWS / "cd.yml").read_text())
PAGES = yaml.safe_load((WORKFLOWS / "pages.yml").read_text())
CI = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())
# PyYAML reads the bare key `on` as the boolean True.
TRIGGERS = True


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job["steps"]


def step_index(job: dict[str, Any], needle: str) -> int:
    for i, step in enumerate(steps(job)):
        if needle in step.get("run", "") or needle in step.get("name", ""):
            return i
    raise AssertionError(f"no step mentioning {needle!r}")


@pytest.mark.parametrize("name", ["cd.yml", "pages.yml"])
def test_every_action_is_pinned_to_a_commit_with_a_version_comment(name: str) -> None:
    text = (WORKFLOWS / name).read_text()
    uses = re.findall(r"^\s*(?:- )?uses: (\S+)(.*)$", text, flags=re.MULTILINE)
    assert uses
    for ref, rest in uses:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), ref
        assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), f"{ref} has no version comment"


def test_actions_match_the_commits_ci_already_uses() -> None:
    ci_pins = dict(re.findall(r"uses: (\S+)@([0-9a-f]{40})", (WORKFLOWS / "ci.yml").read_text()))
    for name in ("cd.yml", "pages.yml"):
        for action, pin in re.findall(
            r"uses: (\S+)@([0-9a-f]{40})", (WORKFLOWS / name).read_text()
        ):
            if action in ci_pins:
                assert pin == ci_pins[action], f"{name}: {action} differs from ci.yml"


@pytest.mark.parametrize("workflow", [CD, PAGES], ids=["cd", "pages"])
def test_every_job_has_a_timeout_and_every_shell_step_the_strict_shell(workflow: dict) -> None:
    assert workflow["defaults"]["run"]["shell"] == "bash -euo pipefail {0}"
    for name, job in workflow["jobs"].items():
        assert isinstance(job.get("timeout-minutes"), int), f"{name} has no timeout-minutes"
        assert not any("shell" in s for s in steps(job)), f"{name} overrides the shell"


@pytest.mark.parametrize("name", ["cd.yml", "pages.yml"])
def test_no_expression_is_ever_interpolated_into_a_shell_script(name: str) -> None:
    workflow = yaml.safe_load((WORKFLOWS / name).read_text())
    for job_name, job in workflow["jobs"].items():
        for step in steps(job):
            assert "${{" not in step.get("run", ""), f"{job_name}: {step.get('name')}"


def test_no_secrets_and_no_credentials_other_than_the_workflow_token() -> None:
    for name in ("cd.yml", "pages.yml"):
        text = (WORKFLOWS / name).read_text()
        assert "secrets." not in text
        assert not re.search(r"azure/login|client-secret|AZURE_", text, re.IGNORECASE)
        assert "github.event.pull_request" not in text
        assert "head_ref" not in text and "head_commit" not in text


def test_cd_grants_nothing_by_default_and_each_job_declares_what_it_needs() -> None:
    assert CD["permissions"] == {"contents": "read"}
    allowed = {"contents", "actions", "deployments", "issues", "pull-requests"}
    for name, job in CD["jobs"].items():
        permissions = job["permissions"]
        assert set(permissions) <= allowed, f"{name} asks for {set(permissions) - allowed}"
        assert set(permissions.values()) <= {"read", "write"}
    writers = {n for n, j in CD["jobs"].items() if "write" in j["permissions"].values()}
    assert writers == {"stage", "promote", "rollback", "superseded"}
    assert CD["jobs"]["build"]["permissions"] == {"contents": "read"}  # runs repository code
    assert CD["jobs"]["smoke"]["permissions"] == {"contents": "read"}
    assert CD["jobs"]["soak"]["permissions"] == {"contents": "read"}


def test_triggers_run_after_a_green_push_ci_on_main_or_on_demand() -> None:
    on = CD[TRIGGERS]
    assert on["workflow_run"] == {"workflows": ["CI"], "types": ["completed"], "branches": ["main"]}
    assert CI["name"] == "CI"
    inputs = on["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"sha", "inject_fault", "soak_minutes"}
    assert inputs["inject_fault"]["options"] == ["none", "smoke"]
    assert inputs["inject_fault"]["default"] == "none"
    assert inputs["soak_minutes"]["default"] == "10"
    condition = " ".join(CD["jobs"]["plan"]["if"].split())
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition


def test_a_newer_run_cancels_an_older_one_but_ignored_runs_cannot() -> None:
    concurrency = CD["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "'cd'" in concurrency["group"] and "cd-ignored-" in concurrency["group"]
    assert PAGES["concurrency"] == {"group": "pages", "cancel-in-progress": False}


def test_the_jobs_form_the_agreed_chain() -> None:
    jobs = CD["jobs"]
    assert set(jobs) == {
        "plan",
        "build",
        "stage",
        "smoke",
        "soak",
        "promote",
        "rollback",
        "superseded",
    }
    assert "build" in jobs["stage"]["needs"]
    assert "stage" in jobs["smoke"]["needs"]
    assert "smoke" in jobs["soak"]["needs"]
    assert {"stage", "smoke", "soak"} <= set(jobs["promote"]["needs"])
    assert jobs["build"]["needs"] == "plan"


def test_rollback_triggers_on_every_failing_job_and_never_on_a_cancel() -> None:
    condition = " ".join(CD["jobs"]["rollback"]["if"].split())
    assert condition.startswith("!cancelled()")
    for job in ("build", "stage", "smoke", "soak", "promote"):
        assert f"needs.{job}.result == 'failure'" in condition
    assert set(CD["jobs"]["rollback"]["needs"]) >= {
        "plan",
        "build",
        "stage",
        "smoke",
        "soak",
        "promote",
    }
    assert CD["jobs"]["superseded"]["if"].startswith("cancelled()")


def test_only_promote_tags_prod_and_only_after_prod_is_live() -> None:
    for name, job in CD["jobs"].items():
        mentions = [s for s in steps(job) if "create-tag" in s.get("run", "")]
        assert bool(mentions) == (name in ("promote", "superseded")), name
    promote = CD["jobs"]["promote"]
    order = [
        step_index(promote, "deploy_branch promote"),
        step_index(promote, "pages_deploy"),
        step_index(promote, "verify_live"),
        step_index(promote, "create-tag"),
    ]
    assert order == sorted(order)
    # a failure after the tag (bookkeeping) must not roll the release back
    for step in steps(promote)[order[-1] + 1 :]:
        assert step["continue-on-error"] is True


def test_the_ticket_is_flagged_last_and_even_when_an_earlier_step_failed() -> None:
    last = steps(CD["jobs"]["rollback"])[-1]
    assert last["if"] == "always()"
    assert "flag_ticket" in last["run"]
    assert "job.status" in last["env"]["ROLLBACK_OK"]


def test_the_fault_is_injected_into_the_built_artifact_not_the_source() -> None:
    build = CD["jobs"]["build"]
    npm_build = step_index(build, "npm run build:pages")
    stamp = step_index(build, "artifact stamp")
    assert npm_build < stamp
    run = steps(build)[stamp]["run"]
    assert run.index("fault-smoke") < run.index("artifact stamp")  # break first, then record it
    assert "dist-pages" in run


def test_the_smoke_and_soak_jobs_test_the_live_staging_url_for_the_deployed_sha() -> None:
    smoke_env = steps(CD["jobs"]["smoke"])[-2]["env"]
    assert smoke_env == {
        "SMOKE_URL": "${{ needs.plan.outputs.staging_url }}",
        "EXPECTED_SHA": "${{ needs.plan.outputs.sha }}",
    }
    assert "SOAK_MINUTES" in CD["jobs"]["soak"]["env"]


def test_pages_is_the_only_deployer_and_renders_the_deploy_branch() -> None:
    assert not any("deploy-pages" in str(job) for job in CD["jobs"].values())
    text = (WORKFLOWS / "pages.yml").read_text()
    for needle in (
        "deploy-checkout/prod",
        "deploy-checkout/staging",
        "PROD_DIST",
        "STAGING_DIST",
        "CONTROL_CENTER_SRC",
        "apps/control-center",
        "metrics-checkout",
    ):
        assert needle in text
    assert set(PAGES[TRIGGERS]) == {"workflow_dispatch", "push", "schedule"}


def test_every_script_module_a_workflow_runs_exists() -> None:
    text = (WORKFLOWS / "cd.yml").read_text()
    modules = set(re.findall(r"python -m scripts\.cd\.(\w+)", text))
    assert {
        "plan",
        "artifact",
        "deploy_branch",
        "pages_deploy",
        "verify_live",
        "soak",
        "release_ops",
        "flag_ticket",
    } <= modules
    for module in modules:
        assert (ROOT / "scripts" / "cd" / f"{module}.py").is_file(), module


def test_plan_outputs_are_all_declared_before_other_jobs_use_them() -> None:
    declared = set(CD["jobs"]["plan"]["outputs"])
    used = set(re.findall(r"needs\.plan\.outputs\.(\w+)", (WORKFLOWS / "cd.yml").read_text()))
    assert used <= declared, used - declared


def test_no_em_dashes_in_what_this_pipeline_ships() -> None:
    files = [
        *(ROOT / "scripts" / "cd").glob("*.py"),
        *(ROOT / "scripts" / "tests" / "cd").glob("*.py"),
        WORKFLOWS / "cd.yml",
        WORKFLOWS / "pages.yml",
        ROOT / "scripts" / "build_pages.sh",
        ROOT / "docs" / "cd.md",
        *(ROOT / "app" / "e2e" / "smoke").glob("*.ts"),
    ]
    offenders = [
        str(f.relative_to(ROOT)) for f in files if f.exists() and chr(0x2014) in f.read_text()
    ]
    assert offenders == []
