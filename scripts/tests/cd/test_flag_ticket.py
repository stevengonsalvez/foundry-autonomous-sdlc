from __future__ import annotations

import json

from scripts.cd import flag_ticket as ft
from scripts.cd.ghcli import GhError

REPO = "o/r"
RUN_URL = "https://github.com/o/r/actions/runs/99"


class FakeGh:
    def __init__(self, comments: list[dict] | None = None, fail_on: str | None = None) -> None:
        self.comments = comments or []
        self.calls: list[tuple[str, str, dict | None]] = []
        self.fail_on = fail_on

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        body = json.loads(stdin) if stdin else None
        if "--slurp" in args:
            self.calls.append(("LIST", args[-1], None))
            return json.dumps([self.comments])
        method = args[args.index("-X") + 1] if "-X" in args else "GET"
        path = args[args.index("-X") + 2] if "-X" in args else args[1]
        self.calls.append((method, path, body))
        if self.fail_on and self.fail_on in path:
            raise GhError(args, "gh: Server Error (HTTP 500)")
        return "{}"

    def writes(self) -> list[tuple[str, str, dict | None]]:
        return [c for c in self.calls if c[0] in ("POST", "PATCH")]


def flag(fake: FakeGh, **overrides: object) -> str:
    params: dict = {
        "repo": REPO,
        "issue": 12,
        "pr": 13,
        "run_id": 99,
        "run_url": RUN_URL,
        "reason": "smoke",
        "version": "v0.4.0",
        "rollback_ok": True,
        "restored_version": "v0.3.1",
    }
    params.update(overrides)
    return ft.flag(fake, **params)


def test_labels_the_issue_and_posts_one_comment() -> None:
    fake = FakeGh()
    result = flag(fake)
    label, comment = fake.writes()
    assert label == ("POST", "repos/o/r/issues/12/labels", {"labels": ["escalated:deploy-failed"]})
    assert comment[1] == "repos/o/r/issues/12/comments"
    body = comment[2]["body"]
    assert body.startswith("<!-- cd-rollback:99 -->")
    assert "`smoke` job failed" in body and "v0.3.1" in body and RUN_URL in body
    assert result == "#12: labelled escalated:deploy-failed, comment created"


def test_flags_the_pr_when_there_is_no_issue() -> None:
    fake = FakeGh()
    flag(fake, issue=None)
    assert {path.split("/")[4] for _, path, _ in fake.writes()} == {"13"}


def test_with_neither_issue_nor_pr_nothing_is_written() -> None:
    fake = FakeGh()
    assert "no issue or pull request" in flag(fake, issue=None, pr=None)
    assert fake.calls == []


def test_the_same_run_updates_its_comment_in_place() -> None:
    old = ft.build_comment(
        run_id=99,
        run_url=RUN_URL,
        reason="soak",
        version="v0.4.0",
        rollback_ok=True,
        restored_version="v0.3.1",
    )
    fake = FakeGh(comments=[{"id": 555, "body": old}, {"id": 556, "body": "<!-- other -->"}])
    result = flag(fake)
    patch = [c for c in fake.writes() if c[0] == "PATCH"]
    assert patch == [("PATCH", "repos/o/r/issues/comments/555", patch[0][2])]
    assert "`smoke` job failed" in patch[0][2]["body"]
    assert not [c for c in fake.writes() if c[1].endswith("/comments")]  # no second comment
    assert result.endswith("comment updated")


def test_an_identical_comment_is_left_alone() -> None:
    body = ft.build_comment(
        run_id=99,
        run_url=RUN_URL,
        reason="smoke",
        version="v0.4.0",
        rollback_ok=True,
        restored_version="v0.3.1",
    )
    fake = FakeGh(comments=[{"id": 1, "body": body}])
    assert flag(fake).endswith("comment unchanged")
    assert [c[0] for c in fake.writes()] == ["POST"]  # only the (idempotent) label


def test_another_run_gets_its_own_comment() -> None:
    old = ft.marker(98) + "\nold"
    fake = FakeGh(comments=[{"id": 1, "body": old}])
    assert flag(fake).endswith("comment created")


def test_the_comment_says_so_when_the_rollback_did_not_finish() -> None:
    body = ft.build_comment(
        run_id=1,
        run_url=RUN_URL,
        reason="promote",
        version="v1",
        rollback_ok=False,
        restored_version="",
    )
    assert "rollback itself did not finish" in body
    first_release = ft.build_comment(
        run_id=1,
        run_url=RUN_URL,
        reason="smoke",
        version="v1",
        rollback_ok=True,
        restored_version="",
    )
    assert "Staging was removed" in first_release


def test_cli_reports_a_gh_failure_with_a_non_zero_exit() -> None:
    argv = [
        "--repo",
        REPO,
        "--issue",
        "12",
        "--run-id",
        "99",
        "--run-url",
        RUN_URL,
        "--reason",
        "smoke",
        "--version",
        "v1",
    ]
    assert ft.main(argv, FakeGh(fail_on="/labels")) == 1
    assert ft.main(argv, FakeGh()) == 0
    assert ft.main([*argv[:2], "--issue", "", *argv[4:]], FakeGh()) == 0  # empty means none
