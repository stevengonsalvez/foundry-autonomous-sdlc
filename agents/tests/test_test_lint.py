"""Designed tests are checked in code before the coder sees them (imports, globals, paths)."""

from __future__ import annotations

import pytest

from sdlc_agents import designed_tests as test_lint

REPO = {
    "app/web/tests/helpers.tsx": (
        'import { vi } from "vitest";\n'
        "export function fakeService() {}\nexport function renderApp() {}\nexport function deferred<T>() {}\n"
    ),
    "app/web/tests/parcel-page.test.tsx": 'import { describe, expect, it } from "vitest";',
    "app/web/src/pages/ParcelPage.tsx": "export function ParcelPage() {}\nexport default ParcelPage;",
    "app/web/src/format.ts": "export const formatDate = () => '';\nexport { formatDate as formatDay };",
    "app/core/src/index.ts": 'export * from "./domain";\nexport * from "./tracking-number";',
    "app/core/src/domain.ts": "export type Parcel = {};\nexport interface ParcelService {}\nexport enum Status {}",
    "app/core/src/tracking-number.ts": (
        "export function normaliseTrackingNumber() {}\nexport class InvalidTrackingNumberError {}"
    ),
}

GOOD = """import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { normaliseTrackingNumber, type Parcel } from "@parcel/core";
import { fakeService, renderApp } from "./helpers";
import ParcelPage, { ParcelPage as Page } from "../src/pages/ParcelPage";
import { formatDay } from "../src/format";

describe("estimated delivery", () => {
  it("shows the date", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");
    expect(await screen.findByText("Estimated delivery: Mon 12 Oct 2026")).toBeInTheDocument();
  });
});
"""


def lint(content: str, path: str = "app/web/tests/estimated-delivery.test.tsx") -> list[str]:
    return test_lint.lint([{"path": path, "content": content}], set(REPO), REPO.get)


def test_a_well_formed_test_passes() -> None:
    assert lint(GOOD) == []


@pytest.mark.parametrize(
    "content, error",
    [
        (
            'import { describe, it } from "vitest";\ndescribe("x", () => { it("y", () => { expect(1).toBe(1); }); });',
            "uses expect without importing it from vitest",
        ),
        ('describe("x", () => {});', "uses describe without importing it from vitest"),
        ('import { it } from "vitest";\nit("x", () => { vi.fn(); });', "uses vi without importing it from vitest"),
        ('import { it } from "vitest";\nimport { x } from "./nope";', "./nope does not resolve to a file"),
        ('import { it } from "vitest";\nimport lodash from "lodash";', "lodash is not an allowed package"),
        (
            'import { it } from "vitest";\nimport { renderPage } from "./helpers";',
            "renderPage is not exported by app/web/tests/helpers.tsx",
        ),
        (
            'import { it } from "vitest";\nimport { getEta } from "@parcel/core";',
            "getEta is not exported by @parcel/core",
        ),
        (
            'import { it } from "vitest";\nimport Format from "../src/format";',
            "default is not exported by app/web/src/format.ts",
        ),
        ('import { it } from "vitest";\nconst m = await import("../src/missing");', "../src/missing does not resolve"),
    ],
)
def test_lint_reports_each_problem(content: str, error: str) -> None:
    errors = lint(content)
    assert any(error in e for e in errors), errors


def test_paths_must_be_test_files_in_a_workspace_tests_folder() -> None:
    errors = lint(GOOD, "app/web/src/pages/estimated.test.tsx")
    assert errors == ["app/web/src/pages/estimated.test.tsx: must be app/<workspace>/tests/**/*.test.ts(x)"]


def test_property_calls_named_like_globals_are_not_flagged() -> None:
    body = 'import { expect, it } from "vitest";\nit("x", () => { const s = { describe() {} }; s.describe(); });'
    assert lint(body) == []


def test_imports_between_designed_files_resolve() -> None:
    tests = [
        {
            "path": "app/web/tests/a.test.tsx",
            "content": 'import { it } from "vitest";\nimport { b } from "./b-helpers";',
        },
        {"path": "app/web/tests/b-helpers.ts", "content": "export const b = 1;"},
    ]
    assert test_lint.lint(tests, set(REPO), REPO.get) == [
        "app/web/tests/b-helpers.ts: must be app/<workspace>/tests/**/*.test.ts(x)"
    ]


def test_exports_listing() -> None:
    assert test_lint.exports_of("app/web/tests/helpers.tsx", REPO.get) == {"fakeService", "renderApp", "deferred"}
    core = test_lint.exports_of("app/core/src/index.ts", REPO.get, set(REPO))
    assert core == {"Parcel", "ParcelService", "Status", "normaliseTrackingNumber", "InvalidTrackingNumberError"}
    assert test_lint.exports_of("app/missing.ts", REPO.get) is None
