#!/usr/bin/env bash
# Assemble the GitHub Pages site: the prod app at the root, the staging app at /staging/, the metrics
# dashboard at /dashboard/ and the control center at /control-center/. GitHub Pages serves one artifact
# for the whole site, so every deploy carries all of them.
#
# Usage: scripts/build_pages.sh <output_dir> [metrics_checkout_dir]
#
#   output_dir            must not exist or must be empty
#   metrics_checkout_dir  checkout of the `metrics` branch; its metrics.json is published only
#                         when it is valid JSON with the schema version the dashboard reads
#
# Environment:
#   PROD_DIST            built app published at the site root (APP_DIST is the older name for the
#                        same thing; set only one). When neither is set the app is built from this
#                        checkout with `npm ci && npm run build:pages` in app/.
#   STAGING_DIST         built app published at /staging/. Unset: no /staging/ is published.
#   CONTROL_CENTER_SRC   source directory of the static control center app. Published at
#                        /control-center/ through an allowlist (index.html, css/, js/, assets/).
#                        Unset or missing: skipped without error.
#
# A built app that has a build.json keeps it; it must be a JSON object with a string `sha`.
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

# A built app dist is copied as is. It must have an index.html, may carry a build.json (which must
# be valid) and must not already use a path this script publishes something else under.
check_dist() {
  local dist="$1" label="$2" reserved
  [ -f "$dist/index.html" ] || die "$label build has no index.html: $dist"
  for reserved in dashboard staging control-center history; do
    [ ! -e "$dist/$reserved" ] || die "$label build already contains a $reserved path: $dist/$reserved"
  done
  if [ -e "$dist/build.json" ]; then
    command -v jq >/dev/null 2>&1 || die "jq is required to validate build.json"
    jq -e 'type == "object" and (.sha | type == "string" and length > 0)' "$dist/build.json" >/dev/null 2>&1 \
      || die "$label build.json is not a JSON object with a sha: $dist/build.json"
  fi
}

# 1. The app (prod at the root, staging under /staging/)
if [ -n "${APP_DIST:-}" ] && [ -n "${PROD_DIST:-}" ]; then
  die "set only one of APP_DIST and PROD_DIST"
fi
prod_dist="${PROD_DIST:-${APP_DIST:-}}"
if [ -n "$prod_dist" ]; then
  app_dist="$prod_dist"
else
  echo "building app (npm ci && npm run build:pages)"
  (cd "$repo_root/app" && npm ci && npm run build:pages)
  app_dist="$repo_root/app/web/dist-pages"
fi
check_dist "$app_dist" "app"
cp -R "$app_dist"/. "$out"/

staging_note="no staging build given, /staging/ is not published"
if [ -n "${STAGING_DIST:-}" ]; then
  check_dist "$STAGING_DIST" "staging"
  mkdir -p "$out/staging"
  cp -R "$STAGING_DIST"/. "$out/staging"/
  staging_note="staging published at /staging/"
fi

# 2. The dashboard: an explicit allowlist, so tests, fixtures, package.json and docs never ship.
mkdir -p "$out/dashboard"
cp "$dashboard_src/index.html" "$out/dashboard/index.html"
cp -R "$dashboard_src/css" "$out/dashboard/css"
cp -R "$dashboard_src/js" "$out/dashboard/js"

# 2b. The control center: the same kind of allowlist, and only what exists.
control_center_note="no control center source, /control-center/ is not published"
cc_src="${CONTROL_CENTER_SRC:-}"
if [ -n "$cc_src" ] && [ -f "$cc_src/index.html" ]; then
  mkdir -p "$out/control-center"
  cp "$cc_src/index.html" "$out/control-center/index.html"
  for part in css js assets; do
    if [ -d "$cc_src/$part" ]; then
      cp -R "$cc_src/$part" "$out/control-center/$part"
    fi
  done
  control_center_note="control center published at /control-center/"
fi

# 2c. App evolution history: the same kind of allowlist, and only what exists.
history_note="no app history source, /history/ is not published"
history_src="${HISTORY_SRC:-$repo_root/history}"
if [ -n "$history_src" ] && [ -f "$history_src/index.html" ]; then
  mkdir -p "$out/history"
  cp "$history_src/index.html" "$out/history/index.html"
  for part in css js screenshots data.json; do
    if [ -e "$history_src/$part" ]; then
      cp -R "$history_src/$part" "$out/history/$part"
    fi
  done
  history_note="app history published at /history/"
fi

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

# Guard rail: nothing test-shaped, and no symlink, may reach the published site from the two
# source-copied apps (built apps are checked by check_dist).
for copied in dashboard control-center history; do
  [ -d "$out/$copied" ] || continue
  leaks="$(cd "$out/$copied" && find . \( -iname '*fixture*' -o -iname '*.sample.json' -o -iname '*.test.*' -o -name test -o -name node_modules -o -name package.json -o -name README.md -o -type l \) -print)"
  if [ -n "$leaks" ]; then
    echo "$leaks" >&2
    die "refusing to publish: test, dev files or symlinks found in the $copied output"
  fi
done

echo "$staging_note"
echo "$control_center_note"
echo "$history_note"
echo "$metrics_note"
echo "published tree ($out):"
(cd "$out" && find . -type f | sort | sed 's|^\./|  |')
