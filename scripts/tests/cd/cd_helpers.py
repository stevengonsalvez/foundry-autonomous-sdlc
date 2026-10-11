"""Builders shared by the CD tests."""

from __future__ import annotations

from scripts.cd import deploy_state as ds

T0 = "2026-10-11T09:00:00Z"
T1 = "2026-10-11T09:30:00Z"
T2 = "2026-10-11T10:00:00Z"
RUN_URL = "https://github.com/o/r/actions/runs/"


def sha(n: int) -> str:
    return f"{n:07x}" + "a" * 33


def include(pr: int, issue: int | None = None, n: int | None = None) -> ds.Include:
    return ds.Include(pr=pr, issue=issue, sha=sha(n if n is not None else pr))


def release(n: int, run_id: int | None = None, **kwargs: object) -> ds.Release:
    fields: dict[str, object] = {
        "sha": sha(n),
        "short": sha(n)[:7],
        "version": f"v0.{n}.0",
        "built_at": T0,
        "run_id": run_id or 1000 + n,
        "run_url": f"{RUN_URL}{run_id or 1000 + n}",
        "pr": 10 + n,
        "issue": 20 + n,
        "includes": (include(10 + n, 20 + n, n),),
    }
    fields.update(kwargs)
    return ds.Release(**fields)  # type: ignore[arg-type]


def staged(state: ds.State, n: int, now: str = T1) -> ds.State:
    return ds.stage(state, release(n), now)


def promoted(state: ds.State, n: int, now: str = T2) -> ds.State:
    """Stage build n and promote it."""
    state = staged(state, n)
    rel = release(n)
    return ds.promote(
        state,
        sha=rel.sha,
        run_id=rel.run_id,
        run_url=rel.run_url,
        now=now,
        tag=ds.tag_name(now, rel.short),
    )


def subject(n: int) -> ds.Subject:
    rel = release(n)
    return ds.Subject(rel.sha, rel.version, rel.pr, rel.issue)
