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
                            └──────│ worker-foreman     │──── egress ───▶ GitHub, agy
                                   └─────────┬──────────┘
                              coder_net      │ (internal, no route out)
                                   ┌─────────▼──┐    ┌──────────────┐
                                   │ coder      │───▶│ egress-proxy │── egress ──▶ allow-list
                                   └────────────┘    └──────────────┘
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
| worker-foreman | workflows plus all foreman activities, one activity at a time (D6) | core, ledger, coder_net, egress |
| coder | coder-service on 8090; agy, node and git; untrusted steps run as `agyuser` | coder_net only |
| egress-proxy | squid, HTTPS CONNECT to an allow-list only | coder_net, egress |

Isolation, enforced by the network layout and checked by `smoke.sh`:

- The coder cannot resolve or reach Temporal, Postgres, Dolt or ledger-api, and has no direct internet.
  Its only way out is `egress-proxy`, which allows `CONNECT host:443` for the hosts in
  `deploy/compose/proxy/allowlist.txt` (each one commented with why) and denies everything else.
- The coder runs as root only to drop to `agyuser` (uid 61000): `cap_drop: ALL` plus `CHOWN,
  DAC_OVERRIDE, FOWNER, KILL, SETUID, SETGID`, read-only root filesystem, `no-new-privileges`, tmpfs for
  `/tmp`, `/root` and `/home/agyuser`, volumes for `WORKROOT` and `STATE_DIR`.
- `agyuser` cannot read `/run/secrets/*`: the files keep the host owner and mode 600.
- The control center is read only: nginx does not proxy `/ingest`.

## 2. Bring-up

Prerequisites: Docker Engine 24+ with compose v2, network access for the first build (Debian, PyPI,
nodejs.org, the agy installer hosts), about 3 GB of disk for images.

```bash
cd deploy/compose
cp .env.example .env
# Edit .env: generate each password and CODER_SERVICE_TOKEN, set FACTORY_UID/FACTORY_GID to `id -u`/`id -g`.
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'

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
`SMOKE_BUILD=0` skips the build. Fake mode replaces the coder with an in-memory fake; the foreman still
starts its real adapters with a dummy GitHub token, so its poll activity fails with 401 against
GitHub and changes nothing.

## 3. Secrets

`deploy/compose/secrets/README.md` has the steps. Summary:

| File | Content | Read by |
|---|---|---|
| `secrets/github_pat.txt` | fine-grained PAT scoped to the target repo | worker-foreman, coder |
| `secrets/agy_cli_token.txt` | `~/.gemini/antigravity-cli/antigravity-oauth-token` from an interactive `agy` login | worker-foreman, coder |

Both are docker secrets (bind mounts at `/run/secrets/...`), never in an image or an environment
variable. Compose ignores `uid`/`mode` for file secrets, so the files keep their host owner and mode:
keep them 600 and owned by `FACTORY_UID`, which is the uid worker-foreman runs as. The services read the
files on every use, so replacing a file needs no restart.

`CODER_SERVICE_TOKEN` (in `.env`) is shared by worker-foreman and the coder; the coder rejects
`/invoke` calls without it in the `x-factory-token` header.

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
| coder job fails with a 403 from the proxy | `docker compose logs egress-proxy \| grep TCP_DENIED` | Add the host to `proxy/allowlist.txt` with a comment, `docker compose up -d --build egress-proxy`. |
| coder job `sandbox-unavailable` | coder logs | `agyuser` missing or uid drop blocked; the image creates it; do not run the coder with a different `user:`. |
| control center shows "not written yet" | `curl -s 127.0.0.1:18080/state.json` | 404 until the first ledger ingest; normal on a fresh stack. |
| control center blank, CSP error in console | browser devtools | The page must be loaded from the same origin as `/state.json` (port 18080); `connect-src 'self'` allows only that. |
| port already in use on `up` | `ss -ltn` | Change the `*_HOST_PORT` values in `.env`. |
| build fails "agy install failed" | network to `antigravity.google` and `storage.googleapis.com` | Fix network; `INSTALL_AGY=0` builds a worker image without agy (fake mode only). |

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
