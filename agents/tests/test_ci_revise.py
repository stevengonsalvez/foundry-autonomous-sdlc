"""
Red required checks on an agent PR are worked on, not escalated at once:
- a failure inside the designed (protected) test files goes back to the test designer, like the
  coder's tests-invalid, and the coder rebuilds on a fresh branch;
- any other failure is triaged (sdlc-ci-triage) and the coder revises the PR with the CI error lines,
  at most two rounds; then escalated:build-failed with the last log line.
Also: the designer is told how this repo's branded types are built, and the lint catches the cheap
cases (a string literal for a branded field, a type imported without `import type`).
"""

from __future__ import annotations

from conftest import World
from test_scenarios import A_BODY

from sdlc_agents import designed_tests, repo_context, state
from sdlc_agents.definitions import AGENT_BY_NAME
from sdlc_agents.gates import REQUIRED_CHECKS

GREEN = dict.fromkeys(REQUIRED_CHECKS, "success")
REAL_BUG_LOG = ("> vitest run\n FAIL app/web/src/pages/ParcelPage.tsx > renders\n"
                "TypeError: Cannot read properties of undefined (reading 'estimatedDelivery')\n"
                "  at ParcelPage (app/web/src/pages/ParcelPage.tsx:41:12)\nTest Files  1 failed (6)\n")


def jobs(world: World) -> list[dict]:
    return [body["job"] for _, body, _ in world.foundry.hosted if body["op"] == "start"]


def red_until_revised(world: World, check: str = "test", log: str = REAL_BUG_LOG):  # type: ignore[no-untyped-def]
    """CI red on every head that has no revise commit yet, green after one."""
    def ci(gh, _number, sha):  # type: ignore[no-untyped-def]
        revised = "fix: address review findings" in gh.commits[sha]["message"]
        if revised:
            return dict(GREEN)
        gh.logs[(sha, check)] = log
        return {**GREEN, check: "failure"}
    world.gh.ci = ci


def test_ci_failure_from_a_real_bug_is_revised_by_the_coder_then_merged(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    red_until_revised(world)
    foundry.script("sdlc-ci-triage", {"cause": "real-bug", "explanation": "ParcelPage reads a missing field.",
                                      "test_files": []})
    n = gh.open_issue("Show the estimated delivery date", A_BODY)

    world.drive(lambda: state.RELEASED in gh.labels(n))

    started = jobs(world)
    assert [j["mode"] for j in started] == ["feature", "revise"]
    notes = started[1]["spec"]["notes"]
    assert "CI check test failed" in notes and "Cannot read properties of undefined" in notes
    assert "ParcelPage reads a missing field." in notes
    st = gh.state_of(n)
    assert st["ci_revise"]["rounds"] == 1 and len(gh.merges) == 1
    triage_input = foundry.agent_calls("sdlc-ci-triage")[0]
    assert "name=log>" in triage_input and "estimatedDelivery" in triage_input


def test_ci_failure_inside_the_designed_tests_goes_back_to_the_designer(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    tsc = (f"app/web/tests/issue-{n}.test.tsx(3,10): error TS2322: Type 'string' is not assignable to type "
           "'TrackingNumber'.\n")
    rebuilt = {"done": False}

    def ci(gh_, _number, sha):  # type: ignore[no-untyped-def]
        branch_rebuilt = any(p["head_ref"].endswith("-r1") and gh_.head_of(k) == sha for k, p in gh_.pulls.items())
        if branch_rebuilt:
            rebuilt["done"] = True
            return dict(GREEN)
        gh_.logs[(sha, "test")] = "> tsc --noEmit\n" + tsc
        return {**GREEN, "test": "failure"}

    gh.ci = ci
    world.drive(lambda: state.RELEASED in gh.labels(n))

    assert rebuilt["done"] and not foundry.agent_calls("sdlc-ci-triage")
    repair_input = foundry.agent_calls("sdlc-test-designer")[1]
    assert "error TS2322" in repair_input.split("name=repair_reason>", 1)[1]
    first_pr = next(k for k, p in gh.pulls.items() if p["head_ref"] == f"agent/issue-{n}")
    assert gh.issues[first_pr]["state"] == "closed" and not gh.pulls[first_pr]["merged"]
    assert gh.state_of(n)["pr"]["branch"] == f"agent/issue-{n}-r1" and len(gh.merges) == 1


def test_two_ci_revisions_that_stay_red_escalate_with_the_last_log_line(world: World) -> None:
    gh = world.gh

    def always_red(gh_, _number, sha):  # type: ignore[no-untyped-def]
        gh_.logs[(sha, "e2e")] = "Running 3 tests\n  1 failed\nError: expect(locator).toBeVisible() failed\n"
        return {**GREEN, "e2e": "failure"}

    gh.ci = always_red
    world.foundry.defaults["sdlc-ci-triage"] = {"cause": "real-bug", "explanation": "UI regression.",
                                                "test_files": []}
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n), max_ticks=60)
    assert [j["mode"] for j in jobs(world)] == ["feature", "revise", "revise"]
    reason = gh.state_of(n)["escalation"]["reasons"][0]
    assert "e2e" in reason and "after 2 CI revise rounds" in reason
    assert "Error: expect(locator).toBeVisible() failed" in reason and gh.merges == []


def test_tsc_lines_from_the_coder_are_a_tests_invalid_repair_like_any_other(world: World) -> None:
    world.coder.outcomes = ["failed:tests-invalid"]
    world.coder.invalid_detail = ("app/web/tests/issue-1.test.tsx(5,22): error TS2345: Argument of type '\"PK1\"' "
                                  "is not assignable to parameter of type 'TrackingNumber'.")
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.RELEASED in world.gh.labels(n))
    repair = world.foundry.agent_calls("sdlc-test-designer")[1].split("name=repair_reason>", 1)[1]
    assert "error TS2345" in repair


def test_designer_prompt_states_the_typecheck_and_branded_type_rules() -> None:
    text = AGENT_BY_NAME["sdlc-test-designer"].instructions
    for rule in ("tsc --noEmit", "import type", "branded", "as TrackingNumber", "unused"):
        assert rule in text, rule


DOMAIN = (
    'export type TrackingNumber = string & { readonly __brand: "TrackingNumber" };\n'
    "export interface Parcel {\n  trackingNumber: TrackingNumber;\n  status: string;\n}\n"
    "export type Status = \"delivered\" | \"in_transit\";\n"
)
REPO = {
    "app/core/src/index.ts": 'export * from "./domain";\nexport * from "./tracking-number";',
    "app/core/src/domain.ts": DOMAIN,
    "app/core/src/tracking-number.ts": "export function parseTrackingNumber(s: string) { return null; }",
    "app/web/tests/helpers.tsx": "export function fakeService() {}",
}


def test_context_explains_how_to_build_branded_values() -> None:
    _, text = repo_context.build(list(REPO), "tracking number parcel", REPO.get)
    assert 'Branded types in @parcel/core: TrackingNumber (string): write "PK1000000001" as TrackingNumber' in text


def lint(content: str) -> list[str]:
    return designed_tests.lint([{"path": "app/web/tests/a.test.tsx", "content": content}], set(REPO), REPO.get)


def test_lint_flags_a_string_literal_for_a_branded_field() -> None:
    errors = lint('import { expect, it } from "vitest";\nconst parcel = { trackingNumber: "PK1000000001" };')
    assert any("trackingNumber is a TrackingNumber" in e for e in errors), errors
    ok = 'import { expect, it } from "vitest";\nimport type { TrackingNumber } from "@parcel/core";\n' \
         'const parcel = { trackingNumber: "PK1000000001" as TrackingNumber };'
    assert lint(ok) == []


def test_lint_flags_a_type_imported_as_a_value() -> None:
    errors = lint('import { expect, it } from "vitest";\nimport { Parcel, parseTrackingNumber } from "@parcel/core";')
    assert errors == ["app/web/tests/a.test.tsx: Parcel is a type: import it with `import type` "
                      "(verbatimModuleSyntax)"]
    assert lint('import { it } from "vitest";\nimport { type Parcel, parseTrackingNumber } from "@parcel/core";') == []
