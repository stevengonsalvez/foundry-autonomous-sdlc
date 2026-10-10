"""
The coder end to end: a real bare git remote, a node-free fake vitest, scripted engines.

Each test drives the Invocations-level service (start, status, cancel) exactly as the
orchestrator does and asserts on what landed in the remote, the PR and the log.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from sdlc_agents.coder import runner as runner_mod
from sdlc_agents.coder import shell
from sdlc_agents.coder.engines import Usage
from sdlc_agents.coder.git_adapter import SubprocessGit
from sdlc_agents.coder.job import JobSpec, JobState, JobStore, Redactor
from sdlc_agents.coder.runner import AGY_LOG_LINES, CoderDeps, CoderService, EngineContext
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.coder.toolchain import AGY_SETTINGS_BYTES
from sdlc_agents.ports import REPO, CommandResult, GitHubError, PullRequest

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
    if "REFERENCE_ERROR" in lines:
        results.append({{"name": str(f), "status": "failed", "message": "", "assertionResults": [
            {{"fullName": "uses expect", "status": "failed",
             "failureMessages": ["ReferenceError: expect is not defined\\n    at x.test.ts:3:5"]}}]}})
        continue
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
                        "failureMessages": [] if ok else
                            [f"AssertionError: expected {{m.group(2)!r}} got {{actual!r}}"]}})
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

# `npm run typecheck` and `npm run lint` as CI runs them in app/: a line "TYPE_ERROR <msg>" in any file
# is a tsc error (path relative to its workspace, like `npm run typecheck --workspaces`), "LINT_ERROR <msg>"
# an eslint error (stylish format, absolute path header). Installed as `npm` in the job's node bin.
FAKE_NPM = f"""#!{sys.executable}
import pathlib, sys
root = pathlib.Path.cwd()
script = sys.argv[1:]
marker = {{("run", "typecheck"): "TYPE_ERROR ", ("run", "lint"): "LINT_ERROR "}}.get(tuple(script))
if marker is None:
    print("fake npm: unexpected", script); sys.exit(1)
found = 0
for f in sorted(root.rglob("*")):
    if not f.is_file() or f.is_symlink():
        continue
    for no, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
        if not line.startswith(marker):
            continue
        found += 1
        rel = f.relative_to(root)
        if marker.startswith("TYPE"):
            ws = rel.parts[0] if len(rel.parts) > 1 else "."
            print(f"> @parcel/{{ws}}@0.1.0 typecheck")
            print(f"{{rel.relative_to(ws) if ws != '.' else rel}}({{no}},1): error TS2322: {{line[len(marker):]}}")
        else:
            print(f)
            print(f"  {{no}}:1  error  {{line[len(marker):]}}  no-restricted-syntax")
sys.exit((2 if marker.startswith("TYPE") else 1) if found else 0)
"""

# Install commands are plain words (JobSpec forbids shell syntax), so test behaviours live in scripts.
TOOLS = {
    "tools/noop.py": "",
    "tools/install_fail.py": "import sys\nprint('npm ERR! missing package')\nsys.exit(1)\n",
    "tools/dump_env.py": "import json, os, sys\nopen(sys.argv[1], 'w').write(json.dumps(dict(os.environ)))\n",
    "tools/plant_link.py": "import os\nos.symlink('/etc', 'web/src/escape')\n",
    "tools/plant_type_error.py": ("import os\nos.makedirs('node_modules/legacy', exist_ok=True)\n"
                                  "open('node_modules/legacy/index.d.ts', 'w').write('TYPE_ERROR legacy typing\\n')\n"),
    # The post-`npm ci` layout of this repo's app/ (cwd is app/): workspace links and a .bin link.
    "tools/npm_links.py": (
        "import os\n"
        "os.makedirs('node_modules/@parcel', exist_ok=True)\n"
        "for name in ('api', 'carrier-mock', 'contracts', 'core', 'e2e', 'web'):\n"
        "    os.makedirs(name, exist_ok=True)\n"
        "    os.symlink('../../' + name, 'node_modules/@parcel/' + name)\n"
        "os.makedirs('node_modules/vitest', exist_ok=True)\n"
        "open('node_modules/vitest/vitest.mjs', 'w').close()\n"
        "os.makedirs('node_modules/.bin', exist_ok=True)\n"
        "os.symlink('../vitest/vitest.mjs', 'node_modules/.bin/vitest')\n"
    ),
}

SEED = {
    ".gitignore": "node_modules/\n",
    "tools/fake_vitest.py": FAKE_VITEST,
    **TOOLS,
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
        self.branches: dict[str, str] = {"main": "base-sha"}

    def get_branch_sha(self, branch: str) -> str | None:
        return self.branches.get(branch)

    def create_branch(self, branch: str, *, from_sha: str) -> None:
        if branch in self.branches:
            raise GitHubError(422, "Reference already exists")
        self.branches[branch] = from_sha

    def delete_branch(self, branch: str) -> None:
        self.branches.pop(branch, None)

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
        self.settings_writes: list[tuple[Path | None, tuple[int, int] | None]] = []

    def env(self) -> dict[str, str]:
        return {"PATH": os.environ["PATH"], "HOME": str(self.home), "CI": "1"}

    def ensure_git(self) -> None: ...
    def ensure_node(self) -> None: ...
    def ensure_agy(self) -> Path:
        return self.agy_path

    def node_bin(self) -> Path:
        return self.home.parent / "shared-node/bin"

    def write_agy_settings(self, *, home: Path | None = None, owner: tuple[int, int] | None = None) -> Path:
        self.settings_writes.append((home, owner))
        path = (home or self.home) / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(AGY_SETTINGS_BYTES)
        path.chmod(0o600)
        return path

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
    last_timed_out: bool = False

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
    reaped: list[RunAs] = field(default_factory=list)

    @property
    def engine_user(self) -> RunAs:
        """The engine user, played by this test's own uid (only root can switch to another)."""
        return RunAs("agyuser", os.getuid(), os.getgid(), self.tmp / "agyuser-home")

    @property
    def checkout(self) -> Path:
        return self.tmp / "srv/j-12-1/checkout"

    def service(self) -> CoderService:
        home = self.tmp / "home"
        self.engine_user.home.mkdir(exist_ok=True)
        npm = FakeToolchain(home).node_bin() / "npm"
        npm.parent.mkdir(parents=True, exist_ok=True)
        npm.write_text(FAKE_NPM)
        npm.chmod(0o755)
        deps = CoderDeps(
            home=home,
            secrets=_Secrets({"github-pat": PAT, "agy-cli-token": AGY_TOKEN}),
            github=lambda pat: self.github,
            git=lambda author, cancel: SubprocessGit(author=author, remote_base=self.base_url, cancel=cancel),
            engines=self._engines,
            toolchain=FakeToolchain(home),
            clock=self.clock,
            owner_user_id=lambda pat: self.owner_id,
            engine_user=lambda: self.engine_user,
            privileged_work_root=self.tmp / "srv",
            agy_installer=lambda src: Path("/opt/agy/bin/agy"),
            reap=self._reap,   # the real one kills by uid, which here is this test's own
        )
        return CoderService(JobStore(home / "jobs", Redactor()), deps)

    def _reap(self, user: RunAs) -> int:
        self.reaped.append(user)
        return 0

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
    checkout = world.checkout
    assert PAT not in (checkout / ".git/config").read_text()


@pytest.mark.parametrize("test_content", [
    "expect web/src/eta.txt == none\n",          # already passes: not red
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
    checkout = world.checkout
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
    world.engines = [ScriptedEngine("agy-unrestricted", [{"app/web/src/eta.txt": "wrong 1\n"},
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


def test_interrupted_job_reports_interrupted_and_resumes_from_the_pushed_branch(world: World) -> None:
    entered, never = threading.Event(), threading.Event()

    def evicted(root: Path) -> None:   # the process vanishes mid-step: this thread never comes back
        entered.set()
        never.wait()

    world.engines = [ScriptedEngine("agy", [evicted])]
    first = world.service()
    start(first, job())
    assert entered.wait(30)
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
    start(service, job(install_cmd=f"{sys.executable} ../tools/install_fail.py"))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "install-failed"
    assert "npm ERR!" in status["detail"]


def test_agy_without_a_token_fails_the_job_instead_of_running_the_loop_alone(world: World) -> None:
    world.engines = [ScriptedEngine("loop", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    service._deps.secrets = _Secrets({"github-pat": PAT})
    start(service, job())
    status = wait(service, "j-12-1")
    assert (status["status"], status["phase"], status["reason"]) == ("failed", "setup", "engine-unavailable")
    assert "agy-cli-token" in status["detail"]
    assert [e["reason"] for e in status["engine_events"]] == ["agy-unavailable"]
    assert "agy-cli-token" in status["engine_events"][0]["detail"]
    assert world.engines[0].prompts == []
    assert git(world.remote_root / f"{REPO}.git", "branch", "--list", "agent/issue-12") == ""


def test_a_failed_agy_install_is_retried_once(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    tools = service._deps.toolchain
    attempts: list[int] = []

    def flaky() -> Path:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("agy installer did not produce agy: curl: (6) could not resolve host")
        return tools.agy_path

    tools.ensure_agy = flaky   # type: ignore[method-assign]
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert len(attempts) == 2
    assert "could not resolve host" in (world.tmp / "home/jobs/j-12-1/log").read_text()


def test_agy_still_missing_after_the_retry_names_the_step_and_redacts(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()

    def broken() -> Path:
        raise RuntimeError(f"agy installer did not produce agy: npm ERR! auth {PAT}")

    service._deps.toolchain.ensure_agy = broken   # type: ignore[method-assign]
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["reason"] == "engine-unavailable", status
    assert "install agy" in status["detail"] and "npm ERR!" in status["detail"]
    assert PAT not in json.dumps(status)


@pytest.mark.parametrize("error", [RuntimeError, SystemExit, KeyboardInterrupt])
def test_any_unexpected_exception_fails_the_job_as_internal_error_and_releases_the_lease(
        world: World, capsys: pytest.CaptureFixture[str], error: type[BaseException]) -> None:
    def boom(root: Path) -> None:
        raise error(f"disk full while using {PAT}")

    world.engines = [ScriptedEngine("agy", [boom])]
    service = world.service()
    start(service, job())
    assert "agent-lease/12" in world.github.branches
    status = wait(service, "j-12-1")
    assert (status["status"], status["reason"]) == ("failed", "internal-error"), status
    assert "Traceback" in status["detail"] and f"{error.__name__}: disk full" in status["detail"]
    assert "in boom" in status["detail"]
    assert PAT not in status["detail"]
    assert "agent-lease/12" not in world.github.branches            # released for the next attempt
    log = (world.tmp / "home/jobs/j-12-1/log").read_text()
    assert "Traceback" in log and PAT not in log
    printed = capsys.readouterr().out                                # the platform logstream
    assert "j-12-1" in printed and "Traceback" in printed and PAT not in printed
    assert service.handle({"op": "status", "job_id": "j-12-1"})[0] == 200    # the server still answers


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
    # A real edit (wrong value) plus a hidden one in an ignored dir that fakes every test green.
    world.engines = [ScriptedEngine("agy", [{"app/node_modules/FORCE_GREEN": "1", "app/web/src/eta.txt": "wrong\n"}])]
    service = world.service()
    start(service, job(max_iterations=1, install_cmd=f"{sys.executable} ../tools/noop.py"))
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
    world.engines = [ScriptedEngine("loop", [{}, {}])]
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
    del world.github.branches["agent-lease/14"]     # the orchestrator releases the lease on a terminal outcome
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
    installed: list[Path] = []
    reaped: list[RunAs] = []
    marker = world.tmp / "install-env.json"
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    service._deps.engine_user = lambda: user
    service._deps.privileged_work_root = world.tmp / "srv"
    service._deps.agy_installer = lambda src: installed.append(src) or Path("/opt/agy/bin/agy")
    service._deps.reap = lambda who: reaped.append(who) or 0    # the real one would kill this test's own uid
    start(service, job(install_cmd=f"{sys.executable} ../tools/dump_env.py {marker}"))
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert status["agy_user"] == "agyuser"
    assert status["tests_user"] == "agyuser"
    ctx = world.contexts[0]
    assert ctx.run_as == user
    assert ctx.agy_home == user.home
    assert ctx.agy_binary == Path("/opt/agy/bin/agy")
    assert installed == [world.tmp / "home/.local/bin/agy"]
    assert reaped
    assert set(reaped) == {user}
    assert service._deps.toolchain.token_writes == [(user.home, (user.uid, user.gid))]
    assert service._deps.toolchain.settings_writes == [(user.home, (user.uid, user.gid))]
    assert (world.tmp / "srv/j-12-1/checkout/.git").is_dir()
    env = json.loads(marker.read_text())
    assert env["HOME"] == str(user.home)
    assert env["PATH"].startswith(f"{world.tmp}/shared-node/bin:")
    assert PAT not in json.dumps(env)
    assert not {"IDENTITY_HEADER", "IDENTITY_ENDPOINT", "KEY_VAULT_URI"} & set(env)
    assert "Engine user: agyuser" in world.github.bodies[100]
    assert "Tests user: agyuser" in world.github.bodies[100]


def test_no_engine_user_means_no_job_never_a_root_fallback(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    service._deps.engine_user = lambda: None
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert status["reason"] == "sandbox-unavailable"
    assert world.engines[0].prompts == []
    assert not world.checkout.exists()
    assert git(world.remote_root / f"{REPO}.git", "branch", "--list", "agent/issue-12").strip() == ""


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
    start(service, job(install_cmd=f"{sys.executable} ../tools/plant_link.py"))
    status = wait(service, "j-12-1")
    assert status["reason"] == "scope-violation"
    assert "install created symlinks" in status["detail"]


def test_surviving_engine_user_processes_stop_the_job_before_root_touches_the_tree(world: World) -> None:
    user = RunAs("agyuser", os.getuid(), os.getgid(), world.tmp / "agyuser-home")
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    service._deps.engine_user = lambda: user
    service._deps.privileged_work_root = world.tmp / "srv"
    service._deps.agy_installer = lambda src: Path("/opt/agy/bin/agy")
    service._deps.reap = lambda who: 1                            # an unkillable process
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "failed"
    assert "survived SIGKILL" in status["detail"]
    assert git(world.remote_root / f"{REPO}.git", "branch", "--list", "agent/issue-12").strip() == ""


SOFT_DENY = ('jetski: no output produced - a tool required the "command" permission that headless mode '
             'cannot prompt for, so it was auto-denied. Add an allow-rule under permissions.allow in settings.json')


def test_soft_denied_agy_hands_over_to_unrestricted_agy_which_commits(world: World) -> None:
    denied = lambda root: CommandResult(0, SOFT_DENY)  # noqa: E731
    world.engines = [ScriptedEngine("agy", [denied]),
                     ScriptedEngine("agy-unrestricted", [{"app/web/src/eta.txt": "2026-10-12\n"}]),
                     ScriptedEngine("loop", [])]
    service = world.service()
    start(service, job(max_iterations=5))
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert status["engine"] == "agy-unrestricted"
    assert status["iterations"] == 2
    events = [(e["iteration"], e["engine"], e["reason"]) for e in status["engine_events"] if e["reason"] != "round"]
    assert events == [(1, "agy", "engine-permission-denied"), (2, "agy-unrestricted", "committed")]
    sha = next(e["sha"] for e in status["engine_events"] if e["reason"] == "committed")
    body = world.github.bodies[100]
    assert "Engine: agy-unrestricted (agyuser, skip-permissions after allow-list denial)" in body
    assert f"{sha[:12]} agy-unrestricted" in body
    log = (world.tmp / "home/jobs/j-12-1/log").read_text()
    assert "engine-permission-denied" in log
    assert "agy output (iteration 1)" in log
    assert world.engines[2].prompts == []


def test_restricted_agy_without_progress_gives_way_after_one_round(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{}]), ScriptedEngine("loop", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(max_iterations=5))
    status = wait(service, "j-12-1")
    assert status["engine"] == "loop"
    reasons = [e["reason"] for e in status["engine_events"] if e["reason"] != "round"]
    assert reasons == ["engine-no-progress", "committed"]


def test_other_engines_get_two_rounds_without_progress(world: World) -> None:
    world.engines = [ScriptedEngine("loop", [{}, {}]),
                     ScriptedEngine("spare", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(max_iterations=5))
    status = wait(service, "j-12-1")
    assert status["engine"] == "spare"
    reasons = [e["reason"] for e in status["engine_events"] if e["reason"] != "round"]
    assert reasons == ["engine-no-progress", "committed"]


def test_prompt_names_the_failing_tests_their_assertions_and_the_allowed_commands(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    wait(service, "j-12-1")
    prompt = world.engines[0].prompts[0]
    assert "Failing tests:" in prompt
    assert f"{ETA_TEST} > expect web/src/eta.txt == 2026-10-12" in prompt
    assert "expected '2026-10-12' got 'none'" in prompt
    rule = "read the failing test first, make the smallest change that satisfies it, do not edit any test file"
    assert rule in prompt
    assert "npx vitest" in prompt
    assert "git status" in prompt


def test_root_rewrites_the_agy_allow_list_before_each_round_and_logs_its_hash(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    wait(service, "j-12-1")
    writes_before = len(service._deps.toolchain.settings_writes)
    world.contexts[0].refresh_agy_settings()
    world.contexts[0].refresh_agy_settings()
    assert len(service._deps.toolchain.settings_writes) == writes_before + 2
    digest = hashlib.sha256(AGY_SETTINGS_BYTES).hexdigest()[:16]
    assert f"agy settings rewritten, sha256 {digest}" in (world.tmp / "home/jobs/j-12-1/log").read_text()


@pytest.mark.parametrize("content", [
    "REFERENCE_ERROR\n",
    "IMPORT_ERROR\nexpect web/src/eta.txt == 2026-10-12\n",
])
def test_broken_designed_tests_stop_the_job_as_tests_invalid(world: World, content: str) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, job(tests=[{"path": ETA_TEST, "content": content}]))
    status = wait(service, "j-12-1")
    assert status["status"] == "failed", status
    assert status["reason"] == "tests-invalid"
    assert ETA_TEST in status["detail"]
    assert world.engines[0].prompts == []
    assert git(world.remote_root / f"{REPO}.git", "branch", "--list", "agent/issue-12").strip() == ""


AGY_DEBUG_LOG = f"""\
2026-10-10T13:40:01Z INFO CLI settings initialized: permissions=&{{Allow:[command(ls) command(cat)]}}
2026-10-10T13:40:02Z DEBUG model streaming 512 tokens
2026-10-10T13:40:03Z INFO tool call run_command: npx tsc --noEmit
2026-10-10T13:40:03Z WARN permission auto-denied: command(npx tsc --noEmit) not in allow list
2026-10-10T13:40:04Z DEBUG using token {PAT}
"""


def test_agy_debug_log_excerpt_shows_which_command_was_denied(world: World) -> None:
    class LoggingAgy(ScriptedEngine):
        last_logs: tuple[Path, ...] = ()

        def edit(self, prompt: str, *, workdir: str, timeout_s: int) -> CommandResult:
            log = world.contexts[-1].agy_log_dir / f"agy-iter{world.contexts[-1].round_no()}.log"
            log.write_text(AGY_DEBUG_LOG)
            self.last_logs = (log, log.parent / "missing.log")
            return super().edit(prompt, workdir=workdir, timeout_s=timeout_s)

    world.engines = [LoggingAgy("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    assert wait(service, "j-12-1")["status"] == "succeeded"
    log = (world.tmp / "home/jobs/j-12-1/log").read_text()
    assert "agy log (iteration 1)" in log
    assert "CLI settings initialized: permissions=&{Allow:[command(ls) command(cat)]}" in log
    assert "permission auto-denied: command(npx tsc --noEmit)" in log
    assert "tool call run_command: npx tsc --noEmit" in log
    assert "model streaming 512 tokens" not in log
    assert PAT not in log
    assert "missing.log unreadable" in log
    settings = world.engine_user.home / "settings.json"
    assert f"agy settings {settings} mode 0600 owner {os.getuid()}:{os.getgid()}" in log


@pytest.mark.parametrize("attack", ["nested-repo", "gitfile", "node-modules-link", "escaping-link-in-node-modules",
                                    "gitattributes"])
def test_untrusted_code_cannot_arm_root_git(world: World, attack: str) -> None:
    def hostile(root: Path) -> None:
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")
        if attack == "nested-repo":
            (root / "app/web/inner").mkdir()
            git(root / "app/web/inner", "init", "-q")
        elif attack == "gitfile":
            (root / "app/web/src/.git").write_text("gitdir: /tmp/elsewhere\n")
        elif attack == "node-modules-link":
            (root / "app/api").mkdir(exist_ok=True)
            (root / "app/api/node_modules").symlink_to("../../.git")
        elif attack == "escaping-link-in-node-modules":
            (root / "app/node_modules").mkdir(exist_ok=True)
            (root / "app/node_modules/evil").symlink_to("/etc")
        else:
            (root / "app/.gitattributes").write_text("* filter=evil\n")

    world.engines = [ScriptedEngine("agy", [hostile])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "failed", status
    assert status["reason"] == "scope-violation"
    assert remote_log(world.remote_root, "agent/issue-12") == ["test: add failing tests for #12"]
    assert not (world.checkout / "app/web/inner/.git").exists()
    assert not (world.checkout / "app/web/src/.git").exists()


def test_a_strangers_pr_with_the_same_branch_name_is_never_reused(world: World) -> None:
    stranger = PullRequest(number=99, title="x", body="", author="mallory", labels=(), state="open", merged=False,
                           head_ref="agent/issue-12", head_sha="", base_ref="main", created_at="",
                           head_repo="mallory/foundry-autonomous-sdlc")
    impostor = PullRequest(number=98, title="x", body="", author="mallory", labels=(), state="open", merged=False,
                           head_ref="agent/issue-12", head_sha="", base_ref="main", created_at="")
    world.github.pulls = [stranger, impostor]
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["pr"]["number"] == 102
    assert 99 not in world.github.labels
    assert 98 not in world.github.labels


def test_start_takes_a_lease_per_issue_and_refuses_a_second_job(world: World) -> None:
    gate = threading.Event()

    def held(root: Path) -> None:
        gate.wait(30)
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")

    world.engines = [ScriptedEngine("agy", [held])]
    service = world.service()
    start(service, job())
    assert world.github.branches["agent-lease/12"] == "base-sha"
    code, refused = service.handle({"op": "start", "job": job(job_id="j-12-2")})
    assert code == 200
    assert refused == {"job_id": "j-12-2", "status": "failed", "reason": "lease-held"}
    assert service.handle({"op": "status", "job_id": "j-12-2"})[0] == 404
    assert start(service, job())["status"] == "running"          # a retried start of the holder is fine
    gate.set()
    assert wait(service, "j-12-1")["status"] == "succeeded"


def test_an_interrupted_job_resumes_without_taking_its_lease_again(world: World) -> None:
    world.github.branches["agent-lease/12"] = "base-sha"           # held by this very job before the eviction
    service = world.service()
    service._store.save(JobState.new(JobSpec.from_request(job()), started_at="2026-10-10T12:00:00Z"))
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    assert service.handle({"op": "status", "job_id": "j-12-1"})[1]["reason"] == "interrupted"
    assert start(service, job())["status"] == "running"
    assert wait(service, "j-12-1")["status"] == "succeeded"


def test_restricted_agy_gets_exactly_one_round_even_with_progress(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "close\n"}, {"app/web/src/eta.txt": "x\n"}]),
                     ScriptedEngine("agy-unrestricted", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(max_iterations=5))
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert len(world.engines[0].prompts) == 1
    assert [(e["engine"], e["reason"]) for e in status["engine_events"] if e["reason"] != "round"] == [
        ("agy", "committed"), ("agy-unrestricted", "committed")]


def test_sandbox_blocked_commands_reach_the_log_excerpt() -> None:
    line = ("run_command_handler.go:574 [sandbox-telemetry] emitting SANDBOX_COMMAND_BLOCKED event with "
            "extra=map[command_line:cat /home/agyuser/.bashrc]")
    assert AGY_LOG_LINES.search(line)


def test_a_real_npm_ci_layout_does_not_stop_the_job(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(install_cmd=f"{sys.executable} ../tools/npm_links.py"))
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert (world.checkout / "app/node_modules/@parcel/core").is_symlink()
    bare = world.remote_root / f"{REPO}.git"
    assert "node_modules" not in git(bare, "ls-tree", "-r", "--name-only", "agent/issue-12")


TYPE_BUG = "TYPE_ERROR Type 'string' is not assignable to type 'TrackingNumber'."


def test_designed_tests_that_do_not_typecheck_go_back_as_tests_invalid(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(tests=[{"path": ETA_TEST, "content": f"expect web/src/eta.txt == 2026-10-12\n{TYPE_BUG}\n"}]))
    status = wait(service, "j-12-1")
    assert (status["status"], status["reason"]) == ("failed", "tests-invalid"), status
    assert status["detail"] == ("app/web/tests/eta.test.ts(2,1): error TS2322: "
                                "Type 'string' is not assignable to type 'TrackingNumber'.")
    assert world.engines[0].prompts == []                       # no engine ran
    assert git(world.remote_root / f"{REPO}.git", "branch", "--list", "agent/issue-12") == ""


def test_typecheck_errors_outside_the_new_tests_do_not_invalidate_them_but_block_green(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}]),
                     ScriptedEngine("agy-unrestricted", [{}, {}])]
    service = world.service()
    start(service, job(install_cmd=f"{sys.executable} ../tools/plant_type_error.py"))
    status = wait(service, "j-12-1")
    assert (status["status"], status["reason"]) == ("failed", "max-iterations"), status
    assert "legacy/index.d.ts(1,1): error TS2322: legacy typing" in status["detail"]
    assert remote_log(world.remote_root, "agent/issue-12")[0] == "test: add failing tests for #12"
    assert world.github.pulls == []


def test_green_needs_typecheck_and_errors_are_fed_to_the_next_round(world: World) -> None:
    world.engines = [
        ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n",
                                "app/web/src/eta.ts": "TYPE_ERROR Property 'eta' is missing.\n"}]),
        ScriptedEngine("agy-unrestricted", [{"app/web/src/eta.ts": "export const eta = '2026-10-12'\n"}]),
    ]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert status["iterations"] == 2
    prompt = world.engines[1].prompts[0]
    assert "Typecheck and lint errors" in prompt
    assert "src/eta.ts(1,1): error TS2322: Property 'eta' is missing." in prompt
    body = world.github.bodies[100]
    assert "`npm run typecheck`: passed" in body and "`npm run lint`: passed" in body
    log = (world.tmp / "home/jobs/j-12-1/log").read_text()
    assert "`npm run typecheck`: failed (1 errors)" in log
    assert "`npm run lint`: passed" in log


def test_lint_errors_block_green_and_nothing_is_published(world: World) -> None:
    world.engines = [
        ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n",
                                "app/web/src/eta.ts": "LINT_ERROR 'x' is unused\n"}]),
        ScriptedEngine("agy-unrestricted", [{}, {}]),
    ]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert (status["status"], status["reason"]) == ("failed", "max-iterations"), status
    assert "app/web/src/eta.ts(1,1): error no-restricted-syntax: 'x' is unused" in status["detail"]
    assert world.github.pulls == []
    assert "Typecheck and lint errors" in world.engines[1].prompts[0]


def test_unrestricted_agy_gets_at_most_two_rounds_then_the_loop(world: World) -> None:
    world.engines = [ScriptedEngine("agy-unrestricted", [{"app/web/src/eta.txt": "close\n"},
                                                         {"app/web/src/eta.txt": "closer\n"},
                                                         {"app/web/src/eta.txt": "2026-10-12\n"}]),
                     ScriptedEngine("loop", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(max_iterations=5))
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert status["engine"] == "loop"
    assert len(world.engines[0].prompts) == 2
    assert "got 'close'" in world.engines[0].prompts[1]     # the second round continues from the first's edits


def test_each_round_records_its_wall_seconds_and_whether_it_timed_out(world: World) -> None:
    engine = ScriptedEngine("agy-unrestricted", [])

    def slow(root: Path) -> CommandResult:
        world.clock.t += 900
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")
        engine.last_timed_out = True
        return CommandResult(0, "[agy timed out after making edits; keeping them for the test run]")

    engine.steps = [slow]
    world.engines = [engine]
    service = world.service()
    start(service, job())
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    rounds = [e for e in status["engine_events"] if e["reason"] == "round"]
    assert rounds == [{"iteration": 1, "engine": "agy-unrestricted", "reason": "round", "seconds": 900,
                       "timed_out": True, "returncode": 0}]


def maintenance(**overrides: Any) -> dict[str, Any]:
    return job(**{"job_id": "j-30-1", "mode": "maintenance", "branch": "agent/issue-30", "tests": [],
                  "pr": {"number": 31}, "issue": {"number": 30, "title": "Heading changed", "body": "stale"},
                  **overrides})


def test_maintenance_with_allowed_paths_that_match_nothing_fails_cleanly_at_setup(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/tests/title.test.ts": "x\n"}])]
    service = world.service()
    start(service, maintenance(allowed_paths=["app/tests/parcel-page.test.tsx"]))
    status = wait(service, "j-30-1")
    assert (status["status"], status["phase"], status["reason"]) == ("failed", "setup", "invalid-allowed-paths")
    assert "app/tests/parcel-page.test.tsx" in status["detail"]
    assert world.engines[0].prompts == []


def test_maintenance_keeps_only_allowed_paths_that_exist_at_the_branch_head(world: World) -> None:
    repaired = "expect web/src/title.txt == Where is my parcel\n"
    world.engines = [ScriptedEngine("agy", [{"app/web/tests/title.test.ts": repaired}])]
    service = world.service()
    start(service, maintenance(allowed_paths=["app/web/tests/title.test.ts", "app/tests/gone.test.tsx"]))
    status = wait(service, "j-30-1")
    assert status["status"] == "succeeded", status
    assert "ignoring allowed_paths that match no file at the branch head: app/tests/gone.test.tsx" \
        in (world.tmp / "home/jobs/j-30-1/log").read_text()


def test_revise_with_allowed_paths_that_match_nothing_fails_cleanly(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, job(job_id="j-40-2", mode="revise", branch="agent/issue-40", tests=[], pr={"number": 41},
                       issue={"number": 40, "title": "ETA", "body": "x"}, allowed_paths=["app/nowhere/"]))
    status = wait(service, "j-40-2")
    assert (status["status"], status["reason"]) == ("failed", "invalid-allowed-paths"), status
    assert "app/nowhere/" in status["detail"]


def test_the_server_answers_500_and_keeps_serving_when_a_request_blows_up(
        world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    service = world.service()
    monkeypatch.setattr(service, "status", lambda job_id: 1 / 0)
    assert service.handle_raw(b'{"op": "status", "job_id": "j-1"}') == (500, {"error": "internal_error"})
    assert "ZeroDivisionError" in capsys.readouterr().out
    monkeypatch.undo()
    assert service.handle_raw(b'{"op": "status", "job_id": "j-1"}')[0] == 404


def test_a_running_job_heartbeats_its_state_and_status_says_how_stale_it_is(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "HEARTBEAT_S", 0.05)
    release = threading.Event()
    state_file = world.tmp / "home/jobs/j-12-1/state.json"

    def slow(root: Path) -> CommandResult:
        world.clock.now_iso = lambda: "2026-10-10T12:07:00Z"   # type: ignore[method-assign]
        end = time.monotonic() + 10
        while json.loads(state_file.read_text())["updated_at"] != "2026-10-10T12:07:00Z" and time.monotonic() < end:
            time.sleep(0.02)
        release.set()
        (root / "app/web/src/eta.txt").write_text("2026-10-12\n")
        return CommandResult(0, "ok")

    world.engines = [ScriptedEngine("agy", [slow])]
    service = world.service()
    start(service, job())
    assert release.wait(15)
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert status["updated_at"] == "2026-10-10T12:07:00Z"
    world.clock.now_iso = lambda: "2026-10-10T12:08:30Z"   # type: ignore[method-assign]
    assert service.handle({"op": "status", "job_id": "j-12-1"})[1]["stale_s"] == 90


def test_the_watchdog_stops_a_job_stuck_past_its_deadline(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_mod, "HEARTBEAT_S", 0.05)
    seen: dict[str, Any] = {}

    def stuck(root: Path) -> CommandResult:
        world.clock.t += 3600 + runner_mod.WATCHDOG_GRACE_S + 1
        cancel = world.contexts[-1].cancel
        assert cancel.wait(10)                                  # the watchdog pulls the cancel cord
        seen.update(service.handle({"op": "status", "job_id": "j-12-1"})[1])
        return CommandResult(0, "stuck")

    world.engines = [ScriptedEngine("agy", [stuck])]
    service = world.service()
    start(service, job(deadline_s=3600))
    status = wait(service, "j-12-1")
    assert (seen["status"], seen["reason"]) == ("timeout", "deadline")   # reported while still stuck
    assert "watchdog" in seen["detail"]
    assert (status["status"], status["reason"]) == ("timeout", "deadline"), status


def test_a_restarted_server_marks_jobs_left_running_as_interrupted_at_once(world: World) -> None:
    spec = JobSpec.from_request(job())
    store = JobStore(world.tmp / "home/jobs", Redactor())
    store.save(JobState.new(spec, started_at="2026-10-10T11:00:00Z"))
    world.service()
    saved = json.loads((world.tmp / "home/jobs/j-12-1/state.json").read_text())
    assert (saved["status"], saved["reason"]) == ("failed", "interrupted")


def test_each_child_step_logs_its_memory_peak(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shell, "take_memory", lambda: shell.MemoryPeak(800 * 1024, 600 * 1024))
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job())
    assert wait(service, "j-12-1")["status"] == "succeeded"
    log = (world.tmp / "home/jobs/j-12-1/log").read_text()
    for step in ("tests", "npm run typecheck", "engine agy"):
        assert f"memory {step}: peak group RSS 800 MiB, largest process 600 MiB" in log


def _everywhere(world: World, service: CoderService, job_id: str, printed: str) -> str:
    """stdout, the job log, state.json and the status reply. state.json keeps the orchestrator's own request
    verbatim (a resume needs it); it never leaves the sandbox, so it is left out here."""
    _code, status = service.handle({"op": "status", "job_id": job_id})
    jobs = world.tmp / "home/jobs" / job_id
    state = json.loads((jobs / "state.json").read_text())
    state.pop("request")
    return "\n".join([printed, (jobs / "log").read_text(), json.dumps(state), json.dumps(status)])


def test_secrets_in_an_exception_or_the_environment_reach_no_output(
        world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IDENTITY_HEADER", "planted-identity-header-77")
    monkeypatch.setenv("SDLC_PLANTED_API_KEY", "planted-env-key-value-88")
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJwbGFudGVkIn0.cGxhbnRlZC1zaWc"
    planted = [PAT, "ya29.SECRETAGY987654321", "planted-identity-header-77", "planted-env-key-value-88", jwt,
               "planted-url-pw", "planted-bearer-99", "local-variable-secret-66"]

    def boom(root: Path) -> None:
        held = "local-variable-secret-66"   # noqa: F841  must not appear: tracebacks never print locals
        raise RuntimeError(f"{PAT} ya29.SECRETAGY987654321 {os.environ['IDENTITY_HEADER']} "
                           f"{os.environ['SDLC_PLANTED_API_KEY']} {jwt} https://u:planted-url-pw@example.com/x "
                           "Authorization: Bearer planted-bearer-99")

    world.engines = [ScriptedEngine("agy", [boom])]
    service = world.service()
    start(service, job())
    assert wait(service, "j-12-1")["reason"] == "internal-error"
    seen = _everywhere(world, service, "j-12-1", capsys.readouterr().out)
    assert "RuntimeError" in seen
    for secret in planted:
        assert secret not in seen, secret


def test_a_secret_on_a_command_line_reaches_no_output(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    token = "planted-cmdline-token-4242"
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, job(install_cmd=f"definitely-not-installed-xyz --token={token}"))
    status = wait(service, "j-12-1")
    assert status["reason"] == "install-failed", status
    seen = _everywhere(world, service, "j-12-1", capsys.readouterr().out)
    assert "definitely-not-installed-xyz" in seen
    assert token not in seen


def test_a_loop_round_that_is_not_strictly_better_is_reverted_and_two_stop_the_loop(world: World) -> None:
    world.engines = [ScriptedEngine("loop", [{"app/web/src/eta.txt": "wrong\n"},
                                            {"app/web/src/eta.txt": "still wrong\n",
                                             "app/web/src/extra.txt": "junk\n"},
                                            {"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(max_iterations=5))
    status = wait(service, "j-12-1")
    assert (status["status"], status["reason"]) == ("failed", "engines-exhausted"), status
    assert status["iterations"] == 2                                  # stopped after two reverts, not five
    assert [e["reason"] for e in status["engine_events"] if e["reason"] != "round"] == [
        "reverted", "reverted", "engine-no-progress"]
    assert remote_log(world.remote_root, "agent/issue-12") == ["test: add failing tests for #12"]
    assert (world.checkout / "app/web/src/eta.txt").read_text() == "none\n"
    assert not (world.checkout / "app/web/src/extra.txt").exists()


def test_a_loop_round_that_trades_a_failure_for_a_type_error_is_reverted(world: World) -> None:
    world.engines = [ScriptedEngine("loop", [{"app/web/src/eta.txt": "2026-10-12\n",
                                             "app/web/src/eta.ts": "TYPE_ERROR Property 'eta' is missing.\n"},
                                            {"app/web/src/eta.txt": "2026-10-12\n"}])]
    service = world.service()
    start(service, job(max_iterations=5))
    status = wait(service, "j-12-1")
    assert status["status"] == "succeeded", status
    assert [e["reason"] for e in status["engine_events"] if e["reason"] not in ("round", "committed")] == [
        "reverted"]
    assert "Property 'eta' is missing" in world.engines[0].prompts[1]   # the reverted round's errors are fed back
    assert not (world.checkout / "app/web/src/eta.ts").exists()


def test_maintenance_pushes_one_squashed_commit_only_when_green(world: World) -> None:
    bare = world.remote_root / f"{REPO}.git"
    before = git(bare, "rev-parse", "agent/issue-30").strip()

    def second(root: Path) -> CommandResult:
        assert git(bare, "rev-parse", "agent/issue-30").strip() == before   # round 1 was not pushed
        (root / "app/web/tests/title.test.ts").write_text("expect web/src/title.txt == Where is my parcel\n")
        return CommandResult(0, "ok")

    world.engines = [ScriptedEngine("agy", [{"app/web/tests/title.test.ts": "expect web/src/title.txt == Where\n"}]),
                     ScriptedEngine("agy-unrestricted", [second])]
    service = world.service()
    start(service, maintenance(allowed_paths=["app/web/tests/title.test.ts"]))
    status = wait(service, "j-30-1")
    assert status["status"] == "succeeded", status
    assert status["iterations"] == 2
    assert remote_log(world.remote_root, "agent/issue-30") == [
        "feat: work on agent/issue-30", "test: repair stale tests for #30"]
    assert remote_file(world.remote_root, "agent/issue-30", "app/web/tests/title.test.ts") == \
        "expect web/src/title.txt == Where is my parcel\n"


def test_a_failed_maintenance_job_pushes_nothing(world: World) -> None:
    bare = world.remote_root / f"{REPO}.git"
    before = git(bare, "rev-parse", "agent/issue-30").strip()
    world.engines = [ScriptedEngine("agy", [{"app/web/tests/title.test.ts": "expect web/src/title.txt == Nope\n"}]),
                     ScriptedEngine("agy-unrestricted", [{"app/web/tests/title.test.ts": "expect web/src/title.txt "
                                                                                       "== Still nope\n"}])]
    service = world.service()
    start(service, maintenance(allowed_paths=["app/web/tests/title.test.ts"], max_iterations=2))
    status = wait(service, "j-30-1")
    assert (status["status"], status["reason"]) == ("failed", "max-iterations"), status
    assert git(bare, "rev-parse", "agent/issue-30").strip() == before


def test_revise_pushes_one_squashed_commit(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta.txt": "broken\n"}]),        # round 1 goes red
                     ScriptedEngine("agy-unrestricted", [{"app/web/src/eta.txt": "2026-10-12\n",
                                                          "app/web/src/eta-label.txt": "Estimated delivery\n"}])]
    service = world.service()
    start(service, revise_job())
    status = wait(service, "j-40-2")
    assert status["status"] == "succeeded", status
    assert status["iterations"] == 2
    assert remote_log(world.remote_root, "agent/issue-40") == [
        "test: add failing tests for #40", "feat: Show the ETA (#40)", "fix: address review findings for #40"]
    assert remote_file(world.remote_root, "agent/issue-40", "app/web/src/eta.txt") == "2026-10-12\n"
