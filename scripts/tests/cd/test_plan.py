from __future__ import annotations

import base64
import json

import pytest
from cd_helpers import sha

from scripts.cd import plan
from scripts.cd.deploy_state import Include
from scripts.cd.ghcli import GhError

REPO = "Owner/Repo"
OWNER = "Owner"


@pytest.mark.parametrize(
    ("body", "branch", "expected"),
    [
        ("Closes #12", None, 12),
        ("This fixes the thing.\n\ncloses #7 and more", "agent/issue-99", 7),
        ("Fixes: #5", None, 5),
        ("Resolved #8", None, 8),
        ("no keyword, mentions #44", None, None),
        ("no keyword", "agent/issue-31", 31),
        (None, "agent/issue-31-r2", 31),
        ("", "feature/issue-31", None),
        ("", "agent/issue-31; rm -rf /", None),
        ("Closes #abc", "agent/issue-3", 3),
        (None, None, None),
    ],
)
def test_parse_issue(body: str | None, branch: str | None, expected: int | None) -> None:
    assert plan.parse_issue(body, branch) == expected


def test_pick_version_takes_the_highest_release_tag_on_the_sha() -> None:
    assert (
        plan.pick_version(["v0.9.0", "v0.10.0", "prod/20261011-1", "latest"], "abc1234")
        == "v0.10.0"
    )
    assert plan.pick_version([], "abc1234") == "main-abc1234"
    assert (
        plan.pick_version(["v1", "vNext", "release-1.0.0", "v1.2.3-rc1"], "abc1234")
        == "main-abc1234"
    )


def test_select_pr_prefers_the_pr_whose_merge_commit_is_the_sha() -> None:
    prs = [
        {"number": 1, "merged_at": None, "merge_commit_sha": sha(1)},
        {"number": 2, "merged_at": "t", "merge_commit_sha": sha(9)},
        {"number": 3, "merged_at": "t", "merge_commit_sha": sha(1)},
    ]
    assert plan.select_pr(prs, sha(1))["number"] == 3
    assert plan.select_pr(prs[:2], sha(1))["number"] == 2
    assert plan.select_pr(prs[:1], sha(1)) is None
    assert plan.select_pr([], sha(1)) is None


def test_only_the_owners_pull_requests_steer_the_pipeline() -> None:
    prs = [
        {"number": 1, "merged_at": "t", "merge_commit_sha": sha(1), "user": {"login": "stranger"}},
        {"number": 2, "merged_at": "t", "merge_commit_sha": sha(1), "user": {"login": "Owner"}},
    ]
    assert plan.select_pr(prs, sha(1), "Owner")["number"] == 2
    assert plan.select_pr(prs[:1], sha(1), "Owner") is None
    assert plan.select_pr(prs[:1], sha(1))["number"] == 1  # no owner given: any merged PR


def test_an_issue_number_that_does_not_check_out_is_dropped() -> None:
    gh = FakeGitHub()
    gh.prs[sha(5)] = [pr(50, 5, "Closes #9001")]
    assert build(gh).issue is None  # 404
    gh.issues[600] = {"user": {"login": "stranger"}}
    gh.prs[sha(5)] = [pr(50, 5, "Closes #600")]
    assert build(gh).issue is None  # someone else's issue
    gh.issues[601] = {"user": {"login": "Owner"}, "pull_request": {}}
    gh.prs[sha(5)] = [pr(50, 5, "Closes #601")]
    assert build(gh).issue is None  # a pull request, not an issue
    gh.prs[sha(5)] = [{**pr(50, 5, "Closes #7"), "user": {"login": "stranger"}}]
    result = build(gh)
    assert (result.pr, result.issue) == (None, None)  # a stranger's PR is ignored entirely


def test_compute_includes_lists_merged_prs_oldest_first_and_skips_direct_commits() -> None:
    prs = {
        sha(3): {"number": 30, "body": "Closes #300", "head": {"ref": "x"}},
        sha(2): None,  # a commit pushed straight to main
        sha(1): {"number": 10, "body": "", "head": {"ref": "agent/issue-100"}},
    }
    includes = plan.compute_includes([sha(3), sha(2), sha(1)], prs.get)
    assert includes == [Include(10, 100, sha(1)), Include(30, 300, sha(3))]


def check(
    name: str,
    conclusion: str | None = "success",
    status: str = "completed",
    run_id: int = 1,
    app: str = "github-actions",
) -> dict:
    return {
        "id": run_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "app": {"slug": app},
    }


def green_checks() -> list[dict]:
    """The six required checks, green, and the optional CI jobs, one of them red."""
    required = [check(name, run_id=i) for i, name in enumerate(plan.REQUIRED_CHECKS, 1)]
    return [
        *required,
        check("gates-tests", "failure", run_id=50),
        check("agents", "failure", run_id=51),
    ]


class FakeGitHub:
    def __init__(self) -> None:
        self.head = sha(5)
        self.prod: str | None = None
        self.prs: dict[str, list[dict]] = {}
        self.tags: list[dict] = []
        self.tag_appears_after: int | None = None  # number of tag lookups before the tag exists
        self.compare_status = "ahead"
        self.calls: list[str] = []
        self.checks: dict[str, list[dict]] = {}  # sha -> check runs; unlisted shas are green
        self.issues: dict[int, dict] = {}  # number -> issue json; unlisted numbers are owner issues

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        path = args[1]
        self.calls.append(path)
        prefix = f"repos/{REPO}/"
        assert path.startswith(prefix), path
        rest = path.removeprefix(prefix)
        if rest.startswith("commits/") and rest.endswith("/pulls"):
            return json.dumps(self.prs.get(rest.split("/")[1], []))
        if rest.startswith("commits/") and "/check-runs" in rest:
            assert "filter=latest" in rest
            return json.dumps({"check_runs": self.checks.get(rest.split("/")[1], green_checks())})
        if rest.startswith("commits/"):
            ref = rest.split("/")[1]
            return json.dumps({"sha": self.head if ref == "main" else ref.ljust(40, "0")})
        if rest.startswith("issues/"):
            number = int(rest.split("/")[1])
            if number not in self.issues and number >= 9000:
                raise GhError(args, "gh: Not Found (HTTP 404)")
            return json.dumps(self.issues.get(number, {"user": {"login": OWNER}}))
        if rest.startswith("compare/"):
            return json.dumps({"status": self.compare_status})
        if rest.startswith("tags"):
            if self.tag_appears_after is not None:
                self.tag_appears_after -= 1
                if self.tag_appears_after >= 0:
                    return "[]"
            return json.dumps(self.tags)
        if rest.startswith("contents/deploy.json"):
            if self.prod is None:
                raise GhError(args, "gh: Not Found (HTTP 404)")
            doc = json.dumps({"prod": {"sha": self.prod}}).encode()
            return json.dumps({"content": base64.b64encode(doc).decode()})
        raise AssertionError(path)


def pr(number: int, sha_n: int, body: str = "", branch: str = "x") -> dict:
    return {
        "number": number,
        "merged_at": "t",
        "merge_commit_sha": sha(sha_n),
        "body": body,
        "head": {"ref": branch},
        "user": {"login": OWNER},
    }


def build(gh: FakeGitHub, **kwargs):
    params = {
        "repo": REPO,
        "event": "workflow_run",
        "requested_sha": gh.head,
        "sleep": lambda _s: None,
        "git_log": lambda prod, sha_: [sha_],
    }
    params.update(kwargs)
    return plan.build_plan(gh, **params)


def test_a_normal_merge_gets_its_pr_issue_version_and_own_include() -> None:
    gh = FakeGitHub()
    gh.prs[sha(5)] = [pr(50, 5, "Closes #500")]
    gh.tags = [
        {"name": "v0.4.0", "commit": {"sha": sha(5)}},
        {"name": "v0.3.0", "commit": {"sha": sha(4)}},
    ]
    result = build(gh)
    assert (result.sha, result.short, result.version) == (sha(5), sha(5)[:7], "v0.4.0")
    assert (result.pr, result.issue, result.proceed) == (50, 500, True)
    assert result.includes == [Include(50, 500, sha(5))]


def test_includes_cover_every_merge_since_the_sha_prod_runs() -> None:
    gh = FakeGitHub()
    gh.prod = sha(2)
    gh.prs = {
        sha(5): [pr(50, 5, "Closes #500")],
        sha(4): [pr(40, 4, "", "agent/issue-400")],
        sha(3): [pr(30, 3, "Closes #300")],
    }
    seen: list[tuple[str, str]] = []

    def git_log(prod: str, head: str) -> list[str]:
        seen.append((prod, head))
        return [sha(5), sha(4), sha(3)]

    result = build(gh, git_log=git_log)
    assert seen == [(sha(2), sha(5))]
    assert result.includes == [
        Include(30, 300, sha(3)),
        Include(40, 400, sha(4)),
        Include(50, 500, sha(5)),
    ]
    assert result.pr == 50


def test_with_nothing_in_prod_includes_is_only_this_shas_own_pr() -> None:
    gh = FakeGitHub()
    gh.prs[sha(5)] = [pr(50, 5)]
    result = build(gh, git_log=lambda *_: pytest.fail("no git log expected"))
    assert result.includes == [Include(50, None, sha(5))]


def test_a_sha_without_a_pr_has_no_pr_issue_or_includes() -> None:
    result = build(FakeGitHub())
    assert (result.pr, result.issue, result.includes) == (None, None, [])


def test_the_tag_is_retried_until_the_orchestrator_has_created_it() -> None:
    gh = FakeGitHub()
    gh.tags = [{"name": "v0.4.0", "commit": {"sha": sha(5)}}]
    gh.tag_appears_after = 3
    sleeps: list[float] = []
    result = build(gh, sleep=sleeps.append)
    assert result.version == "v0.4.0" and sleeps == [15, 15, 15]


def test_without_a_tag_the_version_falls_back_after_a_bounded_wait() -> None:
    sleeps: list[float] = []
    result = build(FakeGitHub(), sleep=sleeps.append)
    assert result.version == f"main-{sha(5)[:7]}" and len(sleeps) == plan.TAG_RETRIES


def test_an_older_sha_is_not_retried_for_a_tag() -> None:
    gh = FakeGitHub()
    sleeps: list[float] = []
    result = build(gh, event="workflow_dispatch", requested_sha=sha(3), sleep=sleeps.append)
    assert result.proceed and sleeps == []


def test_a_ci_run_for_a_sha_that_is_no_longer_main_head_does_not_proceed() -> None:
    gh = FakeGitHub()
    result = build(gh, requested_sha=sha(3))
    assert not result.proceed and "main has moved on" in result.reason


def test_a_dispatched_older_sha_proceeds_when_it_is_on_main() -> None:
    result = build(FakeGitHub(), event="workflow_dispatch", requested_sha=sha(3))
    assert result.proceed and result.sha == sha(3)


def test_a_sha_that_is_not_on_main_is_refused() -> None:
    gh = FakeGitHub()
    gh.compare_status = "diverged"
    with pytest.raises(ValueError, match="not on main"):
        build(gh, event="workflow_dispatch", requested_sha=sha(3))


@pytest.mark.parametrize("bad", ["../../etc", "abc; rm -rf /", "HEAD~1", "x" * 40, "$(id)"])
def test_a_malformed_sha_input_never_reaches_the_api(bad: str) -> None:
    gh = FakeGitHub()
    with pytest.raises(ValueError, match="not a commit sha"):
        build(gh, event="workflow_dispatch", requested_sha=bad)
    assert not any(bad in call for call in gh.calls)


def test_empty_input_means_main_head() -> None:
    gh = FakeGitHub()
    assert build(gh, event="workflow_dispatch", requested_sha="").sha == gh.head


def test_failed_job_reports_the_first_failure_in_pipeline_order() -> None:
    needs = {
        "plan": {"result": "success"},
        "build": {"result": "success"},
        "stage": {"result": "success"},
        "smoke": {"result": "failure"},
        "soak": {"result": "skipped"},
        "promote": {"result": "skipped"},
    }
    assert plan.failed_job(needs) == "smoke"
    needs["stage"] = {"result": "failure"}
    assert plan.failed_job(needs) == "stage"
    assert plan.failed_job({"plan": {"result": "failure"}}) is None


def test_failed_job_cli_reads_the_needs_json_from_the_environment(monkeypatch, tmp_path) -> None:
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("NEEDS_JSON", json.dumps({"soak": {"result": "failure"}}))
    assert plan.main(["failed-job"]) == 0
    assert out.read_text() == "job=soak\n"


def test_resolve_cli_writes_only_safe_outputs(monkeypatch, tmp_path) -> None:
    gh = FakeGitHub()
    # an attacker controls the PR title, body and branch: none of it may reach an output
    gh.prs[sha(5)] = [pr(50, 5, "Closes #500\n$(curl evil)", "agent/issue-500\nmalicious=1")]
    gh.tags = [{"name": "v0.4.0", "commit": {"sha": sha(5)}}]
    out = tmp_path / "out"
    for key, value in {
        "GITHUB_OUTPUT": str(out),
        "REPO": REPO,
        "EVENT_NAME": "workflow_run",
        "RUN_SHA": gh.head,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SHA_INPUT", raising=False)
    monkeypatch.setattr(plan, "first_parent_shas", lambda prod, head: [head])
    assert plan.main(["resolve"], gh) == 0
    lines = out.read_text().splitlines()
    outputs = dict(line.split("=", 1) for line in lines)
    assert len(lines) == len(outputs) == 10
    assert outputs["issue"] == "500" and outputs["pr"] == "50" and outputs["version"] == "v0.4.0"
    assert outputs["staging_url"] == "https://owner.github.io/Repo/staging/"
    assert outputs["prod_url"] == "https://owner.github.io/Repo/"
    assert json.loads(outputs["includes"]) == [{"pr": 50, "issue": 500, "sha": sha(5)}]
    assert "evil" not in out.read_text() and "malicious" not in out.read_text()


def test_resolve_cli_fails_cleanly_for_a_bad_sha(monkeypatch, tmp_path, capsys) -> None:
    for key, value in {
        "GITHUB_OUTPUT": str(tmp_path / "o"),
        "REPO": REPO,
        "EVENT_NAME": "workflow_dispatch",
        "SHA_INPUT": "nope!",
    }.items():
        monkeypatch.setenv(key, value)
    assert plan.main(["resolve"], FakeGitHub()) == 1
    assert "not a commit sha" in capsys.readouterr().err


def test_first_parent_shas_uses_real_git(tmp_path, monkeypatch) -> None:
    import subprocess

    def g(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    g("init", "-q", "-b", "main")
    g("commit", "-q", "--allow-empty", "-m", "base")
    base = g("rev-parse", "HEAD")
    shas = []
    for i in range(3):
        g("checkout", "-q", "-b", f"f{i}")
        g("commit", "-q", "--allow-empty", "-m", f"work {i}")
        g("checkout", "-q", "main")
        g("merge", "-q", "--no-ff", "-m", f"merge {i}", f"f{i}")
        shas.append(g("rev-parse", "HEAD"))
    monkeypatch.chdir(tmp_path)
    assert plan.first_parent_shas(base, shas[2]) == [shas[2], shas[1], shas[0]]  # no branch commits
    assert plan.first_parent_shas(shas[0], shas[2]) == [shas[2], shas[1]]
    assert plan.first_parent_shas("f" * 40, shas[2]) == [shas[2]]  # prod unknown to this clone


def test_the_run_summary_says_what_will_be_deployed_or_why_not(monkeypatch, tmp_path) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    gh = FakeGitHub()
    gh.prs[sha(5)] = [pr(50, 5)]
    gh.tags = [{"name": "v0.4.0", "commit": {"sha": sha(5)}}]
    plan.write_summary(build(gh))
    assert "deploying `v0.4.0`" in summary.read_text() and "#50" in summary.read_text()
    summary.write_text("")
    plan.write_summary(build(FakeGitHub(), requested_sha=sha(3)))
    assert "main has moved on" in summary.read_text()


@pytest.mark.parametrize("minutes", ["31", "-1", "ten", "nan"])
def test_a_bad_soak_time_fails_the_plan_before_anything_is_staged(
    minutes: str, monkeypatch, tmp_path, capsys
) -> None:
    for key, value in {
        "GITHUB_OUTPUT": str(tmp_path / "o"),
        "REPO": REPO,
        "EVENT_NAME": "workflow_dispatch",
        "SOAK_MINUTES": minutes,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("SHA_INPUT", raising=False)
    assert plan.main(["resolve"], FakeGitHub()) == 1
    assert capsys.readouterr().err.startswith("error:")
    assert not (tmp_path / "o").exists()


class TestRequiredChecks:
    """CD waits for the six required checks, not for the CI workflow as a whole."""

    def test_the_list_is_the_one_the_ruleset_requires(self) -> None:
        from scripts import setup_repo

        assert plan.REQUIRED_CHECKS == setup_repo.REQUIRED_CHECKS

    def test_an_optional_job_going_red_does_not_block_a_release(self) -> None:
        gh = FakeGitHub()  # gates-tests and agents are red in green_checks()
        assert build(gh).proceed

    @pytest.mark.parametrize("name", plan.REQUIRED_CHECKS)
    def test_a_missing_required_check_blocks_it_with_a_clear_reason(self, name: str) -> None:
        gh = FakeGitHub()
        gh.checks[gh.head] = [c for c in green_checks() if c["name"] != name]
        result = build(gh)
        assert not result.proceed
        assert result.reason == f"required checks are not green: {name}=missing"

    @pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", None])
    def test_a_required_check_that_did_not_succeed_blocks_it(self, conclusion) -> None:
        gh = FakeGitHub()
        gh.checks[gh.head] = [
            check("e2e", conclusion) if c["name"] == "e2e" else c for c in green_checks()
        ]
        result = build(gh)
        assert not result.proceed and f"e2e={conclusion}" in result.reason

    def test_a_check_that_is_still_running_blocks_it(self) -> None:
        gh = FakeGitHub()
        gh.checks[gh.head] = [
            check("coverage", None, status="in_progress") if c["name"] == "coverage" else c
            for c in green_checks()
        ]
        assert "coverage=in_progress" in build(gh).reason

    def test_every_problem_is_listed_in_pipeline_order(self) -> None:
        gh = FakeGitHub()
        gh.checks[gh.head] = [check("test"), check("gitleaks", "failure")]
        assert build(gh).reason == (
            "required checks are not green: coverage=missing, e2e=missing, "
            "gitleaks=failure, tdd-order=missing, agent-scope=missing"
        )

    def test_the_newest_attempt_of_a_check_decides(self) -> None:
        others = [c for c in green_checks() if c["name"] != "test"]
        gh = FakeGitHub()
        gh.checks[gh.head] = [
            check("test", "failure", run_id=10),
            check("test", run_id=20),
            *others,
        ]
        assert build(gh).proceed  # a rerun went green after the red attempt
        gh.checks[gh.head] = [
            check("test", run_id=10),
            check("test", "failure", run_id=20),
            *others,
        ]
        assert not build(gh).proceed  # a newer red attempt blocks

    def test_a_check_from_another_app_cannot_stand_in_for_a_required_one(self) -> None:
        gh = FakeGitHub()
        gh.checks[gh.head] = [
            check("e2e", app="some-other-app") if c["name"] == "e2e" else c for c in green_checks()
        ]
        assert "e2e=success" not in build(gh).reason and "e2e=missing" in build(gh).reason

    def test_a_manual_run_needs_the_same_checks(self) -> None:
        gh = FakeGitHub()
        gh.checks[sha(3)] = [check("test")]
        result = build(gh, event="workflow_dispatch", requested_sha=sha(3))
        assert not result.proceed and "coverage=missing" in result.reason

    def test_a_manual_run_of_the_sha_prod_already_runs_needs_no_checks(self) -> None:
        gh = FakeGitHub()
        gh.prod = sha(3)
        gh.checks[sha(3)] = []
        result = build(gh, event="workflow_dispatch", requested_sha=sha(3))
        assert result.proceed

    def test_a_blocked_run_does_not_wait_for_a_tag(self) -> None:
        gh = FakeGitHub()
        gh.checks[gh.head] = []
        sleeps: list[float] = []
        result = build(gh, sleep=sleeps.append)
        assert not result.proceed and sleeps == []

    def test_the_summary_says_which_checks_blocked_the_release(self, monkeypatch, tmp_path) -> None:
        summary = tmp_path / "s.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
        gh = FakeGitHub()
        gh.checks[gh.head] = [check("test")]
        plan.write_summary(build(gh))
        assert "CD skipped" in summary.read_text() and "coverage=missing" in summary.read_text()
