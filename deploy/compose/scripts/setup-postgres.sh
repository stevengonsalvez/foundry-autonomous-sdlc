#!/bin/sh
# Vendored from temporalio/samples-server compose/scripts/setup-postgres.sh (main, 2026-10-20).
# Local change: idempotent. Upstream runs `create` and `setup-schema -v 0.0` unconditionally, which fails
# on the second `docker compose up` against the same volume. Here an up-to-date schema is a no-op, and a
# database without a schema (first boot, or a crash mid-setup) gets the full setup.
set -eu

: "${POSTGRES_SEEDS:?ERROR: POSTGRES_SEEDS environment variable is required}"
: "${POSTGRES_USER:?ERROR: POSTGRES_USER environment variable is required}"
PORT=${DB_PORT:-5432}
SCHEMA_ROOT=/etc/temporal/schema/postgresql/v12

echo 'Waiting for PostgreSQL port to be available...'
nc -z -w 10 "$POSTGRES_SEEDS" "$PORT"
echo 'PostgreSQL port is available'

sql_tool() {
  temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" -u "$POSTGRES_USER" -p "$PORT" "$@"
}

setup_db() {
  db=$1
  versioned=$2
  sql_tool --db "$db" create >/dev/null 2>&1 || echo "database $db not created (it may already exist)"
  if sql_tool --db "$db" update-schema -d "$versioned"; then
    echo "database $db: schema up to date"
    return 0
  fi
  echo "database $db: no schema yet, running full setup"
  sql_tool --db "$db" setup-schema -v 0.0
  sql_tool --db "$db" update-schema -d "$versioned"
}

setup_db temporal "$SCHEMA_ROOT/temporal/versioned"
setup_db temporal_visibility "$SCHEMA_ROOT/visibility/versioned"
echo 'PostgreSQL schema setup complete'
