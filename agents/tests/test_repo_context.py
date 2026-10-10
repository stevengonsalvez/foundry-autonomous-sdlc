"""The orchestrator pre-fetches repository context for the test designer so it rarely needs tools."""

from __future__ import annotations

from conftest import World
from test_scenarios import open_scenario

from sdlc_agents import repo_context, state

HELPERS = ('import { vi } from "vitest";\nexport function fakeService() {}\n'
           "export function renderApp() {}\nexport function deferred<T>() {}\n")
APP = {
    "app/package.json": '{"workspaces": ["core", "api", "web"]}',
    "app/web/src/pages/ParcelPage.tsx": "export function ParcelPage() { /* status badge, estimated delivery */ }",
    "app/web/src/pages/HomePage.tsx": "export function HomePage() { return 'Track your parcel'; }",
    "app/web/tests/helpers.tsx": HELPERS,
    "app/web/tests/setup.ts": 'import "@testing-library/jest-dom/vitest";',
    "app/web/tests/parcel-page.test.tsx": 'import { describe, expect, it } from "vitest";\n// parcel page tests',
    "app/web/tests/home-page.test.tsx": 'import { describe, expect, it } from "vitest";\n// home page tests',
    "app/core/src/index.ts": 'export * from "./tracking-number";',
    "app/core/src/tracking-number.ts": "export function isValidTrackingNumber(s: string) { return true; }",
    "app/core/tests/tracking-number.test.ts": 'import { expect, it } from "vitest";',
    "app/api/src/server.ts": "// parcels endpoint",
    "app/web/dist/bundle.js": "minified",
    "app/node_modules/react/index.js": "lib",
    "app/package-lock.json": "{}",
    "infra/main.tf": "resource",
}


def seed(world: World, files: dict[str, str] = APP) -> None:
    for path, text in files.items():
        world.gh.files[("main", path)] = text


def test_listing_keeps_source_paths_under_app_only() -> None:
    listed = repo_context.listable(list(APP))
    assert "app/web/src/pages/ParcelPage.tsx" in listed and "app/package.json" in listed
    assert not [p for p in listed if "node_modules" in p or "/dist/" in p or p.endswith("package-lock.json")]
    assert "infra/main.tf" not in listed


def test_selection_picks_the_page_its_test_template_and_the_helpers() -> None:
    chosen = repo_context.select(list(APP), "Show the estimated delivery date on the parcel page", APP.get)
    assert chosen.sources[0] == "app/web/src/pages/ParcelPage.tsx"
    assert chosen.template == "app/web/tests/parcel-page.test.tsx"
    assert chosen.helpers == "app/web/tests/helpers.tsx"


def test_selection_uses_file_text_and_finds_the_workspace_template() -> None:
    chosen = repo_context.select(list(APP), "Lowercase tracking numbers are rejected as invalid", APP.get)
    assert chosen.sources[0] == "app/core/src/tracking-number.ts"
    assert chosen.template == "app/core/tests/tracking-number.test.ts" and chosen.helpers is None


def test_context_lists_exports_and_puts_the_template_first() -> None:
    _, text = repo_context.build(list(APP), "estimated delivery on the parcel page", APP.get)
    assert text.index("Exports of app/web/tests/helpers.tsx") < text.index("=== FILE app/web/tests/parcel-page")
    assert 'Exports of app/web/tests/helpers.tsx (import from "./helpers"): deferred, fakeService, renderApp' in text
    assert "Exports of @parcel/core: isValidTrackingNumber" in text
    assert text.index("=== FILE app/web/tests/parcel-page.test.tsx") < text.index("=== FILE app/web/src/pages/Parcel")


def test_context_text_is_capped() -> None:
    big = {**APP, "app/web/src/pages/ParcelPage.tsx": "parcel page " * 5_000}
    paths, text = repo_context.build(list(big), "parcel page", big.get)
    assert len(text) <= repo_context.MAX_CONTEXT_CHARS + 600
    assert "=== FILE app/web/src/pages/ParcelPage.tsx ===" in text and "[truncated]" in text
    assert paths.splitlines()[0] == "app/api/src/server.ts"


def test_test_designer_gets_the_file_list_and_relevant_files_inside_the_untrusted_tags(world: World) -> None:
    seed(world)
    n = open_scenario(world, "a")
    world.drive(lambda: state.TESTS_WRITTEN in world.gh.labels(n))
    sent = world.foundry.agent_calls("sdlc-test-designer")[0]
    files = sent.split("name=source_files>\n", 1)[1]
    assert "name=repo_files>\napp/api/src/server.ts" in sent
    assert "=== FILE app/web/tests/parcel-page.test.tsx ===" in files
    assert "node_modules" not in sent and "infra/main.tf" not in sent
    assert world.gh.calls.count("list_tree") == 1


def test_an_empty_repository_still_designs_tests(world: World) -> None:
    n = open_scenario(world, "a")
    world.drive(lambda: state.TESTS_WRITTEN in world.gh.labels(n))
    assert "name=repo_files>" not in world.foundry.agent_calls("sdlc-test-designer")[0]
