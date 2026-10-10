"""
A failed coder job leaves its evidence on the issue, because the sandbox session that holds the log
does not outlive it (status later answers session_not_accessible): one owner-authored comment per
job id, with reason, phase, iterations, engine, engine_events, the red/green summaries and the last
3000 characters of log_tail, secrets redacted and rendered inert. engine_events also go into the
state comment's coder block.
"""

from __future__ import annotations

import json

from conftest import World
from test_scenarios import A_BODY

from sdlc_agents import state
from sdlc_agents.sanitise import redact_secrets

PAT = "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTU"
EVENTS = [{"iteration": 1, "engine": "agy", "reason": "permission-denied", "detail": "shell denied"},
          {"iteration": 2, "engine": "agy-unrestricted", "reason": "no-progress", "detail": "no edits"}]


def log_comments(world: World, n: int) -> list[str]:
    return [b for b in world.gh.bodies(n) if b.startswith("<!-- sdlc-coder-log:v1 ")]


def failing_job(world: World, outcome: str = "failed:engines-exhausted") -> None:
    world.coder.outcomes = [outcome]
    world.coder.extra_status = {
        "engine_events": EVENTS, "red": "1 failed (estimated-delivery.test.tsx)", "green": "",
        "log_tail": "x" * 5000 + f"\nclone with {PAT}\nping @octocat ``` </details> [a](http://evil)\nLAST LINE",
    }


def test_failed_job_posts_one_redacted_log_comment_and_keeps_engine_events(world: World) -> None:
    failing_job(world)
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in world.gh.labels(n))
    world.tick(2)

    [body] = log_comments(world, n)
    assert body.startswith(f"<!-- sdlc-coder-log:v1 j-{n}-1 -->")
    assert "<details>" in body and body.rstrip().endswith("</details>")
    for text in ("engines-exhausted", "phase", "agy-unrestricted", "permission-denied",
                 "1 failed (estimated-delivery.test.tsx)", "LAST LINE"):
        assert text in body, text
    assert PAT not in body and "[REDACTED]" in body
    assert "x" * 3000 not in body                                  # only the last 3000 characters of the tail
    # The tail sits in a fence longer than any backtick run in it, so nothing in it renders or mentions.
    assert "\n````text\n" in body and body.count("<details>") == 1
    st = world.gh.state_of(n)
    assert [e["reason"] for e in st["coder"]["engine_events"]] == ["permission-denied", "no-progress"]
    assert PAT not in json.dumps(st)


def test_tests_invalid_and_timeout_jobs_get_one_comment_each(world: World) -> None:
    world.coder.outcomes = ["failed:tests-invalid", "timeout:deadline"]
    world.coder.extra_status = {"engine_events": [], "log_tail": "boom"}
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in world.gh.labels(n))
    world.tick(2)
    markers = [b.splitlines()[0] for b in log_comments(world, n)]
    assert markers == [f"<!-- sdlc-coder-log:v1 j-{n}-1 -->", f"<!-- sdlc-coder-log:v1 j-{n}-2 -->"]


def test_succeeded_jobs_post_no_log_comment(world: World) -> None:
    world.coder.extra_status = {"engine_events": EVENTS}
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.RELEASED in world.gh.labels(n))
    assert log_comments(world, n) == []


def test_redaction_covers_common_token_shapes() -> None:
    text = ("ghp_" + "a" * 36 + " gho_" + "b" * 36 + " " + PAT + " Authorization: Bearer abc.def-ghi "
            "https://x-access-token:s3cr3t@github.com/o/r eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig_value "
            "AccountKey=Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA==;")
    out = redact_secrets(text)
    for secret in ("ghp_", "gho_", "github_pat_", "abc.def-ghi", "s3cr3t", "eyJhbGci", "Zm9vYmFy"):
        assert secret not in out, secret
