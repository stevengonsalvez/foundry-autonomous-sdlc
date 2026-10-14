"""The ticket record, derived from real state comments of the 2026-10-10 run."""

from __future__ import annotations

import json

import pytest

from sdlc_agents.ledger import events, model
from sdlc_agents.ports import OWNER, Comment
from tests.ledger.conftest import ticket_of


def test_released_feature_walks_the_board_in_order_with_seconds_per_stage(real) -> None:
    t = ticket_of(real[12])
    assert [h["stage"] for h in t["stage_history"]] == [
        "backlog",
        "refining",
        "feasible",
        "tests",
        "building",
        "review",
        "staging",
        "staging",
    ]
    assert t["stage_history"][0]["sdlc_stage"] is None and t["stage_history"][-1]["seconds"] is None
    assert all(h["seconds"] >= 0 for h in t["stage_history"][:-1])
    assert t["sdlc_stage"] == "stage:released" and t["release"]["tag"] == "v0.1.0"
    assert t["pr"]["number"] == 13 and t["pr"]["merge_sha"].startswith("00ad430")
    assert t["cost"]["usd"] == pytest.approx(0.073015, abs=1e-6)
    assert t["cost"]["cap_used_pct"] == pytest.approx(2.43, abs=0.05)


def test_numbers_come_from_the_state_comment_and_agree_with_it(real) -> None:
    for item in real.values():
        t = ticket_of(item)
        data = item["state_data"]
        assert t["cost"]["usd"] == pytest.approx(data["cost"]["usd"], abs=5e-6)
        assert t["cost"]["coder_usd"] == pytest.approx(data["cost"]["coder_usd"], abs=1e-6)
        assert t["cost"]["calls"] == sum(int(c.get("count", 1)) for c in data["cost"]["calls"])
        assert t["cost"]["model_usd"] == pytest.approx(sum(c["usd"] for c in data["cost"]["calls"]), abs=1e-5)


def test_refinement_questions_are_paired_with_labelled_simulated_answers(real) -> None:
    t = ticket_of(real[24])
    assert len(t["qa"]) == 4 and t["qa"][0]["round"] == 1
    assert all(q["answered_by"] == "simulated product owner" for q in t["qa"])
    assert not any(q["answer"].startswith("[Simulated product owner]") for q in t["qa"])
    assert t["reviews"][0]["verdict"] == "approve" and t["reviews"][0]["findings"]
    assert ticket_of(real[12])["qa"] == []


def test_escalated_ticket_says_why_what_was_tried_and_where_the_evidence_is(real) -> None:
    t = ticket_of(real[17])
    assert t["stage"] == "escalated" and t["escalation"]["label"] == "escalated:not-agent-suitable"
    assert len(t["escalation"]["reasons"]) == 4
    assert any("Feasibility: not suitable" in s for s in t["escalation"]["tried"])
    assert t["escalation"]["evidence_url"].startswith(
        "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/17#issuecomment-"
    )


def test_bug_keeps_its_triage_and_maintenance_pr_is_its_own_kind(real) -> None:
    bug = ticket_of(real[25])
    assert bug["type"] == "bug" and bug["triage"]["severity"] == "s3" and bug["triage"]["owner"] == "api"
    pr = ticket_of(real[40])
    assert (
        pr["kind"] == "pr"
        and pr["type"] == "maintenance"
        and pr["url"].endswith("/pull/40")
        and pr["scenario"] == "d-maintenance"
    )


@pytest.mark.parametrize(
    ("stage", "esc", "env", "want"),
    [
        (None, None, "none", "backlog"),
        ("stage:needs-refinement", None, "none", "refining"),
        ("stage:ready", None, "none", "refining"),
        ("stage:feasible", None, "none", "feasible"),
        ("stage:tests-written", None, "none", "tests"),
        ("stage:building", None, "none", "building"),
        ("stage:in-review", None, "none", "review"),
        ("stage:merged", None, "none", "staging"),
        ("stage:released", None, "staging", "staging"),
        ("stage:released", None, "prod", "prod"),
        ("stage:released", None, "rolled-back", "escalated"),
        ("stage:building", "escalated:build-failed", "none", "escalated"),
    ],
)
def test_board_column_follows_stage_escalation_and_environment(stage, esc, env, want) -> None:
    assert model.board_stage(stage, esc, env) == want


def test_text_from_outside_is_cleaned_before_it_is_stored(real) -> None:
    item = json.loads(json.dumps(real[12]))
    item["title"] = "<img src=x onerror=alert(1)> ghp_" + "a" * 36 + "\x00 title"
    item["state_data"]["feasibility"]["reasons"] = ["Authorization: Bearer abc.def.ghi\nnext line"]
    t = ticket_of(item)
    dumped = json.dumps(t)
    assert "ghp_" not in dumped and "\x00" not in t["title"] and "\n" not in json.dumps(t["feasibility"])
    assert "[REDACTED]" in t["title"]
    events.validate(events.make("ticket.updated", t["updated_at"], {"ticket": t}, issue=t["issue"]))


def test_every_real_ticket_validates_as_an_event(real) -> None:
    for item in real.values():
        t = ticket_of(item)
        events.validate(events.make("ticket.updated", t["updated_at"], {"ticket": t}, issue=t["issue"]))
        assert t["stage"] in model.BOARD_STAGES


def test_a_tickets_cost_is_the_orchestrators_figure_and_the_ledger_share_sits_beside_it(real) -> None:
    from sdlc_agents.ledger import fold
    from tests.ledger.conftest import ticket_event

    doc = fold.fold([ticket_event(item) for item in real.values()], "2026-10-11T20:00:00Z")
    for t in doc["tickets"]:
        assert t["cost"]["usd"] == pytest.approx(real[t["issue"]]["state_data"]["cost"]["usd"], rel=0.05)
        assert t["cost"]["total_usd"] == pytest.approx(t["cost"]["usd"] + t["cost"]["ledger_usd"], abs=1e-6)


def test_clean_resolved() -> None:
    assert model.clean_resolved(None) is None
    assert model.clean_resolved("not a dict") is None
    assert model.clean_resolved({"at": "2026-10-10T12:00:00Z", "by": "invalid", "how": "closed"}) is None
    assert model.clean_resolved({"at": "2026-10-10T12:00:00Z", "by": "human", "how": "invalid"}) is None
    assert model.clean_resolved({"at": "", "by": "human", "how": "closed"}) is None
    valid = {"at": "2026-10-10T12:00:00Z", "by": "simulated-human", "how": "answered"}
    assert model.clean_resolved(valid) == valid


def test_derive_resolution_cases() -> None:
    esc_at = "2026-10-10T15:00:00Z"

    # None if no esc_at
    assert model.derive_resolution(esc_at=None, closed_at="2026-10-10T16:00:00Z", comments=None) is None

    # Open issue, no marker
    assert model.derive_resolution(esc_at=esc_at, closed_at=None, comments=[]) is None

    # Closed issue, no marker -> human, closed
    res = model.derive_resolution(esc_at=esc_at, closed_at="2026-10-10T16:00:00Z", comments=[])
    assert res == {"at": "2026-10-10T16:00:00Z", "by": "human", "how": "closed"}

    # Closed issue, with simulated human marker from OWNER -> simulated-human, closed
    comments = [Comment(1, OWNER, "### Simulated human (antigravity)\nAnswer", "2026-10-10T15:30:00Z")]
    res = model.derive_resolution(esc_at=esc_at, closed_at="2026-10-10T16:00:00Z", comments=comments)
    assert res == {"at": "2026-10-10T16:00:00Z", "by": "simulated-human", "how": "closed"}

    # Open issue, with simulated human marker from OWNER -> simulated-human, answered
    res = model.derive_resolution(esc_at=esc_at, closed_at=None, comments=comments)
    assert res == {"at": "2026-10-10T15:30:00Z", "by": "simulated-human", "how": "answered"}

    # Non-owner marker comment -> resolved None
    non_owner_comments = [
        Comment(2, "other_user", "### Simulated human (antigravity)\nAnswer", "2026-10-10T15:30:00Z")
    ]
    assert model.derive_resolution(esc_at=esc_at, closed_at=None, comments=non_owner_comments) is None

    # Comment with no timestamp is ignored
    no_time_comments = [Comment(3, OWNER, "### Simulated human (antigravity)\nAnswer", "")]
    assert model.derive_resolution(esc_at=esc_at, closed_at=None, comments=no_time_comments) is None

    # Closed-then-reopened: old marker before reopen does not resolve it
    res = model.derive_resolution(
        esc_at=esc_at,
        closed_at=None,
        comments=comments,
        reopened_at="2026-10-10T17:00:00Z",
    )
    assert res is None

    # Re-escalated after answered: old marker before new esc_at does not resolve it
    res = model.derive_resolution(
        esc_at="2026-10-10T18:00:00Z",
        closed_at=None,
        comments=comments,
    )
    assert res is None

    # Closed issue with escalated:deploy-failed stays open
    res = model.derive_resolution(
        esc_at=esc_at,
        closed_at="2026-10-10T16:00:00Z",
        comments=[],
        labels=(model.DEPLOY_FAILED_LABEL,),
    )
    assert res is None

    # Closed before escalation -> bounded by esc_at
    res = model.derive_resolution(esc_at="2026-10-10T21:20:00Z", closed_at="2026-10-10T21:14:00Z", comments=[])
    assert res == {"at": "2026-10-10T21:20:00Z", "by": "human", "how": "closed"}


def test_ticket_with_escalation_derives_resolution(real) -> None:
    # Item 18 is closed
    item = real[18]
    comments = [Comment(1, OWNER, "### Simulated human (antigravity)\nDone", "2026-10-10T16:30:00Z")]
    t = model.ticket(
        number=item["number"],
        kind="issue",
        title=item["title"],
        author=item["author"],
        opened_at=item["created_at"],
        closed_at=item["closed_at"],
        labels=tuple(item["labels"]),
        state_data=item["state_data"],
        comments=comments,
    )
    assert t["escalation"]["resolved"] == {
        "at": item["closed_at"],
        "by": "simulated-human",
        "how": "closed",
    }
    assert t["escalation"]["open"] is False
    assert t["updated_at"] >= t["escalation"]["resolved"]["at"]


def test_digest_ignores_updated_at() -> None:
    t1 = {"issue": 1, "stage": "prod", "updated_at": "2026-10-10T12:00:00Z"}
    t2 = {"issue": 1, "stage": "prod", "updated_at": "2026-10-10T12:05:00Z"}
    assert model.digest(t1) == model.digest(t2)


def test_merged_pr_with_deploy_failed_stays_open() -> None:
    t = model.ticket(
        number=50,
        kind="pr",
        title="Fix tracking",
        author=OWNER,
        opened_at="2026-10-10T14:00:00Z",
        closed_at="2026-10-10T15:00:00Z",
        labels=(model.DEPLOY_FAILED_LABEL,),
        state_data={
            "stages": [
                {"stage": "stage:building", "at": "2026-10-10T14:10:00Z"},
                {"stage": "stage:merged", "at": "2026-10-10T15:00:00Z"},
            ],
            "escalation": {
                "label": model.DEPLOY_FAILED_LABEL,
                "reasons": ["smoke failed on staging"],
                "at": "2026-10-10T15:05:00Z",
            },
        },
        env="rolled-back",
    )
    assert t["stage"] == "escalated"
    assert t["escalation"]["resolved"] is None
    assert t["escalation"]["open"] is True
