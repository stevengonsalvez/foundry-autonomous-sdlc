"""Scope rules: which paths an engine may change in each mode."""

from __future__ import annotations

import pytest

from sdlc_agents.coder import scope


@pytest.mark.parametrize("path", [
    "app/api/tests/parcel.test.ts",
    "app/web/src/Home.test.tsx",
    "app/core/src/x.spec.ts",
    "app/e2e/golden.spec.ts",
    "app/e2e/fixtures/data.json",
    "app/core/tests/helpers.ts",
    "app/core/src/__fixtures__/shipments.json",
    "x.test.ts",
])
def test_test_globs_match_the_architecture_list(path: str) -> None:
    assert scope.is_test_path(path)


@pytest.mark.parametrize("path", [
    "app/api/src/server.ts", "app/web/src/Home.tsx", "app/package.json", "app/teste/x.ts", "app/x.test.js",
])
def test_non_test_paths_are_not_tests(path: str) -> None:
    assert not scope.is_test_path(path)


def test_within_allowed_is_a_directory_prefix_not_a_string_prefix() -> None:
    assert scope.within_allowed("app/api/src/x.ts", ("app/",))
    assert scope.within_allowed("app/api/src/x.ts", ("app",))
    assert not scope.within_allowed("apps/x.ts", ("app",))
    assert scope.within_allowed("README.md", ("README.md",))
    assert not scope.within_allowed("README.md.bak", ("README.md",))


@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "app/../.github/workflows/ci.yml", "", "app/./x"])
def test_unsafe_or_non_canonical_paths_are_never_allowed(path: str) -> None:
    assert not scope.is_safe_relative(path)
    assert not scope.within_allowed(path, ("app/",))


def test_feature_mode_rejects_outside_paths_and_protected_tests_only() -> None:
    changed = ["app/api/src/x.ts", ".github/workflows/ci.yml", "app/api/tests/a.test.ts", "app/api/tests/new.test.ts"]
    bad = scope.violations(changed, allowed_paths=("app/",), protected=("app/api/tests/a.test.ts",), tests_only=False)
    assert bad == [".github/workflows/ci.yml", "app/api/tests/a.test.ts"]


def test_maintenance_mode_allows_only_test_files_inside_allowed_paths() -> None:
    changed = ["app/web/src/Home.test.tsx", "app/web/src/Home.tsx", "tests/root.test.ts"]
    bad = scope.violations(changed, allowed_paths=("app/",), protected=(), tests_only=True)
    assert bad == ["app/web/src/Home.tsx", "tests/root.test.ts"]


@pytest.mark.parametrize("path", ["app/vitest.config.ts", "app/web/vitest.config.mts", "app/vitest.workspace.ts",
                                  "app/web/vitest.setup.ts"])
def test_test_runner_config_is_never_engine_editable(path: str) -> None:
    assert scope.violations([path], allowed_paths=("app/",), protected=(), tests_only=False) == [path]


@pytest.mark.parametrize("path", [".git/config", "app/.git/hooks/pre-commit", ".git/hooks/post-checkout"])
def test_git_metadata_is_never_in_scope_even_when_everything_is_allowed(path: str) -> None:
    assert not scope.within_allowed(path, (".",))
    assert scope.violations([path], allowed_paths=(".",), protected=(), tests_only=False) == [path]


def test_contained_path_accepts_plain_files_and_new_directories(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "app/src").mkdir(parents=True)
    assert scope.contained_path(tmp_path, "app/src/x.ts") == tmp_path.resolve() / "app/src/x.ts"
    assert scope.contained_path(tmp_path, "app/new/dir/y.ts") == tmp_path.resolve() / "app/new/dir/y.ts"


@pytest.mark.parametrize("path", [
    "../x", "/etc/passwd", "app/../../x", "a/../../x", "app\\..\\x", "app/\x00x", ".git/config",
    "app/link/x.ts", "app/filelink",
])
def test_contained_path_refuses_escapes_and_symlinks(tmp_path, path: str) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "app").mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "app/link").symlink_to(outside)
    (tmp_path / "app/filelink").symlink_to(outside / "f")
    assert scope.contained_path(tmp_path, path) is None


@pytest.mark.parametrize("path", ["App/x.ts", "app∕x.ts", "app/․․/x.ts", "app／..／x.ts"])
def test_case_and_unicode_lookalikes_stay_inside_or_out_of_scope(tmp_path, path: str) -> None:  # type: ignore[no-untyped-def]
    target = scope.contained_path(tmp_path, path)
    assert target is None or tmp_path.resolve() in target.parents
    assert not scope.within_allowed(path, ("app/",)) or path.startswith("app/")
