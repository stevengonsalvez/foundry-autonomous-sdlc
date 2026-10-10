"""
GitHub REST adapter for GitHubPort (stdlib urllib through an injectable transport).

- Hard-scoped to REPO: the constructor refuses any other repository and every URL is built from it.
  Pagination never follows server-supplied URLs; pages are requested by number.
- Rate limits: 429, or 403 with Retry-After or x-ratelimit-remaining 0, waits and retries up to
  max_retries when the wait is at most max_wait_s; longer waits raise GitHubError so the tick moves
  on instead of sleeping through its budget. 5xx on reads and deletes retries with exponential
  backoff; 5xx on writes is not retried (the write may have happened).
- The token is sent only to api.github.com, never logged, never in an error message, and never
  forwarded on a redirect (the log download redirect goes to blob storage without it).
"""

from __future__ import annotations

import base64
import json
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from sdlc_agents.ports import REPO, CheckRun, Comment, GitHubError, Issue, PullCommit, PullRequest
from sdlc_agents.transport import HttpRequest, HttpResponse, Transport, urllib_transport

API = "https://api.github.com"
PER_PAGE = 100
MAX_PAGES = 20
LOG_TAIL_CHARS = 60_000
_JSON = "application/vnd.github+json"
# A 5xx on a write may still have taken effect (a comment posted, a PR merged), so only reads and
# deletes are retried; writes surface the error and the next tick re-reads before acting.
_RETRY_ON_5XX = frozenset({"GET", "DELETE"})


def _q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _labels(item: dict[str, Any]) -> tuple[str, ...]:
    return tuple(label["name"] for label in item.get("labels") or [])


def _issue(item: dict[str, Any]) -> Issue:
    return Issue(
        number=item["number"], title=item.get("title") or "", body=item.get("body") or "",
        author=(item.get("user") or {}).get("login", ""), labels=_labels(item), state=item["state"],
        created_at=item["created_at"], closed_at=item.get("closed_at"),
        is_pull_request="pull_request" in item,
    )


def _pull(item: dict[str, Any]) -> PullRequest:
    return PullRequest(
        number=item["number"], title=item.get("title") or "", body=item.get("body") or "",
        author=(item.get("user") or {}).get("login", ""), labels=_labels(item), state=item["state"],
        merged=bool(item.get("merged") or item.get("merged_at")),
        head_ref=item["head"]["ref"], head_sha=item["head"]["sha"], base_ref=item["base"]["ref"],
        created_at=item["created_at"], merged_at=item.get("merged_at"),
        merge_commit_sha=item.get("merge_commit_sha"),
        head_repo=((item["head"].get("repo") or {}).get("full_name") or "") if "repo" in item["head"] else REPO,
    )


def _comment(item: dict[str, Any]) -> Comment:
    return Comment(id=item["id"], author=(item.get("user") or {}).get("login", ""),
                   body=item.get("body") or "", created_at=item["created_at"])


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        repo: str = REPO,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
        max_retries: int = 3,
        max_wait_s: float = 30.0,
        timeout_s: float = 30.0,
    ):
        if repo != REPO:
            raise ValueError(f"this client only works on {REPO}, refusing {repo!r}")
        if not token:
            raise ValueError("a GitHub token is required")
        self._token = token
        self._transport = transport
        self._sleep = sleep
        self._now = now
        self._max_retries = max_retries
        self._max_wait_s = max_wait_s
        self._timeout_s = timeout_s
        self._base = f"{API}/repos/{REPO}"

    def __repr__(self) -> str:
        return f"GitHubClient({REPO})"

    # -- plumbing -------------------------------------------------------------

    def _rate_limit_wait(self, resp: HttpResponse) -> float | None:
        """Seconds to wait if the response is a rate limit, None if it is not one."""
        if resp.status not in (403, 429):
            return None
        retry_after = resp.headers.get("retry-after")
        if retry_after is not None:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                return self._max_wait_s
        if resp.headers.get("x-ratelimit-remaining") == "0":
            reset = float(resp.headers.get("x-ratelimit-reset", "0") or 0)
            return max(reset - self._now(), 1.0)
        return 60.0 if resp.status == 429 else None

    def _send(self, method: str, path: str, *, params: dict[str, Any] | None = None,
              body: Any = None, accept: str = _JSON) -> HttpResponse:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sdlc-orchestrator",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = HttpRequest(method, f"{self._base}{path}{query}", headers, data, self._timeout_s)
        attempt = 0
        while True:
            resp = self._transport(request)
            wait = self._rate_limit_wait(resp)
            if wait is not None:
                if attempt >= self._max_retries or wait > self._max_wait_s:
                    raise GitHubError(resp.status, f"{method} {path}: rate limited, retry after {int(wait)} s")
                self._sleep(wait)
            elif resp.status >= 500 and method in _RETRY_ON_5XX and attempt < self._max_retries:
                self._sleep(float(2**attempt))
            else:
                return resp
            attempt += 1

    def _call(self, method: str, path: str, *, ok: tuple[int, ...] = (200, 201), **kwargs: Any) -> Any:
        resp = self._send(method, path, **kwargs)
        if resp.status not in ok:
            raise GitHubError(resp.status, f"{method} {path}: {self._message(resp)}")
        if resp.status == 204 or not resp.body:
            return None
        return json.loads(resp.body)

    @staticmethod
    def _message(resp: HttpResponse) -> str:
        try:
            data = json.loads(resp.body)
            message = data.get("message", "") if isinstance(data, dict) else ""
        except ValueError:
            message = resp.text()
        return str(message)[:200]

    def _paginate(self, path: str, params: dict[str, Any] | None = None, *, key: str | None = None) -> list[Any]:
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            resp = self._send("GET", path, params={**(params or {}), "per_page": PER_PAGE, "page": page})
            if resp.status != 200:
                raise GitHubError(resp.status, f"GET {path}: {self._message(resp)}")
            data = json.loads(resp.body)
            batch = data[key] if key else data
            items.extend(batch)
            if 'rel="next"' not in resp.headers.get("link", "") or len(batch) < PER_PAGE:
                return items
        # Never return a silently shortened list: callers check every item (PR files, issues).
        raise GitHubError(422, f"GET {path}: more than {MAX_PAGES * PER_PAGE} items, refusing a partial list")

    # -- issues and comments --------------------------------------------------

    def list_issues(self, *, state: str = "open", labels: tuple[str, ...] = ()) -> list[Issue]:
        params: dict[str, Any] = {"state": state}
        if labels:
            params["labels"] = ",".join(labels)
        return [_issue(i) for i in self._paginate("/issues", params)]

    def get_issue(self, number: int) -> Issue:
        return _issue(self._call("GET", f"/issues/{number}"))

    def add_labels(self, number: int, labels: tuple[str, ...]) -> None:
        if labels:
            self._call("POST", f"/issues/{number}/labels", body={"labels": list(labels)})

    def remove_label(self, number: int, label: str) -> None:
        self._call("DELETE", f"/issues/{number}/labels/{_q(label)}", ok=(200, 204, 404))

    def list_comments(self, number: int) -> list[Comment]:
        return [_comment(c) for c in self._paginate(f"/issues/{number}/comments")]

    def create_comment(self, number: int, body: str) -> Comment:
        return _comment(self._call("POST", f"/issues/{number}/comments", body={"body": body}))

    def update_comment(self, comment_id: int, body: str) -> None:
        self._call("PATCH", f"/issues/comments/{comment_id}", body={"body": body})

    def close_issue(self, number: int) -> None:
        self._call("PATCH", f"/issues/{number}", body={"state": "closed"})

    # -- pull requests and checks ---------------------------------------------

    def list_pulls(self, *, state: str = "open") -> list[PullRequest]:
        return [_pull(p) for p in self._paginate("/pulls", {"state": state})]

    def get_pull(self, number: int) -> PullRequest:
        return _pull(self._call("GET", f"/pulls/{number}"))

    def get_pull_diff(self, number: int) -> str:
        resp = self._send("GET", f"/pulls/{number}", accept="application/vnd.github.diff")
        if resp.status != 200:
            raise GitHubError(resp.status, f"GET /pulls/{number} diff: {self._message(resp)}")
        return resp.text()

    def list_pull_commits(self, number: int) -> list[PullCommit]:
        commits = self._paginate(f"/pulls/{number}/commits")
        result: list[PullCommit] = []
        for item in commits:
            detail = self._call("GET", f"/commits/{item['sha']}")
            files = tuple(f["filename"] for f in detail.get("files") or [])
            result.append(PullCommit(sha=item["sha"], message=item["commit"]["message"], files=files))
        return result

    def list_pull_files(self, number: int) -> list[str]:
        files: list[str] = []
        for item in self._paginate(f"/pulls/{number}/files"):
            files.append(item["filename"])
            if item.get("previous_filename"):
                files.append(item["previous_filename"])
        return files

    def create_pull(self, *, title: str, head: str, base: str, body: str) -> PullRequest:
        return _pull(self._call("POST", "/pulls", body={"title": title, "head": head, "base": base, "body": body}))

    def merge_pull(self, number: int, *, sha: str, method: str = "merge") -> str:
        data = self._call("PUT", f"/pulls/{number}/merge", body={"sha": sha, "merge_method": method})
        return str(data["sha"])

    def get_check_runs(self, sha: str) -> list[CheckRun]:
        # filter=all: with `latest` a newer run of the same name from another context (a fork PR on
        # the same sha) would hide this PR's run. gates.check_summary picks the latest per PR.
        runs = self._paginate(f"/commits/{sha}/check-runs", {"filter": "all"}, key="check_runs")
        return [CheckRun(r["name"], r["status"], r.get("conclusion"), r.get("completed_at"),
                         tuple(p["number"] for p in r.get("pull_requests") or []))
                for r in runs]

    def get_check_log(self, sha: str, name: str) -> str:
        data = self._call("GET", f"/commits/{sha}/check-runs", params={"check_name": name, "filter": "latest"})
        runs = data.get("check_runs") or []
        if not runs:
            return ""
        run = runs[0]
        output = run.get("output") or {}
        fallback = "\n".join(filter(None, [output.get("summary"), output.get("text")]))
        resp = self._send("GET", f"/actions/jobs/{run['id']}/logs")
        if resp.status == 200:
            return resp.text()[-LOG_TAIL_CHARS:]
        location = resp.headers.get("location", "")
        if resp.status not in (301, 302, 303, 307) or not location.startswith("https://"):
            return fallback[-LOG_TAIL_CHARS:]
        # The signed blob URL carries its own credential: the GitHub token must not go there.
        blob = self._transport(HttpRequest("GET", location, {"User-Agent": "sdlc-orchestrator"}, None, self._timeout_s))
        if blob.status != 200:
            return fallback[-LOG_TAIL_CHARS:]
        return blob.text()[-LOG_TAIL_CHARS:]

    # -- contents, refs, commits ----------------------------------------------

    def get_file(self, path: str, *, ref: str) -> str | None:
        resp = self._send("GET", f"/contents/{urllib.parse.quote(path)}", params={"ref": ref})
        if resp.status == 404:
            return None
        if resp.status != 200:
            raise GitHubError(resp.status, f"GET contents {path}: {self._message(resp)}")
        data = json.loads(resp.body)
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        return base64.b64decode(data.get("content", "")).decode("utf-8")

    def list_tree(self, ref: str) -> list[str]:
        data = self._call("GET", f"/git/trees/{urllib.parse.quote(ref, safe='')}", params={"recursive": "1"})
        if data.get("truncated"):
            raise GitHubError(422, f"tree of {ref} is truncated by GitHub, refusing a partial listing")
        return [item["path"] for item in data.get("tree") or [] if item.get("type") == "blob"]

    def put_file(self, path: str, content: str, *, branch: str, message: str) -> None:
        resp = self._send("GET", f"/contents/{urllib.parse.quote(path)}", params={"ref": branch})
        body: dict[str, Any] = {
            "message": message, "branch": branch,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        }
        if resp.status == 200:
            body["sha"] = json.loads(resp.body)["sha"]
        elif resp.status != 404:
            raise GitHubError(resp.status, f"GET contents {path}: {self._message(resp)}")
        self._call("PUT", f"/contents/{urllib.parse.quote(path)}", body=body)

    def get_branch_sha(self, branch: str) -> str | None:
        resp = self._send("GET", f"/git/ref/heads/{urllib.parse.quote(branch)}")
        if resp.status == 404:
            return None
        if resp.status != 200:
            raise GitHubError(resp.status, f"GET ref {branch}: {self._message(resp)}")
        return str(json.loads(resp.body)["object"]["sha"])

    def create_branch(self, branch: str, *, from_sha: str) -> None:
        self._call("POST", "/git/refs", body={"ref": f"refs/heads/{branch}", "sha": from_sha})

    def delete_branch(self, branch: str) -> None:
        self._call("DELETE", f"/git/refs/heads/{urllib.parse.quote(branch)}", ok=(200, 204, 404, 422))

    def branch_commit_time(self, branch: str) -> str | None:
        sha = self.get_branch_sha(branch)
        if sha is None:
            return None
        return str(self._call("GET", f"/git/commits/{sha}")["committer"]["date"])

    def create_commit(self, message: str, *, parent_sha: str) -> str:
        tree = self._call("GET", f"/git/commits/{parent_sha}")["tree"]["sha"]
        data = self._call("POST", "/git/commits", body={"message": message, "tree": tree, "parents": [parent_sha]})
        return str(data["sha"])

    # -- releases and workflows -----------------------------------------------

    def list_tags(self) -> list[str]:
        return [t["name"] for t in self._paginate("/tags")]

    def create_release(self, *, tag: str, target_sha: str, name: str, body: str) -> str:
        data = self._call("POST", "/releases", body={
            "tag_name": tag, "target_commitish": target_sha, "name": name, "body": body,
        })
        return str(data["html_url"])

    def dispatch_workflow(self, workflow_file: str, *, ref: str) -> None:
        self._call("POST", f"/actions/workflows/{_q(workflow_file)}/dispatches", body={"ref": ref}, ok=(204,))
