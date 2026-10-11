"""The ledger service: ingest, reconcile from GitHub, rebuild, conflicts, billing and summaries."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fakes import FakeClock, FakeGitHub

from sdlc_agents import state
from sdlc_agents.ledger import events, fold
from sdlc_agents.ledger.service import Ledger, LedgerError
from sdlc_agents.ledger.store import EVENTS_FILE, STATE_FILE, MemoryBranchStore, StoreConflict
from tests.ledger.conftest import ticket_event


class Clock(FakeClock):
    def __init__(self) -> None:
        super().__init__("2026-10-11T20:00:00Z", step_s=2.0)


def ledger(**kw: Any) -> tuple[Ledger, MemoryBranchStore]:
    store = MemoryBranchStore()
    return Ledger(store, Clock(), **kw), store


def state_of(store: MemoryBranchStore) -> dict[str, Any]:
    return json.loads(store.files[STATE_FILE])


def test_ingest_writes_state_and_the_event_log_in_one_commit(real) -> None:
    led, store = ledger()
    reply = led.handle({"op": "ingest", "events": [ticket_event(real[12]), ticket_event(real[24])]})
    assert reply["ok"] and reply["appended"] == 3 and len(store.commits) == 1
    state = state_of(store)
    assert [t["issue"] for t in state["tickets"]] == [12, 24] and state["seq"] == 3
    lines = store.files[EVENTS_FILE].splitlines()
    assert len(lines) == 3 and json.loads(lines[-1])["type"] == "ledger.invoked"
    assert store.commits[0][1].startswith("ledger: ingest +3 events")


def test_sending_the_same_events_twice_adds_no_ticket_events(real) -> None:
    led, store = ledger()
    batch = [ticket_event(real[12])]
    led.handle({"op": "ingest", "events": batch})
    led.handle({"op": "ingest", "events": batch})
    types = [json.loads(line)["type"] for line in store.files[EVENTS_FILE].splitlines()]
    assert types.count("ticket.updated") == 1 and types.count("ledger.invoked") == 2


def test_the_ledgers_own_compute_is_priced_and_counted(real) -> None:
    led, store = ledger()
    reply = led.handle({"op": "ingest", "events": [ticket_event(real[12])]})
    assert 0.002 < reply["usd"] < 0.004  # (seconds + 120 s idle) at 0.25 vCPU / 0.5 GiB
    state = state_of(store)
    assert state["cost"]["ledger"]["invocations"] == 1 and state["cost"]["ledger"]["usd"] == reply["usd"]
    assert state["cost"]["totals"]["ledger_usd"] == reply["usd"]
    inline, store2 = ledger(mode="inline")
    assert inline.handle({"op": "ingest", "events": []})["usd"] == 0.0
    assert state_of(store2)["ledger"]["mode"] == "inline"


def test_a_second_writer_that_wins_the_race_is_retried_from_a_fresh_read(real) -> None:
    led, store = ledger()
    led.handle({"op": "ingest", "events": [ticket_event(real[12])]})
    store.fail_next = [StoreConflict("branch moved")]
    reply = led.handle({"op": "ingest", "events": [ticket_event(real[24])]})
    assert reply["ok"] and {t["issue"] for t in state_of(store)["tickets"]} == {12, 24}
    store.fail_next = [StoreConflict("x")] * 4
    with pytest.raises(StoreConflict):
        led.handle({"op": "ingest", "events": [ticket_event(real[25])]})


def test_a_lost_or_corrupt_state_file_is_rebuilt_from_the_event_log(real) -> None:
    led, store = ledger()
    led.handle({"op": "ingest", "events": [ticket_event(real[12]), ticket_event(real[24])]})
    before = state_of(store)
    store.files[STATE_FILE] = "{ not json"
    led.handle({"op": "ingest", "events": [ticket_event(real[25])]})
    after = state_of(store)
    assert {t["issue"] for t in after["tickets"]} == {12, 24, 25}
    assert after["ledger"]["errors"][0]["message"].startswith("state.json was unreadable")
    assert before["tickets"][0]["issue"] == 12
    del store.files[STATE_FILE]
    led.handle({"op": "rebuild"})
    assert {t["issue"] for t in state_of(store)["tickets"]} == {12, 24, 25}


def test_bad_requests_write_nothing(real) -> None:
    led, store = ledger()
    for body in (
        {"op": "drop-table"},
        {"op": "ingest", "events": "nope"},
        {"op": "ingest", "events": [{"v": 1}]},
        {"op": "ingest", "events": [{**ticket_event(real[12]), "issue": 99}]},
        {"op": "reconcile"},
    ):
        with pytest.raises((LedgerError, events.EventError)):
            led.handle(body)
    assert store.commits == []


def test_secrets_in_an_incoming_event_never_reach_the_branch(real) -> None:
    led, store = ledger()
    ev = ticket_event(real[12])
    ev["data"]["ticket"]["title"] = "leak ghp_" + "b" * 36
    led.handle({"op": "ingest", "events": [ev]})
    assert "ghp_" not in store.files[STATE_FILE] and "ghp_" not in store.files[EVENTS_FILE]


def test_billing_is_read_at_most_every_six_hours_and_its_failure_never_blocks_state(real) -> None:
    class Billing:
        calls = 0

        def observe(self, now: str) -> dict[str, Any]:
            Billing.calls += 1
            if Billing.calls == 3:
                raise RuntimeError("Cost Management returned HTTP 429")
            return {
                "source": "azure-cost-management",
                "billed_usd": 13.02,
                "currency": "USD",
                "as_of": now,
                "by_meter": [],
            }

    led, store = ledger(billing=Billing())
    led.handle({"op": "ingest", "events": [ticket_event(real[12])]})
    led.handle({"op": "ingest", "events": []})
    assert Billing.calls == 1 and state_of(store)["cost"]["gap"]["billed_usd"] == 13.02
    reply = led.handle({"op": "ingest", "events": [], "billing": True})
    assert Billing.calls == 2 and reply["ok"]
    reply = led.handle({"op": "ingest", "events": [], "billing": True})
    assert reply["ok"] and "billing: RuntimeError" in reply["problems"][0]


def test_a_model_summary_replaces_the_sentence_only_while_its_facts_hold(real) -> None:
    class Summariser:
        def summarise(self, ticket: dict[str, Any]) -> tuple[str | None, dict[str, int]]:
            return f"Ticket {ticket['issue']} reached production.", {"in": 200, "out": 40}

    led, store = ledger(summariser=Summariser())
    reply = led.handle({"op": "ingest", "events": [ticket_event(real[12]), ticket_event(real[17])]})
    state = state_of(store)
    by = {t["issue"]: t for t in state["tickets"]}
    assert by[12]["summary"] == "Ticket 12 reached production." and by[17]["summary"] == "Ticket 17 reached production."
    assert reply["usd"] > 0.0026 and state["cost"]["ledger"]["usd"] == reply["usd"]
    led.handle({"op": "ingest", "events": []})
    assert led.summariser is not None and sum(1 for _ in store.files[EVENTS_FILE].splitlines()) == 4  # not asked again


def test_reconcile_rebuilds_tickets_from_github_and_is_quiet_when_nothing_changed(real) -> None:
    gh = FakeGitHub(Clock())
    for item in real.values():
        if item["number"] in (6, 17):
            number = gh.open_issue(item["title"], "body", labels=tuple(item["labels"]))
            gh.create_comment(number, state.render(state.State(item["state_data"])))
    led, store = ledger(github=gh)
    first = led.handle({"op": "reconcile"})
    assert first["ok"] and first["tickets"] == 2
    again = led.handle({"op": "reconcile"})
    types = [json.loads(line)["type"] for line in store.files[EVENTS_FILE].splitlines()]
    assert again["ok"] and types.count("ticket.updated") == 2


def test_fold_of_the_written_log_equals_the_written_state(real) -> None:
    led, store = ledger()
    led.handle({"op": "ingest", "events": [ticket_event(real[12]), ticket_event(real[24]), ticket_event(real[17])]})
    state = state_of(store)
    replay = fold.fold(events.loads_lines(store.files[EVENTS_FILE]), state["generated_at"])
    for key in ("tickets", "environments", "cost", "agents", "flow"):
        assert replay[key] == state[key], key


def test_reconcile_also_reads_the_cd_record_and_the_orchestrators_spend_estimate() -> None:
    gh = FakeGitHub(Clock())
    deploy = {
        "version": 1,
        "staging": None,
        "prod": {
            "sha": "a" * 40,
            "short": "aaaaaaa",
            "version": "v0.4.0",
            "promoted_at": "2026-10-11T19:00:00Z",
            "gates": ["smoke", "soak"],
        },
        "previous_prod": None,
        "history": [
            {"at": "2026-10-11T19:00:00Z", "action": "promote", "env": "prod", "sha": "a" * 40, "version": "v0.4.0"}
        ],
    }
    gh.files[("deploy", "deploy.json")] = json.dumps(deploy)
    gh.files[("metrics", "metrics.json")] = json.dumps(
        {
            "version": 1,
            "generated_at": "2026-10-11T19:30:00Z",
            "repo": "x",
            "totals": {"usd": 1.86, "orchestrator_usd": 0.76, "issues": 22, "released": 5},
            "issues": [],
        }
    )
    gh.branches["metrics"] = "m" * 40
    led, store = ledger(github=gh)
    led.handle({"op": "reconcile"})
    state = state_of(store)
    assert state["environments"]["prod"]["version"] == "v0.4.0" and state["environments"]["prod"]["gates_cleared"] == [
        "smoke",
        "soak",
    ]
    assert state["cost"]["metrics"]["usd"] == 1.86 and state["cost"]["totals"]["orchestrator_usd"] == 0.76
    led.handle({"op": "reconcile"})
    types = [json.loads(line)["type"] for line in store.files[EVENTS_FILE].splitlines()]
    assert types.count("env.changed") == 1 and types.count("metrics.observed") == 1
