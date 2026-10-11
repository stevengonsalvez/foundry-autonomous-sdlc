"""The orchestrator hands every stage change to the ledger, and the ledger turns it into what the board shows."""

from __future__ import annotations

import json
from typing import Any

from conftest import World

from sdlc_agents.ledger.emitter import EmitResult, HostedEmitter, InlineEmitter
from sdlc_agents.ledger.service import Ledger
from sdlc_agents.ledger.store import STATE_FILE, MemoryBranchStore
from sdlc_agents.ports import AgentResult
from tests.test_scenarios import A_BODY, state


def board(store: MemoryBranchStore) -> dict[str, Any]:
    return json.loads(store.files[STATE_FILE])


def open_a(world: World) -> int:
    return world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))


def test_a_feature_walks_every_stage_on_the_board_with_the_orchestrators_timestamps(world: World) -> None:
    store = MemoryBranchStore()
    world.emitter = InlineEmitter(Ledger(store, world.clock, github=world.gh, mode="inline"))
    n = open_a(world)
    seen: list[str] = []

    def watch() -> bool:
        tickets = [t for t in board(store)["tickets"] if t["issue"] == n] if STATE_FILE in store.files else []
        if tickets and (not seen or seen[-1] != tickets[0]["stage"]):
            seen.append(tickets[0]["stage"])
        return state.RELEASED in world.gh.labels(n)

    world.drive(watch)
    world.tick()
    # No CD record exists in this world, so a merged and released change counts as published straight to prod.
    assert seen == ["refining", "feasible", "tests", "building", "review", "prod"]
    doc = board(store)
    t = next(t for t in doc["tickets"] if t["issue"] == n)
    assert [h["stage"] for h in t["stage_history"]][:7] == [
        "backlog",
        "refining",
        "feasible",
        "tests",
        "building",
        "review",
        "staging",
    ]
    stamps = [h["at"] for h in t["stage_history"]]
    assert stamps == sorted(stamps)
    assert t["release"]["tag"] == "v0.1.0" and t["pr"]["number"] == world.gh.state_of(n)["pr"]["number"]
    assert set(t["gates"]) >= {"test", "coverage", "e2e", "gitleaks", "tdd-order", "agent-scope"}
    assert t["cost"]["usd"] == world.gh.state_of(n)["cost"]["usd"] and t["cost"]["calls"] == 5
    assert doc["ledger"]["last_tick"]["lock"] == "acquired"
    assert any(a["name"] == "sdlc-req-gate" and a["calls_total"] == 1 for a in doc["agents"])


def test_a_quiet_loop_only_sends_a_heartbeat_every_couple_of_ticks(world: World) -> None:
    sent: list[int] = []

    class Spy:
        def emit(self, evs: list[dict[str, Any]], *, reconcile: bool = False) -> EmitResult:
            sent.append(len(evs))
            return EmitResult(usd=0.003)

    world.emitter = Spy()
    reports = world.tick(6)
    assert [r.ledger for r in reports] == ["emitted", "quiet", "emitted", "quiet", "emitted", "quiet"]
    assert world.gh.files[("metrics", "metrics.json")]
    totals = json.loads(world.gh.files[("metrics", "metrics.json")])["totals"]
    assert totals["ledger_usd"] == 0.009 and totals["usd"] >= totals["ledger_usd"] + totals["orchestrator_usd"] - 1e-9


def test_a_ledger_that_is_down_never_fails_or_stalls_the_tick(world: World) -> None:
    class Down:
        def emit(self, evs: list[dict[str, Any]], *, reconcile: bool = False) -> EmitResult:
            return EmitResult(error="ledger: AgentRunError: invocation failed: URLError")

    world.emitter = Down()
    n = open_a(world)
    world.drive(lambda: state.RELEASED in world.gh.labels(n))
    report = world.tick()[0]
    assert report.ledger in ("error", "quiet")
    totals = json.loads(world.gh.files[("metrics", "metrics.json")])["totals"]
    assert totals["ledger_usd"] == 0.0


def test_the_hosted_emitter_calls_the_ledger_agent_and_reuses_its_session(world: World) -> None:
    calls: list[tuple[str, dict[str, Any], str | None]] = []

    class Foundry:
        def invoke_hosted(
            self, agent: str, body: dict[str, Any], *, session_id: str | None = None, timeout_s: int = 240
        ):
            calls.append((agent, body, session_id))
            return {"ok": True, "usd": 0.0027, "appended": len(body["events"])}, "sess-1"

        def call_prompt_agent(self, *a: Any, **k: Any) -> AgentResult:  # pragma: no cover
            raise AssertionError

    emitter = HostedEmitter(Foundry())
    assert emitter.emit([{"x": 1}]).usd == 0.0027
    emitter.emit([], reconcile=True)
    assert [c[0] for c in calls] == ["sdlc-ledger", "sdlc-ledger"]
    assert calls[0][1] == {"op": "ingest", "events": [{"x": 1}], "reconcile": False} and calls[1][2] == "sess-1"

    class Broken(Foundry):
        def invoke_hosted(self, *a: Any, **k: Any):
            raise OSError("boom")

    out = HostedEmitter(Broken()).emit([])
    assert out.error and out.error.startswith("ledger: OSError")
