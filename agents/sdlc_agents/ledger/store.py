"""
Where the ledger keeps its files: git branch `state` (files `state.json`, `events.jsonl`, `archive.json`).

Writes are one commit that sets all changed files, moved onto the branch without force, so a second
writer (which should not exist) makes the commit fail with StoreConflict and the ledger re-reads and
folds again instead of overwriting. The ledger is the only writer of this branch. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sdlc_agents.ports import GitHubError

STATE_BRANCH = "state"
STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"
ARCHIVE_FILE = "archive.json"
FILES = (STATE_FILE, EVENTS_FILE, ARCHIVE_FILE)


class StoreConflict(RuntimeError):
    """The branch moved between our read and our write."""


@dataclass
class Snapshot:
    files: dict[str, str] = field(default_factory=dict)
    head: str | None = None


class BranchStore(Protocol):
    def read(self) -> Snapshot: ...
    def write(self, files: dict[str, str], *, message: str, parent: str | None) -> str: ...


class GitHubBranchStore:
    """BranchStore over GitHubClient.read_files / commit_files."""

    def __init__(self, github: Any, branch: str = STATE_BRANCH):
        self._github = github
        self._branch = branch

    def read(self) -> Snapshot:
        files = self._github.read_files(self._branch, FILES)
        if files is None:
            return Snapshot()
        return Snapshot(files, self._github.get_branch_sha(self._branch))

    def write(self, files: dict[str, str], *, message: str, parent: str | None) -> str:
        try:
            return str(self._github.commit_files(self._branch, files, message=message, parent_sha=parent))
        except GitHubError as exc:
            if exc.status in (409, 422):
                raise StoreConflict(str(exc)) from exc
            raise


class MemoryBranchStore:
    """In-memory store for tests and dry runs: same compare-and-swap rule as the real branch."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.head: str | None = None
        self.commits: list[tuple[str, str, dict[str, str]]] = []
        self.fail_next: list[Exception] = []

    def read(self) -> Snapshot:
        return Snapshot(dict(self.files), self.head)

    def write(self, files: dict[str, str], *, message: str, parent: str | None) -> str:
        if self.fail_next:
            raise self.fail_next.pop(0)
        if parent != self.head:
            raise StoreConflict("branch moved")
        self.files.update(files)
        self.head = f"{len(self.commits) + 1:040x}"
        self.commits.append((self.head, message, dict(files)))
        return self.head
