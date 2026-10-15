from __future__ import annotations

import io
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
import yaml

from scripts import setup_repo as sr

ROOT = Path(__file__).resolve().parents[2]


class FakeGitHub:
    """In-memory stand-in for the slice of the GitHub REST API that setup_repo uses."""

    def __init__(self, admin: bool = True) -> None:
        self.labels: dict[str, dict[str, str]] = {}
        self.repo: dict[str, Any] = {
            "permissions": {"admin": admin},
            "has_issues": True,
            "allow_merge_commit": True,
            "allow_squash_merge": True,
            "allow_rebase_merge": True,
            "delete_branch_on_merge": False,
            "has_wiki": True,
            "has_projects": True,
        }
        self.pages: dict[str, Any] | None = None
        self.actions: dict[str, Any] = {"enabled": False, "allowed_actions": "all"}
        self.workflow: dict[str, Any] = {
            "default_workflow_permissions": "write",
            "can_approve_pull_request_reviews": True,
        }
        self.rulesets: dict[int, dict[str, Any]] = {}
        self.calls: list[tuple[str, str, Any]] = []

    @property
    def writes(self) -> list[tuple[str, str, Any]]:
        return [call for call in self.calls if call[0] != "GET"]

    def __call__(self, args: list[str], stdin: str | None = None) -> str:
        assert args[0] == "api", args
        if "-X" in args:
            method, path = args[args.index("-X") + 1], args[args.index("-X") + 2]
            body = json.loads(stdin or "null")
        else:
            method, path, body = "GET", args[1], None
        self.calls.append((method, path, body))
        path, _, _ = path.partition("?")
        return json.dumps(self.handle(method, path.removeprefix(f"repos/{sr.REPO}"), body))

    def handle(self, method: str, path: str, body: Any) -> Any:
        if path == "/labels":
            if method == "POST":
                self.labels[body["name"]] = dict(body)
                return body
            return list(self.labels.values())
        if path.startswith("/labels/"):
            name = unquote(path.removeprefix("/labels/"))
            assert method == "PATCH" and name in self.labels, (method, name)
            self.labels[name] = dict(body)
            return body
        if path == "":
            if method == "PATCH":
                self.repo.update(body)
            return self.repo
        if path == "/pages":
            if self.pages is None and method == "GET":
                raise sr.GhError(["api", path], "gh: Not Found (HTTP 404)")
            if method in ("POST", "PUT"):
                self.pages = dict(body)
            return self.pages
        if path == "/actions/permissions":
            if method == "PUT":
                self.actions.update(body)
            return self.actions
        if path == "/actions/permissions/workflow":
            if method == "PUT":
                self.workflow.update(body)
            return self.workflow
        if path == "/rulesets":
            if method == "POST":
                self.rulesets[len(self.rulesets) + 1] = {**body, "id": len(self.rulesets) + 1}
                return body
            return [{"id": i, "name": r["name"]} for i, r in self.rulesets.items()]
        match = re.fullmatch(r"/rulesets/(\d+)", path)
        if match:
            ruleset_id = int(match.group(1))
            if method == "PUT":
                self.rulesets[ruleset_id] = {**body, "id": ruleset_id}
            return self.rulesets[ruleset_id]
        raise AssertionError(f"unexpected {method} {path}")


def run_phase(fake: FakeGitHub, phase: str, dry_run: bool = False) -> str:
    out = io.StringIO()
    assert sr.main(["--phase", phase, *(["--dry-run"] if dry_run else [])], fake, out) == 0
    return out.getvalue()


class TestBootstrap:
    def test_applies_everything_on_a_fresh_repo(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "bootstrap")

        assert set(fake.labels) == set(sr.LABELS) and len(sr.LABELS) == 28
        assert fake.repo["allow_merge_commit"] is True
        assert fake.repo["allow_squash_merge"] is False
        assert fake.repo["allow_rebase_merge"] is False
        assert fake.repo["delete_branch_on_merge"] is True
        assert (fake.repo["has_wiki"], fake.repo["has_projects"]) == (False, False)
        assert fake.pages == {"build_type": "workflow"}
        assert fake.actions["enabled"] is True
        assert fake.workflow == {
            "default_workflow_permissions": "read",
            "can_approve_pull_request_reviews": False,
        }
        assert fake.rulesets == {}

    def test_second_run_changes_nothing(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "bootstrap")
        fake.calls.clear()
        out = run_phase(fake, "bootstrap")
        assert fake.writes == []
        assert "0 change(s) applied" in out

    def test_dry_run_reads_but_never_writes(self) -> None:
        fake = FakeGitHub()
        out = run_phase(fake, "bootstrap", dry_run=True)
        assert fake.writes == []
        assert fake.labels == {} and fake.pages is None
        assert "would   label stage:ready: create" in out
        assert "would   pages: enable (build from workflow)" in out
        assert "nothing applied (dry run)" in out

    def test_drifted_state_is_repaired_and_only_that(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "bootstrap")
        fake.labels["type:bug"]["color"] = "ffffff"
        fake.labels["stage:ready"]["description"] = "old words"
        del fake.labels["owner:web"]
        fake.repo["allow_squash_merge"] = True
        fake.pages = {"build_type": "legacy"}
        fake.calls.clear()

        run_phase(fake, "bootstrap")

        assert sorted((m, p.split(sr.REPO)[1]) for m, p, _ in fake.writes) == [
            ("PATCH", ""),
            ("PATCH", "/labels/stage%3Aready"),
            ("PATCH", "/labels/type%3Abug"),
            ("POST", "/labels"),
            ("PUT", "/pages"),
        ]
        assert fake.repo["allow_squash_merge"] is False
        assert fake.labels["type:bug"]["color"] == sr.LABELS["type:bug"][0]
        assert fake.pages == {"build_type": "workflow"}

    def test_repo_patch_only_carries_the_drifted_keys(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "bootstrap")
        fake.repo["has_wiki"] = True
        fake.calls.clear()
        run_phase(fake, "bootstrap")
        assert fake.writes == [("PATCH", f"repos/{sr.REPO}", {"has_wiki": False})]

    def test_refuses_without_admin_and_writes_nothing(self, capsys: pytest.CaptureFixture) -> None:
        fake = FakeGitHub(admin=False)
        assert sr.main(["--phase", "bootstrap"], fake, io.StringIO()) == 1
        assert "not authenticated as an admin" in capsys.readouterr().err
        assert fake.writes == []

    def test_pages_errors_other_than_404_are_not_swallowed(self) -> None:
        def broken(args: list[str], stdin: str | None = None) -> str:
            if args[1].endswith("/pages"):
                raise sr.GhError(args, "gh: Server Error (HTTP 500)")
            return FakeGitHub()(args, stdin)

        assert sr.main(["--phase", "bootstrap", "--dry-run"], broken, io.StringIO()) == 1

    def test_label_colours_are_grouped_by_prefix(self) -> None:
        by_prefix: dict[str, set[str]] = {}
        for name, (color, description) in sr.LABELS.items():
            by_prefix.setdefault(name.split(":")[0], set()).add(color)
            assert re.fullmatch(r"[0-9a-f]{6}", color) and 0 < len(description) <= 100
        assert all(len(colors) == 1 for colors in by_prefix.values())
        assert len({next(iter(c)) for c in by_prefix.values()}) == len(by_prefix)

    def test_labels_match_the_architecture_doc(self) -> None:
        doc = (ROOT / "docs/architecture.md").read_text()
        section = doc.split("Label set", 1)[1].split("### State comment", 1)[0]
        label = r"`((?:stage|escalated|type|bug|severity|owner|agent|maintenance):[a-z0-9-]+)`"
        documented = set(re.findall(label, section))
        # The release pipeline owns one label of its own; docs/cd.md documents it.
        documented |= set(re.findall(label, (ROOT / "docs/cd.md").read_text()))
        assert documented == set(sr.LABELS)

    def test_the_deploy_failed_label_is_terminal_red(self) -> None:
        color, description = sr.LABELS["escalated:deploy-failed"]
        assert color == sr.LABELS["escalated:build-failed"][0]
        assert "rolled back" in description

    def test_the_merge_conflict_label_is_terminal_red(self) -> None:
        color, description = sr.LABELS["escalated:merge-conflict"]
        assert color == sr.LABELS["escalated:build-failed"][0]
        assert "conflict" in description


class TestProtectDeploy:
    def test_only_the_actions_app_may_move_the_deploy_branch(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "protect-deploy")
        ruleset = fake.rulesets[1]
        assert ruleset["name"] == "deploy-branch" and ruleset["enforcement"] == "active"
        assert ruleset["conditions"]["ref_name"]["include"] == ["refs/heads/deploy"]
        assert ruleset["bypass_actors"] == [
            {
                "actor_id": sr.GITHUB_ACTIONS_APP_ID,
                "actor_type": "Integration",
                "bypass_mode": "always",
            }
        ]
        assert {rule["type"] for rule in ruleset["rules"]} == {
            "deletion",
            "non_fast_forward",
            "update",
        }

    def test_it_is_idempotent_and_not_part_of_all(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "protect-deploy")
        run_phase(fake, "protect-deploy")
        assert len(fake.rulesets) == 1
        run_phase(FakeGitHub(), "all")
        assert "protect-deploy" not in sr.PHASES["all"] and sr.PHASES["all"] == [
            *sr.PHASES["bootstrap"],
            *sr.PHASES["protect"],
        ]


class TestProtect:
    def test_creates_the_ruleset(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "protect")
        assert fake.labels == {} and fake.pages is None  # protect touches nothing else

        ruleset = fake.rulesets[1]
        assert ruleset["name"] == "main-gates"
        assert ruleset["enforcement"] == "active"
        assert ruleset["bypass_actors"] == []
        assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
        rules = {rule["type"]: rule.get("parameters") for rule in ruleset["rules"]}
        assert set(rules) == {
            "deletion",
            "non_fast_forward",
            "pull_request",
            "required_status_checks",
        }
        assert "required_linear_history" not in rules
        assert rules["pull_request"]["required_approving_review_count"] == 0
        assert rules["pull_request"]["allowed_merge_methods"] == ["merge"]
        checks = rules["required_status_checks"]
        assert checks["strict_required_status_checks_policy"] is False
        assert [c["context"] for c in checks["required_status_checks"]] == [
            "test",
            "coverage",
            "e2e",
            "gitleaks",
            "tdd-order",
            "agent-scope",
            "evals",
        ]
        assert {c["integration_id"] for c in checks["required_status_checks"]} == {15368}

    def test_second_run_is_a_no_op(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "protect")
        fake.calls.clear()
        run_phase(fake, "protect")
        assert fake.writes == []

    def test_a_weakened_ruleset_is_restored_in_place(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "protect")
        fake.rulesets[1]["rules"] = [
            r for r in fake.rulesets[1]["rules"] if r["type"] != "deletion"
        ]
        fake.rulesets[1]["bypass_actors"] = [{"actor_id": 5, "actor_type": "RepositoryRole"}]
        fake.calls.clear()
        run_phase(fake, "protect")
        assert [(m, p.split(sr.REPO)[1]) for m, p, _ in fake.writes] == [("PUT", "/rulesets/1")]
        assert fake.rulesets[1]["bypass_actors"] == []
        assert len(fake.rulesets) == 1

    def test_dropped_required_check_is_restored(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "protect")
        for rule in fake.rulesets[1]["rules"]:
            if rule["type"] == "required_status_checks":
                rule["parameters"]["required_status_checks"].pop()
        run_phase(fake, "protect")
        rule = next(r for r in fake.rulesets[1]["rules"] if r["type"] == "required_status_checks")
        assert len(rule["parameters"]["required_status_checks"]) == len(sr.REQUIRED_CHECKS)

    def test_extra_fields_from_github_do_not_cause_churn(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "protect")
        fake.rulesets[1].update(
            {"node_id": "x", "source": sr.REPO, "current_user_can_bypass": "never"}
        )
        fake.rulesets[1]["rules"][2]["parameters"]["allowed_merge_methods"] = ["merge"]
        fake.calls.clear()
        run_phase(fake, "protect")
        assert fake.writes == []

    def test_other_rulesets_are_left_alone(self) -> None:
        fake = FakeGitHub()
        fake.rulesets[1] = {"id": 1, "name": "someone-elses", "rules": []}
        run_phase(fake, "protect")
        assert fake.rulesets[1]["name"] == "someone-elses"
        assert fake.rulesets[2]["name"] == "main-gates"

    def test_required_checks_are_the_ci_job_names(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        job_names = {job.get("name", job_id) for job_id, job in workflow["jobs"].items()}
        assert set(sr.REQUIRED_CHECKS) <= job_names

    def test_required_checks_match_gates(self) -> None:
        import re

        agents_dir = str(ROOT / "agents")
        if agents_dir not in sys.path:
            sys.path.insert(0, agents_dir)
        from sdlc_agents import gates
        from sdlc_agents.ledger import model

        import scripts.cd.plan as plan
        import scripts.collect_evidence as ce

        assert sr.REQUIRED_CHECKS == gates.REQUIRED_CHECKS
        assert sr.REQUIRED_CHECKS == plan.REQUIRED_CHECKS
        assert sr.REQUIRED_CHECKS == ce.GATES
        assert "evals" in sr.REQUIRED_CHECKS

        # Verify JS dashboard GATE_ORDER
        agg_text = (ROOT / "dashboard" / "js" / "aggregate.js").read_text(encoding="utf-8")
        m_agg = re.search(r"export const GATE_ORDER = \[(.*?)\];", agg_text)
        assert m_agg
        agg_gates = tuple(re.findall(r"['\"]([^'\"]+)['\"]", m_agg.group(1)))
        assert agg_gates == sr.REQUIRED_CHECKS

        # Verify control center GATES and ledger GATE_NAMES
        cc_text = (ROOT / "apps" / "control-center" / "js" / "model.js").read_text(encoding="utf-8")
        m_cc = re.search(r"export const GATES = Object\.freeze\(\[(.*?)\]\);", cc_text)
        assert m_cc
        cc_gates = tuple(re.findall(r"['\"]([^'\"]+)['\"]", m_cc.group(1)))
        assert cc_gates == model.GATE_NAMES
        assert cc_gates[:7] == sr.REQUIRED_CHECKS


class TestAll:
    def test_all_runs_both_phases(self) -> None:
        fake = FakeGitHub()
        run_phase(fake, "all")
        assert fake.labels and fake.pages and fake.rulesets


class TestRealGhWrapper:
    """Drive the script as a subprocess against a fake `gh` executable on PATH."""

    FAKE_GH = """\
#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
path = args[1]
if path.endswith("/pages"):
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
if "/labels" in path or "/rulesets" in path:
    print("[]")
elif path.endswith("/actions/permissions"):
    print(json.dumps({"enabled": True}))
elif path.endswith("/actions/permissions/workflow"):
    print(json.dumps({"default_workflow_permissions": "write",
                      "can_approve_pull_request_reviews": False}))
else:
    print(json.dumps({"permissions": {"admin": True}}))
"""

    def test_dry_run_issues_only_get_requests(self, tmp_path: Path) -> None:
        gh_bin = tmp_path / "bin"
        gh_bin.mkdir()
        fake = gh_bin / "gh"
        fake.write_text(self.FAKE_GH)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        log = tmp_path / "calls.log"
        env = {
            **os.environ,
            "PATH": f"{gh_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_LOG": str(log),
        }

        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/setup_repo.py"), "--phase", "all", "--dry-run"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        assert calls and all(call[0] == "api" and "-X" not in call for call in calls)
        assert "would   label stage:ready: create" in proc.stdout
        assert "would   pages: enable" in proc.stdout
        assert "would   ruleset main-gates: create" in proc.stdout
        assert "would   actions: read-only default token: set" in proc.stdout

    def test_gh_failure_exits_one_with_a_message(self, tmp_path: Path) -> None:
        gh_bin = tmp_path / "bin"
        gh_bin.mkdir()
        fake = gh_bin / "gh"
        fake.write_text("#!/bin/sh\necho 'gh: Bad credentials (HTTP 401)' >&2\nexit 1\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        env = {**os.environ, "PATH": f"{gh_bin}{os.pathsep}{os.environ['PATH']}"}
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts/setup_repo.py"), "--phase", "bootstrap"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert proc.returncode == 1
        assert "Bad credentials" in proc.stderr
