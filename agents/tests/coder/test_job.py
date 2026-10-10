"""Job request validation, persisted state and the redacting log."""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from sdlc_agents.coder.job import JobSpec, JobSpecError, JobState, JobStore, Mode, Redactor, Status
from sdlc_agents.ports import REPO


def request(**overrides: Any) -> dict[str, Any]:
    job: dict[str, Any] = {
        "job_id": "j-12-1", "repo": REPO, "base": "main", "branch": "agent/issue-12", "mode": "feature",
        "issue": {"number": 12, "title": "Show ETA", "body": "Show the estimated delivery date."},
        "spec": {"acceptance_criteria": ["ETA visible"], "notes": "use core"},
        "tests": [{"path": "app/web/tests/eta.test.ts", "content": "test"}],
        "test_cmd": "npm test", "max_iterations": 5, "deadline_s": 7200, "allowed_paths": ["app/"],
    }
    job.update(overrides)
    return job


def test_contract_request_parses_with_defaults() -> None:
    spec = JobSpec.from_request(request())
    assert spec.mode is Mode.FEATURE
    assert spec.issue_number == 12
    assert spec.workdir == "app"
    assert spec.install_cmd == "npm ci"
    assert spec.tests[0].path == "app/web/tests/eta.test.ts"
    assert JobSpec.from_request(spec.to_request()) == spec


@pytest.mark.parametrize(("overrides", "message"), [
    ({"job_id": "../etc"}, "job_id"),
    ({"repo": "someone/else"}, "repo"),
    ({"branch": "main"}, "branch"),
    ({"branch": "agent/x..y"}, "branch"),
    ({"mode": "yolo"}, "mode"),
    ({"tests": []}, "tests"),
    ({"tests": [{"path": "app/src/x.ts", "content": "x"}]}, "test glob"),
    ({"tests": [{"path": ".github/tests/x.test.ts", "content": "x"}]}, "allowed_paths"),
    ({"max_iterations": 0}, "max_iterations"),
    ({"deadline_s": 999999}, "deadline_s"),
    ({"allowed_paths": []}, "allowed_paths"),
    ({"allowed_paths": ["../"]}, "allowed_paths"),
    ({"test_cmd": ""}, "test_cmd"),
    ({"issue": {"title": "no number"}}, "issue"),
    ({"workdir": "../x"}, "workdir"),
])
def test_invalid_requests_are_rejected_with_the_field_named(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(JobSpecError, match=message):
        JobSpec.from_request(request(**overrides))


def test_maintenance_needs_no_tests() -> None:
    spec = JobSpec.from_request(request(mode="maintenance", tests=[], pr={"number": 13},
                                        allowed_paths=["app/web/tests/a.test.ts"]))
    assert spec.mode is Mode.MAINTENANCE
    assert spec.tests == ()


def test_store_round_trips_state_and_rejects_unknown_ids(tmp_path: Path) -> None:
    store = JobStore(tmp_path, Redactor())
    assert store.load("j-1") is None
    state = JobState.new(JobSpec.from_request(request(job_id="j-1")), started_at="2026-10-10T12:00:00Z")
    state.iterations = 2
    store.save(state)
    loaded = store.load("j-1")
    assert loaded is not None
    assert loaded.iterations == 2
    assert loaded.status is Status.RUNNING
    assert json.loads((tmp_path / "j-1" / "state.json").read_text())["job_id"] == "j-1"
    assert not list((tmp_path / "j-1").glob("*.tmp"))


def test_log_redacts_secrets_and_their_basic_auth_form_and_tails(tmp_path: Path) -> None:
    redactor = Redactor()
    store = JobStore(tmp_path, redactor)
    pat = "github_pat_ABCDEF0123456789"
    redactor.add(pat)
    redactor.add("")  # ignored, would otherwise redact everything
    basic = base64.b64encode(f"x-access-token:{pat}".encode()).decode()
    store.log("j-1", f"clone with {pat} and header {basic}")
    store.log("j-1", "x" * 10_000 + "END")
    text = (tmp_path / "j-1" / "log").read_text()
    assert pat not in text
    assert basic not in text
    assert "***" in text
    assert store.tail("j-1", 100).endswith("END\n")
    assert store.tail("missing") == ""
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "j-1").stat().st_mode) == 0o700


@pytest.mark.parametrize("value", ["nan", "inf", -1, 5, "x", None])
def test_model_cost_cap_must_be_a_sane_number(value: Any) -> None:
    with pytest.raises(JobSpecError, match="max_model_usd"):
        JobSpec.from_request(request(max_model_usd=value))


@pytest.mark.parametrize("tests", [[{"content": "no path"}], ["not an object"], [{"path": 3, "content": None}]])
def test_malformed_test_entries_are_a_spec_error_not_a_crash(tests: list[Any]) -> None:
    with pytest.raises(JobSpecError):
        JobSpec.from_request(request(tests=tests))


def test_json_secrets_also_redact_their_inner_strings() -> None:
    redactor = Redactor()
    redactor.add('{"access_token": "ya29.AAAAAAAAAAAAAAAAAAAA", '
                 '"refresh_token": "1//BBBBBBBBBBBBBBBBBB", "x": "short"}')
    text = redactor("refresh=1//BBBBBBBBBBBBBBBBBB access=ya29.AAAAAAAAAAAAAAAAAAAA keep=short")
    assert text == "refresh=*** access=*** keep=short"


def test_revise_needs_an_existing_pr_and_no_new_tests() -> None:
    spec = JobSpec.from_request(request(mode="revise", tests=[], pr={"number": 13}))
    assert spec.mode is Mode.REVISE
    assert spec.pr_number == 13
    assert spec.mode.commit_prefix == "fix"
    with pytest.raises(JobSpecError, match=r"pr\.number"):
        JobSpec.from_request(request(mode="revise", tests=[]))
    with pytest.raises(JobSpecError, match="tests"):
        JobSpec.from_request(request(mode="revise", pr={"number": 13}))


def test_maintenance_targets_a_pr_branch_with_test_file_scope() -> None:
    spec = JobSpec.from_request(request(
        job_id="j-pr14-1", mode="maintenance", branch="chore/update-home-heading", tests=[], pr={"number": 14},
        issue=None, allowed_paths=["app/web/tests/Home.test.tsx"]))
    assert spec.branch == "chore/update-home-heading"
    assert spec.pr_number == 14
    assert spec.issue_number == 14
    assert spec.allowed_paths == ("app/web/tests/Home.test.tsx",)


@pytest.mark.parametrize("branch", ["main", "-x", "chore/../main", "chore//x", "x.lock", "refs/heads/main", "chore/x/"])
def test_maintenance_never_pushes_to_main_or_odd_refs(branch: str) -> None:
    with pytest.raises(JobSpecError, match="branch"):
        JobSpec.from_request(request(mode="maintenance", branch=branch, tests=[], pr={"number": 14},
                                     allowed_paths=["app/web/tests/a.test.ts"]))


def test_feature_branches_stay_under_agent() -> None:
    with pytest.raises(JobSpecError, match="branch"):
        JobSpec.from_request(request(branch="chore/x"))


def test_deadline_defaults_to_two_hours_and_never_exceeds_it() -> None:
    body = request()
    del body["deadline_s"]
    assert JobSpec.from_request(body).deadline_s == 7200
    with pytest.raises(JobSpecError, match="deadline_s"):
        JobSpec.from_request(request(deadline_s=7201))


def test_maintenance_scope_must_be_test_files() -> None:
    with pytest.raises(JobSpecError, match="test glob"):
        JobSpec.from_request(request(mode="maintenance", branch="chore/x", tests=[], pr={"number": 14},
                                     allowed_paths=["app/web/src/Home.tsx"]))


@pytest.mark.parametrize("branch", ["HEAD", "master", "refs/tags/v1", "refs/heads/chore/x"])
def test_maintenance_refuses_protected_and_qualified_refs(branch: str) -> None:
    with pytest.raises(JobSpecError, match="branch"):
        JobSpec.from_request(request(mode="maintenance", branch=branch, tests=[], pr={"number": 14},
                                     allowed_paths=["app/web/tests/a.test.ts"]))


@pytest.mark.parametrize(("field", "value"), [
    ("test_cmd", "npm test; curl evil"), ("test_cmd", "npm test $(id)"), ("install_cmd", "npm ci && rm -rf /"),
    ("install_cmd", "npm ci\nid"), ("base", "-x"), ("base", "main;id"), ("base", "refs/heads/main"),
])
def test_shell_and_ref_fields_are_restricted(field: str, value: str) -> None:
    with pytest.raises(JobSpecError, match=field):
        JobSpec.from_request(request(**{field: value}))


JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJlLXBhcnQ"
BLOB = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlqa2xtbm9wcXJzdHV2d3h5ejAxMjM0NTY3ODk="


def test_redactor_scrubs_secret_shapes_it_was_never_told_about() -> None:
    redact = Redactor(env={})
    text = redact(f"headers {{'Authorization': 'Bearer abc.def-ghi'}} Authorization: token zzz111 "
                  f"clone https://x-access-token:pw123@github.com/o/r.git jwt {JWT} "
                  f"pat ghp_{'A1' * 18} fine github_pat_{'B2' * 20} blob {BLOB}")
    for leaked in ("abc.def-ghi", "zzz111", "pw123", JWT, "ghp_A1", "github_pat_B2", BLOB):
        assert leaked not in text
    assert "https://***@github.com/o/r.git" in text


def test_redactor_keeps_shas_and_paths_readable() -> None:
    redact = Redactor(env={})
    sha = "0123456789abcdef0123456789abcdef01234567"
    path = "/srv/sdlc-work/j-12-1/checkout/app/web/src/components/TrackingNumberInput.tsx"
    tmp = "/private/var/folders/2y/jj4x2fjx2vn36g1jp774sly80000gr/T/pytest-of-x/agyuser-home/settings.json"
    assert redact(f"commit {sha} at {path} {tmp}") == f"commit {sha} at {path} {tmp}"
    assert BLOB[:30] not in redact(f"key a/b/{BLOB}")    # a blob behind a path is still caught


def test_redactor_scrubs_values_of_secret_looking_environment_variables() -> None:
    env = {"IDENTITY_HEADER": "hdr-0123456789", "IDENTITY_ENDPOINT": "http://100.64.100.2/msi/token",
           "MY_SERVICE_PASSWORD": "planted-pw-555", "ANTHROPIC_API_KEY": "sk-planted-1234", "CI": "1",
           "GIT_AUTHOR_NAME": "steven gonsalvez", "SSH_AUTH_SOCK": "/tmp/agent.sock.42", "LANG": "C.UTF-8"}
    redact = Redactor(env=env)
    text = redact(" ".join(env.values()))
    for name in ("IDENTITY_HEADER", "IDENTITY_ENDPOINT", "MY_SERVICE_PASSWORD", "ANTHROPIC_API_KEY", "SSH_AUTH_SOCK"):
        assert env[name] not in text
    assert "steven gonsalvez" in text and "C.UTF-8" in text   # not secret-named; short values never redacted


def test_tracebacks_are_redacted_capped_free_of_locals_and_home_paths() -> None:
    redact = Redactor(env={})
    redact.add("planted-pat-123456")

    def fail() -> None:
        secret_local = "local-only-value-987"   # noqa: F841  a traceback with locals would print it
        raise RuntimeError("y" * 9000 + "\npush failed for /home/agyuser/.config/x using planted-pat-123456")

    try:
        fail()
    except RuntimeError as exc:
        text = redact.traceback(exc)
    assert "local-only-value-987" not in text and "planted-pat-123456" not in text
    assert "/home/agyuser" not in text and "~/.config/x" in text
    assert text.startswith("Traceback (most recent call last):")
    assert len(text) <= 4000
