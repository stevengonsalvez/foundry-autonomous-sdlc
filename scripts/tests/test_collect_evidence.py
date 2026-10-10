import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_evidence as ce  # noqa: E402

OWNER = {"login": "stevengonsalvez"}


def fake_api(path: str):
    state = {"scenario": "a", "stages": [{"stage": "stage:ready"}, {"stage": "stage:released"}],
             "quality": {"score": 100}, "coder": {"engine": "agy"}, "cost": {"usd": 0.0123},
             "pr": {"number": 5}, "release": {"tag": "v0.1.0", "url": "https://example.test/r"}}
    routes = {
        "issues?state=all": [{"number": 4, "title": "T", "state": "closed", "labels": [{"name": "stage:released"}],
                              "user": OWNER}],
        "issues/4/comments": [{"user": OWNER, "body": f"<!-- sdlc-state:v1\n{json.dumps(state)}\n-->"}],
        "check-runs": {"check_runs": [{"name": g, "conclusion": "success", "status": "completed"} for g in ce.GATES]},
        "pulls/5/commits": [{"sha": "a" * 40, "commit": {"message": "test: x", "verification": {"verified": False}}},
                            {"sha": "b" * 40, "commit": {"message": "feat: y", "verification": {"verified": False}}}],
        "commits/" + "a" * 40 + "": {"files": [{"filename": "app/web/tests/x.test.tsx"}]},
        "commits/" + "b" * 40 + "": {"files": [{"filename": "app/web/src/p.tsx"}]},
        "pulls/5": {"number": 5, "state": "closed", "merged_at": "2026-10-10T00:00:00Z", "merge_commit_sha": "c" * 40,
                    "html_url": "https://example.test/pr/5", "head": {"sha": "b" * 40}},
        "issues/5/comments": [{"user": OWNER, "body": '<!-- sdlc-review:v1 {"verdict":"approve","head":"' + "b" * 40 + '"} -->'}],
        "metrics.json": {"content": base64.b64encode(json.dumps(
            {"totals": {"usd": 0.1}, "gate_pass_rates": {"test": {"pass": 1}}}).encode()).decode()},
    }
    for key, value in routes.items():
        if key in path:
            return value
    raise AssertionError(path)


def test_report_shows_tests_first_checks_review_and_release():
    text = ce.build(fake_api)
    assert "Tests first: **yes**" in text
    assert "| tdd-order | success |" in text
    assert "approve" in text and "[v0.1.0](https://example.test/r)" in text
    assert "Scenario a: T" in text and '"usd": 0.1' in text


def test_implementation_first_is_flagged():
    rows = [{"kind": "implementation"}, {"kind": "test-only"}]
    assert not ce.tests_first(rows)


def test_review_for_another_head_does_not_count():
    comments = [{"user": OWNER, "body": '<!-- sdlc-review:v1 {"verdict":"approve","head":"old"} -->'}]
    assert ce.review_verdict(comments, "new") == "none for this head"
