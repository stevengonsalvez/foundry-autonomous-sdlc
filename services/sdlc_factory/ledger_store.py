"""
The ledger's files in a Dolt database, behind the same BranchStore protocol as the GitHub `state` branch.

    files(path PK, content LONGTEXT)   state.json, events.jsonl, archive.json
    meta(id PK, head)                  one row, id 1: the token of the last write, NULL before the first

    write = UPDATE meta SET head=<new> WHERE id=1 AND head <=> <parent>   0 rows: StoreConflict
            REPLACE the changed files, COMMIT, CALL DOLT_COMMIT('-Am', message)

The conditional UPDATE is the compare-and-swap: of N writers holding one parent, one changes the row and the
rest see zero rows (or lose the commit race) and get StoreConflict, so the ledger re-reads and folds again.
SQL commit and DOLT_COMMIT are two steps; a crash between them leaves working-set changes that the next
write's `-Am` sweeps into its commit, which is fine because the ledger rebuilds from events.jsonl.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

import pymysql
from sdlc_agents.ledger.store import Snapshot, StoreConflict

META_ID = 1
# MySQL 1213 deadlock, 1105 (Dolt reports a lost optimistic commit as a generic error), 1062 duplicate key.
CONFLICT_CODES = frozenset({1213, 1105, 1062})

Connect = Callable[[], Any]  # a DB-API connection: cursor(), commit(), rollback(), close()


def pymysql_connector(host: str, port: int, database: str, *, user: str = "root", password: str = "") -> Connect:
    """Connection factory for a Dolt (or MySQL) server. Autocommit is off so each call is one transaction."""

    def connect() -> Any:
        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database or None,
            autocommit=False,
            charset="utf8mb4",
            connect_timeout=10,
        )

    return connect


class DoltBranchStore:
    def __init__(self, connect: Connect):
        self._connect = connect

    def ensure_schema(self) -> None:
        """Create the tables and the single meta row if absent. Safe to run on every start."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS files (path VARCHAR(255) PRIMARY KEY, content LONGTEXT NOT NULL)")
            cur.execute("CREATE TABLE IF NOT EXISTS meta (id INT PRIMARY KEY, head VARCHAR(64) NULL)")
            cur.execute("INSERT IGNORE INTO meta (id, head) VALUES (%s, NULL)", (META_ID,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def read(self) -> Snapshot:
        conn = self._connect()
        try:
            cur = conn.cursor()
            # One transaction, so head and files come from the same snapshot even while a write lands.
            cur.execute("SELECT head FROM meta WHERE id = %s", (META_ID,))
            row = cur.fetchone()
            cur.execute("SELECT path, content FROM files")
            files = {str(path): str(content) for path, content in cur.fetchall()}
            return Snapshot(files, row[0] if row and row[0] is not None else None)
        finally:
            conn.rollback()
            conn.close()

    def write(self, files: dict[str, str], *, message: str, parent: str | None) -> str:
        head = secrets.token_hex(20)  # the same shape as a git sha, so callers cannot tell the stores apart
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE meta SET head = %s WHERE id = %s AND head <=> %s", (head, META_ID, parent))
            if cur.rowcount == 0:
                raise StoreConflict("ledger head moved")
            for path, content in files.items():
                cur.execute("REPLACE INTO files (path, content) VALUES (%s, %s)", (path, content))
            conn.commit()
        except StoreConflict:
            conn.rollback()
            raise
        except pymysql.MySQLError as exc:
            conn.rollback()
            if exc.args and exc.args[0] in CONFLICT_CODES:
                raise StoreConflict(f"ledger write lost the race: {exc}") from exc
            raise
        except Exception:
            conn.rollback()
            raise
        else:
            self._dolt_commit(conn, message)
            return head
        finally:
            conn.close()

    @staticmethod
    def _dolt_commit(conn: Any, message: str) -> None:
        cur = conn.cursor()
        cur.execute("CALL DOLT_COMMIT('-Am', %s)", (message,))
        conn.commit()
