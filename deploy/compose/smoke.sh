#!/usr/bin/env bash
# Compose smoke test, FACTORY_MODE=fake. Boots the whole stack as its own project (sdlc-factory-smoke) on
# distinct high ports with dummy secrets, checks wiring and network isolation, prints a PASS/FAIL table,
# then removes ONLY its own project (`docker compose -p sdlc-factory-smoke down -v`).
#
#   deploy/compose/smoke.sh               # build, run, tear down
#   KEEP=1 deploy/compose/smoke.sh        # leave the smoke project running for inspection
#   SMOKE_BUILD=0 deploy/compose/smoke.sh # reuse already-built images
#
# Ports (override with env): SMOKE_TEMPORAL_PORT 27233, SMOKE_UI_PORT 28233, SMOKE_CC_PORT 28080.
# Nothing here touches another compose project or container: every docker command goes through dc().
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT=sdlc-factory-smoke
COMPOSE_FILE="$HERE/docker-compose.yml"
TEMPORAL_PORT=${SMOKE_TEMPORAL_PORT:-27233}
UI_PORT=${SMOKE_UI_PORT:-28233}
CC_PORT=${SMOKE_CC_PORT:-28080}
BOOT_TIMEOUT_S=${SMOKE_BOOT_TIMEOUT_S:-300}
CC="http://127.0.0.1:${CC_PORT}"
NAMESPACE=factory
SMOKE_ISSUE=4242

WORK=$(mktemp -d "${TMPDIR:-/tmp}/sdlc-factory-smoke.XXXXXX")
ENV_FILE="$WORK/smoke.env"
RESULTS=()
FAILED=0

unset COMPOSE_PROJECT_NAME   # -p wins anyway; this keeps a stray shell value out of the picture

dc() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

cleanup() {
  local rc=$?
  if [ "${KEEP:-0}" = "1" ]; then
    echo "KEEP=1: project $PROJECT left running. Remove it with:"
    echo "  docker compose -p $PROJECT -f $COMPOSE_FILE --env-file $ENV_FILE down -v"
  else
    dc down -v --remove-orphans >/dev/null 2>&1 || echo "warning: teardown of $PROJECT failed" >&2
    rm -rf "$WORK"
  fi
  exit "$rc"
}
trap cleanup EXIT

log() { printf '[smoke] %s\n' "$*"; }

record() {  # record <PASS|FAIL|SKIP> <name> [detail]
  RESULTS+=("$1|$2|${3:-}")
  [ "$1" = FAIL ] && FAILED=$((FAILED + 1))
  printf '[smoke] %-4s %s %s\n' "$1" "$2" "${3:-}"
}

check() {  # check <name> <command...>: PASS when the command succeeds
  local name=$1; shift
  if "$@" >"$WORK/last.log" 2>&1; then record PASS "$name"; else record FAIL "$name" "$(tail -c 300 "$WORK/last.log" | tr '\n' ' ')"; fi
}

check_fails() {  # check_fails <name> <command...>: PASS when the command FAILS (isolation checks)
  local name=$1; shift
  if "$@" >"$WORK/last.log" 2>&1; then record FAIL "$name" "unexpectedly succeeded: $(tail -c 200 "$WORK/last.log" | tr '\n' ' ')"; else record PASS "$name"; fi
}

wait_until() {  # wait_until <timeout_s> <command...>: poll every 2 s, bounded
  local deadline=$((SECONDS + $1)); shift
  until "$@" >/dev/null 2>&1; do
    [ "$SECONDS" -ge "$deadline" ] && return 1
    sleep 2
  done
}

container_state() {  # container_state <service>: running|exited:<code>|healthy|unhealthy|starting|missing
  local id
  id=$(dc ps -a -q "$1" 2>/dev/null | head -1)
  [ -n "$id" ] || { echo missing; return; }
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{if .State.Running}}running{{else}}exited:{{.State.ExitCode}}{{end}}{{end}}' "$id"
}

is_state() { [ "$(container_state "$1")" = "$2" ]; }

port_free() { ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

random_secret() { od -An -N24 -tx1 /dev/urandom | tr -d ' \n'; }

# --- setup ---------------------------------------------------------------------------------------------

for port in "$TEMPORAL_PORT" "$UI_PORT" "$CC_PORT"; do
  port_free "$port" || { echo "port $port is in use; set SMOKE_*_PORT to free ports" >&2; exit 2; }
done

umask 077
printf 'fake-github-pat-not-used' > "$WORK/github_pat.txt"
printf 'fake-agy-token-not-used' > "$WORK/agy_cli_token.txt"
CODER_TOKEN=$(random_secret)

# .env.example supplies the pinned versions; everything a smoke run must own is overridden below.
grep -vE '^(FACTORY_MODE|BIND_ADDR|TEMPORAL_HOST_PORT|TEMPORAL_UI_HOST_PORT|CONTROL_CENTER_HOST_PORT|FACTORY_UID|FACTORY_GID|POSTGRES_PASSWORD|DOLT_ROOT_PASSWORD|DOLT_PASSWORD|CODER_SERVICE_TOKEN|GITHUB_PAT_HOST_FILE|AGY_TOKEN_HOST_FILE|PO_INTAKE_ENABLED)=' \
  "$HERE/.env.example" > "$ENV_FILE"
cat >> "$ENV_FILE" <<EOF
FACTORY_MODE=fake
BIND_ADDR=127.0.0.1
TEMPORAL_HOST_PORT=$TEMPORAL_PORT
TEMPORAL_UI_HOST_PORT=$UI_PORT
CONTROL_CENTER_HOST_PORT=$CC_PORT
FACTORY_UID=$(id -u)
FACTORY_GID=$(id -g)
POSTGRES_PASSWORD=$(random_secret)
DOLT_ROOT_PASSWORD=$(random_secret)
DOLT_PASSWORD=$(random_secret)
CODER_SERVICE_TOKEN=$CODER_TOKEN
GITHUB_PAT_HOST_FILE=$WORK/github_pat.txt
AGY_TOKEN_HOST_FILE=$WORK/agy_cli_token.txt
PO_INTAKE_ENABLED=0
EOF

log "validating compose config"
dc config -q

if [ "${SMOKE_BUILD:-1}" = "1" ]; then
  log "building images (agy and node downloads need network on a cold cache)"
  dc build
fi

log "starting project $PROJECT (ports $TEMPORAL_PORT, $UI_PORT, $CC_PORT on 127.0.0.1)"
# A dependency that never gets healthy makes `up` fail; keep going so the table shows which check broke.
if dc up -d; then record PASS "compose up -d"; else record FAIL "compose up -d" "a dependency failed to start, see logs below"; fi

# --- boot ----------------------------------------------------------------------------------------------

log "waiting up to ${BOOT_TIMEOUT_S}s for temporal, namespace, schedule-init, ledger-api, coder, foreman"
if wait_until "$BOOT_TIMEOUT_S" is_state temporal healthy; then record PASS "temporal healthy"; else record FAIL "temporal healthy" "state $(container_state temporal)"; fi
if wait_until 120 is_state temporal-create-namespace exited:0; then record PASS "temporal-create-namespace exited 0"; else record FAIL "temporal-create-namespace exited 0" "state $(container_state temporal-create-namespace)"; fi

admin() { dc run --rm --no-deps -T --entrypoint temporal temporal-admin-tools "$@" --address temporal:7233; }
check "namespace '$NAMESPACE' exists" admin operator namespace describe -n "$NAMESPACE"

if wait_until 120 is_state schedule-init exited:0; then record PASS "schedule-init exited 0"; else record FAIL "schedule-init exited 0" "state $(container_state schedule-init)"; fi
check "schedule github-poll exists" admin schedule describe --schedule-id github-poll -n "$NAMESPACE"

wait_until 120 is_state ledger-api healthy || true
wait_until 120 is_state coder healthy || true
wait_until 120 is_state control-center healthy || true
wait_until 60 is_state worker-foreman running || true

# --- ledger and control center -------------------------------------------------------------------------

check "ledger-api /healthz 200" dc exec -T ledger-api python -c \
  "import urllib.request as u; r = u.urlopen('http://127.0.0.1:8080/healthz', timeout=5); assert r.status == 200"

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1"; }

index_ok() { [ "$(http_code "$CC/index.html")" = 200 ] && curl -s --max-time 10 "$CC/index.html" | grep -q 'Control Center'; }
check "control center index.html 200" index_ok
root_redirects() {
  curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 "$CC/" | grep -qE '^302 .*/\?data=state\.json&issues=issues\.json$'
}
check "control center / redirects to ?data=state.json&issues=issues.json" root_redirects

state_ok_or_404() {
  local code
  code=$(curl -s -o "$WORK/state.json" -w '%{http_code}' --max-time 10 "$CC/state.json")
  [ "$code" = 404 ] && return 0
  [ "$code" = 200 ] && python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["version"] == 1' "$WORK/state.json"
}
check "nginx /state.json is 404 or v1 JSON before ingest" state_ok_or_404
issues_is_list() { curl -sf --max-time 10 "$CC/issues.json" | python3 -c 'import json, sys; assert isinstance(json.load(sys.stdin), list)'; }
check "nginx /issues.json 200 JSON list" issues_is_list

# One ticket.updated event, built with the ledger's own constructors (as services/tests/test_ledger_api.py).
ingest_one() {
  dc exec -T ledger-api python - "$SMOKE_ISSUE" <<'PY'
import json, sys, urllib.request
from sdlc_agents.ledger import events, model

issue, now = int(sys.argv[1]), "2026-10-20T10:00:00Z"
ticket = model.ticket(number=issue, kind="issue", title="Smoke test ticket", author="po", opened_at=now,
                      closed_at=None, labels=("type:feature", "stage:refining"), state_data=None)
body = json.dumps({"events": [events.make("ticket.updated", now, {"ticket": ticket}, issue=issue)]}).encode()
req = urllib.request.Request("http://127.0.0.1:8080/ingest", data=body, method="POST",
                             headers={"Content-Type": "application/json"})
reply = json.load(urllib.request.urlopen(req, timeout=15))
assert reply.get("ok") is True and reply.get("tickets", 0) >= 1, reply
print(reply)
PY
}
check "ledger-api /ingest accepts one ticket.updated" ingest_one

state_has_ticket() {
  curl -sf --max-time 10 "$CC/state.json" -o "$WORK/state.json"
  python3 - "$WORK/state.json" "$SMOKE_ISSUE" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc["version"] == 1, doc.get("version")
assert int(sys.argv[2]) in [t["issue"] for t in doc["tickets"]], [t.get("issue") for t in doc["tickets"]]
PY
}
check "nginx /state.json is v1 with ticket #$SMOKE_ISSUE" state_has_ticket
ingest_is_2xx_via_nginx() {
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST -H 'Content-Type: application/json' -d '{"events": []}' "$CC/ingest")
  echo "POST /ingest via nginx -> $code"
  [ "${code:0:1}" = 2 ]
}
check_fails "nginx does not expose POST /ingest" ingest_is_2xx_via_nginx

# --- coder isolation -----------------------------------------------------------------------------------

coder_py() { dc exec -T coder python -c "$1"; }
tcp_probe() { printf 'import socket; socket.create_connection((%s, %s), timeout=5).close()' "'$1'" "$2"; }

check_fails "coder cannot reach temporal:7233" coder_py "$(tcp_probe temporal 7233)"
check_fails "coder cannot reach dolt:3306" coder_py "$(tcp_probe dolt 3306)"
check_fails "coder cannot reach postgres:5432" coder_py "$(tcp_probe postgres 5432)"
check_fails "coder cannot reach ledger-api:8080" coder_py "$(tcp_probe ledger-api 8080)"
check_fails "coder direct HTTPS (no proxy) to example.com" coder_py \
  "import urllib.request as u; u.build_opener(u.ProxyHandler({})).open('https://example.com', timeout=8)"

# CONNECT through the proxy: 200 for a listed host, 403 for an unlisted one.
proxy_connect_is() {  # proxy_connect_is <host> <expected status>
  local got
  got=$(coder_py "import http.client as h; c = h.HTTPConnection('egress-proxy', 3128, timeout=10); c.request('CONNECT', '$1:443'); print(c.getresponse().status)")
  echo "CONNECT $1:443 -> $got"
  [ "$got" = "$2" ]
}
if curl -s -o /dev/null --max-time 8 https://github.com; then
  check "proxy allows CONNECT github.com:443 (200)" proxy_connect_is github.com 200
else
  record SKIP "proxy allows CONNECT github.com:443 (200)" "host is offline"
fi
check "proxy denies CONNECT example.com:443 (403)" proxy_connect_is example.com 403

agyuser_uid_is_61000() { [ "$(dc exec -T coder runuser -u agyuser -- id -u)" = 61000 ]; }
check "coder drops to agyuser (uid 61000) under no-new-privileges" agyuser_uid_is_61000
check_fails "agyuser cannot read /run/secrets/github_pat" dc exec -T coder runuser -u agyuser -- cat /run/secrets/github_pat
check_fails "agyuser cannot read /run/secrets/agy_cli_token" dc exec -T coder runuser -u agyuser -- cat /run/secrets/agy_cli_token
check_fails "coder root filesystem is read-only" dc exec -T coder touch /usr/local/smoke-write-test

# --- fake coder over the foreman's network -------------------------------------------------------------

check "worker-foreman is running" is_state worker-foreman running

fake_coder_flow() {
  dc exec -T worker-foreman python - "$CODER_TOKEN" <<'PY'
import json, sys, time, urllib.error, urllib.request

token, url = sys.argv[1], "http://coder:8090/invoke"
job = {"job_id": "smoke-4242-1", "repo": "stevengonsalvez/foundry-autonomous-sdlc", "base": "main",
       "branch": "agent/issue-4242", "mode": "feature",
       "issue": {"number": 4242, "title": "Smoke", "body": "Compose smoke test job."},
       "spec": {"acceptance_criteria": ["smoke"], "notes": ""},
       "tests": [{"path": "app/web/tests/smoke.test.ts", "content": "it('smoke', () => {})\n"}],
       "test_cmd": "npm test", "install_cmd": "", "max_iterations": 1, "deadline_s": 600,
       "allowed_paths": ["app/"]}

def call(body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, {}

code, _ = call({"op": "status", "job_id": "x"}, {})
assert code == 401, f"no token: expected 401, got {code}"
auth = {"x-factory-token": token}
code, started = call({"op": "start", "job": job}, auth)
assert code == 200 and started["status"] == "running", (code, started)
seen = ["running"]
for _ in range(20):
    code, status = call({"op": "status", "job_id": job["job_id"]}, auth)
    assert code == 200, (code, status)
    seen.append(status["status"])
    if status["status"] != "running":
        break
    time.sleep(0.5)
assert seen[-1] == "succeeded", seen
print(" -> ".join(seen))
PY
}
check "fake coder: 401 without token, start running, status succeeded" fake_coder_flow

# --- report --------------------------------------------------------------------------------------------

if [ "$FAILED" -gt 0 ]; then
  log "failures: service states and recent logs"
  dc ps -a || true
  dc logs --tail 30 >"$WORK/logs.txt" 2>&1 || true
  tail -n 200 "$WORK/logs.txt" || true
fi

echo
printf '%-6s %-66s %s\n' RESULT CHECK DETAIL
printf '%-6s %-66s %s\n' ------ ------------------------------------------------------------------ ------
for row in "${RESULTS[@]}"; do
  IFS='|' read -r status name detail <<<"$row"
  printf '%-6s %-66s %s\n' "$status" "$name" "${detail:0:120}"
done
echo
if [ "$FAILED" -gt 0 ]; then
  echo "SMOKE FAIL: $FAILED check(s) failed"
  exit 1
fi
echo "SMOKE PASS: ${#RESULTS[@]} checks"
