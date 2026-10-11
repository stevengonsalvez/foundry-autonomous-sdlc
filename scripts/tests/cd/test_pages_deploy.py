from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scripts.cd import pages_deploy as pd

REPO = "o/r"


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class World:
    """GitHub as seen by the dispatcher: runs appear after a delay and finish after another."""

    def __init__(
        self,
        appears_after: float = 12,
        runs_for: float = 60,
        conclusion: str = "success",
        older: list[dict] | None = None,
    ) -> None:
        self.t = 1_000_000.0
        self.dispatched_at: float | None = None
        self.appears_after, self.runs_for, self.conclusion = appears_after, runs_for, conclusion
        self.older = older or []
        self.dispatches = 0

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        if "-X" in args:
            assert args[args.index("-X") + 2].endswith("/workflows/pages.yml/dispatches")
            assert json.loads(stdin or "") == {"ref": "main"}
            self.dispatches += 1
            self.dispatched_at = self.t
            return ""
        path = args[1]
        assert self.dispatched_at is not None
        created = self.dispatched_at + self.appears_after
        if "/workflows/pages.yml/runs" in path:
            runs = list(self.older)
            if self.t >= created:
                runs.append({"id": 77, "html_url": "https://run/77", "created_at": iso(created)})
            return json.dumps({"workflow_runs": runs})
        assert path.endswith("/actions/runs/77")
        done = self.t >= created + self.runs_for
        return json.dumps(
            {
                "status": "completed" if done else "in_progress",
                "conclusion": self.conclusion if done else None,
            }
        )


def go(world: World, **kwargs) -> str:
    return pd.dispatch_and_wait(
        world, REPO, clock=world.clock, sleep=world.sleep, log=lambda _l: None, **kwargs
    )


def test_dispatches_finds_its_own_run_and_waits_for_success() -> None:
    world = World()
    assert go(world) == "success"
    assert world.dispatches == 1 and world.t >= 1_000_000 + 12 + 60


def test_ignores_runs_created_before_the_dispatch() -> None:
    stale = {"id": 5, "html_url": "https://run/5", "created_at": iso(1_000_000 - 600)}
    assert go(World(older=[stale])) == "success"  # run 77 was waited for, not the stale run 5


def test_a_failed_pages_run_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="ended failure"):
        go(World(conclusion="failure"))


def test_a_cancelled_pages_run_is_tolerated_because_the_live_check_decides() -> None:
    assert go(World(conclusion="cancelled")) == "cancelled"


def test_no_run_appearing_is_an_error_after_the_find_timeout() -> None:
    with pytest.raises(RuntimeError, match=r"no pages\.yml run appeared"):
        go(World(appears_after=10_000), find_timeout_s=60)


def test_a_run_that_never_finishes_is_an_error_at_the_hard_cap() -> None:
    with pytest.raises(RuntimeError, match="did not finish within 120s"):
        go(World(runs_for=10_000), timeout_s=120)
