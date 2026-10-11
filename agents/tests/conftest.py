from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fakes import FakeClock, FakeCoder, FakeFoundry, FakeGitHub, NoSecrets

from sdlc_agents.ports import Budget
from sdlc_agents.tick import TickReport, run_tick


@dataclass
class World:
    clock: FakeClock
    gh: FakeGitHub
    coder: FakeCoder
    foundry: FakeFoundry
    sleeps: list[float]
    budget: Budget | None = None     # a test that needs a different cap sets this; drive() and tick() use it
    emitter: Any = None              # the state-keeper hand-off; None means the ledger is off

    def sleep(self, seconds: float) -> None:
        """Waits inside a tick (retry backoff) pass on the fake clock."""
        self.sleeps.append(seconds)
        self.clock.advance(seconds)

    def tick(self, count: int = 1, *, budget: Budget | None = None, wall_s: int = 240) -> list[TickReport]:
        reports = []
        for _ in range(count):
            reports.append(run_tick(self.gh, self.foundry, NoSecrets(), self.clock, wall_s,
                                    budget=budget or self.budget, sleep=self.sleep, emitter=self.emitter))
            self.clock.advance(300)
        return reports

    def drive(self, done: Callable[[], bool], max_ticks: int = 40) -> int:
        """Tick until `done()` holds; return the number of ticks used."""
        for used in range(1, max_ticks + 1):
            self.tick()
            if done():
                return used
        raise AssertionError(f"not done after {max_ticks} ticks")


@pytest.fixture
def world() -> World:
    clock = FakeClock()
    gh = FakeGitHub(clock)
    coder = FakeCoder(gh)
    return World(clock, gh, coder, FakeFoundry(coder, clock), [])
