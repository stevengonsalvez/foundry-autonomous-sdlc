"""
Tick lock: the ref refs/heads/sdlc-lock (docs/architecture.md, "Control loop", step 1).

Creating a ref is atomic on GitHub (422 when it exists), so whoever creates it holds the lock. The
ref points at an empty commit made for this tick, so the tip commit time is the lock time. A lock
older than STALE_AFTER_S belongs to a tick that died and may be replaced. Two ticks that both see
the same stale lock can both take it over; the schedule fires every five minutes and a tick lasts
at most four, so that needs a crashed tick plus a manual dispatch in the same second. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass

from sdlc_agents.clock import seconds_between
from sdlc_agents.ports import ClockPort, GitHubError, GitHubPort

LOCK_BRANCH = "sdlc-lock"
STALE_AFTER_S = 600


class LockHeld(RuntimeError):
    def __init__(self, age_s: int):
        super().__init__(f"lock {LOCK_BRANCH} is held (age {age_s} s)")
        self.age_s = age_s


@dataclass(frozen=True)
class Lock:
    sha: str
    took_over_stale: bool = False


def _create(github: GitHubPort, clock: ClockPort, holder: str) -> str:
    base = github.get_branch_sha("main")
    if base is None:
        raise GitHubError(404, "branch main not found")
    sha = github.create_commit(f"sdlc-lock {holder} {clock.now_iso()}", parent_sha=base)
    github.create_branch(LOCK_BRANCH, from_sha=sha)
    return sha


def acquire(github: GitHubPort, clock: ClockPort, holder: str) -> Lock:
    """Take the lock or raise LockHeld. A stale lock is deleted and taken over."""
    try:
        return Lock(_create(github, clock, holder))
    except GitHubError as exc:
        if exc.status != 422:
            raise
    taken_at = github.branch_commit_time(LOCK_BRANCH)
    age = seconds_between(taken_at, clock.now_iso()) if taken_at else STALE_AFTER_S
    if age < STALE_AFTER_S:
        raise LockHeld(age)
    github.delete_branch(LOCK_BRANCH)
    try:
        return Lock(_create(github, clock, holder), took_over_stale=True)
    except GitHubError as exc:
        if exc.status == 422:
            raise LockHeld(0) from exc
        raise


def release(github: GitHubPort, lock: Lock) -> bool:
    """Delete the lock ref if it is still ours. Returns whether it was deleted."""
    if github.get_branch_sha(LOCK_BRANCH) != lock.sha:
        return False
    github.delete_branch(LOCK_BRANCH)
    return True
