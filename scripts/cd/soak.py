"""Soak: probe staging for a while after the smoke tests passed; any new failure fails the release.

    python -m scripts.cd.soak --url https://x.github.io/repo/staging/ --expect-sha <sha> \
        --minutes 10 --interval 30 --browser-cmd "npm run smoke --workspace @parcel/e2e"

Each probe fetches index.html (200 and the root element), build.json (the expected sha), and the
JS and CSS assets index.html names (200, not empty). The first probe, the middle one and the last
one also run the browser smoke command. Real traffic is not involved: this is a probe loop.

Tolerance: none. A failed probe is repeated once, immediately, so one dropped packet does not
fail a release; if the repeat fails too, the soak fails. The browser command has its own retry
inside Playwright and is not repeated here.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

from .fetch import Fetch, http_fetch
from .ghcli import fail

MAX_MINUTES = 30
_SCRIPT = re.compile(r"""<script\b[^>]*\bsrc="([^"]+)\"""")
_STYLESHEET = re.compile(r"""<link\b[^>]*\brel="stylesheet"[^>]*\bhref="([^"]+)\"""")
_ROOT = re.compile(r"""\bid=["']root["']""")


@dataclass
class SoakReport:
    ok: bool
    probes: int = 0
    recovered: int = 0
    browser_runs: int = 0
    lines: list[str] = field(default_factory=list)


def asset_urls(html: str, base_url: str) -> list[str]:
    """Absolute URLs of the scripts and stylesheets index.html loads from the same site."""
    refs = [*_SCRIPT.findall(html), *_STYLESHEET.findall(html)]
    urls = [urljoin(base_url, ref) for ref in refs if not ref.startswith(("data:", "//"))]
    return [url for url in urls if url.startswith(base_url)]


def probe(fetch: Fetch, base_url: str, expect_sha: str) -> list[str]:
    """Everything wrong with the site right now; an empty list is a healthy probe."""
    problems: list[str] = []
    status, html = fetch(base_url)
    if status != 200:
        return [f"index.html answered {status}"]
    if not _ROOT.search(html):
        problems.append("index.html has no root element")
    assets = asset_urls(html, base_url)
    if not any(url.endswith(".js") for url in assets):
        problems.append("index.html names no script")
    if not any(url.endswith(".css") for url in assets):
        problems.append("index.html names no stylesheet")

    status, body = fetch(urljoin(base_url, "build.json"))
    try:
        served = json.loads(body)["sha"] if status == 200 else None
    except (ValueError, KeyError, TypeError):
        served = None
    if status != 200:
        problems.append(f"build.json answered {status}")
    elif served != expect_sha:
        problems.append(f"build.json serves {served}, expected {expect_sha}")

    for url in assets:
        status, body = fetch(url)
        if status != 200:
            problems.append(f"{url} answered {status}")
        elif not body:
            problems.append(f"{url} is empty")
    return problems


def browser_indexes(probes: int) -> set[int]:
    """Probe numbers that also run the browser: first, middle and last."""
    return {0, probes // 2, probes - 1}


def run_soak(
    *,
    fetch: Fetch,
    base_url: str,
    expect_sha: str,
    minutes: float,
    interval_s: float,
    browser: Callable[[], bool],
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> SoakReport:
    probes = int(minutes * 60 // interval_s) + 1
    report = SoakReport(ok=True)
    started = clock()

    def note(text: str) -> None:
        report.lines.append(text)
        log(text)

    for i in range(probes):
        if i:
            sleep(max(0.0, started + i * interval_s - clock()))
        elapsed = int(clock() - started)
        problems = probe(fetch, base_url, expect_sha)
        report.probes += 1
        if problems:
            note(f"probe {i + 1}/{probes} at {elapsed}s failed: {'; '.join(problems)}; repeating")
            problems = probe(fetch, base_url, expect_sha)
            if problems:
                note(f"probe {i + 1}/{probes} failed again: {'; '.join(problems)}")
                report.ok = False
                return report
            report.recovered += 1
            note(f"probe {i + 1}/{probes} recovered on the immediate repeat")
        else:
            note(f"probe {i + 1}/{probes} at {elapsed}s ok")
        if i in browser_indexes(probes):
            report.browser_runs += 1
            note(f"browser smoke at probe {i + 1}/{probes}")
            if not browser():
                note(f"browser smoke failed at probe {i + 1}/{probes}")
                report.ok = False
                return report
    note(f"soak passed: {report.probes} probes, {report.browser_runs} browser runs")
    return report


def command_runner(command: str, cwd: str | None) -> Callable[[], bool]:
    argv = shlex.split(command)

    def run() -> bool:
        return subprocess.run(argv, cwd=cwd, check=False).returncode == 0

    return run


def minutes_arg(text: str) -> float:
    value = float(text)
    if not 0 <= value <= MAX_MINUTES:
        raise argparse.ArgumentTypeError(f"minutes must be between 0 and {MAX_MINUTES}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", required=True, help="staging base URL")
    parser.add_argument("--expect-sha", required=True)
    parser.add_argument("--minutes", type=minutes_arg, default=10)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--browser-cmd", required=True)
    parser.add_argument("--browser-cwd")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        return fail("--interval must be positive")
    base_url = args.url if args.url.endswith("/") else args.url + "/"
    report = run_soak(
        fetch=http_fetch,
        base_url=base_url,
        expect_sha=args.expect_sha,
        minutes=args.minutes,
        interval_s=args.interval,
        browser=command_runner(args.browser_cmd, args.browser_cwd),
    )
    return 0 if report.ok else fail("soak failed: a probe failed after the smoke tests passed")


if __name__ == "__main__":
    sys.exit(main())
