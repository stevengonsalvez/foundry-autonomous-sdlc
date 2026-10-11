from __future__ import annotations

import json

import pytest
from cd_helpers import sha

from scripts.cd import release_ops as ro
from scripts.cd.ghcli import GhError

REPO = "o/r"
URL = "https://github.com/o/r/actions/runs/9"


class FakeGh:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, dict]] = []
        self.deployments: list[dict] = []
        self.comments: dict[int, list[dict]] = {}
        self.refs: dict[str, str] = {}
        self.next_id = 100

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        if "--slurp" in args:
            number = int(args[-1].split("/")[4])
            return json.dumps([self.comments.get(number, [])])
        method = args[args.index("-X") + 1] if "-X" in args else "GET"
        path = args[args.index("-X") + 2] if "-X" in args else args[1]
        body = json.loads(stdin) if stdin else None
        path = path.removeprefix(f"repos/{REPO}/")
        if method == "GET" and path.startswith("deployments?"):
            return json.dumps(self.deployments)
        if method == "GET" and path.startswith("git/ref/tags/"):
            tag = path.removeprefix("git/ref/tags/")
            return json.dumps({"object": {"sha": self.refs[f"refs/tags/{tag}"]}})
        self.writes.append((method, path, body))
        if path == "deployments":
            return json.dumps({"id": self.next_id})
        if path == "git/refs":
            if body["ref"] in self.refs:
                raise GhError(args, "gh: Reference already exists (HTTP 422)")
            self.refs[body["ref"]] = body["sha"]
        return "{}"


def test_deploy_start_creates_a_deployment_and_its_first_status() -> None:
    fake = FakeGh()
    deployment = ro.deploy_start(
        fake, REPO, "staging", sha(1), URL, "https://x/staging/", "in_progress"
    )
    assert deployment == 100
    create, status = fake.writes
    assert create[2]["ref"] == sha(1) and create[2]["environment"] == "staging"
    assert create[2]["required_contexts"] == [] and create[2]["transient_environment"] is True
    assert status[1] == "deployments/100/statuses"
    assert status[2] == {
        "state": "in_progress",
        "auto_inactive": True,
        "log_url": URL,
        "environment_url": "https://x/staging/",
    }


def test_production_deployments_are_flagged_as_production() -> None:
    fake = FakeGh()
    ro.deploy_start(fake, REPO, "production", sha(1), URL, "https://x/", "success")
    assert fake.writes[0][2]["production_environment"] is True
    assert fake.writes[0][2]["transient_environment"] is False
    assert fake.writes[1][2]["state"] == "success"


def test_failure_statuses_carry_no_environment_url() -> None:
    fake = FakeGh()
    fake.deployments = [{"id": 7}, {"id": 8}]
    assert ro.deploy_mark(fake, REPO, "staging", sha(1), "failure", URL) == 2
    assert [w[1] for w in fake.writes] == ["deployments/7/statuses", "deployments/8/statuses"]
    assert all("environment_url" not in w[2] and w[2]["state"] == "failure" for w in fake.writes)


def test_deploy_mark_with_no_deployments_marks_nothing() -> None:
    assert ro.deploy_mark(FakeGh(), REPO, "staging", sha(1), "failure") == 0


def test_create_tag_is_idempotent_on_the_same_sha_and_refuses_another() -> None:
    fake = FakeGh()
    assert ro.create_tag(fake, REPO, "prod/1", sha(1)) == "created"
    assert ro.create_tag(fake, REPO, "prod/1", sha(1)) == "exists"
    with pytest.raises(RuntimeError, match="already exists on"):
        ro.create_tag(fake, REPO, "prod/1", sha(2))
    assert fake.refs == {"refs/tags/prod/1": sha(1)}


def test_the_release_comment_has_the_agreed_wording() -> None:
    marker, body = ro.release_comment(sha(1), "v0.4.0", URL, 10)
    assert marker == f"<!-- cd-release:{sha(1)} -->"
    assert body.splitlines()[1] == "Released to prod: v0.4.0 (smoke and 10 minute soak passed)"
    assert body.endswith(f"Run: {URL}")


def test_tickets_are_this_release_first_then_everything_it_carried() -> None:
    includes = [{"pr": 5, "issue": 50}, {"pr": 6, "issue": None}, {"pr": 7, "issue": 70}]
    assert ro.ticket_numbers(7, 70, includes) == [7, 70, 5, 50, 6]
    assert ro.ticket_numbers(None, None, []) == []
    many = [{"pr": i, "issue": None} for i in range(100)]
    assert len(ro.ticket_numbers(None, None, many)) == ro.MAX_TICKETS


def test_comment_release_comments_once_on_every_ticket_and_updates_on_rerun() -> None:
    fake = FakeGh()
    kwargs = {
        "sha": sha(3),
        "version": "v0.4.0",
        "run_url": URL,
        "soak_minutes": 10,
        "pr": 13,
        "issue": 12,
        "includes": [{"pr": 11, "issue": 10}, {"pr": 13, "issue": 12}],
    }
    first = ro.comment_release(fake, REPO, **kwargs)
    flag = ", escalated:deploy-failed cleared"
    assert first == [
        f"#13: created{flag}",
        f"#12: created{flag}",
        f"#11: created{flag}",
        f"#10: created{flag}",
    ]
    assert len([w for w in fake.writes if w[0] != "DELETE"]) == 4
    # a re-run finds each marker comment and writes nothing
    for number in (13, 12, 11, 10):
        fake.comments[number] = [
            {
                "id": number,
                "user": {"login": "github-actions[bot]"},
                "body": ro.release_comment(sha(3), "v0.4.0", URL, 10)[1],
            }
        ]
    fake.writes.clear()
    assert set(ro.comment_release(fake, REPO, **kwargs)) == {
        f"#{n}: unchanged{flag}" for n in (13, 12, 11, 10)
    }
    assert [w for w in fake.writes if w[0] != "DELETE"] == []


def test_a_ticket_that_failed_before_and_is_live_now_loses_its_failure_flag() -> None:
    fake = FakeGh()
    out = ro.comment_release(
        fake,
        REPO,
        sha=sha(3),
        version="v0.4.0",
        run_url=URL,
        soak_minutes=10,
        pr=13,
        issue=12,
        includes=[],
    )
    deletes = [w for w in fake.writes if w[0] == "DELETE"]
    assert [w[1] for w in deletes] == [
        "issues/13/labels/escalated:deploy-failed",
        "issues/12/labels/escalated:deploy-failed",
    ]
    assert all(line.endswith("escalated:deploy-failed cleared") for line in out)


def test_clearing_the_flag_is_quiet_when_there_was_none() -> None:
    class NotFound(FakeGh):
        def __call__(self, args: list[str], stdin: str | None = None) -> str:
            if "-X" in args and args[args.index("-X") + 1] == "DELETE":
                raise GhError(args, "gh: Label does not exist (HTTP 404)")
            return super().__call__(args, stdin)

    out = ro.comment_release(
        NotFound(),
        REPO,
        sha=sha(3),
        version="v0.4.0",
        run_url=URL,
        soak_minutes=10,
        pr=13,
        issue=None,
        includes=[],
    )
    assert out == ["#13: created"]
