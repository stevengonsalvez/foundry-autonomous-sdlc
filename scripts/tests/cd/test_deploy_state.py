from __future__ import annotations

import copy
import json

import pytest
from cd_helpers import RUN_URL, T0, T1, T2, include, promoted, release, sha, staged, subject

from scripts.cd import deploy_state as ds


def test_empty_state_is_valid_and_round_trips() -> None:
    state = ds.empty_state()
    assert ds.validate(state) == []
    assert ds.parse(ds.dumps(state)) == state
    assert ds.parse("") == state
    assert ds.parse("  \n") == state


def test_stage_records_the_build_and_history() -> None:
    state = staged(ds.empty_state(), 1)
    staging = state["staging"]
    assert staging["sha"] == sha(1)
    assert staging["status"] == "deployed"
    assert staging["deployed_at"] == T1
    assert staging["includes"] == [{"pr": 11, "issue": 21, "sha": sha(1)}]
    assert state["prod"] is None
    [entry] = state["history"]
    assert (entry["action"], entry["env"], entry["sha"]) == ("stage", "staging", sha(1))
    assert entry["includes"] == staging["includes"]
    assert ds.validate(state) == []


def test_transitions_never_change_their_input() -> None:
    before = promoted(ds.empty_state(), 1)
    snapshot = copy.deepcopy(before)
    staged(before, 2)
    ds.rollback(before, subject=subject(1), run_id=1001, run_url=RUN_URL, reason="smoke", now=T2)
    ds.skip(before, subject=subject(1), run_url=RUN_URL, reason="x", now=T2)
    assert before == snapshot


def test_promote_moves_staging_to_prod_and_prod_to_previous() -> None:
    state = promoted(ds.empty_state(), 1)
    assert state["prod"]["sha"] == sha(1)
    assert state["prod"]["gates"] == ["smoke", "soak"]
    assert state["prod"]["tag"] == f"prod/20261011-100000-{sha(1)[:7]}"
    assert state["previous_prod"] is None
    assert state["staging"]["status"] == "promoted"

    state = promoted(state, 2, now="2026-10-11T11:00:00Z")
    assert state["prod"]["sha"] == sha(2)
    assert state["previous_prod"]["sha"] == sha(1)
    assert state["prod"]["promoted_at"] == "2026-10-11T11:00:00Z"
    assert [h["action"] for h in state["history"]] == ["stage", "promote", "stage", "promote"]
    assert state["history"][-1]["includes"] == state["prod"]["includes"]
    assert ds.validate(state) == []


def test_promote_is_idempotent_for_the_sha_that_is_already_prod() -> None:
    state = promoted(ds.empty_state(), 1)
    state = promoted(state, 2)
    again = ds.promote(
        state,
        sha=sha(2),
        run_id=1002,
        run_url=RUN_URL,
        now="2026-10-11T12:00:00Z",
        tag="prod/other",
    )
    assert again["prod"] == state["prod"]
    assert again["previous_prod"]["sha"] == sha(1)  # not overwritten with the build just promoted
    assert again["history"] == state["history"]  # no duplicate entry


def test_promote_refuses_a_sha_that_is_not_staged() -> None:
    with pytest.raises(ds.DeployStateError, match="staging holds nothing"):
        ds.promote(ds.empty_state(), sha=sha(1), run_id=1, run_url="u", now=T1, tag="t")
    state = staged(ds.empty_state(), 1)
    with pytest.raises(ds.DeployStateError, match=f"staging holds {sha(1)}"):
        ds.promote(state, sha=sha(2), run_id=1, run_url="u", now=T1, tag="t")


def test_includes_travel_from_staging_to_prod_and_rollback_target() -> None:
    state = ds.stage(
        ds.empty_state(),
        release(3, includes=(include(11, 21, 1), include(12, None, 2), include(13, 23, 3))),
        T1,
    )
    state = ds.promote(state, sha=sha(3), run_id=1003, run_url="u", now=T2, tag="t")
    assert [i["pr"] for i in state["prod"]["includes"]] == [11, 12, 13]
    assert state["history"][-1]["includes"] == state["prod"]["includes"]
    state = ds.rollback(
        state, subject=subject(3), run_id=1003, run_url="u", reason="promote", now=T2
    )
    assert state["prod"] is None and state["staging"] is None


def test_history_is_capped_to_the_newest_sixty() -> None:
    state = ds.empty_state()
    for i in range(1, 90):
        state = staged(state, i)
    assert len(state["history"]) == ds.HISTORY_LIMIT == 60
    assert state["history"][-1]["sha"] == sha(89)
    assert state["history"][0]["sha"] == sha(30)


def test_skip_marks_in_flight_staging_superseded() -> None:
    state = staged(ds.empty_state(), 1)
    state = ds.skip(state, subject=subject(1), run_url="u", reason="superseded", now=T2)
    assert state["staging"]["status"] == "superseded"
    assert state["history"][-1]["action"] == "skip"
    assert state["history"][-1]["reason"] == "superseded"


def test_skip_leaves_other_builds_and_promoted_builds_alone() -> None:
    state = promoted(ds.empty_state(), 1)
    state = ds.skip(state, subject=subject(1), run_url="u", reason="r", now=T2)
    assert state["staging"]["status"] == "promoted"
    state = staged(state, 2)
    state = ds.skip(state, subject=subject(1), run_url="u", reason="r", now=T2)
    assert state["staging"]["status"] == "deployed"  # build 1 is not what staging holds


def test_tag_name_uses_utc_time_and_the_short_sha() -> None:
    assert ds.tag_name("2026-01-02T03:04:05Z", "abc1234") == "prod/20260102-030405-abc1234"
    with pytest.raises(ds.DeployStateError):
        ds.tag_name("yesterday", "abc1234")


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda s: s.update(version=2), "version must be 1"),
        (lambda s: s["staging"].update(status="weird"), "staging.status"),
        (lambda s: s["staging"].update(sha="abc"), "staging.sha must be 40 hex"),
        (lambda s: s["staging"].update(run_id="7"), "staging.run_id"),
        (lambda s: s["staging"].update(pr="x"), "staging.pr"),
        (lambda s: s["staging"].update(includes=[{"pr": 1}]), "staging.includes[0]"),
        (lambda s: s["staging"].update(includes="no"), "staging.includes must be a list"),
        (lambda s: s["history"][0].update(action="deploy"), "history[0].action"),
        (lambda s: s["history"][0].update(env="qa"), "history[0].env"),
        (lambda s: s.update(history={}), "history must be a list"),
        (lambda s: s["prod"].update(gates="smoke"), "prod.gates"),
    ],
)
def test_validation_names_the_problem(mutate, expected: str) -> None:
    state = promoted(ds.empty_state(), 1)
    mutate(state)
    problems = ds.validate(state)
    assert any(expected in p for p in problems), problems
    with pytest.raises(ds.DeployStateError):
        ds.dumps(state)


def test_parse_rejects_garbage_and_non_objects() -> None:
    with pytest.raises(ds.DeployStateError, match="not JSON"):
        ds.parse("{nope")
    with pytest.raises(ds.DeployStateError, match="must be an object"):
        ds.parse("[]")


def test_a_state_without_includes_reads_as_including_nothing() -> None:
    state = promoted(ds.empty_state(), 1)
    for key in ("staging", "prod"):
        del state[key]["includes"]
    parsed = ds.parse(json.dumps(state))
    assert parsed["staging"]["includes"] == [] and parsed["prod"]["includes"] == []


def test_the_schema_in_the_doc_matches_the_state_keys() -> None:
    state = promoted(promoted(ds.empty_state(), 1), 2)
    assert set(state) == {"version", "staging", "prod", "previous_prod", "history"}
    assert set(state["staging"]) == {
        "sha",
        "short",
        "version",
        "built_at",
        "deployed_at",
        "run_id",
        "run_url",
        "status",
        "pr",
        "issue",
        "includes",
    }
    assert set(state["prod"]) == {
        "sha",
        "short",
        "version",
        "built_at",
        "promoted_at",
        "run_id",
        "run_url",
        "gates",
        "pr",
        "issue",
        "tag",
        "includes",
    }
    assert set(state["history"][0]) == {
        "at",
        "action",
        "env",
        "sha",
        "version",
        "run_url",
        "reason",
        "issue",
        "pr",
        "includes",
    }
    assert T0 < T1 < T2
