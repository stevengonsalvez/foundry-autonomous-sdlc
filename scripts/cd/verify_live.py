"""Poll a live `build.json` until it names the sha we deployed.

GitHub Pages is a CDN: a finished deployment is not instantly what every request sees. A
cache-busting query string plus no-cache headers asks for the origin copy.

    python -m scripts.cd.verify_live --url https://x.github.io/repo/staging/build.json --sha <sha>
    python -m scripts.cd.verify_live --url .../staging/build.json --expect-absent
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from .fetch import Fetch, http_fetch
from .ghcli import fail


@dataclass(frozen=True)
class Outcome:
    ok: bool
    detail: str
    attempts: int


def _observe(fetch: Fetch, url: str, cache_buster: int) -> tuple[str | None, str]:
    """(the sha served or None, a description of what was seen)."""
    status, body = fetch(f"{url}?nocache={cache_buster}")
    if status == 404:
        return None, "404 not found"
    if status != 200:
        return None, f"HTTP {status}"
    try:
        sha = json.loads(body)["sha"]
    except (ValueError, KeyError, TypeError):
        return None, "200 but not a build.json"
    return (sha, f"sha {sha}") if isinstance(sha, str) else (None, "200 but no sha")


def wait_for_build(
    fetch: Fetch,
    url: str,
    *,
    expected_sha: str | None,
    timeout_s: float,
    interval_s: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Outcome:
    """Wait until `url` serves `expected_sha`, or (expected_sha None) until it is a 404."""
    deadline = clock() + timeout_s
    attempts = 0
    seen = "nothing"
    while True:
        attempts += 1
        sha, seen = _observe(fetch, url, int(clock() * 1000))
        if expected_sha is None and seen == "404 not found":
            return Outcome(True, "build.json is gone", attempts)
        if expected_sha is not None and sha == expected_sha:
            return Outcome(True, f"serving {sha}", attempts)
        if clock() + interval_s > deadline:
            wanted = "a 404" if expected_sha is None else expected_sha
            return Outcome(False, f"wanted {wanted}, last saw {seen}", attempts)
        sleep(interval_s)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sha")
    group.add_argument("--expect-absent", action="store_true")
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)
    outcome = wait_for_build(
        http_fetch,
        args.url,
        expected_sha=None if args.expect_absent else args.sha,
        timeout_s=args.timeout,
        interval_s=args.interval,
    )
    print(f"{args.url}: {outcome.detail} after {outcome.attempts} attempt(s)")
    return 0 if outcome.ok else fail(f"live check failed: {outcome.detail}")


if __name__ == "__main__":
    sys.exit(main())
