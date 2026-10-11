"""Configure the GitHub repository for the autonomous SDLC demo.

Idempotent: every run reads the current state and changes only what differs.
Needs the `gh` CLI authenticated as a repo admin. Only this repository is ever touched.

    python scripts/setup_repo.py --phase bootstrap --dry-run
    python scripts/setup_repo.py --phase bootstrap   # labels, Pages, settings, Actions
    python scripts/setup_repo.py --phase protect     # branch ruleset `main-gates`

Run `protect` after the first push of the scaffold: the ruleset requires pull
requests, so it blocks direct pushes to main.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TextIO
from urllib.parse import quote

REPO = "stevengonsalvez/foundry-autonomous-sdlc"
RULESET_NAME = "main-gates"
REQUIRED_CHECKS = ("test", "coverage", "e2e", "gitleaks", "tdd-order", "agent-scope")
GITHUB_ACTIONS_APP_ID = 15368  # pins each check to Actions, so a commit status cannot fake it

# (name, description) by prefix group; the group decides the colour.
LABEL_GROUPS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "stage": (
        "1d76db",
        [
            ("stage:needs-refinement", "Requirements scored below 80, waiting for answers"),
            ("stage:ready", "Requirements scored 80 or more"),
            ("stage:feasible", "Judged suitable for the coding agent"),
            ("stage:tests-written", "Tests designed, waiting for the coder"),
            ("stage:building", "Coder is working"),
            ("stage:in-review", "PR open, CI and review running"),
            ("stage:merged", "PR merged"),
            ("stage:released", "Release tagged and published"),
        ],
    ),
    "escalated": (
        "d93f0b",
        [
            ("escalated:not-agent-suitable", "Terminal: not suitable for the coding agent"),
            ("escalated:requirements", "Terminal: requirements still unclear after 2 rounds"),
            ("escalated:review-failed", "Terminal: review kept requesting changes"),
            ("escalated:cost-cap", "Terminal: issue cost passed the cap"),
            ("escalated:build-failed", "Terminal: coder could not make the tests pass"),
            ("escalated:agent-error", "Terminal: an agent kept returning unusable output"),
            (
                "escalated:deploy-failed",
                "Terminal: a release failed smoke or soak and was rolled back",
            ),
        ],
    ),
    "type": (
        "5319e7",
        [
            ("type:feature", "New behaviour"),
            ("type:bug", "Defect in existing behaviour"),
            ("type:maintenance", "Repair of tests or tooling, no behaviour change"),
        ],
    ),
    "bug": ("d73a4a", [("bug:triaged", "Severity and owner assigned")]),
    "severity": (
        "fbca04",
        [
            ("severity:s1", "Outage or data loss"),
            ("severity:s2", "Major feature broken"),
            ("severity:s3", "Minor defect with a workaround"),
            ("severity:s4", "Cosmetic"),
        ],
    ),
    "owner": (
        "0e8a16",
        [
            ("owner:web", "Defect owned by the web workspace"),
            ("owner:api", "Defect owned by the api workspace"),
            ("owner:carrier-mock", "Defect owned by the carrier mock"),
        ],
    ),
    "agent": ("006b75", [("agent:pr", "Pull request opened by the coding agent")]),
    "maintenance": (
        "c5def5",
        [("maintenance:test-repair", "Pull request that repairs stale tests")],
    ),
}
LABELS: dict[str, tuple[str, str]] = {
    name: (color, description)
    for color, entries in LABEL_GROUPS.values()
    for name, description in entries
}

REPO_SETTINGS: dict[str, bool] = {
    "has_issues": True,
    "allow_merge_commit": True,
    "allow_squash_merge": False,
    "allow_rebase_merge": False,
    "delete_branch_on_merge": True,
    "has_wiki": False,
    "has_projects": False,
}
ACTIONS_PERMISSIONS: dict[str, Any] = {"enabled": True}
WORKFLOW_PERMISSIONS: dict[str, Any] = {
    "default_workflow_permissions": "read",
    "can_approve_pull_request_reviews": False,
}
PAGES: dict[str, str] = {"build_type": "workflow"}

RULESET: dict[str, Any] = {
    "name": RULESET_NAME,
    "target": "branch",
    "enforcement": "active",
    "bypass_actors": [],
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "rules": [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 0,
                "dismiss_stale_reviews_on_push": False,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
                "required_review_thread_resolution": False,
                "allowed_merge_methods": ["merge"],
            },
        },
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": False,
                "required_status_checks": [
                    {"context": check, "integration_id": GITHUB_ACTIONS_APP_ID}
                    for check in REQUIRED_CHECKS
                ],
            },
        },
    ],
}

Gh = Callable[[list[str], str | None], str]


class GhError(RuntimeError):
    def __init__(self, args: list[str], stderr: str) -> None:
        super().__init__(f"gh {' '.join(args[:4])} failed: {stderr.strip()[:300]}")
        self.stderr = stderr

    @property
    def not_found(self) -> bool:
        return "HTTP 404" in self.stderr


def gh(args: list[str], stdin: str | None = None) -> str:
    done = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=False)
    if done.returncode:
        raise GhError(args, done.stderr)
    return done.stdout


@dataclass(frozen=True)
class Step:
    """One desired change; `method` is None when the state is already correct."""

    summary: str
    method: str | None = None
    path: str = ""
    body: dict[str, Any] | None = None


def api_get(run: Gh, path: str) -> Any:
    return json.loads(run(["api", path], None))


def covers(actual: Any, desired: Any) -> bool:
    """True when `actual` holds everything in `desired` (extra keys in actual are fine)."""
    if isinstance(desired, dict):
        return isinstance(actual, dict) and all(
            key in actual and covers(actual[key], value) for key, value in desired.items()
        )
    if isinstance(desired, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(desired)
            and all(any(covers(a, d) for a in actual) for d in desired)
        )
    return bool(actual == desired)


def plan_labels(run: Gh) -> list[Step]:
    existing = {label["name"]: label for label in api_get(run, f"repos/{REPO}/labels?per_page=100")}
    steps = []
    for name, (color, description) in LABELS.items():
        current = existing.get(name)
        body = {"name": name, "color": color, "description": description}
        if current is None:
            steps.append(Step(f"label {name}: create", "POST", f"repos/{REPO}/labels", body))
        elif (current["color"].lower(), current.get("description") or "") != (color, description):
            path = f"repos/{REPO}/labels/{quote(name, safe='')}"
            steps.append(Step(f"label {name}: update", "PATCH", path, body))
        else:
            steps.append(Step(f"label {name}: ok"))
    return steps


def plan_repo_settings(run: Gh) -> list[Step]:
    repo = api_get(run, f"repos/{REPO}")
    if not repo.get("permissions", {}).get("admin", False):
        raise RuntimeError(f"gh is not authenticated as an admin of {REPO}")
    drift = {k: v for k, v in REPO_SETTINGS.items() if repo.get(k) != v}
    if not drift:
        return [Step("repo settings: ok")]
    shown = ", ".join(f"{k}={str(v).lower()}" for k, v in drift.items())
    return [Step(f"repo settings: set {shown}", "PATCH", f"repos/{REPO}", drift)]


def plan_pages(run: Gh) -> list[Step]:
    try:
        current = api_get(run, f"repos/{REPO}/pages")
    except GhError as err:
        if not err.not_found:
            raise
        return [Step("pages: enable (build from workflow)", "POST", f"repos/{REPO}/pages", PAGES)]
    if current.get("build_type") == PAGES["build_type"]:
        return [Step("pages: ok")]
    return [Step("pages: switch to build from workflow", "PUT", f"repos/{REPO}/pages", PAGES)]


def plan_actions(run: Gh) -> list[Step]:
    steps = []
    for label, path, desired in (
        ("actions: enable", "actions/permissions", ACTIONS_PERMISSIONS),
        ("actions: read-only default token", "actions/permissions/workflow", WORKFLOW_PERMISSIONS),
    ):
        current = api_get(run, f"repos/{REPO}/{path}")
        if covers(current, desired):
            steps.append(Step(f"{label}: ok"))
        else:
            steps.append(Step(f"{label}: set", "PUT", f"repos/{REPO}/{path}", desired))
    return steps


def plan_ruleset(run: Gh) -> list[Step]:
    listed = api_get(run, f"repos/{REPO}/rulesets?per_page=100")
    found = next((r for r in listed if r["name"] == RULESET_NAME), None)
    if found is None:
        return [Step(f"ruleset {RULESET_NAME}: create", "POST", f"repos/{REPO}/rulesets", RULESET)]
    path = f"repos/{REPO}/rulesets/{found['id']}"
    if covers(api_get(run, path), RULESET):
        return [Step(f"ruleset {RULESET_NAME}: ok")]
    return [Step(f"ruleset {RULESET_NAME}: update", "PUT", path, RULESET)]


# Branch `deploy` is published to the live site by pages.yml without review, so only the CD
# workflow (the GitHub Actions app, through GITHUB_TOKEN) may move it. Without this, any
# credential with contents write on the repository could push straight to prod. Apply it after
# the first CD run has created the branch, then confirm the next CD run still passes.
DEPLOY_RULESET_NAME = "deploy-branch"
DEPLOY_RULESET: dict[str, Any] = {
    "name": DEPLOY_RULESET_NAME,
    "target": "branch",
    "enforcement": "active",
    "bypass_actors": [
        {"actor_id": GITHUB_ACTIONS_APP_ID, "actor_type": "Integration", "bypass_mode": "always"}
    ],
    "conditions": {"ref_name": {"include": ["refs/heads/deploy"], "exclude": []}},
    "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "update"}],
}


def plan_deploy_ruleset(run: Gh) -> list[Step]:
    listed = api_get(run, f"repos/{REPO}/rulesets?per_page=100")
    found = next((r for r in listed if r["name"] == DEPLOY_RULESET_NAME), None)
    if found is None:
        return [
            Step(
                f"ruleset {DEPLOY_RULESET_NAME}: create",
                "POST",
                f"repos/{REPO}/rulesets",
                DEPLOY_RULESET,
            )
        ]
    path = f"repos/{REPO}/rulesets/{found['id']}"
    if covers(api_get(run, path), DEPLOY_RULESET):
        return [Step(f"ruleset {DEPLOY_RULESET_NAME}: ok")]
    return [Step(f"ruleset {DEPLOY_RULESET_NAME}: update", "PUT", path, DEPLOY_RULESET)]


PHASES: dict[str, list[Callable[[Gh], list[Step]]]] = {
    "bootstrap": [plan_repo_settings, plan_labels, plan_pages, plan_actions],
    "protect": [plan_ruleset],
    "protect-deploy": [plan_deploy_ruleset],
}
PHASES["all"] = [
    *PHASES["bootstrap"],
    *PHASES["protect"],
]  # protect-deploy is applied separately, after CD ran once


def apply_phase(phase: str, dry_run: bool, run: Gh, out: TextIO) -> list[Step]:
    steps: list[Step] = []
    for planner in PHASES[phase]:
        steps.extend(planner(run))
    for step in steps:
        if step.method is None:
            out.write(f"  ok      {step.summary}\n")
            continue
        if not dry_run:
            run(["api", "-X", step.method, step.path, "--input", "-"], json.dumps(step.body))
        out.write(f"  {'would' if dry_run else 'done':<7} {step.summary}\n")
    changes = sum(step.method is not None for step in steps)
    outcome = "planned, nothing applied (dry run)" if dry_run else "applied"
    out.write(f"{REPO} phase={phase}: {changes} change(s) {outcome}\n")
    return steps


def main(argv: list[str] | None = None, run: Gh = gh, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--phase", choices=sorted(PHASES), required=True)
    parser.add_argument("--dry-run", action="store_true", help="read state and print the plan only")
    args = parser.parse_args(argv)
    try:
        apply_phase(args.phase, args.dry_run, run, out)
    except (GhError, RuntimeError) as err:
        sys.stderr.write(f"error: {err}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
