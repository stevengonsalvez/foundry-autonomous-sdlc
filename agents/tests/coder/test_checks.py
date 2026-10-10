"""Typecheck and lint output (npm workspaces running tsc, eslint stylish) parsed into error lines."""

from __future__ import annotations

from sdlc_agents.coder import checks

ROOT = "/srv/sdlc-work/j-15-1/checkout"

TSC = f"""
> parcel-tracker@0.1.0 typecheck
> npm run typecheck --workspaces --if-present


> @parcel/web@0.1.0 typecheck
> tsc --noEmit

tests/last-updated.test.tsx(24,7): error TS2322: Type 'string' is not assignable to type 'TrackingNumber'.
src/eta.ts(3,1): error TS2304: Cannot find name 'foo'.
  Additional detail line that tsc indents.
npm error Lifecycle script `typecheck` failed with error:
npm error code 2
npm error path {ROOT}/app/web
"""

ESLINT = f"""
{ROOT}/app/web/tests/last-updated.test.tsx
  12:5  error    'x' is assigned a value but never used  @typescript-eslint/no-unused-vars
  14:1  warning  Unexpected console statement            no-console

{ROOT}/app/core/src/money.ts
  2:10  error  Parsing error: Unexpected token

x 3 problems (2 errors, 1 warning)
"""


def test_tsc_errors_are_parsed_with_code_and_position() -> None:
    result = checks.parse("npm run typecheck", 2, TSC, ROOT)
    assert not result.passed
    assert result.lines() == [
        "tests/last-updated.test.tsx(24,7): error TS2322: Type 'string' is not assignable to type 'TrackingNumber'.",
        "src/eta.ts(3,1): error TS2304: Cannot find name 'foo'.",
    ]


def test_eslint_errors_are_parsed_relative_to_the_checkout_and_warnings_ignored() -> None:
    result = checks.parse("npm run lint", 1, ESLINT, ROOT)
    assert result.lines() == [
        "app/web/tests/last-updated.test.tsx(12,5): error @typescript-eslint/no-unused-vars: "
        "'x' is assigned a value but never used",
        "app/core/src/money.ts(2,10): error Parsing error: Unexpected token",
    ]
    assert ROOT not in "\n".join(result.lines())


def test_errors_in_new_test_files_are_named_by_repo_path() -> None:
    results = [checks.parse("npm run typecheck", 2, TSC, ROOT), checks.parse("npm run lint", 1, ESLINT, ROOT)]
    found = checks.errors_in(results, ["app/web/tests/last-updated.test.tsx"], workdir="app")
    assert found == [
        "app/web/tests/last-updated.test.tsx(24,7): error TS2322: "
        "Type 'string' is not assignable to type 'TrackingNumber'.",
        "app/web/tests/last-updated.test.tsx(12,5): error @typescript-eslint/no-unused-vars: "
        "'x' is assigned a value but never used",
    ]
    assert checks.errors_in(results, ["app/web/tests/other.test.ts"], workdir="app") == []


def test_a_failure_without_parsable_errors_falls_back_to_the_output_tail() -> None:
    result = checks.parse("npm run lint", 1, "npm error Missing script: \"lint\"\n", ROOT)
    assert result.lines() == ['npm error Missing script: "lint"']
    assert checks.parse("npm run lint", 0, "all good\n", ROOT).lines() == []


def test_lines_are_capped_and_summaries_name_the_command() -> None:
    many = "\n".join(f"src/a.ts({i},1): error TS1005: ';' expected." for i in range(1, 60))
    result = checks.parse("npm run typecheck", 2, many, ROOT)
    assert len(result.lines()) == checks.MAX_CHECK_LINES == 40
    assert result.summary() == "`npm run typecheck`: failed (59 errors)"
    assert checks.parse("npm run lint", 0, "", ROOT).summary() == "`npm run lint`: passed"
    assert checks.CHECK_COMMANDS == ("npm run typecheck", "npm run lint")
