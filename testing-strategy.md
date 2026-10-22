# Testing strategy

- Runner: `pytest` (matches `agents/`). `services/` uses `pytest` + `pytest-asyncio`; Temporal tests use `temporalio.testing.WorkflowEnvironment.start_time_skipping()`.
- Layout: `services/tests/test_<module>.py`, e2e in `services/tests/e2e/`. Agents tests unchanged in `agents/tests/`.
- Reuse: `agents/tests/fakes.py` (`FakeGitHub`, `FakeFoundry`, `FakeCoder`, `FakeClock`) and `agents/tests/conftest.py` `World`. `services/tests/conftest.py` puts `agents/tests` on `sys.path` and re-exports the fixtures.
- Mocks: fake `CliEngine` (scripted outcomes) and recorded agy `stream-json` fixtures from the spike (`services/tests/fixtures/agy_*.ndjson`: valid JSON, timeout-empty, denied-tools-empty, auth-required). No network, no real agy, no Docker in unit tests.
- Gate commands (all must pass before each commit):
  - `cd agents && uv run pytest -q && uv run ruff check`
  - `cd services && uv run pytest -q && uv run ruff check`
- Compose smoke (C10): `deploy/compose/smoke.sh` boots the stack with `FACTORY_MODE=fake`, asserts Temporal healthy, namespace exists, schedule registered, ledger-api `/state.json` is valid v1, control center HTML loads. Not part of unit gate; run manually and in CI later.
- Hermetic scenario proofs: workflow tests drive `FakeGitHub` via activities bound to the fakes; success criteria equal the existing `agents/tests/test_scenarios.py` assertions for a, d, b+c, d-maintenance.
- Never test: live GitHub, live agy, real merges.

Example skeleton:
```python
@pytest.mark.asyncio
async def test_feature_happy_path_reaches_released(world):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue="foreman", workflows=[WorkItemWorkflow],
                          activities=build_activities(world), max_concurrent_activities=1):
            world.gh.add_issue(...)
            await env.client.execute_workflow(WorkItemWorkflow.run, 1, id="issue-1", task_queue="foreman")
    assert "stage:released" in world.gh.get_issue(1).labels
```
