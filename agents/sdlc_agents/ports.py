"""
Ports: the narrow interfaces between the orchestrator logic, the coder runtime and the outside world.

Business logic (state machine, gates, coder loop) depends only on these Protocols and dataclasses.
Real adapters (urllib GitHub client, Foundry client, Key Vault REST, subprocess git) implement them;
tests use in-memory fakes. Stdlib only, so the hosted agent zips stay small.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

REPO = "stevengonsalvez/foundry-autonomous-sdlc"
OWNER = "stevengonsalvez"


# ---------------------------------------------------------------------------
# GitHub value objects (only the fields the system reads)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    author: str
    labels: tuple[str, ...]
    state: str            # "open" | "closed"
    created_at: str       # ISO 8601 UTC
    closed_at: str | None = None
    is_pull_request: bool = False


@dataclass(frozen=True)
class Comment:
    id: int
    author: str
    body: str
    created_at: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    author: str
    labels: tuple[str, ...]
    state: str            # "open" | "closed"
    merged: bool
    head_ref: str
    head_sha: str
    base_ref: str
    created_at: str
    merged_at: str | None = None
    merge_commit_sha: str | None = None


@dataclass(frozen=True)
class CheckRun:
    name: str
    status: str           # "queued" | "in_progress" | "completed"
    conclusion: str | None  # "success" | "failure" | "cancelled" | "skipped" | ... | None while running
    completed_at: str | None = None
    pull_requests: tuple[int, ...] = ()   # same-repo PRs the run belongs to (GitHub omits fork PRs)


@dataclass(frozen=True)
class PullCommit:
    sha: str
    message: str
    files: tuple[str, ...]   # paths changed by this commit


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


class GitHubPort(Protocol):
    """Everything is scoped to REPO. Implementations must refuse any other repository."""

    def list_issues(self, *, state: str = "open", labels: tuple[str, ...] = ()) -> list[Issue]: ...
    def get_issue(self, number: int) -> Issue: ...
    def add_labels(self, number: int, labels: tuple[str, ...]) -> None: ...
    def remove_label(self, number: int, label: str) -> None: ...   # no error if absent
    def list_comments(self, number: int) -> list[Comment]: ...
    def create_comment(self, number: int, body: str) -> Comment: ...
    def update_comment(self, comment_id: int, body: str) -> None: ...
    def close_issue(self, number: int) -> None: ...

    def list_pulls(self, *, state: str = "open") -> list[PullRequest]: ...
    def get_pull(self, number: int) -> PullRequest: ...
    def get_pull_diff(self, number: int) -> str: ...
    def list_pull_commits(self, number: int) -> list[PullCommit]: ...
    def list_pull_files(self, number: int) -> list[str]: ...                         # incl. rename sources
    def create_pull(self, *, title: str, head: str, base: str, body: str) -> PullRequest: ...
    def merge_pull(self, number: int, *, sha: str, method: str = "merge") -> str: ...  # returns merge commit sha
    def get_check_runs(self, sha: str) -> list[CheckRun]: ...
    def get_check_log(self, sha: str, name: str) -> str: ...                        # log tail, "" if unavailable

    def get_file(self, path: str, *, ref: str) -> str | None: ...                   # None if absent
    def put_file(self, path: str, content: str, *, branch: str, message: str) -> None: ...  # create or update
    def get_branch_sha(self, branch: str) -> str | None: ...
    def create_branch(self, branch: str, *, from_sha: str) -> None: ...             # GitHubError(422) if it exists
    def delete_branch(self, branch: str) -> None: ...
    def branch_commit_time(self, branch: str) -> str | None: ...                    # ISO time of the branch tip commit
    def create_commit(self, message: str, *, parent_sha: str) -> str: ...           # empty commit on parent's tree

    def list_tags(self) -> list[str]: ...
    def create_release(self, *, tag: str, target_sha: str, name: str, body: str) -> str: ...  # returns html_url
    def dispatch_workflow(self, workflow_file: str, *, ref: str) -> None: ...


# ---------------------------------------------------------------------------
# Foundry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentResult:
    text: str
    input_tokens: int
    output_tokens: int


class FoundryPort(Protocol):
    def call_prompt_agent(self, agent: str, input_text: str, *, max_output_tokens: int = 8000) -> AgentResult:
        """Invoke a prompt agent by name (latest version) and return its text. Raises on non-completed responses."""
        ...

    def invoke_hosted(self, agent: str, body: dict[str, Any], *, session_id: str | None = None,
                      timeout_s: int = 240) -> tuple[dict[str, Any], str]:
        """POST to a hosted agent's Invocations endpoint. Returns (json_body, session_id)."""
        ...


class SecretsPort(Protocol):
    def get_secret(self, name: str) -> str: ...


# ---------------------------------------------------------------------------
# Git (coder runtime). Methods run in a working copy and raise GitError on failure.
# ---------------------------------------------------------------------------

class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str           # combined stdout and stderr, truncated by the adapter if huge


class GitPort(Protocol):
    def clone(self, repo: str, dest: str, *, token: str) -> None: ...
    def checkout_new_branch(self, name: str, *, base: str) -> None: ...
    def checkout_existing_branch(self, name: str) -> None: ...
    def write_files(self, files: dict[str, str]) -> None: ...
    def changed_paths(self) -> list[str]: ...
    def revert_paths(self, paths: list[str]) -> None: ...
    def commit_all(self, message: str) -> str: ...      # returns sha; no-op raises GitError if nothing to commit
    def push(self, branch: str, *, force: bool = False) -> None: ...
    def head_sha(self) -> str: ...
    def run(self, cmd: list[str] | str, *, timeout_s: int) -> CommandResult: ...


class CodingEnginePort(Protocol):
    """A CLI or model loop that edits files in the working copy. It never runs git."""
    name: str

    def edit(self, prompt: str, *, workdir: str, timeout_s: int) -> CommandResult: ...


# ---------------------------------------------------------------------------
# Time and ids (injected for deterministic tests)
# ---------------------------------------------------------------------------

class ClockPort(Protocol):
    def now_iso(self) -> str: ...
    def monotonic(self) -> float: ...


@dataclass
class Budget:
    """Cumulative money and wall-clock accounting, shared across a tick."""
    usd_total: float = 0.0
    usd_cap_total: float = 4.50
    usd_cap_issue: float = 1.00
    extras: dict[str, Any] = field(default_factory=dict)
