"""
The ledger service: one place that turns "something happened" into a commit on branch `state`.

    ingest(events) ┐
    reconcile()    ├─▶ read branch ─▶ fold ─▶ (archive, summarise, bill) ─▶ one commit ─▶ reply with cost
    rebuild()      ┘

The same class is the hosted agent's brain (agents/hosted/ledger) and the inline fallback the
orchestrator can run in its own process (`LEDGER_MODE=inline`), so the event and state schema never
differ. It is the only writer of the branch; a lost compare-and-swap is retried from a fresh read.
Compute is metered and recorded as `ledger.invoked`, so the ledger's own cost reaches the cost view.
Stdlib only.
"""

from __future__ import annotations

import json
from typing import Any

from sdlc_agents import cost
from sdlc_agents.clock import seconds_between
from sdlc_agents.ledger import events as ev
from sdlc_agents.ledger import fold, reconcile
from sdlc_agents.ledger.billing import BillingPort
from sdlc_agents.ledger.store import ARCHIVE_FILE, EVENTS_FILE, STATE_FILE, BranchStore, Snapshot, StoreConflict
from sdlc_agents.ledger.summary import Summariser
from sdlc_agents.ports import ClockPort, GitHubPort

MAX_ATTEMPTS = 4
BILLING_EVERY_S = 6 * 3600
MAX_SUMMARIES_PER_CALL = 3
MAX_ERRORS = 20
SUMMARY_STAGES = ("prod", "escalated")
OPS = ("ingest", "reconcile", "rebuild", "status")


class LedgerError(RuntimeError):
    """The request cannot be served (bad op, bad events); nothing was written."""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


class Ledger:
    def __init__(
        self,
        store: BranchStore,
        clock: ClockPort,
        *,
        github: GitHubPort | None = None,
        billing: BillingPort | None = None,
        summariser: Summariser | None = None,
        mode: str = "hosted",
    ):
        self.store = store
        self.clock = clock
        self.github = github
        self.billing = billing
        self.summariser = summariser
        self.mode = mode

    # -- entry point (Invocations body) -----------------------------------------

    def handle(self, body: dict[str, Any]) -> dict[str, Any]:
        op = body.get("op")
        if op not in OPS:
            raise LedgerError(f"unknown op {op!r}; expected one of {', '.join(OPS)}")
        if op == "status":
            return self.status()
        incoming: list[dict[str, Any]] = []
        if op == "ingest":
            incoming = ev.validate_batch(body.get("events", []))
        want_reconcile = op == "reconcile" or bool(body.get("reconcile"))
        issue = body.get("issue") if isinstance(body.get("issue"), int) else None
        return self._commit(
            op,
            incoming,
            reconcile_now=want_reconcile,
            issue=issue,
            force_billing=bool(body.get("billing")),
            rebuild=op == "rebuild",
        )

    def status(self) -> dict[str, Any]:
        snap = self.store.read()
        try:
            doc = json.loads(snap.files[STATE_FILE])
        except (KeyError, ValueError):
            return {"ok": True, "op": "status", "state": None, "head": snap.head, "mode": self.mode}
        return {
            "ok": True,
            "op": "status",
            "head": snap.head,
            "mode": self.mode,
            "seq": doc["seq"],
            "tickets": len(doc["tickets"]),
            "updated_at": doc["updated_at"],
            "generated_at": doc["generated_at"],
            "ledger_usd": doc["cost"]["ledger"]["usd"],
        }

    # -- internals -----------------------------------------------------------------

    def _load(self, snap: Snapshot, now: str, *, rebuild: bool) -> tuple[dict[str, Any], list[str]]:
        notes: list[str] = []
        if not rebuild and STATE_FILE in snap.files:
            try:
                doc = json.loads(snap.files[STATE_FILE])
                if doc.get("version") == fold.VERSION:
                    return doc, notes
                notes.append(f"state.json version {doc.get('version')} is not {fold.VERSION}, rebuilt from events")
            except ValueError:
                notes.append("state.json was unreadable, rebuilt from events")
        lines = snap.files.get(EVENTS_FILE, "")
        doc = fold.fold(ev.loads_lines(lines), now) if lines.strip() else fold.empty(now)
        return doc, notes

    def _commit(
        self,
        op: str,
        incoming: list[dict[str, Any]],
        *,
        reconcile_now: bool,
        issue: int | None,
        force_billing: bool,
        rebuild: bool,
    ) -> dict[str, Any]:
        started = self.clock.monotonic()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            now = self.clock.now_iso()
            snap = self.store.read()
            doc, notes = self._load(snap, now, rebuild=rebuild)
            new: list[dict[str, Any]] = list(incoming)
            problems: list[str] = list(notes)
            if reconcile_now:
                if self.github is None:
                    raise LedgerError("reconcile needs a GitHub client")
                events_, found = reconcile.reconcile(self.github, doc, now, issue=issue)
                new += events_
                problems += found
            new += self._billing_events(doc, now, force=force_billing, problems=problems)
            appended = [e for e in new if fold.apply(doc, e)]
            old = fold.archive_old(doc, now)
            fold.finalise(doc, now)
            model_usd, summarised = self._summaries(doc, now, appended)
            elapsed = max(self.clock.monotonic() - started, 0.0)
            usd = round(cost.ledger_call_usd(elapsed), 6) if self.mode == "hosted" else 0.0
            touched = sorted({e["issue"] for e in appended if e["issue"]})
            invoked = ev.make(
                "ledger.invoked",
                now,
                {
                    "op": op,
                    "seconds": round(elapsed, 3),
                    "usd": round(usd + model_usd, 6),
                    "compute_usd": usd,
                    "model_usd": model_usd,
                    "events": len(appended),
                    "issues": touched,
                    "mode": self.mode,
                    "summaries": summarised,
                },
                source="ledger",
            )
            appended.append(invoked)
            fold.apply(doc, invoked)
            doc["ledger"]["errors"] = [*[{"at": now, "message": p} for p in problems], *doc["ledger"]["errors"]][
                :MAX_ERRORS
            ]
            fold.finalise(doc, now)
            files = {
                STATE_FILE: _dumps(doc),
                EVENTS_FILE: snap.files.get(EVENTS_FILE, "") + "".join(ev.dumps_line(e) + "\n" for e in appended),
            }
            if old:
                archive = (
                    json.loads(snap.files[ARCHIVE_FILE])
                    if ARCHIVE_FILE in snap.files
                    else {"version": 1, "tickets": []}
                )
                archive["tickets"] = [*archive["tickets"], *old]
                files[ARCHIVE_FILE] = _dumps(archive)
            try:
                head = self.store.write(
                    files, message=f"ledger: {op} +{len(appended)} events (seq {doc['seq']})", parent=snap.head
                )
            except StoreConflict:
                if attempt == MAX_ATTEMPTS:
                    raise
                continue
            return {
                "ok": True,
                "op": op,
                "head": head,
                "appended": len(appended),
                "tickets": len(doc["tickets"]),
                "seq": doc["seq"],
                "seconds": round(elapsed, 3),
                "usd": round(usd + model_usd, 6),
                "problems": problems,
                "mode": self.mode,
            }
        raise AssertionError("unreachable")  # pragma: no cover

    def _billing_events(
        self, doc: dict[str, Any], now: str, *, force: bool, problems: list[str]
    ) -> list[dict[str, Any]]:
        if self.billing is None:
            return []
        seen = (doc["cost"].get("billing") or {}).get("as_of")
        if not force and seen and seconds_between(seen, now) < BILLING_EVERY_S:
            return []
        try:
            return [ev.make("billing.observed", now, self.billing.observe(now), source="ledger")]
        except Exception as exc:  # cost data is a nicety: its failure never blocks the state commit
            problems.append(f"billing: {type(exc).__name__}: {str(exc)[:120]}")
            return []

    def _summaries(self, doc: dict[str, Any], now: str, appended: list[dict[str, Any]]) -> tuple[float, int]:
        """Ask the model for a summary of up to a few finished tickets that have none for their current facts."""
        if self.summariser is None:
            return 0.0, 0
        todo = [
            t
            for t in doc["tickets"]
            if t["stage"] in SUMMARY_STAGES and doc["summaries"].get(str(t["issue"]), {}).get("digest") != t["digest"]
        ][:MAX_SUMMARIES_PER_CALL]
        spent, done = 0.0, 0
        for t in todo:
            try:
                text, usage = self.summariser.summarise(t)
            except Exception as exc:
                doc["ledger"]["errors"] = [
                    {"at": now, "message": f"summary #{t['issue']}: {type(exc).__name__}"},
                    *doc["ledger"]["errors"],
                ][:MAX_ERRORS]
                continue
            spent += cost.token_usd(usage["in"], usage["out"])
            if text:
                doc["summaries"][str(t["issue"])] = {"digest": t["digest"], "text": text}
                done += 1
        if done:
            fold.finalise(doc, now)
        return round(spent, 6), done
