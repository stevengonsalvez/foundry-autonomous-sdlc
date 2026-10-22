# Factory runbook: Temporal + CLI compose stack

Operating the `sdlc-factory` docker compose stack in `deploy/compose/`. Spec:
`research/2026-10-20_14-10-54_temporal-cli-factory-replatform-spec.md`. Plan: `tdd-development-plan.md`
(C9, C10). The older Foundry runbook is `docs/runbook.md`.

## 1. What runs

```
                 ┌──────── core ─────────┐   ┌────── ledger ───────┐
 host 127.0.0.1  │ postgres  temporal    │   │ dolt   ledger-api   │
 :17233 ────────▶│ temporal-ui (:18233)  │   │ control-center      │◀── :18080
                 │ admin-tools, ns init  │   │ (nginx, read only)  │
                 │ schedule-init         │   └─────────▲───────────┘
                 └──────────▲────────────┘             │
                            │      ┌───────────────────┴┐
                            └──────│ worker-foreman     │──── egress ───▶ GitHub
                                   └─────────┬──────────┘
                              coder_net      │ /invoke, /agent-run (internal, no route out)
                                   ┌─────────▼──┐    ┌──────────────┐
                                   │ coder      │───▶│ egress-proxy │── egress ──▶ allow-list
                                   │ agy as     │    └──────────────┘
                                   │ agyuser /  │
                                   │ agyagent   │
                                   └────────────┘
```

| Service | Role | Networks |
|---|---|---|
| postgres | Temporal persistence and visibility (volume `postgres-data`) | core |
| temporal-admin-tools | one-shot schema setup (`scripts/setup-postgres.sh`, idempotent) | core |
| temporal | Temporal server 1.31.4, published on `127.0.0.1:17233` | core |
| temporal-create-namespace | one-shot, creates namespace `factory` | core |
| temporal-ui | Temporal UI on `127.0.0.1:18233` | core |
| dolt | ledger database `ledger` (volume `dolt-data`), no host port | ledger |
| ledger-api | `/state.json`, `/issues.json`, `/ingest`, `/healthz` on 8080 | ledger |
| control-center | nginx: the static app plus same-origin `/state.json`, `/issues.json` on `127.0.0.1:18080` | ledger |
| schedule-init | one-shot, registers `github-poll` (60 s) and `po-intake` (4 h, paused by default) | core |
| worker-foreman | workflows plus all foreman activities, one activity at a time (D6); no agy, no agy token | core, ledger, coder_net, egress |
| coder | coder-service on 8090: coder jobs (`/invoke`) and every prompt-agent call (`/agent-run`); agy, node and git; untrusted steps run as `agyuser` | coder_net only |
| egress-proxy | squid, HTTPS CONNECT to an allow-list only | coder_net, egress |

Isolation, enforced by the network layout and checked by `smoke.sh`:

- The coder cannot resolve or reach Temporal, Postgres, Dolt or ledger-api, and has no direct internet.
  Its only way out is `egress-proxy`, which allows `CONNECT host:443` for the hosts in
  `deploy/compose/proxy/allowlist.txt` (each one commented with why) and denies everything else.
- The coder runs as root only to drop to `agyuser` (uid 61000): `cap_drop: ALL` plus `CHOWN,
  DAC_OVERRIDE, FOWNER, KILL, SETUID, SETGID`, read-only root filesystem, `no-new-privileges`, tmpfs for
  `/tmp`, `/root` and `/home/agyuser`, volumes for `WORKROOT` and `STATE_DIR`.
- `agyuser` cannot read `/run/secrets/*`: the files keep the host owner and mode 600.
- The control center is read only: nginx does not proxy `/ingest`, and ledger-api refuses `/ingest`
  without `LEDGER_TOKEN` in `x-factory-token`.

### The agy boundary

```
┌────────────────┐ POST /agent-run      ┌──────────────────┐ setuid  ┌───────────────────┐
│ worker-foreman │ {prompt, schema,     │ coder (root)     │────────▶│ agy --mode plan   │
│ github_pat     │──timeout_s} + token─▶│ builds argv, env │         │ uid agyagent      │
│ no agy, no     │                      │ per-call cwd+HOME│         │ cwd empty, HOME   │
│ agy token      │◀── raw stdout/stderr─│ deletes both     │         │ = token copy 0600 │
└────────────────┘  classified locally  └──────────────────┘         └───────────────────┘
```

Every agy run, coder jobs and prompt agents alike, happens in the coder: coder jobs as `agyuser`
(61000), prompt agents as `agyagent` (61001). Separate uids, because coder jobs run unrestricted agy
and npm on untrusted repositories: with one uid a job could read an agent call's `/proc/<pid>/cwd`
and rewrite its schema or HOME (forging a reviewer verdict), and a job's process reap would kill
in-flight agent calls. Prompt agents
used to run in worker-foreman as the uid that owns `github_pat`, where agy plan mode's `read_file` can
read any file that uid can (a test proved it reads `/tmp`), next to unauthenticated Temporal, the
ledger and the internet. Now:

- worker-foreman mounts only `github_pat`; its image has no agy binary (`INSTALL_AGY=0`); with
  `AGENT_SANDBOX_URL` (or `CODER_URL`) set, `CliFoundry` never reads `AGY_TOKEN_FILE` and never spawns
  agy. Without either URL (dev and tests only) it runs agy locally as before.
- `/agent-run` takes exactly `prompt` (1..100000 chars), `schema` (object or null) and `timeout_s`
  (1..900). Any other field is a 400: the client cannot choose argv, flags, mode, binary or env. The
  server runs agy in plan mode with an environment built from nothing plus the proxy and CA settings.
- Each call: a fresh `cwd` (empty) and `HOME` (the token copy, 0600, written without following links;
  `TMPDIR` inside it), owned by `agyagent`; both deleted afterwards. When the last call in flight ends,
  any `agyagent` process left behind is killed. At most `AGENT_RUN_CONCURRENCY` (2) run at once; a call
  that finds no slot within 60 s gets 429 and the object defers.
- The coder requires `CODER_SERVICE_TOKEN` on every POST, checked before the body is read, and live
  mode refuses to start without it. Bind address: `CODER_HOST` (0.0.0.0 inside the internal network).

### Residual risks (accepted, know them)

| Risk | Why it remains | Mitigation |
|---|---|---|
| `agyuser` can read other coder jobs' working trees and token copies; concurrent agent calls (`agyagent`) can read and write each other's HOME | one uid per role, not per call, in one container | per-call uids or one container per trust level is phase 2; keep `AGENT_RUN_CONCURRENCY` low |
| agy's own account token is reachable by any agy run | agy needs it to work | dedicated Google account (section 7); rotate on suspicion |
| A prompt injection into the reviewer model approves a bad PR, which then auto-merges | Stevie enabled auto-merge (`humanGates.merge: false`) | set `humanGates.merge: true` for any repository whose issues or PRs untrusted people can write |
| Temporal frontend has no authentication | Temporal OSS default | published on `127.0.0.1` only (`BIND_ADDR`); never change that on a shared host |
| agy plan-mode `read_file` is the first barrier for files outside the call's cwd | agy 1.4.3 auto-denies it headless (measured, `live-agy-check.sh`); a later agy may not | uid split: `agyagent` cannot read root or `agyuser` 0600 files; rerun the live check after every agy upgrade |
| An `agyagent` process that escaped its group lives until no agent call is in flight | reaping while a sibling call runs would kill it | the reap runs when the last call ends; `pids_limit: 1024`, `no-new-privileges` on the coder |

## 2. Bring-up

Prerequisites: Docker Engine 24+ with compose v2, network access for the first build (Debian, PyPI,
nodejs.org, the agy installer hosts), about 3 GB of disk for images.

```bash
cd deploy/compose
cp .env.example .env
# Edit .env: set FACTORY_UID/FACTORY_GID to `id -u`/`id -g`, and give each of POSTGRES_PASSWORD,
# DOLT_ROOT_PASSWORD, DOLT_PASSWORD, CODER_SERVICE_TOKEN and LEDGER_TOKEN its own value from:
openssl rand -hex 32
# Compose refuses to start while any of them is missing.

# Secrets, see secrets/README.md
ls -l secrets/github_pat.txt secrets/agy_cli_token.txt    # both -rw------- owned by FACTORY_UID

docker compose up -d --build
docker compose ps -a
```

Expected after about a minute: `temporal-admin-tools`, `temporal-create-namespace` and `schedule-init`
are `Exited (0)`; every other service is `Up` (`healthy` where a healthcheck exists).

- Temporal UI: <http://127.0.0.1:18233/namespaces/factory/workflows>
- Control center: <http://127.0.0.1:18080/> (redirects to `/?data=state.json&issues=issues.json`)
- Temporal CLI from the host: `temporal --address 127.0.0.1:17233 -n factory workflow list`

The project name is fixed (`name: sdlc-factory`). Do not set `COMPOSE_PROJECT_NAME` in `.env` or the
shell: it overrides `name:`. The upstream Temporal sample's `.env` does exactly that, which is how two
stacks on one host collide.

Change host ports in `.env` (`TEMPORAL_HOST_PORT`, `TEMPORAL_UI_HOST_PORT`, `CONTROL_CENTER_HOST_PORT`).
They bind to `BIND_ADDR` (127.0.0.1); do not change that to `0.0.0.0` on a shared or public host:
nothing in the stack authenticates the UI or the control center.

### Smoke test

```bash
deploy/compose/smoke.sh          # about 2 minutes with warm images
```

It runs the whole stack as a separate project `sdlc-factory-smoke` on ports 27233, 28233, 28080, with
`FACTORY_MODE=fake` and dummy secrets in a temp directory, prints a PASS/FAIL table, and removes only
that project (`docker compose -p sdlc-factory-smoke down -v`). `KEEP=1` leaves it running;
`SMOKE_BUILD=0` skips the build. Fake mode replaces the coder with an in-memory fake and `/agent-run`
with a scripted agy result; the foreman still starts its real adapters with a dummy GitHub token, so
its poll activity fails with 401 against GitHub and changes nothing. It also checks the boundary: the
foreman has only `github_pat`, no agy token or binary; `/agent-run` is 401 without the token and 400
for an `argv` field; ledger `/ingest` is 401 without `LEDGER_TOKEN` from inside the ledger network.

### Live agy check (real agy, spends quota)

```bash
deploy/compose/live-agy-check.sh                       # about 1 minute warm, 5 agy calls
LIVE_CHECKS="basic" deploy/compose/live-agy-check.sh   # one call; checks: basic canary auth
LIVE_BUILD=0 deploy/compose/live-agy-check.sh          # reuse built images
```

It starts only `coder` and `egress-proxy` as project `sdlc-factory-live`, `FACTORY_MODE=live`, with a
copy of `~/.gemini/antigravity-cli/antigravity-oauth-token` (override: `AGY_TOKEN_SOURCE`) in a 0700
temp directory outside the repo (shredded on exit) and a dummy `github_pat` (nothing calls GitHub).
It POSTs to the coder's `/agent-run` from inside the coder, classifies each reply with the real
`AgyEngine.classify`, prints the squid CONNECT log, and removes only its own project (`down -v`).
Run it after an agy upgrade or any change to `proxy/allowlist.txt`.

Measured 2026-10-20, agy 1.4.3, in the coder sandbox (read-only rootfs, `coder_net` only, agy as
`agyagent` 61001, per-call HOME and cwd):

| Check | Result | Timing | Usage (in/out/think/total) |
|---|---|---|---|
| plan call, `--json-schema` `{answer: string}` | `OK`, stderr empty (per-call HOME on a read-only rootfs: no stall) | 12 s wall, agy 10.4 s | 15991/923/900/16914 |
| `read_file` of a root-only 0600 file | `DENIED`, not disclosed | 10 s | 7532/805/781/8337 |
| `read_file` of an `agyagent`-owned 0600 file | `DENIED`, not disclosed | 10 s | 7513/857/833/8370 |
| token with expired access and revoked refresh token | `AUTH`, rc 125 (abort_on) | 0.27 s server | none |
| garbage token file | `AUTH`, rc 125 (abort_on) | 0.29 s server | none |

Egress agy 1.4.3 needs, measured from the squid access log (each one added after a failed call that
named it; the call fails in 0.5 to 3 s with `Eligibility check failed: ... Forbidden` without it):

| Host | Role | Allowed |
|---|---|---|
| `oauth2.googleapis.com` | OAuth token refresh | yes |
| `daily-cloudcode-pa.googleapis.com` | model backend: eligibility check and turns | yes |
| `www.googleapis.com` | account lookup (`oauth2/v2/userinfo`) | yes |
| `lh3.googleusercontent.com` | account profile picture, fetched by the eligibility check | yes |
| `play.googleapis.com` | telemetry (clearcut log) | no: denied, calls still OK |
| `antigravity-unleash.goog` | feature flags | no: denied, calls still OK |
| `cloudcode-pa.googleapis.com` | the previously inferred entry | removed: never requested |

Findings:

- `read_file` outside the empty per-call cwd is auto-denied by agy 1.4.3 headless plan mode ("a tool
  required the read_file permission that headless mode cannot prompt for"). So the root-only file was
  stopped by agy's permission rule, before the uid boundary was tested. The uid boundary (agyagent
  cannot open root 0600 files, smoke.sh) is the second layer; a future agy that allows reads outside
  the workspace in plan mode would leave only that layer, and then `agyagent`-owned files (the token
  copy in the call's HOME, concurrent calls' HOMEs) become readable. Rerun this check after upgrades.
- Auth failure is prompt: agy prints the device-login prompt ("Authentication required ... Waiting for
  authentication (timeout 60s)") and `abort_on` kills it in under 0.3 s; it never waits out the
  timeout. An empty token file never starts agy (500 `token_unavailable`).
- With `--json-schema`, the response held two lines: `{"answer":"ok"}` and a second object wrapping
  the first as a string, `{"answer":"{\"answer\":\"ok\"}"}`. `extract_json` picks the longer, wrapped one. One
  sample with a schema that was a single string field; check real agent schemas before relying on it.

## 3. Secrets

`deploy/compose/secrets/README.md` has the steps. Summary:

| File | Content | Read by |
|---|---|---|
| `secrets/github_pat.txt` | fine-grained PAT scoped to the target repo | worker-foreman, coder |
| `secrets/agy_cli_token.txt` | `~/.gemini/antigravity-cli/antigravity-oauth-token` from an interactive `agy` login | coder only |

Both are docker secrets (bind mounts at `/run/secrets/...`), never in an image or an environment
variable. Compose ignores `uid`/`mode` for file secrets, so the files keep their host owner and mode:
keep them 600 and owned by `FACTORY_UID`, which is the uid worker-foreman runs as. The services read the
files on every use, so replacing a file needs no restart.

Tokens in `.env` (generate each with `openssl rand -hex 32`; all required):

| Variable | Shared by | Enforced by |
|---|---|---|
| `CODER_SERVICE_TOKEN` | worker-foreman, coder | coder: 401 on `/invoke` and `/agent-run` without it; live mode will not start without it |
| `LEDGER_TOKEN` | worker-foreman, ledger-api | ledger-api: 401 on `POST /ingest` without it; will not start without it |
| `DOLT_PASSWORD` | dolt, ledger-api | Dolt creates user `ledger` with it on first init; ledger-api has no default user or password |

Rotating `CODER_SERVICE_TOKEN` or `LEDGER_TOKEN`: edit `.env`, then `docker compose up -d` (both
sides restart with the new value). `DOLT_PASSWORD` only applies on the first init of `dolt-data`.

## 4. Configuration

`factory/factory.yaml` is baked into the worker and coder images (rebuild after editing:
`docker compose up -d --build`).

- `repositories`: the target repo. The coder only accepts jobs for this repo.
- `humanGates.spec` / `humanGates.merge`: `false` (this deployment) means the workflow continues and
  auto-merges after the gates. `true` holds the workflow until a `human_approved` signal, for example:

  ```bash
  temporal --address 127.0.0.1:17233 -n factory workflow signal \
    --workflow-id issue-12 --name human_approved --input '"merge"'
  ```

  `schedule-init` re-registers `github-poll` with the current gates on every start, so after a change
  run `docker compose up -d --build schedule-init worker-foreman`.
- `budget`: `perIssue.maxCalls`, `perIssue.maxMinutes`, `total.maxCalls` are the real caps;
  `callUsd`/`minuteUsd` map them onto the USD caps the tick enforces (D7). An exhausted budget escalates
  the issue; it never spends past the cap.
- `engines.agy.printTimeoutS`: always passed explicitly (agy defaults to unbounded).
- `AGENT_RUN_CONCURRENCY` in `.env` (default 2): prompt-agent agy calls the coder runs at once.
- `PO_INTAKE_ENABLED=1` in `.env` un-pauses the simulated product owner schedule (`po-intake`), which
  files issues on its own.

## 5. Live run checklist (manual, NOT automated)

A live run spends agy quota and **merges PRs into the target repository** (with `humanGates.merge:
false`). It is deliberately not part of any script. Run it only on purpose.

1. `deploy/compose/smoke.sh` passes on this host.
2. Real secrets in place (section 3); `FACTORY_MODE=live` in `.env`.
3. Target repo checked: `factory/factory.yaml` `repositories` names the repo you mean; branch protection
   and required checks exist (`scripts/setup_repo.py`).
4. Decide the merge gate: for a first run set `humanGates.merge: true` and approve by signal.
5. `docker compose up -d --build`, then watch `docker compose logs -f worker-foreman coder`.
6. File the scenario inputs: `python scripts/run_scenarios.py --dry-run`, then without `--dry-run`
   (`--only` picks scenarios). It files owner-authored issues and the stale-test PR; the pipeline does
   the rest.
   Scenarios a, a2, d and d-maintenance were built by earlier runs and already pass on `main`: for a live
   run use `a3`, `d2` and `d-maintenance2` (b and c never merge code).
7. Follow each item in the Temporal UI (`issue-N` workflows) and on the control center board.
8. Afterwards: review merged PRs, release tags and `escalated:*` labels on GitHub. Pause polling if you
   are done: `temporal --address 127.0.0.1:17233 -n factory schedule toggle --schedule-id github-poll --pause --reason done`.

## 6. agy token expiry and re-login

Symptoms: an agent call or coder job escalates with "authentication required: the token in
AGY_TOKEN_FILE is missing or expired"; no retry storm follows (auth failures are not transient).

Refreshed tokens are not persisted (each job gets a fresh copy of the file), so the file only ages.
To renew:

1. On the dev machine: run `agy`, sign in again, quit.
2. `install -m 600 ~/.gemini/antigravity-cli/antigravity-oauth-token deploy/compose/secrets/agy_cli_token.txt`
   (copy to the compose host first if it is another machine; keep mode 600 and owner `FACTORY_UID`).
3. No restart needed. Remove the escalation label from affected issues so the poll picks them up again.

## 7. ToS note: personal agy OAuth token

The agy token is a personal Google OAuth token, used here by automation. That may breach the
Antigravity Terms (section 6) and risks suspension of the Google account. Stevie accepted this risk for
v1 (spec, Risks). Mitigations: the token is only a file behind `provision`, so swapping to an API key or
ADC changes one engine method and the secret file, not the stack; the token never transits the proxy in
clear (TLS end to end, no interception); use a dedicated Google account if possible.

## 8. Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `temporal-admin-tools` restarting | `docker compose logs temporal-admin-tools` | Postgres password changed after first boot: the volume keeps the old one. Restore it, or `down -v` (destroys history). |
| `temporal-create-namespace` exits 1 | its logs | Temporal never got healthy; check `docker compose logs temporal`. |
| `schedule-init` exits 1 | its logs | Namespace missing or Temporal unreachable for 120 s; `docker compose up -d schedule-init` retries. |
| worker-foreman restarting, `GITHUB_PAT_FILE ... cannot read` | `stat -c '%a %u' secrets/*.txt`, `FACTORY_UID` | Make the files owned by `FACTORY_UID`, mode 600. |
| worker-foreman waits forever | `docker compose ps coder` | foreman starts only after the coder is healthy; read `docker compose logs coder`. |
| coder exits "CODER_SERVICE_TOKEN is not set" | `.env` | Set it (live mode never serves without it). |
| ledger-api exits "LEDGER_TOKEN is not set" (or DOLT_USER/DOLT_PASSWORD) | `.env` | Set it; compose passes it to ledger-api and worker-foreman. |
| ledger events missing, foreman log `ledger: HTTP 401` | `LEDGER_TOKEN` in both containers | `docker compose up -d` after editing `.env` so both sides have the same value. |
| prompt agents fail with `sandbox_unavailable` or `token_unavailable` | `docker compose logs coder` | agyuser missing, or `secrets/agy_cli_token.txt` unreadable or empty in the coder. Not retried: fix and remove the escalation label. |
| prompt agents deferred with HTTP 429 `busy` | coder logs | more calls than `AGENT_RUN_CONCURRENCY`; they retry on the next poll. |
| agent call `FAILED` in seconds, stderr `Eligibility check failed: ... Forbidden` | `docker compose logs egress-proxy \| grep TCP_DENIED` | a host agy needs is not allow-listed (agy upgrade?): run `live-agy-check.sh`, add the exact host it names to `proxy/allowlist.txt`. |
| coder job fails with a 403 from the proxy | `docker compose logs egress-proxy \| grep TCP_DENIED` | Add the host to `proxy/allowlist.txt` with a comment, `docker compose up -d --build egress-proxy`. |
| coder job `sandbox-unavailable` | coder logs | `agyuser` missing or uid drop blocked; the image creates it; do not run the coder with a different `user:`. |
| prompt agents fail `sandbox_unavailable` | `docker compose exec coder id agyagent` | `agyagent` (61001) missing: rebuild the coder image. |
| control center shows "not written yet" | `curl -s 127.0.0.1:18080/state.json` | 404 until the first ledger ingest; normal on a fresh stack. |
| control center blank, CSP error in console | browser devtools | The page must be loaded from the same origin as `/state.json` (port 18080); `connect-src 'self'` allows only that. |
| port already in use on `up` | `ss -ltn` | Change the `*_HOST_PORT` values in `.env`. |
| issue escalated, you want a retry | `escalated:*` label plus the state comment | Removing the label does not retry: the stored `escalation` in the state comment puts it back within seconds. Close the issue and file a fresh one. |
| escalated `agent-error`, "ended denied", text mentions "auto-denied" or "allow-rule" | the escalation comment quotes agy's stderr tail | The model tried a tool; plan mode has none. Every prompt agent already gets a no-tools notice (`NO_TOOLS_NOTICE`); if it still happens, retry by refiling. Never add allow-rules. |
| escalated `agent-error`, "CancelledError" | Temporal UI, activity timeout | A step outlived `STEP_TIMEOUT` (45 min). Real agy test design can take 10 to 30 min; `test_step_timeout.py` pins the limit to the slowest agent. |
| coder `failed ... install-failed`, `npm ci` cannot find the lockfile | `ls -ld /srv/sdlc-work/<job>` in the coder | The job dir or checkout is not traversable by `agyuser`: `give_tree` sets both to 0755 (the coder runs with umask 077). |
| coder `failed ... error`, "agyuser processes survived SIGKILL" | `/proc/<pid>/status` shows `State: Z` | Zombies, not survivors: they are skipped, and the coder runs under `init: true` so orphans are reaped. |
| coder `internal-error`, `git push` "cannot exec ... askpass" | `mount | grep ' /tmp '` shows `noexec` | The askpass helper lives in `ASKPASS_DIR` (`/var/lib/sdlc-coder/askpass`, root only, on the state volume), not `/tmp`. |
| coder `failed ... tests-not-red` | the job log: all tests passed before any code | The feature already exists on `main`; the TDD gate is working. Use a scenario for something `main` lacks (a3, d2, d-maintenance2). |
| build fails "agy install failed" | network to `antigravity.google` and `storage.googleapis.com` | Fix network (only the coder image installs agy; the worker image is built with `INSTALL_AGY=0`). |

Useful commands (always from `deploy/compose`, so they act on this project only):

```bash
docker compose ps -a
docker compose logs -f --tail 100 worker-foreman
docker compose exec dolt dolt --use-db ledger sql -q "select message from dolt_log limit 5"
docker compose run --rm --no-deps --entrypoint temporal temporal-admin-tools \
  schedule describe --schedule-id github-poll -n factory --address temporal:7233
```

## 9. Teardown

```bash
cd deploy/compose
docker compose down          # stop, keep volumes (Temporal history, ledger, coder state)
docker compose down -v       # also delete this project's volumes: Temporal history and the ledger are lost
```

Both act only on project `sdlc-factory`. Never use `docker system prune` or `docker volume prune` on a
shared host: they delete other projects' data. The ledger can be rebuilt from events, Temporal history
cannot.

## 10. Azure VM (later)

The same compose file is the plan for an Azure VM; nothing here is Azure specific.

- Ubuntu LTS VM, Docker Engine from Docker's apt repo, the repo checked out, `.env` and `secrets/` copied
  with `scp -p` (keeps mode 600), `FACTORY_UID` set to the VM user.
- Keep `BIND_ADDR=127.0.0.1` and reach the UIs over an SSH tunnel
  (`ssh -L 18233:127.0.0.1:18233 -L 18080:127.0.0.1:18080 vm`); no inbound NSG rule beyond SSH.
- Polling (not webhooks) means no inbound traffic is needed at all.
- Use a managed disk for the Docker volumes and snapshot it: Temporal history lives only there.
- Not done yet: systemd unit for `docker compose up -d` on boot, log shipping, backups of `dolt-data`.
