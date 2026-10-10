#!/usr/bin/env bash
# Assemble the GitHub Pages site: the demo app at the root, the metrics dashboard at /dashboard/.
#
# Usage: scripts/build_pages.sh <output_dir> [metrics_checkout_dir]
#
#   output_dir            must not exist or must be empty
#   metrics_checkout_dir  checkout of the `metrics` branch; its metrics.json is published only
#                         when it is valid JSON with the schema version the dashboard reads
#
# Environment:
#   APP_DIST   use this already built app directory instead of running
#              `npm ci && npm run build:pages` in app/ (used by tests and by CI jobs that
#              build the app in an earlier step)
set -euo pipefail

usage() {
  echo "usage: scripts/build_pages.sh <output_dir> [metrics_checkout_dir]" >&2
  exit 2
}

die() {
  echo "build_pages: $*" >&2
  exit 1
}

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  usage
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
dashboard_src="$repo_root/dashboard"
metrics_dir="${2:-}"

out="$1"
[ -n "$out" ] || usage
mkdir -p "$out"
out="$(cd "$out" && pwd -P)"

case "$repo_root/" in
  "$out"/*) die "output_dir must not be the repository root or one of its parents: $out" ;;
esac
if [ -n "$(ls -A "$out")" ]; then
  die "output_dir is not empty: $out"
fi

# The schema version the dashboard reads lives in one place: dashboard/js/aggregate.js.
schema_version="$(sed -n 's/^export const SCHEMA_VERSION = \([0-9][0-9]*\);.*/\1/p' "$dashboard_src/js/aggregate.js")"
[ -n "$schema_version" ] || die "cannot read SCHEMA_VERSION from dashboard/js/aggregate.js"

# 1. The app
if [ -n "${APP_DIST:-}" ]; then
  app_dist="$APP_DIST"
else
  echo "building app (npm ci && npm run build:pages)"
  (cd "$repo_root/app" && npm ci && npm run build:pages)
  app_dist="$repo_root/app/web/dist-pages"
fi
[ -f "$app_dist/index.html" ] || die "app build has no index.html: $app_dist"
[ ! -e "$app_dist/dashboard" ] || die "app build already contains a dashboard path: $app_dist/dashboard"
cp -R "$app_dist"/. "$out"/

# 2. The dashboard: an explicit allowlist, so tests, fixtures, package.json and docs never ship.
mkdir -p "$out/dashboard"
cp "$dashboard_src/index.html" "$out/dashboard/index.html"
cp -R "$dashboard_src/css" "$out/dashboard/css"
cp -R "$dashboard_src/js" "$out/dashboard/js"

# 3. Metrics, only when present and readable by this dashboard version
metrics_note="no metrics checkout given, dashboard will show its no-data state"
if [ -n "$metrics_dir" ]; then
  src="$metrics_dir/metrics.json"
  if [ ! -f "$src" ] || [ -L "$src" ]; then
    metrics_note="metrics.json not found in $metrics_dir, dashboard will show its no-data state"
  elif ! command -v jq >/dev/null 2>&1; then
    die "jq is required to validate metrics.json"
  elif ! jq -e -s --argjson v "$schema_version" 'length == 1 and (.[0] | type == "object" and .version == $v)' "$src" >/dev/null 2>&1; then
    metrics_note="metrics.json skipped: not valid JSON or not schema version $schema_version"
  else
    cp "$src" "$out/dashboard/metrics.json"
    metrics_note="metrics.json published (schema version $schema_version)"
  fi
fi

touch "$out/.nojekyll"

# Guard rail: nothing test-shaped may reach the published site.
leaks="$(cd "$out/dashboard" && find . \( -iname '*fixture*' -o -iname '*.sample.json' -o -iname '*.test.*' -o -name test -o -name node_modules -o -name package.json -o -name README.md \) -print)"
if [ -n "$leaks" ]; then
  echo "$leaks" >&2
  die "refusing to publish: test or dev files found in the dashboard output"
fi

echo "$metrics_note"
echo "published tree ($out):"
(cd "$out" && find . -type f | sort | sed 's|^\./|  |')
