"""BranchStore contract: MemoryBranchStore and DoltBranchStore must behave the same.

The Dolt store runs against a fake DB-API connection (SQLite plus a tiny dialect shim) always, and against a
real `dolt sql-server` when DOLT_TEST_PORT is set.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from sdlc_agents.ledger.store import BranchStore, MemoryBranchStore, StoreConflict

from sdlc_factory.ledger_store import DoltBranchStore, pymysql_connector


class FakeDolt:
    """A MySQL-protocol stand-in: one in-memory SQLite shared by every connection, like a server.

    A connection holds the database lock from its first statement until commit, rollback or close, so racing
    writers queue the way row locks make them queue on a real server. dolt_commits records DOLT_COMMIT messages.
    """

    def __init__(self) -> None:
        self._db = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        self.dolt_commits: list[str] = []

    def connect(self) -> FakeConnection:
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, server: FakeDolt):
        self._server = server
        self._holding = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def _enter(self) -> sqlite3.Connection:
        if not self._holding:
            self._server._lock.acquire()
            self._holding = True
            self._server._db.execute("BEGIN")
        return self._server._db

    def _leave(self, how: str) -> None:
        if self._holding:
            self._server._db.execute(how)
            self._holding = False
            self._server._lock.release()

    def commit(self) -> None:
        self._leave("COMMIT")

    def rollback(self) -> None:
        self._leave("ROLLBACK")

    def close(self) -> None:
        self._leave("ROLLBACK")


class FakeCursor:
    """Maps the MySQL/Dolt statements the store issues onto SQLite; DOLT_COMMIT is recorded, not run."""

    def __init__(self, conn: FakeConnection):
        self._conn = conn
        self._raw: sqlite3.Cursor | None = None
        self.rowcount = -1

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        db = self._conn._enter()
        if sql.strip().upper().startswith("CALL DOLT_COMMIT"):
            self._conn._server.dolt_commits.append(str(params[0]))
            return
        translated = sql.replace("%s", "?").replace("<=>", "IS").replace("INSERT IGNORE", "INSERT OR IGNORE")
        self._raw = db.execute(translated, params)
        self.rowcount = self._raw.rowcount

    def fetchall(self) -> list[tuple[Any, ...]]:
        assert self._raw is not None
        return self._raw.fetchall()

    def fetchone(self) -> tuple[Any, ...] | None:
        assert self._raw is not None
        return self._raw.fetchone()

    def close(self) -> None:
        pass


def _dolt_over_fake() -> tuple[DoltBranchStore, FakeDolt]:
    fake = FakeDolt()
    store = DoltBranchStore(fake.connect)
    store.ensure_schema()
    return store, fake


def _real_dolt_store() -> DoltBranchStore:
    port = int(os.environ["DOLT_TEST_PORT"])
    database = f"ledger_{uuid.uuid4().hex[:8]}"
    admin = pymysql_connector("127.0.0.1", port, "")()
    admin.cursor().execute(f"CREATE DATABASE {database}")
    admin.close()
    store = DoltBranchStore(pymysql_connector("127.0.0.1", port, database))
    store.ensure_schema()
    return store


@pytest.fixture(
    params=[
        "memory",
        "dolt-fake",
        pytest.param(
            "dolt-server",
            marks=pytest.mark.skipif(not os.environ.get("DOLT_TEST_PORT"), reason="DOLT_TEST_PORT not set"),
        ),
    ]
)
def store(request: pytest.FixtureRequest) -> Iterator[BranchStore]:
    if request.param == "memory":
        yield MemoryBranchStore()
    elif request.param == "dolt-fake":
        yield _dolt_over_fake()[0]
    else:
        yield _real_dolt_store()


def test_a_new_store_is_empty_with_no_head(store: BranchStore) -> None:
    snap = store.read()
    assert snap.head is None and snap.files == {}


def test_write_advances_head_and_files_round_trip(store: BranchStore) -> None:
    first = store.write({"state.json": '{"a":1}\n', "events.jsonl": "é\n"}, message="one", parent=None)
    snap = store.read()
    assert first and snap.head == first
    assert snap.files == {"state.json": '{"a":1}\n', "events.jsonl": "é\n"}

    second = store.write({"state.json": '{"a":2}\n'}, message="two", parent=first)
    snap = store.read()
    assert second != first and snap.head == second
    assert snap.files == {"state.json": '{"a":2}\n', "events.jsonl": "é\n"}  # unchanged file kept


def test_a_stale_parent_raises_conflict_and_changes_nothing(store: BranchStore) -> None:
    first = store.write({"state.json": "1"}, message="one", parent=None)
    store.write({"state.json": "2"}, message="two", parent=first)
    with pytest.raises(StoreConflict):
        store.write({"state.json": "stale", "extra.json": "x"}, message="late", parent=first)
    snap = store.read()
    assert snap.files == {"state.json": "2"}


def test_writing_from_no_parent_twice_conflicts(store: BranchStore) -> None:
    store.write({"state.json": "1"}, message="one", parent=None)
    with pytest.raises(StoreConflict):
        store.write({"state.json": "other"}, message="two", parent=None)


def test_racing_writers_on_one_parent_have_one_winner(store: BranchStore) -> None:
    if isinstance(store, MemoryBranchStore):
        pytest.skip("single-threaded by design")
    parent = store.write({"state.json": "0"}, message="seed", parent=None)
    results: list[str] = []

    def attempt(n: int) -> None:
        try:
            store.write({"state.json": str(n)}, message=f"w{n}", parent=parent)
            results.append("won")
        except StoreConflict:
            results.append("conflict")

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["conflict"] * 7 + ["won"]


def test_each_write_makes_one_dolt_commit_with_the_message() -> None:
    store, fake = _dolt_over_fake()
    first = store.write({"state.json": "1"}, message="ledger: ingest +1 events (seq 1)", parent=None)
    store.write({"state.json": "2"}, message="ledger: ingest +2 events (seq 3)", parent=first)
    with pytest.raises(StoreConflict):
        store.write({"state.json": "3"}, message="never", parent=first)
    assert fake.dolt_commits == ["ledger: ingest +1 events (seq 1)", "ledger: ingest +2 events (seq 3)"]


def test_a_failure_while_writing_files_rolls_back_the_head() -> None:
    store, fake = _dolt_over_fake()
    first = store.write({"state.json": "1"}, message="one", parent=None)

    real_connect: Callable[[], Any] = fake.connect

    def exploding() -> Any:
        conn = real_connect()
        inner = conn.cursor

        def cursor() -> Any:
            cur = inner()
            execute = cur.execute

            def boom(sql: str, params: tuple[Any, ...] = ()) -> Any:
                if sql.startswith("REPLACE"):
                    raise RuntimeError("disk full")
                return execute(sql, params)

            cur.execute = boom
            return cur

        conn.cursor = cursor
        return conn

    broken = DoltBranchStore(exploding)
    with pytest.raises(RuntimeError, match="disk full"):
        broken.write({"state.json": "2"}, message="two", parent=first)
    snap = store.read()
    assert snap.head == first and snap.files == {"state.json": "1"}
