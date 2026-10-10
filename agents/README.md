# sdlc-agents

The orchestrator, its adapters, and the prompt agent definitions for the autonomous SDLC demo.
The contract is [`docs/architecture.md`](../docs/architecture.md).

```
Routine (*/5) ──▶ hosted/orchestrator/main.py ──▶ runtime.run_once ──▶ tick.run_tick
                                                                          │
           lock ◀──┬── machine.next_action (pure) ◀── state comment + labels + PR + checks
                   └── executes one step per object: prompt agents (foundry.run_agent),
                       coder (invoke_hosted), merge (gates.verify_merge), release, metrics
```

## Modules

| Module | Role |
|---|---|
| `ports.py` | Protocols and value objects the logic depends on (GitHub, Foundry, secrets, git, clock). |
| `tick.py` | One bounded tick: lock, load owner objects, one step each, metrics, unlock. Never raises; failed steps roll back. |
| `machine.py` | Pure state machine: `next_action(ctx)` plus `after_*` result rules, caps and failure limits. |
| `state.py` | The `<!-- sdlc-state:v1` comment: parse, validate, render, owner-only discovery. |
| `gates.py` | Pre-merge verification on the head sha; review markers; check summaries. |
| `cost.py` | Token and hosted compute pricing, per-object accounting. |
| `metrics.py` | `metrics.json` builder (schema validated) and publisher on branch `metrics`. |
| `release.py` | Next semver from tags, idempotent release publishing. |
| `lock.py` | `refs/heads/sdlc-lock` with stale takeover. |
| `definitions.py` | The eight prompt agents: instructions, strict JSON schemas, output checks, MCP use. |
| `create_agents.py` | Idempotent registration of the prompt agents (GitHub MCP tool where needed). |
| `foundry.py` | Foundry adapter (Responses API agent calls, hosted Invocations) and `run_agent`. |
| `github.py` | GitHub REST adapter, hard-scoped to the demo repo. |
| `keyvault.py` | Key Vault secrets over REST with an Entra token. |
| `transport.py` | Injectable HTTP transport (no redirects followed). |
| `sanitise.py` | Nonce wrapping of untrusted input, strict JSON, markdown defanging, marker-safe JSON. |
| `paths.py` | Test globs and the app/ path policy for model-proposed files. |
| `schema_check.py` | The JSON Schema subset used by agent, state and metrics schemas. |
| `runtime.py` | Environment to adapters to one tick, for the hosted entrypoint. |
| `coder/` | The hosted coder runtime (separate component). |

## Run the tests (offline, no Azure)

```
uv sync --extra dev --extra hosted
uv run pytest
uv run pytest --cov=sdlc_agents --cov-report=term-missing
uv run ruff check
```

## Register the prompt agents (Foundry User on the project)

```
export FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
uv run python -m sdlc_agents.create_agents
```

## Build the orchestrator zip

```
uv run python hosted/orchestrator/build_zip.py --out dist/sdlc-orchestrator.zip
```

The zip holds `main.py`, the pinned `requirements.txt` and the `sdlc_agents` sources at its root.
It is byte-for-byte reproducible. The hosted agent reads `FOUNDRY_PROJECT_ENDPOINT` and `KEY_VAULT_URI`.
