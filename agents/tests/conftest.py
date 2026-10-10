from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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

    def tick(self, count: int = 1, *, budget: Budget | None = None, wall_s: int = 240) -> list[TickReport]:
        reports = []
        for _ in range(count):
            reports.append(run_tick(self.gh, self.foundry, NoSecrets(), self.clock, wall_s, budget=budget))
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
    return World(clock, gh, coder, FakeFoundry(coder, clock))
