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
        details: bool = True,
    ) -> None:
        self.details = details
        self.listings = 0
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
            assert json.loads(stdin or "") == {"ref": "main", "return_run_details": True}
            self.dispatches += 1
            self.dispatched_at = self.t
            if not self.details:  # an old API answers 204 with no body
                return ""
            return json.dumps(
                {
                    "workflow_run_id": 77,
                    "run_url": "https://api/runs/77",
                    "html_url": "https://run/77",
                }
            )
        path = args[1]
        assert self.dispatched_at is not None
        created = self.dispatched_at + self.appears_after
        if "/workflows/pages.yml/runs" in path:
            self.listings += 1
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


def test_the_dispatch_response_names_the_run_so_no_search_happens() -> None:
    world = World()
    assert go(world) == "success"
    assert world.dispatches == 1 and world.listings == 0
    assert world.t >= 1_000_000 + 12 + 60


def test_another_dispatch_in_the_same_window_cannot_be_mistaken_for_ours() -> None:
    rival = {"id": 99, "html_url": "https://run/99", "created_at": iso(1_000_000 + 1)}
    world = World(older=[rival])  # run 99 is a rival dispatch, created before our own run
    assert go(world) == "success"
    assert world.listings == 0  # run 77 was followed by id; run 99 was never looked at


def test_without_run_details_the_run_is_found_by_creation_time_and_waited_for() -> None:
    world = World(details=False)
    assert go(world) == "success"
    assert world.dispatches == 1 and world.listings >= 1 and world.t >= 1_000_000 + 12 + 60


def test_ignores_runs_created_before_the_dispatch() -> None:
    stale = {"id": 5, "html_url": "https://run/5", "created_at": iso(1_000_000 - 600)}
    assert (
        go(World(older=[stale], details=False)) == "success"
    )  # run 77 was waited for, not the stale run 5


def test_a_failed_pages_run_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="ended failure"):
        go(World(conclusion="failure"))


def test_a_cancelled_pages_run_is_tolerated_because_the_live_check_decides() -> None:
    assert go(World(conclusion="cancelled")) == "cancelled"


def test_no_run_appearing_is_an_error_after_the_find_timeout() -> None:
    with pytest.raises(RuntimeError, match=r"no pages\.yml run appeared"):
        go(World(appears_after=10_000, details=False), find_timeout_s=60)


def test_a_run_that_never_finishes_is_an_error_at_the_hard_cap() -> None:
    with pytest.raises(RuntimeError, match="did not finish within 120s"):
        go(World(runs_for=10_000), timeout_s=120)
