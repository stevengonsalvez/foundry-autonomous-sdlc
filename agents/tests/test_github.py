"""GitHub adapter against a recorded-style fake transport (no network)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from sdlc_agents.github import API, GitHubClient, _issue
from sdlc_agents.ports import GitHubError
from sdlc_agents.transport import HttpRequest, HttpResponse

TOKEN = "ghp_test_token_value"
BASE = f"{API}/repos/stevengonsalvez/foundry-autonomous-sdlc"


class Recorded:
    """Replays responses keyed by 'METHOD path?query' (path relative to the repo, or a full URL)."""

    def __init__(self, routes: dict[str, list[HttpResponse] | HttpResponse]):
        self.routes = {k: (v if isinstance(v, list) else [v]) for k, v in routes.items()}
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        key = request.url[len(BASE):] if request.url.startswith(BASE) else request.url
        queue = self.routes.get(f"{request.method} {key}")
        if not queue:
            raise AssertionError(f"unexpected request {request.method} {key}")
        return queue.pop(0) if len(queue) > 1 else queue[0]


def ok(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(status, headers or {}, json.dumps(body).encode())


def issue_json(number: int, **extra: Any) -> dict[str, Any]:
    return {"number": number, "title": f"t{number}", "body": None, "user": {"login": "stevengonsalvez"},
            "labels": [{"name": "type:bug"}], "state": "open", "created_at": "2026-10-10T12:00:00Z",
            "closed_at": None, **extra}


def pull_json(number: int, **extra: Any) -> dict[str, Any]:
    return {**issue_json(number), "merged": False, "merged_at": None, "merge_commit_sha": None,
            "head": {"ref": "agent/issue-1", "sha": "a" * 40}, "base": {"ref": "main"}, **extra}


def client(routes: dict[str, Any], **kwargs: Any) -> tuple[GitHubClient, Recorded, list[float]]:
    transport = Recorded(routes)
    sleeps: list[float] = []
    gh = GitHubClient(TOKEN, transport=transport, sleep=sleeps.append, now=lambda: 1000.0, **kwargs)
    return gh, transport, sleeps


def test_refuses_any_other_repository_and_an_empty_token() -> None:
    with pytest.raises(ValueError, match="refusing"):
        GitHubClient(TOKEN, repo="someone/else", transport=Recorded({}))
    with pytest.raises(ValueError, match="token"):
        GitHubClient("", transport=Recorded({}))


def test_list_issues_pages_by_number_and_marks_pull_requests() -> None:
    page1 = [issue_json(i) for i in range(1, 101)]
    page2 = [issue_json(101, pull_request={"url": "x"})]
    gh, transport, _ = client({
        "GET /issues?state=all&per_page=100&page=1": ok(page1, headers={
            "link": '<https://api.github.com/repositories/9/issues?page=2>; rel="next"'}),
        "GET /issues?state=all&per_page=100&page=2": ok(page2),
    })
    issues = gh.list_issues(state="all")
    assert len(issues) == 101 and issues[0].body == "" and issues[0].labels == ("type:bug",)
    assert issues[-1].is_pull_request and not issues[0].is_pull_request
    # the server's next link (a repositories/<id> URL) is never followed directly
    assert all(r.url.startswith(BASE) for r in transport.requests)


def test_requests_carry_the_token_only_in_the_authorization_header() -> None:
    gh, transport, _ = client({"GET /issues/3": ok(issue_json(3))})
    assert gh.get_issue(3).number == 3
    request = transport.requests[0]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in request.url and TOKEN not in repr(request) and TOKEN not in repr(gh)


def test_rate_limit_with_retry_after_waits_then_succeeds() -> None:
    limited = HttpResponse(403, {"retry-after": "7"}, b'{"message":"secondary rate limit"}')
    gh, _, sleeps = client({"GET /issues/3": [limited, ok(issue_json(3))]})
    assert gh.get_issue(3).number == 3
    assert sleeps == [7.0]


def test_primary_rate_limit_waits_until_reset_and_429_is_retried() -> None:
    exhausted = HttpResponse(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1012"}, b"{}")
    too_many = HttpResponse(429, {"retry-after": "2"}, b"{}")
    gh, _, sleeps = client({"GET /issues/3": [exhausted, too_many, ok(issue_json(3))]})
    gh.get_issue(3)
    assert sleeps == [12.0, 2.0]


def test_rate_limit_longer_than_the_wait_cap_raises_instead_of_sleeping() -> None:
    gh, _, sleeps = client({"GET /issues/3": HttpResponse(429, {"retry-after": "600"}, b"{}")})
    with pytest.raises(GitHubError) as exc:
        gh.get_issue(3)
    assert exc.value.status == 429 and sleeps == [] and TOKEN not in str(exc.value)


def test_rate_limit_retries_are_bounded() -> None:
    gh, _, sleeps = client({"GET /issues/3": HttpResponse(403, {"retry-after": "1"}, b"{}")}, max_retries=2)
    with pytest.raises(GitHubError, match="rate limited"):
        gh.get_issue(3)
    assert sleeps == [1.0, 1.0]


def test_forbidden_without_rate_limit_headers_fails_fast() -> None:
    gh, _, sleeps = client({"GET /issues/3": HttpResponse(403, {}, b'{"message":"Resource not accessible"}')})
    with pytest.raises(GitHubError, match="Resource not accessible"):
        gh.get_issue(3)
    assert sleeps == []


def test_server_errors_back_off_exponentially() -> None:
    gh, _, sleeps = client({"GET /issues/3": [HttpResponse(502, {}, b"bad gateway"),
                                              HttpResponse(503, {}, b""), ok(issue_json(3))]})
    gh.get_issue(3)
    assert sleeps == [1.0, 2.0]


def test_labels_comments_and_issue_writes() -> None:
    gh, transport, _ = client({
        "POST /issues/3/labels": ok([]),
        "DELETE /issues/3/labels/stage%3Aready": HttpResponse(404, {}, b"{}"),
        "GET /issues/3/comments?per_page=100&page=1": ok([{"id": 9, "user": {"login": "x"}, "body": "hi",
                                                           "created_at": "2026-10-10T12:00:00Z"}]),
        "POST /issues/3/comments": ok({"id": 10, "user": {"login": "stevengonsalvez"}, "body": "b",
                                       "created_at": "2026-10-10T12:00:00Z"}, 201),
        "PATCH /issues/comments/10": ok({}),
        "PATCH /issues/3": ok({}),
    })
    gh.add_labels(3, ("stage:ready",))
    gh.add_labels(3, ())
    gh.remove_label(3, "stage:ready")
    assert gh.list_comments(3)[0].author == "x"
    assert gh.create_comment(3, "b").id == 10
    gh.update_comment(10, "c")
    gh.close_issue(3)
    bodies = [json.loads(r.body) for r in transport.requests if r.body]
    assert bodies == [{"labels": ["stage:ready"]}, {"body": "b"}, {"body": "c"}, {"state": "closed"}]


def test_pull_requests_diff_commits_and_merge() -> None:
    gh, transport, _ = client({
        "GET /pulls?state=open&per_page=100&page=1": ok([pull_json(5, merged_at="2026-10-10T13:00:00Z")]),
        "GET /pulls/5": [ok(pull_json(5)), HttpResponse(200, {}, b"diff --git a/x b/x")],
        "GET /pulls/5/commits?per_page=100&page=1": ok([{"sha": "c1", "commit": {"message": "test: a"}}]),
        "GET /commits/c1": ok({"files": [{"filename": "app/web/a.test.tsx"}]}),
        "POST /pulls": ok(pull_json(6), 201),
        "GET /pulls/5/files?per_page=100&page=1": ok([{"filename": "app/a.ts"},
                                                      {"filename": "app/b.ts", "previous_filename": ".github/x.yml"}]),
        "PUT /pulls/5/merge": ok({"sha": "m" * 40, "merged": True}),
    })
    assert gh.list_pulls()[0].merged
    pr = gh.get_pull(5)
    assert pr.head_ref == "agent/issue-1" and pr.head_sha == "a" * 40 and not pr.merged
    assert gh.get_pull_diff(5).startswith("diff --git")
    assert transport.requests[2].headers["Accept"] == "application/vnd.github.diff"
    assert gh.list_pull_commits(5)[0].files == ("app/web/a.test.tsx",)
    assert gh.list_pull_files(5) == ["app/a.ts", "app/b.ts", ".github/x.yml"]
    assert gh.create_pull(title="t", head="h", base="main", body="b").number == 6
    assert gh.merge_pull(5, sha="a" * 40) == "m" * 40
    assert json.loads(transport.requests[-1].body) == {"sha": "a" * 40, "merge_method": "merge"}


def test_merge_conflict_surfaces_as_github_error() -> None:
    gh, _, _ = client({"PUT /pulls/5/merge": HttpResponse(409, {}, b'{"message":"Head branch was modified"}')})
    with pytest.raises(GitHubError) as exc:
        gh.merge_pull(5, sha="a" * 40)
    assert exc.value.status == 409


def test_check_runs_and_log_download_without_forwarding_the_token() -> None:
    runs = {"check_runs": [{"id": 77, "name": "test", "status": "completed", "conclusion": "failure",
                            "completed_at": "2026-10-10T12:00:00Z", "output": {"summary": "1 failed"},
                            "pull_requests": [{"number": 5}]}]}
    blob = "https://pipelines.example.blob.core.windows.net/logs/77?sig=abc"
    gh, transport, _ = client({
        "GET /commits/abc/check-runs?filter=all&per_page=100&page=1": ok(runs),
        "GET /commits/abc/check-runs?check_name=test&filter=latest": ok(runs),
        "GET /actions/jobs/77/logs": HttpResponse(302, {"location": blob}, b""),
        f"GET {blob}": HttpResponse(200, {}, b"x" * 70_000 + b"FAIL Home.test.tsx"),
    })
    run = gh.get_check_runs("abc")[0]
    assert run.conclusion == "failure" and run.pull_requests == (5,)
    log = gh.get_check_log("abc", "test")
    assert log.endswith("FAIL Home.test.tsx") and len(log) == 60_000
    blob_request = transport.requests[-1]
    assert blob_request.url == blob and "Authorization" not in blob_request.headers


def test_check_log_falls_back_to_the_check_output_and_handles_absent_runs() -> None:
    runs = {"check_runs": [{"id": 8, "name": "test", "status": "completed", "conclusion": "failure",
                            "output": {"summary": "1 failed", "text": "expected heading"}}]}
    gh, _, _ = client({
        "GET /commits/abc/check-runs?check_name=test&filter=latest": ok(runs),
        "GET /commits/def/check-runs?check_name=test&filter=latest": ok({"check_runs": []}),
        "GET /actions/jobs/8/logs": HttpResponse(410, {}, b""),
    })
    assert gh.get_check_log("abc", "test") == "1 failed\nexpected heading"
    assert gh.get_check_log("def", "test") == ""


def test_check_log_returned_directly_and_blob_failure_falls_back() -> None:
    runs = {"check_runs": [{"id": 8, "name": "test", "status": "completed", "conclusion": "failure", "output": {}}]}
    blob = "https://blob.example/logs"
    gh, _, _ = client({
        "GET /commits/a/check-runs?check_name=test&filter=latest": ok(runs),
        "GET /commits/b/check-runs?check_name=test&filter=latest": ok(runs),
        "GET /actions/jobs/8/logs": [HttpResponse(200, {}, b"direct log"), HttpResponse(302, {"location": blob}, b"")],
        f"GET {blob}": HttpResponse(403, {}, b""),
    })
    assert gh.get_check_log("a", "test") == "direct log"
    assert gh.get_check_log("b", "test") == ""


def test_contents_read_and_create_or_update() -> None:
    encoded = base64.b64encode(b'{"v": 1}').decode()
    gh, transport, _ = client({
        "GET /contents/metrics.json?ref=metrics": [ok({"type": "file", "content": encoded, "sha": "s1"}),
                                                   ok({"type": "file", "content": encoded, "sha": "s1"}),
                                                   HttpResponse(404, {}, b"{}")],
        "GET /contents/app?ref=main": ok([{"name": "x"}]),
        "PUT /contents/metrics.json": ok({}, 201),
    })
    assert gh.get_file("metrics.json", ref="metrics") == '{"v": 1}'
    assert gh.get_file("app", ref="main") is None
    gh.put_file("metrics.json", "new", branch="metrics", message="m")
    gh.put_file("metrics.json", "first", branch="metrics", message="m")
    updates = [json.loads(r.body) for r in transport.requests if r.method == "PUT"]
    assert updates[0]["sha"] == "s1" and "sha" not in updates[1]
    assert base64.b64decode(updates[1]["content"]) == b"first" and updates[1]["branch"] == "metrics"


def test_contents_errors_raise() -> None:
    gh, _, _ = client({"GET /contents/a?ref=main": HttpResponse(500, {}, b"{}")}, max_retries=0)
    with pytest.raises(GitHubError):
        gh.get_file("a", ref="main")
    gh2, _, _ = client({"GET /contents/a?ref=b": HttpResponse(403, {}, b"{}")})
    with pytest.raises(GitHubError):
        gh2.put_file("a", "x", branch="b", message="m")


def test_refs_commits_and_lock_primitives() -> None:
    gh, transport, _ = client({
        "GET /git/ref/heads/main": ok({"object": {"sha": "m1"}}),
        "GET /git/ref/heads/missing": HttpResponse(404, {}, b"{}"),
        "GET /git/ref/heads/sdlc-lock": ok({"object": {"sha": "l1"}}),
        "GET /git/commits/l1": ok({"committer": {"date": "2026-10-10T12:00:00Z"}}),
        "GET /git/commits/m1": ok({"tree": {"sha": "t1"}}),
        "POST /git/commits": ok({"sha": "c9"}, 201),
        "POST /git/refs": [ok({}, 201), HttpResponse(422, {}, b'{"message":"Reference already exists"}')],
        "DELETE /git/refs/heads/sdlc-lock": HttpResponse(204, {}, b""),
    })
    assert gh.get_branch_sha("main") == "m1" and gh.get_branch_sha("missing") is None
    assert gh.branch_commit_time("sdlc-lock") == "2026-10-10T12:00:00Z"
    assert gh.create_commit("lock", parent_sha="m1") == "c9"
    commit_body = json.loads(next(r.body for r in transport.requests if r.url.endswith("/git/commits")))
    assert commit_body == {"message": "lock", "tree": "t1", "parents": ["m1"]}
    gh.create_branch("sdlc-lock", from_sha="c9")
    with pytest.raises(GitHubError) as exc:
        gh.create_branch("sdlc-lock", from_sha="c9")
    assert exc.value.status == 422
    gh.delete_branch("sdlc-lock")


def test_branch_commit_time_of_a_missing_branch_is_none_and_ref_errors_raise() -> None:
    gh, _, _ = client({"GET /git/ref/heads/x": [HttpResponse(404, {}, b"{}"), HttpResponse(401, {}, b"{}")]})
    assert gh.branch_commit_time("x") is None
    with pytest.raises(GitHubError):
        gh.get_branch_sha("x")


def test_tags_releases_and_workflow_dispatch() -> None:
    gh, transport, _ = client({
        "GET /tags?per_page=100&page=1": ok([{"name": "v0.1.0"}]),
        "GET /git/trees/main?recursive=1": ok({"tree": [{"path": "app", "type": "tree"},
                                                        {"path": "app/a.ts", "type": "blob"}], "truncated": False}),
        "POST /releases": ok({"html_url": "https://github.com/r/releases/tag/v0.2.0"}, 201),
        "POST /actions/workflows/pages.yml/dispatches": HttpResponse(204, {}, b""),
    })
    assert gh.list_tags() == ["v0.1.0"]
    assert gh.list_tree("main") == ["app/a.ts"]
    assert gh.create_release(tag="v0.2.0", target_sha="m", name="n", body="b").endswith("v0.2.0")
    gh.dispatch_workflow("pages.yml", ref="main")
    assert json.loads(transport.requests[-1].body) == {"ref": "main"}


def test_paginate_raises_on_error_and_non_json_error_bodies_are_reported() -> None:
    gh, _, _ = client({"GET /tags?per_page=100&page=1": HttpResponse(404, {}, b"not json at all")})
    with pytest.raises(GitHubError, match="not json at all"):
        gh.list_tags()


def test_rate_limit_with_unparseable_retry_after_uses_the_cap() -> None:
    gh, _, sleeps = client({"GET /issues/3": [HttpResponse(429, {"retry-after": "soon"}, b"{}"), ok(issue_json(3))]})
    gh.get_issue(3)
    assert sleeps == [30.0]


def test_issue_maps_updated_at() -> None:
    item = issue_json(3, updated_at="2026-10-10T12:05:00Z")
    issue = _issue(item)
    assert issue.updated_at == "2026-10-10T12:05:00Z"
