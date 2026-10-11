"""The state file `deploy.json` on the `deploy` branch, as pure functions.

Every transition takes a state and returns a new one; nothing here touches the disk, the
network or the clock (callers pass `now`). The git side lives in `deploy_branch.py`.

Layout of the `deploy` branch: `prod/` is the app live at the site root, `staging/` the app on
/staging/, `prod-prev/` the app prod had before the last promotion (the rollback target).
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
HISTORY_LIMIT = 60
GATES = ["smoke", "soak"]
STAGING_STATUSES = (
    "deployed",
    "smoke-passed",
    "soaking",
    "promoted",
    "failed",
    "rolled-back",
    "superseded",
)
IN_FLIGHT = ("deployed", "smoke-passed", "soaking")
HISTORY_ACTIONS = ("stage", "promote", "rollback", "skip", "fail")
ENVS = ("staging", "prod")

State = dict[str, Any]

_SHA = re.compile(r"[0-9a-f]{40}")
_ENTRY_STRINGS = ("sha", "short", "version", "built_at", "run_url")


class DeployStateError(ValueError):
    """The state file is malformed, or a transition does not apply to it."""


@dataclass(frozen=True)
class Include:
    """One merged pull request that reaches an environment with a build."""

    pr: int
    issue: int | None
    sha: str

    def as_dict(self) -> dict[str, Any]:
        return {"pr": self.pr, "issue": self.issue, "sha": self.sha}


@dataclass(frozen=True)
class Release:
    """What a build is, as known when it is staged."""

    sha: str
    short: str
    version: str
    built_at: str
    run_id: int
    run_url: str
    pr: int | None = None
    issue: int | None = None
    includes: tuple[Include, ...] = ()

    @property
    def subject(self) -> Subject:
        return Subject(self.sha, self.version, self.pr, self.issue)


@dataclass(frozen=True)
class Subject:
    """The release a failure or a skip is about."""

    sha: str
    version: str | None = None
    pr: int | None = None
    issue: int | None = None


def empty_state() -> State:
    return {
        "version": SCHEMA_VERSION,
        "staging": None,
        "prod": None,
        "previous_prod": None,
        "history": [],
    }


def tag_name(now: str, short: str) -> str:
    """`prod/<UTC yyyymmdd-HHMMSS>-<short sha>` from an ISO time like 2026-10-11T09:30:05Z."""
    match = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)Z", now)
    if not match:
        raise DeployStateError(f"not a UTC timestamp: {now!r}")
    date = "".join(match.groups()[:3])
    clock = "".join(match.groups()[3:])
    return f"prod/{date}-{clock}-{short}"


# ---- validation and serialisation -------------------------------------------------------------


def _is_int_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool))


def _check_includes(where: str, value: Any, problems: list[str]) -> None:
    if not isinstance(value, list):
        problems.append(f"{where}.includes must be a list")
        return
    for i, item in enumerate(value):
        ok = (
            isinstance(item, dict)
            and isinstance(item.get("pr"), int)
            and not isinstance(item.get("pr"), bool)
            and _is_int_or_none(item.get("issue"))
            and isinstance(item.get("sha"), str)
            and bool(_SHA.fullmatch(item["sha"]))
        )
        if not ok:
            problems.append(f"{where}.includes[{i}] must be {{pr:int, issue:int|null, sha:40 hex}}")


def _check_entry(where: str, entry: Any, time_key: str, problems: list[str]) -> None:
    if entry is None:
        return
    if not isinstance(entry, dict):
        problems.append(f"{where} must be an object or null")
        return
    for key in (*_ENTRY_STRINGS, time_key):
        if not isinstance(entry.get(key), str) or not entry[key]:
            problems.append(f"{where}.{key} must be a non-empty string")
    if isinstance(entry.get("sha"), str) and not _SHA.fullmatch(entry["sha"]):
        problems.append(f"{where}.sha must be 40 hex characters")
    if not isinstance(entry.get("run_id"), int) or isinstance(entry.get("run_id"), bool):
        problems.append(f"{where}.run_id must be an integer")
    for key in ("pr", "issue"):
        if not _is_int_or_none(entry.get(key)):
            problems.append(f"{where}.{key} must be an integer or null")
    _check_includes(where, entry.get("includes"), problems)
    if where == "staging" and entry.get("status") not in STAGING_STATUSES:
        problems.append(f"staging.status must be one of {', '.join(STAGING_STATUSES)}")
    if where != "staging":
        if not _is_int_or_none(entry.get("run_attempt")):
            problems.append(f"{where}.run_attempt must be an integer when present")
        if not isinstance(entry.get("gates"), list):
            problems.append(f"{where}.gates must be a list")
        if entry.get("tag") is not None and not isinstance(entry.get("tag"), str):
            problems.append(f"{where}.tag must be a string or null")


def validate(state: Any) -> list[str]:
    """Every problem found, empty when the state is a valid schema v1 file."""
    if not isinstance(state, dict):
        return ["state must be an object"]
    problems: list[str] = []
    if state.get("version") != SCHEMA_VERSION:
        problems.append(f"version must be {SCHEMA_VERSION}")
    _check_entry("staging", state.get("staging"), "deployed_at", problems)
    _check_entry("prod", state.get("prod"), "promoted_at", problems)
    _check_entry("previous_prod", state.get("previous_prod"), "promoted_at", problems)
    history = state.get("history")
    if not isinstance(history, list):
        problems.append("history must be a list")
        return problems
    for i, item in enumerate(history):
        where = f"history[{i}]"
        if not isinstance(item, dict):
            problems.append(f"{where} must be an object")
            continue
        if item.get("action") not in HISTORY_ACTIONS:
            problems.append(f"{where}.action must be one of {', '.join(HISTORY_ACTIONS)}")
        if item.get("env") not in ENVS:
            problems.append(f"{where}.env must be one of {', '.join(ENVS)}")
        if not isinstance(item.get("at"), str) or not isinstance(item.get("sha"), str):
            problems.append(f"{where}.at and {where}.sha must be strings")
        if "includes" in item:
            _check_includes(where, item["includes"], problems)
    return problems


def parse(text: str) -> State:
    """Read a deploy.json body; an empty file is the empty state. Raises on anything invalid."""
    if not text.strip():
        return empty_state()
    try:
        state = json.loads(text)
    except json.JSONDecodeError as err:
        raise DeployStateError(f"deploy.json is not JSON: {err}") from err
    _default_includes(state)
    problems = validate(state)
    if problems:
        raise DeployStateError("deploy.json is invalid: " + "; ".join(problems))
    assert isinstance(state, dict)
    return state


def _default_includes(state: Any) -> None:
    """Files written before `includes` existed read as including nothing."""
    if not isinstance(state, dict):
        return
    for key in ("staging", "prod", "previous_prod"):
        entry = state.get(key)
        if isinstance(entry, dict):
            entry.setdefault("includes", [])


def dumps(state: State) -> str:
    problems = validate(state)
    if problems:
        raise DeployStateError("refusing to write an invalid state: " + "; ".join(problems))
    return json.dumps(state, indent=2) + "\n"


# ---- transitions -----------------------------------------------------------------------------


def _history_entry(
    now: str,
    action: str,
    env: str,
    subject: Subject,
    run_url: str,
    reason: str,
    includes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "at": now,
        "action": action,
        "env": env,
        "sha": subject.sha,
        "version": subject.version,
        "run_url": run_url,
        "reason": reason,
        "issue": subject.issue,
        "pr": subject.pr,
    }
    if includes is not None:
        entry["includes"] = copy.deepcopy(includes)
    return entry


def _append(state: State, entry: dict[str, Any]) -> None:
    history = state["history"]
    history.append(entry)
    del history[:-HISTORY_LIMIT]


def stage(state: State, release: Release, now: str) -> State:
    """A build was copied to staging/. Replaces whatever staging held."""
    new = copy.deepcopy(state)
    includes = [item.as_dict() for item in release.includes]
    new["staging"] = {
        "sha": release.sha,
        "short": release.short,
        "version": release.version,
        "built_at": release.built_at,
        "deployed_at": now,
        "run_id": release.run_id,
        "run_url": release.run_url,
        "status": "deployed",
        "pr": release.pr,
        "issue": release.issue,
        "includes": includes,
    }
    _append(
        new,
        _history_entry(
            now,
            "stage",
            "staging",
            release.subject,
            release.run_url,
            "deployed to staging",
            includes,
        ),
    )
    return new


def is_prod(state: State, sha: str) -> bool:
    prod = state["prod"]
    return prod is not None and prod["sha"] == sha


def promote(
    state: State,
    *,
    sha: str,
    run_id: int,
    run_attempt: int,
    run_url: str,
    now: str,
    tag: str,
) -> State:
    """Staging becomes prod, the old prod becomes `previous_prod`.

    Running it again for the sha that is already prod changes nothing but the staging status, so
    a re-run never overwrites `previous_prod` with the build it just promoted.
    """
    staging = state["staging"]
    if staging is None or staging["sha"] != sha:
        held = staging["sha"] if staging else "nothing"
        raise DeployStateError(f"cannot promote {sha}: staging holds {held}")
    new = copy.deepcopy(state)
    new["staging"]["status"] = "promoted"
    if is_prod(state, sha):
        return new
    new["previous_prod"] = copy.deepcopy(state["prod"])
    new["prod"] = {
        "sha": staging["sha"],
        "short": staging["short"],
        "version": staging["version"],
        "built_at": staging["built_at"],
        "promoted_at": now,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "run_url": run_url,
        "gates": list(GATES),
        "pr": staging["pr"],
        "issue": staging["issue"],
        "tag": tag,
        "includes": copy.deepcopy(staging["includes"]),
    }
    subject = Subject(sha, staging["version"], staging["pr"], staging["issue"])
    _append(
        new,
        _history_entry(
            now, "promote", "prod", subject, run_url, "smoke and soak passed", staging["includes"]
        ),
    )
    return new


def prod_overwritten_by(
    state: State, sha: str, run_id: int, run_attempt: int, promote_failed: bool
) -> bool:
    """True when the promote job of THIS attempt failed after writing `sha` to prod.

    A run id is the same across "Re-run all jobs", so it cannot tell attempts apart: a rerun of a
    release that was promoted in attempt 1 must never roll prod back in attempt 2. Prod is only
    treated as overwritten when the promote job failed in this attempt and prod's own record
    names this run id and this attempt (a record without an attempt, written before it existed,
    never matches).
    """
    prod = state["prod"]
    return (
        promote_failed
        and prod is not None
        and prod["sha"] == sha
        and prod["run_id"] == run_id
        and prod.get("run_attempt") == run_attempt
    )


def rollback(
    state: State,
    *,
    subject: Subject,
    run_id: int,
    run_attempt: int,
    promote_failed: bool,
    run_url: str,
    reason: str,
    now: str,
) -> State:
    """A release failed. `reason` is the failing job.

    Prod goes back to `previous_prod` when this run had already promoted; staging always goes back
    to what prod holds (the last known good build), or to nothing when prod has never been set.
    """
    new = copy.deepcopy(state)
    overwritten = prod_overwritten_by(state, subject.sha, run_id, run_attempt, promote_failed)
    if overwritten:
        new["prod"], new["previous_prod"] = state["previous_prod"], None
    failed_env = "prod" if overwritten else "staging"
    _append(new, _history_entry(now, "fail", failed_env, subject, run_url, f"job {reason} failed"))

    prod = new["prod"]
    if prod is None:
        new["staging"] = None
    else:
        new["staging"] = {
            "sha": prod["sha"],
            "short": prod["short"],
            "version": prod["version"],
            "built_at": prod["built_at"],
            "deployed_at": now,
            "run_id": prod["run_id"],
            "run_url": prod["run_url"],
            "status": "rolled-back",
            "pr": prod["pr"],
            "issue": prod["issue"],
            "includes": copy.deepcopy(prod["includes"]),
        }
    if overwritten:
        _append(new, _history_entry(now, "rollback", "prod", subject, run_url, reason))
    _append(new, _history_entry(now, "rollback", "staging", subject, run_url, reason))
    return new


def skip(state: State, *, subject: Subject, run_url: str, reason: str, now: str) -> State:
    """A run ended without finishing (a newer merge superseded it, or it was cancelled)."""
    new = copy.deepcopy(state)
    staging = new["staging"]
    if staging is not None and staging["sha"] == subject.sha and staging["status"] in IN_FLIGHT:
        staging["status"] = "superseded"
    _append(new, _history_entry(now, "skip", "staging", subject, run_url, reason))
    return new
