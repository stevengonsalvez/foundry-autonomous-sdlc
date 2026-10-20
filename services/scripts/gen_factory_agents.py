"""Generate `factory/agents/<name>/{agent.md,schema.json}` from `sdlc_agents.definitions`.

definitions.py stays the single source of truth for prompts and output schemas. Run:

    uv run python scripts/gen_factory_agents.py            # write the files
    uv run python scripts/gen_factory_agents.py --check    # exit 1 when committed files drifted
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agents"))

from sdlc_agents import definitions  # noqa: E402

FACTORY_DIR = REPO_ROOT / "factory"
MODEL = "gemini-3.8-flash-medium"
ENGINE = "agy"


@dataclass(frozen=True)
class Profile:
    description: str
    agent_type: str
    effort: str = "medium"
    timeout_s: int = 300


# Cheap one-shot classifiers run at low effort; stages that judge code or write tests think longer.
PROFILES: dict[str, Profile] = {
    "sdlc-req-gate": Profile(
        "Scores an issue against the requirement-quality rubric and asks clarifying questions.",
        "SPEC", "low",
    ),
    "sdlc-product-owner": Profile(
        "Simulated product owner: answers clarifying questions on a demo issue.",
        "SPEC", "low",
    ),
    "sdlc-feasibility": Profile(
        "Decides whether an autonomous coder can build the issue safely.",
        "SPEC", "medium",
    ),
    "sdlc-test-designer": Profile(
        "Writes the failing tests the coder must make pass.",
        "SPEC", "high", 600,
    ),
    "sdlc-reviewer": Profile(
        "Independent code review of an agent pull request, bound to the head sha.",
        "REVIEW", "high", 600,
    ),
    "sdlc-triage": Profile(
        "Assigns severity and owning team to a bug report.",
        "TRIAGE", "low",
    ),
    "sdlc-ci-triage": Profile(
        "Classifies a failed test check as stale-test, regression or flake.",
        "TRIAGE", "medium",
    ),
    "sdlc-release-notes": Profile(
        "Writes short release notes for a merged change.",
        "CUSTOM", "low",
    ),
    "sdlc-ui-tester": Profile(
        "Inspects rendered screenshots for layout regressions.",
        "VERIFY", "medium", 600,
    ),
}

FOREMAN_INSTRUCTIONS = """\
You are the foreman of the autonomous SDLC factory. You are a deterministic workflow, not a prompt agent:
one Temporal WorkItemWorkflow per GitHub issue or pull request (workflow id issue-N or pr-N).

Loop for each work item:
1. load_context: read the issue, labels, pull request, checks and the state comment.
2. machine.next_action (pure, from sdlc_agents.machine) picks the next step.
3. Run the matching activity: requirement gate, product owner answer, feasibility, test design,
   coder, CI triage, review, verify_merge, release.
4. Wait on a durable timer or on the signals checks_changed, pr_changed and human_approved.

Rules:
- Only issues opened by the repository owner are processed. Anything else is ignored, with no spend.
- Spend is fail-closed: when budget accounting cannot be determined, no spending step runs.
- humanGates.spec and humanGates.merge in factory.yaml hold the workflow until human_approved arrives.
  verify_merge runs in full whether or not the merge gate is on.
- The foreman task queue runs one activity at a time, which serialises metrics and release tag
  reservation across work items.
- Quota errors park the workflow on a durable timer; after the bound the item is escalated with
  escalated:agent-quota. Authentication errors escalate at once, with no retry.
"""

CODER_INSTRUCTIONS = """\
You are the coder. You implement one GitHub issue inside a disposable checkout of the target repository
and push the result to a branch for review.

Process:
1. Read the issue, the spec and the designed tests. The designed failing tests are committed first (red).
2. Make the tests pass with the smallest correct change (green), then tidy with the tests still green.
3. Touch only paths inside the job's allowed scope. Never edit, delete or weaken a designed test.
4. Never read or print credentials. Network access is limited to the allow-list proxy.
5. Finish by stating what you changed and which tests prove it.

An exit with no edits is a failure, not a success.
"""


def _frontmatter(profile: Profile, *, read_only: bool, output_kind: str) -> str:
    meta = {
        "description": profile.description,
        "agentType": profile.agent_type,
        "engine": ENGINE,
        "model": MODEL,
        "effort": profile.effort,
        "timeoutS": profile.timeout_s,
        "readOnly": read_only,
        "outputKind": output_kind,
    }
    return yaml.safe_dump(meta, sort_keys=False, width=1000, allow_unicode=True)


def _agent_md(profile: Profile, instructions: str, *, read_only: bool, output_kind: str) -> str:
    front = _frontmatter(profile, read_only=read_only, output_kind=output_kind)
    return f"---\n{front}---\n\n{instructions.strip()}\n"


def render_all() -> dict[str, str]:
    """Relative path under factory/ -> file text, for every generated file."""
    files: dict[str, str] = {}
    for agent in definitions.AGENTS:
        profile = PROFILES[agent.name]
        files[f"agents/{agent.name}/agent.md"] = _agent_md(
            profile, agent.instructions, read_only=True, output_kind=agent.output_kind
        )
        if agent.schema is not None:
            files[f"agents/{agent.name}/schema.json"] = json.dumps(agent.schema, indent=2) + "\n"
    files["agents/foreman/agent.md"] = _agent_md(
        Profile("Workflow that drives one issue or pull request from intake to release.", "FOREMAN", "medium", 3600),
        FOREMAN_INSTRUCTIONS,
        read_only=False,
        output_kind="markdown",
    )
    files["agents/coder/agent.md"] = _agent_md(
        Profile(
            "Implements an issue test-first in an isolated checkout and pushes a branch.", "IMPLEMENT", "high", 900
        ),
        CODER_INSTRUCTIONS,
        read_only=False,
        output_kind="markdown",
    )
    return files


def write_all(factory_dir: Path) -> list[Path]:
    written = []
    for rel, text in sorted(render_all().items()):
        target = factory_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def check(factory_dir: Path) -> list[str]:
    """Relative paths whose on-disk content differs from the generator output (or is missing)."""
    drifted = []
    for rel, text in sorted(render_all().items()):
        target = factory_dir / rel
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            drifted.append(rel)
    return drifted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=FACTORY_DIR, help="factory directory (default: ./factory)")
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    args = parser.parse_args(argv)
    if args.check:
        drifted = check(args.out)
        for rel in drifted:
            print(f"drifted: {rel}", file=sys.stderr)
        return 1 if drifted else 0
    for path in write_all(args.out):
        print(f"wrote {path.relative_to(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
