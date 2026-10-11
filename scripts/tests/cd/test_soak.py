from __future__ import annotations

import json

import pytest
from cd_helpers import sha

from scripts.cd import soak

BASE = "https://o.github.io/r/staging/"
HTML = (
    '<!doctype html><html><head><script type="module" crossorigin src="./assets/index-1.js">'
    '</script><link rel="stylesheet" crossorigin href="./assets/index-1.css"></head>'
    '<body><div id="root"></div></body></html>'
)


class Site:
    """A fake site that can break on demand. `breaks` maps request number -> answer."""

    def __init__(self, expect: str = sha(1)) -> None:
        self.pages: dict[str, tuple[int, str]] = {
            BASE: (200, HTML),
            BASE + "build.json": (200, json.dumps({"sha": expect})),
            BASE + "assets/index-1.js": (200, "console.log(1)"),
            BASE + "assets/index-1.css": (200, "body{}"),
        }
        self.requests: list[str] = []  # without the cache-buster query
        self.raw_requests: list[str] = []
        self.flaky: dict[int, tuple[int, str]] = {}  # request number -> forced answer

    def __call__(self, url: str) -> tuple[int, str]:
        self.raw_requests.append(url)
        url = url.split("?")[0]
        self.requests.append(url)
        if len(self.requests) in self.flaky:
            return self.flaky[len(self.requests)]
        return self.pages.get(url, (404, "not found"))


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def run(site, minutes: float = 10, interval: float = 30, browser=lambda: True):
    clock = Clock()
    browser_calls: list[float] = []

    def spy() -> bool:
        browser_calls.append(clock.t)
        return browser()

    report = soak.run_soak(
        fetch=site,
        base_url=BASE,
        expect_sha=sha(1),
        minutes=minutes,
        interval_s=interval,
        browser=spy,
        clock=clock,
        sleep=clock.sleep,
        log=lambda _line: None,
    )
    return report, clock, browser_calls


def test_a_healthy_site_passes_with_21_probes_in_10_minutes() -> None:
    report, clock, browser_calls = run(Site())
    assert report.ok and report.probes == 21 and report.recovered == 0
    assert clock.t == 600  # the whole soak is exactly ten minutes of probing
    assert browser_calls == [0, 300, 600]  # first, middle and last
    assert report.browser_runs == 3


def test_probes_are_spaced_by_the_interval_without_drift() -> None:
    site = Site()
    _, clock, _ = run(site, minutes=2)
    assert clock.sleeps == [30.0] * 4


def test_zero_minutes_is_one_probe_with_one_browser_run() -> None:
    report, _, browser_calls = run(Site(), minutes=0)
    assert report.ok and report.probes == 1 and browser_calls == [0]


def test_every_probe_checks_page_build_json_and_both_assets() -> None:
    site = Site()
    run(site, minutes=0)
    assert site.requests == [
        BASE,
        BASE + "build.json",
        BASE + "assets/index-1.js",
        BASE + "assets/index-1.css",
    ]


@pytest.mark.parametrize(
    ("url", "answer", "needle"),
    [
        (BASE, (500, "oops"), "index.html answered 500"),
        (BASE, (200, HTML.replace('id="root"', 'id="x"')), "no root element"),
        (BASE, (200, HTML.replace(".js", ".txt")), "names no script"),
        (BASE, (200, HTML.replace(".css", ".txt")), "names no stylesheet"),
        (BASE + "build.json", (200, json.dumps({"sha": sha(2)})), "serves " + sha(2)),
        (BASE + "build.json", (404, ""), "build.json answered 404"),
        (BASE + "build.json", (200, "<html>"), "serves None"),
        (BASE + "assets/index-1.js", (404, ""), "index-1.js answered 404"),
        (BASE + "assets/index-1.css", (200, ""), "index-1.css is empty"),
    ],
)
def test_a_broken_site_fails_the_soak(url: str, answer: tuple[int, str], needle: str) -> None:
    site = Site()
    site.pages[url] = answer
    report, _, browser_calls = run(site)
    assert not report.ok and report.probes == 1
    assert needle in " ".join(report.lines)
    assert browser_calls == []  # failed before the first browser run


def test_a_failure_in_the_middle_of_the_soak_fails_it() -> None:
    site = Site()
    original = site.__call__
    state = {"probes": 0}

    def breaking(url: str) -> tuple[int, str]:
        path = url.split("?")[0]
        if path == BASE:
            state["probes"] += 1
        # healthy for eight probes, then the sha changes
        if state["probes"] > 8 and path == BASE + "build.json":
            return 200, json.dumps({"sha": sha(9)})
        return original(url)

    report, clock, _ = run(breaking)
    assert not report.ok
    assert report.probes == 9 and clock.t == 240


def test_one_dropped_request_is_repeated_once_and_passes() -> None:
    site = Site()
    site.flaky = {1: (0, "connection reset")}  # only the very first request fails
    report, _, _ = run(site, minutes=1)
    assert report.ok and report.recovered == 1
    assert any("recovered on the immediate repeat" in line for line in report.lines)


def test_a_failure_that_repeats_is_not_forgiven() -> None:
    site = Site()
    site.flaky = {1: (0, "reset"), 5: (0, "reset")}  # first attempt, then the repeat (5th request)
    report, _, _ = run(site, minutes=1)
    assert not report.ok and report.recovered == 0
    assert any("failed again" in line for line in report.lines)


def test_a_failing_browser_run_fails_the_soak() -> None:
    report, _, browser_calls = run(Site(), browser=lambda: False)
    assert not report.ok and browser_calls == [0] and report.probes == 1


def test_asset_urls_ignore_other_origins_data_urls_and_protocol_relative_links() -> None:
    html = (
        '<script src="https://cdn.example.com/x.js"></script><script src="//cdn/x.js"></script>'
        '<link rel="stylesheet" href="data:text/css,a"><script src="./assets/a.js"></script>'
        '<link rel="icon" href="./favicon.ico">'
    )
    assert soak.asset_urls(html, BASE) == [BASE + "assets/a.js"]


def test_the_main_entry_point_rejects_bad_arguments() -> None:
    with pytest.raises(SystemExit):
        soak.main(["--url", BASE, "--expect-sha", "x", "--browser-cmd", "true", "--minutes", "31"])
    assert (
        soak.main(["--url", BASE, "--expect-sha", "x", "--browser-cmd", "true", "--interval", "0"])
        == 1
    )


def test_browser_command_runner_reports_exit_status() -> None:
    assert soak.command_runner("true", None)() is True
    assert soak.command_runner("false", None)() is False


def test_every_request_carries_its_own_cache_buster() -> None:
    site = Site()
    run(site, minutes=1)
    assert len(site.raw_requests) == 3 * 4 + 0  # three probes of four requests
    busters = [url.split("?cb=")[1] for url in site.raw_requests]
    assert len(set(busters)) == len(busters) and all(len(b) == 32 for b in busters)
    assert all(url.count("?") == 1 for url in site.raw_requests)
