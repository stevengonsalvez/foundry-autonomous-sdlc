import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_scenarios as rs  # noqa: E402


class FakeGh:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.next_number = 7

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        self.calls.append((args, stdin))
        url = args[1] if args[0] == "api" else args[3]
        if url.endswith("/issues") or url.endswith("/pulls"):
            self.next_number += 1
            return json.dumps({"number": self.next_number})
        if "/git/ref/heads/main" in url:
            return "abc123\n"
        if "/contents/" in url and "-X" not in args:
            return json.dumps({"sha": "f1", "content": base64.b64encode(
                b"<h1>Track your parcel</h1>").decode()})
        return "{}"


def test_every_scenario_file_parses():
    for key, name in rs.FILES.items():
        meta, body = rs.parse(rs.SCENARIOS / name)
        assert body and (meta.get("title") or meta.get("pr_title")), key


def test_issue_carries_the_scenario_marker_and_owner_flow_only():
    fake = FakeGh()
    created = rs.run_scenarios(["b"], run=fake)
    sent = json.loads(fake.calls[0][1])
    assert created == {"b": 8}
    assert sent["title"] == "Make the parcel tracker better"
    assert sent["body"].endswith("<!-- scenario: b -->")
    assert sent["labels"] == ["type:feature"]


def test_bug_scenario_is_labelled_as_a_bug():
    fake = FakeGh()
    rs.run_scenarios(["d"], run=fake)
    assert json.loads(fake.calls[0][1])["labels"] == ["type:bug"]


def test_stale_test_pr_changes_only_the_heading_and_is_labelled(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(rs, "find_heading_file", lambda: "app/web/src/pages/HomePage.tsx")
    created = rs.run_scenarios(["d-maintenance"], run=fake)
    put = next(json.loads(i) for a, i in fake.calls if "PUT" in a)
    assert base64.b64decode(put["content"]) == b"<h1>Track a parcel</h1>"
    assert put["branch"] == "chore/update-home-heading"
    labels = json.loads(fake.calls[-1][1])
    assert labels == {"labels": ["maintenance:test-repair"]} and created["d-maintenance"] == 8


def test_dry_run_creates_nothing():
    fake = FakeGh()
    assert rs.run_scenarios(list(rs.FILES), run=fake, dry_run=True) == {}
    assert fake.calls == []


def test_stale_test_pr_takes_the_copy_change_from_the_scenario():
    # a scenario names its own old and new text, so a copy change can be staged again once main has moved on
    fake = FakeGh()
    meta = {"pr_title": "Retitle", "branch": "chore/x", "old": "Track your parcel", "new": "Follow it"}
    rs.create_stale_test_pr(meta, "body", fake, "app/web/src/pages/HomePage.tsx")
    put = next(json.loads(i) for a, i in fake.calls if "PUT" in a)
    assert base64.b64decode(put["content"]) == b"<h1>Follow it</h1>"


def test_a_scenario_old_text_is_the_one_searched_for(monkeypatch):
    seen: list[str | None] = []
    monkeypatch.setattr(rs, "find_heading_file", lambda old=None: seen.append(old) or "app/web/src/x.tsx")
    monkeypatch.setattr(rs, "create_stale_test_pr", lambda meta, body, run, path: 9)
    rs.run_scenarios(["d-maintenance2"], run=FakeGh())
    assert seen == ["All statuses"]
