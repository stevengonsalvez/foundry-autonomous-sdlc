# sdlc-agents

Python package for invoking Azure AI Foundry SDLC prompt agents.

## Layout

| Module | Role |
|---|---|
| `definitions.py` | One `AgentDef` per agent: instructions, output kind, JSON schema, extra checks, triage label allow-list. `create_agents.py` registers the schema; `call.py` validates output against the same dict. |
| `codegen_policy.py` | Path allow-list (`src/`, `tests/`, `docs/`), file count and content size limits. Shared by `call.py` and the sandbox's `scripts/apply_codegen.py`. |
| `schema_check.py` | Validates JSON against the subset of JSON Schema the agent schemas use. |
| `call.py` | CLI: invoke an agent by name (latest version), validate and sanitise the answer. |
| `create_agents.py` | Idempotent registration of every agent version. |

## Prerequisites

```
uv sync
export FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
az login  # or azure/login OIDC in GitHub Actions
```

## Create / update agents (deployer role, Foundry User required)

```
uv run python -m sdlc_agents.create_agents
```

## Call an agent

```
uv run python -m sdlc_agents.call --agent sdlc-triage --input-file issue.txt
uv run python -m sdlc_agents.call --agent sdlc-codegen --input-file spec.txt --max-output-tokens 2000
```

Agents: `sdlc-triage` `sdlc-codegen` `sdlc-review` `sdlc-ci-triage` `sdlc-release-notes`

## Sandbox copy

The sandbox runs a vendored copy at `sandbox/tools/sdlc_agents`. After changing this package:

```
scripts/sync-sandbox.sh           # from the repo root; commit the updated copy
scripts/sync-sandbox.sh --check   # exits 1 with a diff if the copy is stale
```

The test suite runs the `--check`, so a stale copy fails the tests. If `pyproject.toml` or
`uv.lock` changes, regenerate `sandbox/requirements-agents.txt` with the command in its header.

## Run tests (no Azure access needed)

```
uv run --with pytest python -m pytest -q
```
