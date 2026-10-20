"""
Harness for the hermetic scenario proofs (decision D9): the agents test world (FakeGitHub, FakeFoundry,
FakeCoder, FakeClock) behind the real activities, driven by the real workflows on the time-skipping
test server.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from conftest import World
from temporalio.testing import WorkflowEnvironment


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


@pytest.fixture
def created_branches(world: World) -> list[str]:
    """Every branch name the run creates, so a test can prove the lock ref was never taken."""
    names: list[str] = []
    create = world.gh.create_branch

    def recording(branch: str, *, from_sha: str) -> None:
        names.append(branch)
        create(branch, from_sha=from_sha)

    world.gh.create_branch = recording  # type: ignore[method-assign]
    return names
