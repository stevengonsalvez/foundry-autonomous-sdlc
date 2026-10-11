from __future__ import annotations

import json

from cd_helpers import sha

from scripts.cd import verify_live as vl

URL = "https://o.github.io/r/staging/build.json"


class Script:
    """Answers one scripted response per request, repeating the last; time moves with sleep."""

    def __init__(self, answers: list[tuple[int, str]]) -> None:
        self.answers = answers
        self.urls: list[str] = []
        self.t = 0.0

    def fetch(self, url: str) -> tuple[int, str]:
        self.urls.append(url)
        return self.answers[min(len(self.urls) - 1, len(self.answers) - 1)]

    def clock(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def wait(script: Script, expected: str | None, timeout: float = 360, interval: float = 15):
    return vl.wait_for_build(
        script.fetch,
        URL,
        expected_sha=expected,
        timeout_s=timeout,
        interval_s=interval,
        clock=script.clock,
        sleep=script.sleep,
    )


def body(n: int) -> tuple[int, str]:
    return 200, json.dumps({"sha": sha(n)})


def test_passes_at_once_when_the_sha_already_matches() -> None:
    script = Script([body(1)])
    outcome = wait(script, sha(1))
    assert outcome.ok and outcome.attempts == 1 and script.t == 0


def test_waits_through_the_old_build_and_404s_until_the_new_one_shows() -> None:
    script = Script([body(0), (404, "x"), (500, "x"), (200, "<html>"), body(1)])
    outcome = wait(script, sha(1))
    assert outcome.ok and outcome.attempts == 5 and script.t == 60


def test_gives_up_at_the_deadline_and_says_what_it_last_saw() -> None:
    script = Script([body(0)])
    outcome = wait(script, sha(1), timeout=360, interval=15)
    assert not outcome.ok
    assert f"wanted {sha(1)}, last saw sha {sha(0)}" == outcome.detail
    assert script.t <= 360 and outcome.attempts == 25


def test_every_request_has_its_own_cache_buster() -> None:
    script = Script([body(0), body(0), body(1)])
    wait(script, sha(1))
    queries = [u.split("?")[1] for u in script.urls]
    assert len(set(queries)) == 3 and all(q.startswith("nocache=") for q in queries)


def test_expecting_absence_waits_for_a_404() -> None:
    script = Script([body(1), body(1), (404, "")])
    outcome = wait(script, None)
    assert outcome.ok and outcome.attempts == 3


def test_expecting_absence_fails_while_something_is_still_served() -> None:
    assert not wait(Script([body(1)]), None, timeout=30).ok


def test_a_200_that_is_not_build_json_never_matches() -> None:
    assert not wait(Script([(200, "<html>nope</html>")]), sha(1), timeout=30).ok
    assert not wait(Script([(200, json.dumps({"sha": 5}))]), sha(1), timeout=30).ok
