"""
Coder job: the validated request, its persisted state and its redacting log.

State lives in $HOME/jobs/<job_id>/state.json (atomic replace) next to an append-only log,
so a status call after the sandbox was evicted and restored still answers.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import threading
import traceback
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from sdlc_agents.coder import scope
from sdlc_agents.cost import HOSTED_GIB_USD_PER_HOUR, HOSTED_VCPU_USD_PER_HOUR
from sdlc_agents.ports import REPO

DEFAULT_MAX_ITERATIONS = 5
MAX_ITERATIONS_CAP = 20
# Two hours: coder compute costs about 0.27 USD per hour and the per-issue cap is 3 USD.
DEFAULT_DEADLINE_S = 7200
MIN_DEADLINE_S = 60
DEFAULT_MAX_MODEL_USD = 0.50
MAX_MODEL_USD_CAP = 3.00   # the per-issue cost cap; one job can never be allowed more
LOG_TAIL_CHARS = 4000

_JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_AGENT_BRANCH = re.compile(r"agent/[A-Za-z0-9._/-]+")
_ANY_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_FORBIDDEN_BRANCHES = {"main", "master", "HEAD", "sdlc-lock", "metrics"}
# Commands run through a shell (as the engine user): words of plain characters only, so no
# job field can chain, substitute or redirect (no ; & | $ ` < > quotes or newlines).
_COMMAND = re.compile(r"[A-Za-z0-9 ._/=:@,+%-]*")


class Mode(StrEnum):
    FEATURE = "feature"          # new red tests, then an implementation, then a new PR
    BUGFIX = "bugfix"
    REVISE = "revise"            # review asked for changes: new head on the existing PR, tests untouched
    MAINTENANCE = "maintenance"  # stale tests on an existing PR branch: only test files change

    @property
    def commit_prefix(self) -> str:
        return {Mode.FEATURE: "feat", Mode.BUGFIX: "fix", Mode.REVISE: "fix", Mode.MAINTENANCE: "test"}[self]

    @property
    def writes_red_tests(self) -> bool:
        return self in (Mode.FEATURE, Mode.BUGFIX)


class Status(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Phase(StrEnum):
    SETUP = "setup"
    TESTS = "tests"
    IMPLEMENT = "implement"
    PUSH = "push"
    PR = "pr"


class JobSpecError(ValueError):
    pass


@dataclass(frozen=True)
class TestFile:
    __test__ = False  # not a pytest class

    path: str
    content: str


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    repo: str
    base: str
    branch: str
    mode: Mode
    issue_number: int
    issue_title: str
    issue_body: str
    acceptance_criteria: tuple[str, ...]
    notes: str
    tests: tuple[TestFile, ...]
    test_cmd: str
    max_iterations: int
    deadline_s: int
    allowed_paths: tuple[str, ...]
    workdir: str
    install_cmd: str
    max_model_usd: float
    pr_number: int | None = None
    merge_main: bool = False      # revise only: merge origin/<base> into the branch first (the PR conflicts)

    @classmethod
    def from_request(cls, job: Any) -> JobSpec:
        try:
            return cls._parse(job)
        except JobSpecError:
            raise
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise JobSpecError(f"malformed job: {type(exc).__name__}: {exc}") from None

    @classmethod
    def _parse(cls, job: Any) -> JobSpec:
        if not isinstance(job, dict):
            raise JobSpecError("job must be an object")
        job_id = _str(job, "job_id")
        if not _JOB_ID.fullmatch(job_id):
            raise JobSpecError("job_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        if job.get("repo") != REPO:
            raise JobSpecError(f"repo must be {REPO}")
        try:
            mode = Mode(job.get("mode"))
        except ValueError:
            raise JobSpecError("mode must be feature, bugfix, revise or maintenance") from None
        base = _base(job.get("base", "main"))
        branch = _branch(_str(job, "branch"), mode, base=base)
        pr = job.get("pr")
        pr_number = pr.get("number") if isinstance(pr, dict) else None
        if mode in (Mode.REVISE, Mode.MAINTENANCE) and (not isinstance(pr_number, int) or isinstance(pr_number, bool)):
            raise JobSpecError("pr.number is required for revise and maintenance jobs")
        issue = job.get("issue") or {}
        if not isinstance(issue.get("number"), int):
            if mode is not Mode.MAINTENANCE:
                raise JobSpecError("issue.number is required")
            issue = {**issue, "number": pr_number}
        merge_main = job.get("merge_main", False)
        if not isinstance(merge_main, bool) or (merge_main and mode is not Mode.REVISE):
            raise JobSpecError("merge_main must be a boolean and is only for revise jobs")
        allowed = tuple(job.get("allowed_paths") or ())
        if not allowed or not all(isinstance(p, str) and scope.is_safe_relative(p.rstrip("/")) for p in allowed):
            raise JobSpecError("allowed_paths must be non-empty repo-relative paths")
        tests = tuple(TestFile(str(t["path"]), str(t["content"])) for t in job.get("tests") or ())
        if mode.writes_red_tests and not tests:
            raise JobSpecError("tests are required for feature and bugfix jobs")
        if not mode.writes_red_tests and tests:
            raise JobSpecError("tests must be empty for revise and maintenance jobs")
        if mode is Mode.MAINTENANCE and not all(scope.is_test_path(p) for p in allowed):
            raise JobSpecError("allowed_paths for maintenance must be test files matching a test glob")
        for t in tests:
            if not scope.is_test_path(t.path):
                raise JobSpecError(f"tests: {t.path} does not match a test glob")
            if not scope.within_allowed(t.path, allowed):
                raise JobSpecError(f"tests: {t.path} is outside allowed_paths")
        workdir = str(job.get("workdir", "app"))
        if workdir != "." and not scope.is_safe_relative(workdir):
            raise JobSpecError("workdir must be a repo-relative directory")
        spec = job.get("spec") or {}
        return cls(
            job_id=job_id, repo=REPO, base=base, branch=branch, mode=mode,
            issue_number=issue["number"], issue_title=str(issue.get("title", "")),
            issue_body=str(issue.get("body", "")),
            acceptance_criteria=tuple(str(c) for c in spec.get("acceptance_criteria", ())),
            notes=str(spec.get("notes", "")), tests=tests, test_cmd=_command(job, "test_cmd", required=True),
            max_iterations=_int(job, "max_iterations", DEFAULT_MAX_ITERATIONS, 1, MAX_ITERATIONS_CAP),
            deadline_s=_int(job, "deadline_s", DEFAULT_DEADLINE_S, MIN_DEADLINE_S, DEFAULT_DEADLINE_S),
            allowed_paths=allowed, workdir=workdir, install_cmd=_command(job, "install_cmd", default="npm ci"),
            max_model_usd=_usd(job.get("max_model_usd", DEFAULT_MAX_MODEL_USD)),
            pr_number=pr_number if isinstance(pr_number, int) else None, merge_main=merge_main,
        )

    def to_request(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id, "repo": self.repo, "base": self.base, "branch": self.branch,
            "mode": self.mode.value,
            "issue": {"number": self.issue_number, "title": self.issue_title, "body": self.issue_body},
            "spec": {"acceptance_criteria": list(self.acceptance_criteria), "notes": self.notes},
            "tests": [{"path": t.path, "content": t.content} for t in self.tests],
            "test_cmd": self.test_cmd, "max_iterations": self.max_iterations, "deadline_s": self.deadline_s,
            "allowed_paths": list(self.allowed_paths), "workdir": self.workdir, "install_cmd": self.install_cmd,
            "max_model_usd": self.max_model_usd,
            **({"pr": {"number": self.pr_number}} if self.pr_number is not None else {}),
            **({"merge_main": True} if self.merge_main else {}),
        }


def _command(job: dict[str, Any], key: str, *, required: bool = False, default: str = "") -> str:
    value = job.get(key, default)
    if not isinstance(value, str) or not _COMMAND.fullmatch(value) or (required and not value.strip()):
        raise JobSpecError(f"{key} must be plain words (letters, digits, spaces and ._/=:@,+%-)")
    return value


def _base(base: Any) -> str:
    if (not isinstance(base, str) or not _ANY_BRANCH.fullmatch(base) or ".." in base or base.startswith("refs/")
            or base.endswith(("/", ".lock"))):
        raise JobSpecError("base must be a plain branch name")
    return base


def _branch(branch: str, mode: Mode, *, base: str) -> str:
    """agent/* for agent work; maintenance may target any PR branch, never a protected or odd ref."""
    pattern = _ANY_BRANCH if mode is Mode.MAINTENANCE else _AGENT_BRANCH
    if (not pattern.fullmatch(branch) or ".." in branch or "//" in branch or branch.endswith(("/", ".lock"))
            or branch in _FORBIDDEN_BRANCHES or branch == base or branch.startswith("refs/")):
        raise JobSpecError("branch must be a valid agent/* ref (maintenance: a PR branch other than the base)")
    return branch


def _str(job: dict[str, Any], key: str, default: str | None = None) -> str:
    value = job.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise JobSpecError(f"{key} must be a non-empty string")
    return value


def _usd(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) \
            or not 0 < value <= MAX_MODEL_USD_CAP:
        raise JobSpecError(f"max_model_usd must be a number in (0, {MAX_MODEL_USD_CAP}]")
    return float(value)


def _int(job: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = job.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise JobSpecError(f"{key} must be an integer in [{low}, {high}]")
    return value


@dataclass
class JobState:
    job_id: str
    request: dict[str, Any]
    status: Status = Status.RUNNING
    phase: Phase = Phase.SETUP
    reason: str | None = None
    detail: str = ""
    iterations: int = 0
    engine: str | None = None
    started_at: str = ""
    updated_at: str = ""
    elapsed_s: float = 0.0
    pr: dict[str, Any] | None = None
    red_summary: str = ""
    green_summary: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model_usd: float = 0.0
    violations: list[str] = field(default_factory=list)
    session_id: str = ""      # platform session the job runs in (x-agent-session-id)
    agy_user: str = ""        # who ran agy: agyuser, or root when the sandbox could not create the user
    tests_user: str = ""      # who ran install_cmd and test_cmd (same rule)
    engine_events: list[dict[str, Any]] = field(default_factory=list)   # per-iteration engine trouble

    @classmethod
    def new(cls, spec: JobSpec, *, started_at: str) -> JobState:
        return cls(job_id=spec.job_id, request=spec.to_request(), started_at=started_at, updated_at=started_at)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobState:
        state = cls(**data)
        state.status = Status(state.status)
        state.phase = Phase(state.phase)
        return state

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def terminal(self) -> bool:
        return self.status is not Status.RUNNING

    def view(self, log_tail: str, *, usd_per_hour: float = 0.0, now: str = "") -> dict[str, Any]:
        """The Coder contract status response. `usd_per_hour` prices this agent's hosted compute;
        `stale_s` is how long ago the job last wrote its state (a running job heartbeats every 30 s)."""
        return {
            "updated_at": self.updated_at, "stale_s": _seconds_between(self.updated_at, now),
            "job_id": self.job_id, "status": self.status.value, "phase": self.phase.value, "reason": self.reason,
            "detail": self.detail, "iterations": self.iterations, "engine": self.engine,
            "session_id": self.session_id, "agy_user": self.agy_user, "tests_user": self.tests_user,
            "engine_events": self.engine_events,
            "elapsed_s": round(self.elapsed_s), "pr": self.pr, "red": self.red_summary, "green": self.green_summary,
            "cost": {"model_usd": round(self.model_usd, 6), "input_tokens": self.input_tokens,
                     "output_tokens": self.output_tokens, "coder_seconds": round(self.elapsed_s),
                     "coder_usd": round(self.elapsed_s * usd_per_hour / 3600, 6),
                     "hosted_vcpu_usd_per_hour": HOSTED_VCPU_USD_PER_HOUR,
                     "hosted_gib_usd_per_hour": HOSTED_GIB_USD_PER_HOUR,
                     "note": "agy usage is billed to its plan and not metered here"},
            "log_tail": log_tail,
        }


def _seconds_between(earlier: str, later: str) -> int | None:
    try:
        return round((datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds())
    except ValueError:
        return None


# Secret shapes scrubbed even when nobody registered the value.
_SHAPES = (
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(?:(?:bearer|basic|token)\s+)?[^\s'\",}]+"), r"\1***"),
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+(?::[^/\s@]*)?@"), r"\1***@"),        # credentials in a URL
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "***"),      # JWT
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), "***"),  # GitHub tokens
)
_BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_SECRET_ENV = re.compile(r"TOKEN|SECRET|PASSWORD|PASSWD|APIKEY|(?:^|_)(?:KEY|HEADER|AUTH)(?:_|$)|^IDENTITY_ENDPOINT$",
                         re.IGNORECASE)
_HOME = re.compile(r"/(?:home|Users)/[^/\s'\"]+")
MIN_ENV_SECRET = 8        # shorter values (1, true) would redact half of every log line
TRACEBACK_MAX_CHARS = 4000


def _blob(match: re.Match[str]) -> str:
    """Long base64 runs with mixed case and digits are secrets; hex shas and paths are not. A run with two or
    more slashes is a path unless one of its segments alone looks random (random base64 of 40 characters
    has about six digits and under one slash; a path of words rarely has three digits and an upper case)."""
    text = match.group()
    if text.count("/") < 2:
        return "***" if _random(text, digits=3) else text
    return "/".join("***" if len(seg) >= 20 and _random(seg, digits=2) else seg for seg in text.split("/"))


def _random(text: str, *, digits: int) -> bool:
    return (bool(re.search("[A-Z]", text) and re.search("[a-z]", text)) and len(re.findall("[0-9]", text)) >= digits
            and not re.fullmatch(r"[0-9a-f]+", text))


class Redactor:
    """Replaces every known secret (and its git basic-auth form), the values of secret-named environment
    variables, and anything shaped like a credential (Authorization values, URL userinfo, JWTs, GitHub
    tokens, long base64 blobs) with ***."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._secrets: set[str] = set()
        self._lock = threading.Lock()
        for name, value in (os.environ if env is None else env).items():
            if _SECRET_ENV.search(name) and len(value) >= MIN_ENV_SECRET:
                self.add(value)

    def add(self, secret: str) -> None:
        if len(secret) < 4:
            return
        basic = base64.b64encode(f"x-access-token:{secret}".encode()).decode()
        with self._lock:
            self._secrets.update({secret, basic, *_json_strings(secret)})

    def __call__(self, text: str) -> str:
        with self._lock:
            secrets = sorted(self._secrets, key=len, reverse=True)
        for secret in secrets:
            text = text.replace(secret, "***")
        for pattern, replacement in _SHAPES:
            text = pattern.sub(replacement, text)
        return _BLOB.sub(_blob, text)

    def traceback(self, exc: BaseException, limit: int = TRACEBACK_MAX_CHARS) -> str:
        """A redacted traceback for logs and status: no local variables, home paths shortened, the header
        kept and the tail (where the error is) capped."""
        text = _HOME.sub("~", self("".join(traceback.format_exception(exc))))
        if len(text) <= limit:
            return text
        header = "Traceback (most recent call last):\n...\n"
        return header + text[-(limit - len(header)):]


def _json_strings(secret: str, min_len: int = 16) -> set[str]:
    """String values inside a JSON secret (the agy token file), so a single printed field is redacted too."""
    try:
        data = json.loads(secret)
    except ValueError:
        return set()
    found: set[str] = set()
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and len(item) >= min_len:
            found.add(item)
    return found


class JobStore:
    def __init__(self, root: Path, redactor: Redactor):
        self.root = root
        self.redact = redactor
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()

    def job_dir(self, job_id: str) -> Path:
        if not _JOB_ID.fullmatch(job_id):
            raise JobSpecError("invalid job_id")
        path = self.root / job_id
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path

    def load(self, job_id: str) -> JobState | None:
        path = self.root / job_id / "state.json"
        if not _JOB_ID.fullmatch(job_id) or not path.exists():
            return None
        return JobState.from_dict(json.loads(path.read_text()))

    def save(self, state: JobState) -> None:
        path = self.job_dir(state.job_id) / "state.json"
        tmp = path.with_suffix(".tmp")
        with self._save_lock:   # the job thread and its heartbeat both save
            tmp.write_text(json.dumps(state.to_dict(), indent=1))
            os.replace(tmp, path)

    def job_ids(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("*") if (p / "state.json").is_file()) if self.root.is_dir() else []

    def log(self, job_id: str, text: str) -> None:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = self.redact(f"{stamp} {text.rstrip()}\n")
        with self._lock, open(self.job_dir(job_id) / "log", "a", encoding="utf-8") as fh:
            fh.write(line)

    def tail(self, job_id: str, chars: int = LOG_TAIL_CHARS) -> str:
        path = self.root / job_id / "log"
        if not _JOB_ID.fullmatch(job_id) or not path.exists():
            return ""
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(fh.tell() - chars, 0))
            return self.redact(fh.read().decode("utf-8", errors="replace"))
