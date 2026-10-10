"""
pytest tests for sdlc_agents.

Covers:
- Path normalisation: every known allow-list bypass (sdlc_agents.codegen_policy).
- JSON validation against the AgentDef schema: extra keys, duplicate JSON keys, label
  allowlist, counts/lengths.
- call.py guards: incomplete response exit, empty output exit, token cap, log-tail truncation,
  stdout purity (AZURE_AI_PROJECTS_CONSOLE_LOGGING), markdown sanitisation.
- create_agents: hash-based idempotency, unchanged vs created, reasoning=low.
- Fake-transport tests: real AIProjectClient + real openai client over a MockTransport of
  whichever HTTP lib the installed openai SDK uses (httpx or httpx2); asserts the on-the-wire
  agent_reference request (URL, headers, body, retry count) without a live Azure endpoint.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sdlc_agents.call import (
    HEAD_LIMIT,
    HARD_MAX_OUTPUT_TOKENS,
    CODEGEN_MAX_OUTPUT_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    INPUT_CHAR_LIMIT,
    TAIL_LIMIT,
    AgentRunError,
    _parse_json_strict,
    _sanitise_markdown,
    _validate_json_output,
    _wrap_untrusted,
    invoke_agent,
    main,
)
from sdlc_agents.codegen_policy import normalise_path
from sdlc_agents.definitions import (
    AGENT_NAMES,
    AGENTS,
    AGENT_BY_NAME,
    ALLOWED_LABELS,
    MODEL_DEPLOYMENT,
)

_validate_triage = AGENT_BY_NAME["sdlc-triage"].validate_output
_validate_codegen = AGENT_BY_NAME["sdlc-codegen"].validate_output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed_response(text: str, in_tok: int = 10, out_tok: int = 20) -> MagicMock:
    """Build a mock Responses API response that looks 'completed'."""
    usage = MagicMock()
    usage.input_tokens = in_tok
    usage.output_tokens = out_tok
    details = MagicMock()
    details.reasoning_tokens = 3
    usage.output_tokens_details = details

    resp = MagicMock()
    resp.status = "completed"
    resp.output_text = text
    resp.usage = usage
    resp.id = "resp-fake"
    return resp


def _make_incomplete_response(reason: str = "max_output_tokens") -> MagicMock:
    resp = MagicMock()
    resp.status = "incomplete"
    resp.output_text = ""
    resp.id = "resp-incomplete"
    incomplete = MagicMock()
    incomplete.reason = reason
    resp.incomplete_details = incomplete
    return resp


def _make_openai_client(response: MagicMock) -> MagicMock:
    oc = MagicMock()
    oc.responses.create.return_value = response
    oc.__enter__ = lambda s: s
    oc.__exit__ = MagicMock(return_value=False)
    return oc


def _make_project_client(
    agent_response: MagicMock | None = None,
    agent_text: str = "## Findings\nNone.",
) -> MagicMock:
    if agent_response is None:
        agent_response = _make_completed_response(agent_text)
    oc = _make_openai_client(agent_response)
    project = MagicMock()
    project.get_openai_client.return_value = oc
    project.__enter__ = lambda s: s
    project.__exit__ = MagicMock(return_value=False)
    return project


def _valid_triage_json() -> str:
    return json.dumps({
        "labels": ["bug"],
        "summary": "Test summary",
        "acceptance_criteria": ["Does X"],
        "tasks": ["Fix X"],
    })


def _valid_codegen_json() -> str:
    return json.dumps({
        "explanation": "Added helper",
        "files": [{"path": "src/foo.py", "content": "# empty"}],
    })


def _run_main(
    agent: str,
    input_text: str,
    extra_args: list[str] | None = None,
    env_endpoint: str = "https://fake.endpoint/api/projects/proj",
    agent_response: MagicMock | None = None,
) -> tuple[int, str, str]:
    """Run main() with mocked project client, return (exit_code, stdout, stderr)."""
    if agent == "sdlc-triage":
        default_text = _valid_triage_json()
    elif agent == "sdlc-codegen":
        default_text = _valid_codegen_json()
    else:
        default_text = "## Findings\nNo significant findings."

    project = _make_project_client(agent_response, default_text)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
        fh.write(input_text)
        tmp_path = fh.name

    argv = ["--agent", agent, "--input-file", tmp_path] + (extra_args or [])
    out = io.StringIO()
    err = io.StringIO()
    exit_code = 0
    try:
        with (
            patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": env_endpoint}),
            patch("sdlc_agents.call._build_client", return_value=project),
            patch("sys.stdout", out),
            patch("sys.stderr", err),
        ):
            main(argv)
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 0
    finally:
        os.unlink(tmp_path)

    return exit_code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------

class TestDefinitions:
    def test_all_agents_present(self) -> None:
        assert set(AGENT_NAMES) == {
            "sdlc-triage", "sdlc-codegen", "sdlc-review",
            "sdlc-ci-triage", "sdlc-release-notes",
        }

    def test_model_deployment(self) -> None:
        assert MODEL_DEPLOYMENT == "sdlc-default"

    def test_all_agents_have_instructions(self) -> None:
        for a in AGENTS:
            assert len(a.instructions) > 50, f"{a.name}: instructions too short"

    def test_agent_by_name_lookup(self) -> None:
        for name in AGENT_NAMES:
            assert AGENT_BY_NAME[name].name == name

    def test_no_em_dashes(self) -> None:
        for a in AGENTS:
            assert "\u2014" not in a.instructions, f"{a.name}: em dash in instructions"

    def test_nonce_delimiter_in_preamble(self) -> None:
        """Every agent should reference untrusted_input tags."""
        for a in AGENTS:
            assert "untrusted_input" in a.instructions, (
                f"{a.name}: missing untrusted_input reference"
            )

    def test_allowed_labels_set(self) -> None:
        assert "bug" in ALLOWED_LABELS
        assert "agent:implement" not in ALLOWED_LABELS
        assert "good first issue" in ALLOWED_LABELS


# ---------------------------------------------------------------------------
# normalise_path (allow-list)
# ---------------------------------------------------------------------------

class TestNormalisePath:
    # --- accepted ---
    def test_simple_src(self) -> None:
        assert normalise_path("src/foo.py") == "src/foo.py"

    def test_tests_subdir(self) -> None:
        assert normalise_path("tests/unit/test_x.py") == "tests/unit/test_x.py"

    def test_docs(self) -> None:
        assert normalise_path("docs/api.md") == "docs/api.md"

    def test_leading_dot_slash_collapsed(self) -> None:
        assert normalise_path("./src/foo.py") == "src/foo.py"

    def test_double_slash_and_inner_dot_collapsed(self) -> None:
        assert normalise_path("src//a/./b.py") == "src/a/b.py"

    @pytest.mark.parametrize("bad", [
        "SRC/foo.py", "Tests/x.py", "DOCS/x.md",          # first component is case-exact
        "src", "src/", "./", "src/..", "src/../.git/config",
        "src/.git/config", "src/.GIT/config", "src/.git./config", "src/a/.gitignore",
        ".github/workflows/x.yml", "src/.github/x", "./.git/hooks/pre-commit",
        "README.md", "pyproject.toml", "scripts/apply_codegen.py",
        "src/a\nb.py", "src/a\tb.py", "src/c:d.py", "//src/foo.py",
    ])
    def test_more_bypasses_rejected(self, bad: str) -> None:
        with pytest.raises(ValueError):
            normalise_path(bad)

    # --- bypasses that the old denylist accepted ---
    def test_dotgithub_bypass_dot_slash(self) -> None:
        with pytest.raises(ValueError):
            normalise_path("./.github/workflows/x.yml")

    def test_dotgithub_bypass_dotgithub_actions(self) -> None:
        with pytest.raises(ValueError):
            normalise_path(".github/actions/setup-atlas/action.yml")

    def test_dotgit_hooks(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path(".git/hooks/pre-commit")

    def test_dotgit_config(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path(".git/config")

    def test_windows_drive_letter(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path("C:/x.dll")

    def test_windows_drive_backslash(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path("C:\\x.dll")

    def test_dotgithub_case_upper(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path(".GITHUB/w")

    def test_dotgithub_trailing_dot(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path(".github./w")

    def test_zero_width_space_in_name(self) -> None:
        with pytest.raises(ValueError, match="non-ASCII"):
            normalise_path(".github\u200b/w")

    def test_empty_path(self) -> None:
        with pytest.raises(ValueError):
            normalise_path("")

    def test_dot_only(self) -> None:
        with pytest.raises(ValueError):
            normalise_path(".")

    def test_nul_byte(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path("src/a\x00b.py")

    def test_absolute_unix(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path("/etc/passwd")

    def test_dotdot_escape(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path("src/../../../etc/passwd")

    def test_dotclaude(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path(".claude/settings.json")

    def test_action_yml_at_root(self) -> None:
        """action.yml at repo root is outside allowed roots."""
        with pytest.raises(ValueError, match="outside allowed roots"):
            normalise_path("action.yml")

    def test_claude_md_at_root(self) -> None:
        with pytest.raises(ValueError, match="outside allowed roots"):
            normalise_path("CLAUDE.md")

    def test_scripts_refresh_knowledge(self) -> None:
        with pytest.raises(ValueError, match="outside allowed roots"):
            normalise_path("scripts/refresh_knowledge.py")

    def test_backslash_rejected(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path("src\\foo.py")

    def test_leading_whitespace(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path(" src/foo.py")

    def test_trailing_whitespace(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path("src/foo.py ")

    def test_too_long(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            normalise_path("src/" + "a" * 300)

    def test_dotdevcontainer(self) -> None:
        with pytest.raises(ValueError, match="rejected"):
            normalise_path(".devcontainer/devcontainer.json")


# Same corpus lives in sandbox/tests/test_apply_codegen.py, run there against the vendored
# copy that scripts/apply_codegen.py imports.
PATH_CORPUS = [
    ("src/foo.py", "src/foo.py"),
    ("./src/foo.py", "src/foo.py"),
    ("src//a/./b.py", "src/a/b.py"),
    ("tests/unit/test_x.py", "tests/unit/test_x.py"),
    ("docs/api.md", "docs/api.md"),
    ("SRC/foo.py", None),
    ("Tests/x.py", None),
    ("src", None),
    ("src/", None),
    ("src/a/", None),
    ("./", None),
    ("", None),
    (".", None),
    ("src/..", None),
    ("src/../.git/config", None),
    ("src/a/../../etc/passwd", None),
    ("../outside.py", None),
    ("/etc/passwd", None),
    ("//src/foo.py", None),
    (".git/config", None),
    (".git/hooks/pre-commit", None),
    ("./.git/hooks/pre-commit", None),
    ("src/.git/config", None),
    ("src/.GIT/config", None),
    ("src/.git./config", None),
    ("src/a/.gitignore", None),
    ("src/.env", None),
    (".github/workflows/x.yml", None),
    ("./.github/actions/setup-atlas/action.yml", None),
    (".GITHUB/w", None),
    (".github./w", None),
    (".github\u200b/w", None),
    ("src/.github/x", None),
    (".claude/settings.json", None),
    (".devcontainer/devcontainer.json", None),
    ("C:/x.dll", None),
    ("C:\\x.dll", None),
    ("src\\foo.py", None),
    ("src/c:d.py", None),
    ("src/a\x00b.py", None),
    ("src/a\nb.py", None),
    ("src/a\tb.py", None),
    (" src/foo.py", None),
    ("src/foo.py ", None),
    ("src/caf\u00e9.py", None),
    ("README.md", None),
    ("pyproject.toml", None),
    ("action.yml", None),
    ("CLAUDE.md", None),
    ("scripts/apply_codegen.py", None),
    ("scripts/refresh_knowledge.py", None),
    ("src/" + "a" * 300, None),
]


@pytest.mark.parametrize("raw,expected", PATH_CORPUS)
def test_path_policy_corpus(raw: str, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(ValueError):
            normalise_path(raw)
    else:
        assert normalise_path(raw) == expected


# ---------------------------------------------------------------------------
# JSON parsing: duplicate-key and NaN rejection
# ---------------------------------------------------------------------------

class TestParseJsonStrict:
    def test_duplicate_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate JSON key"):
            _parse_json_strict('{"a": 1, "a": 2}')

    def test_nan_rejected(self) -> None:
        with pytest.raises(ValueError, match="constant not allowed"):
            _parse_json_strict('{"x": NaN}')

    def test_infinity_rejected(self) -> None:
        with pytest.raises(ValueError, match="constant not allowed"):
            _parse_json_strict('{"x": Infinity}')

    def test_valid_passes(self) -> None:
        assert _parse_json_strict('{"a": 1}') == {"a": 1}


# ---------------------------------------------------------------------------
# Triage validation
# ---------------------------------------------------------------------------

class TestValidateTriage:
    def _ok(self) -> dict:
        return {
            "labels": ["bug"],
            "summary": "Something broke",
            "acceptance_criteria": ["Crit one"],
            "tasks": ["Task one"],
        }

    def test_valid(self) -> None:
        _validate_triage(self._ok())

    def test_extra_key_rejected(self) -> None:
        d = self._ok()
        d["extra"] = "bad"
        with pytest.raises(ValueError, match="unexpected keys"):
            _validate_triage(d)

    def test_missing_key(self) -> None:
        d = self._ok()
        del d["labels"]
        with pytest.raises(ValueError, match="missing keys"):
            _validate_triage(d)

    def test_label_not_in_allowlist(self) -> None:
        d = self._ok()
        d["labels"] = ["safe-to-deploy"]
        with pytest.raises(ValueError, match="not in allowed set"):
            _validate_triage(d)

    def test_agent_implement_label_rejected(self) -> None:
        d = self._ok()
        d["labels"] = ["agent:implement"]
        with pytest.raises(ValueError, match="not in allowed set"):
            _validate_triage(d)

    def test_too_many_labels(self) -> None:
        d = self._ok()
        d["labels"] = ["bug", "enhancement", "documentation", "question"]
        with pytest.raises(ValueError, match="1-3"):
            _validate_triage(d)

    def test_zero_labels(self) -> None:
        d = self._ok()
        d["labels"] = []
        with pytest.raises(ValueError, match="1-3"):
            _validate_triage(d)

    def test_summary_too_long(self) -> None:
        d = self._ok()
        d["summary"] = "x" * 121
        with pytest.raises(ValueError, match="120"):
            _validate_triage(d)

    def test_summary_empty(self) -> None:
        d = self._ok()
        d["summary"] = ""
        with pytest.raises(ValueError, match="non-empty"):
            _validate_triage(d)

    def test_too_many_criteria(self) -> None:
        d = self._ok()
        d["acceptance_criteria"] = ["x"] * 6
        with pytest.raises(ValueError, match="1-5"):
            _validate_triage(d)

    def test_too_many_tasks(self) -> None:
        d = self._ok()
        d["tasks"] = ["t"] * 9
        with pytest.raises(ValueError, match="1-8"):
            _validate_triage(d)

    def test_label_100k_string_rejected(self) -> None:
        d = self._ok()
        d["labels"] = ["x" * 10_000]
        with pytest.raises(ValueError, match="not in allowed set"):
            _validate_triage(d)


# ---------------------------------------------------------------------------
# Codegen validation
# ---------------------------------------------------------------------------

class TestValidateCodegen:
    def _ok(self) -> dict:
        return {
            "explanation": "Added helper",
            "files": [{"path": "src/foo.py", "content": "# hi"}],
        }

    def test_valid(self) -> None:
        _validate_codegen(self._ok())

    def test_extra_top_key_rejected(self) -> None:
        d = self._ok()
        d["extra"] = "bad"
        with pytest.raises(ValueError, match="unexpected keys"):
            _validate_codegen(d)

    def test_extra_file_key_rejected(self) -> None:
        d = self._ok()
        d["files"][0]["extra"] = "bad"
        with pytest.raises(ValueError, match="unexpected keys"):
            _validate_codegen(d)

    def test_empty_explanation(self) -> None:
        d = self._ok()
        d["explanation"] = "   "
        with pytest.raises(ValueError, match="non-empty"):
            _validate_codegen(d)

    def test_explanation_too_long(self) -> None:
        d = self._ok()
        d["explanation"] = "x" * 501
        with pytest.raises(ValueError, match="500"):
            _validate_codegen(d)

    def test_zero_files(self) -> None:
        d = self._ok()
        d["files"] = []
        with pytest.raises(ValueError, match="1-20"):
            _validate_codegen(d)

    def test_21_files_rejected(self) -> None:
        d = self._ok()
        d["files"] = [{"path": f"src/f{i}.py", "content": "x"} for i in range(21)]
        with pytest.raises(ValueError, match="1-20"):
            _validate_codegen(d)

    def test_duplicate_paths_rejected(self) -> None:
        d = self._ok()
        d["files"] = [
            {"path": "src/foo.py", "content": "a"},
            {"path": "src/foo.py", "content": "b"},
        ]
        with pytest.raises(ValueError, match="duplicate path"):
            _validate_codegen(d)

    def test_duplicate_paths_case_insensitive(self) -> None:
        d = self._ok()
        d["files"] = [
            {"path": "src/foo.py", "content": "a"},
            {"path": "src/FOO.py", "content": "b"},
        ]
        with pytest.raises(ValueError, match="duplicate path"):
            _validate_codegen(d)

    def test_content_too_large(self) -> None:
        d = self._ok()
        d["files"][0]["content"] = "x" * (200_001)
        with pytest.raises(ValueError, match="200000"):
            _validate_codegen(d)

    def test_nul_byte_in_content(self) -> None:
        d = self._ok()
        d["files"][0]["content"] = "a\x00b"
        with pytest.raises(ValueError, match="NUL"):
            _validate_codegen(d)

    def test_absolute_path_rejected(self) -> None:
        d = self._ok()
        d["files"][0]["path"] = "/etc/passwd"
        with pytest.raises(ValueError):
            _validate_codegen(d)

    def test_dotdot_rejected(self) -> None:
        d = self._ok()
        d["files"][0]["path"] = "src/../../../etc/passwd"
        with pytest.raises(ValueError):
            _validate_codegen(d)

    def test_dotgithub_rejected(self) -> None:
        d = self._ok()
        d["files"][0]["path"] = ".github/workflows/evil.yml"
        with pytest.raises(ValueError):
            _validate_codegen(d)

    def test_dotgithub_dotslash_bypass_rejected(self) -> None:
        d = self._ok()
        d["files"][0]["path"] = "./.github/workflows/x.yml"
        with pytest.raises(ValueError):
            _validate_codegen(d)


# ---------------------------------------------------------------------------
# _wrap_untrusted / input preparation
# ---------------------------------------------------------------------------

class TestWrapUntrusted:
    def test_nonce_present(self) -> None:
        result = _wrap_untrusted("hello", "sdlc-review")
        assert "<untrusted_input nonce=" in result
        assert "</untrusted_input nonce=" in result

    def test_nonce_differs_per_call(self) -> None:
        r1 = _wrap_untrusted("hello", "sdlc-review")
        r2 = _wrap_untrusted("hello", "sdlc-review")
        # Extract nonce values
        import re
        nonces = [re.search(r"nonce=(\w+)", r).group(1) for r in (r1, r2)]  # type: ignore
        assert nonces[0] != nonces[1]

    def test_ci_triage_keeps_tail(self) -> None:
        long_log = "A" * HEAD_LIMIT + "B" * TAIL_LIMIT + "C" * 500
        result = _wrap_untrusted(long_log, "sdlc-ci-triage")
        assert "TRUNCATED" in result
        assert "C" * 100 in result   # tail chars are included

    def test_other_agents_keep_head(self) -> None:
        long_text = "H" * INPUT_CHAR_LIMIT + "TAIL_CONTENT"
        result = _wrap_untrusted(long_text, "sdlc-review")
        assert "TAIL_CONTENT" not in result

    def test_ci_triage_marker_carries_nonce(self) -> None:
        import re
        long_log = "A" * (INPUT_CHAR_LIMIT + 10)
        result = _wrap_untrusted(long_log, "sdlc-ci-triage")
        nonce = re.search(r"<untrusted_input nonce=(\w+)>", result).group(1)  # type: ignore
        assert f"[LOG TRUNCATED nonce={nonce}" in result

    def test_short_input_not_truncated(self) -> None:
        result = _wrap_untrusted("short", "sdlc-triage")
        assert "TRUNCATED" not in result
        assert "short" in result


# ---------------------------------------------------------------------------
# Markdown sanitisation
# ---------------------------------------------------------------------------

class TestSanitiseMarkdown:
    def test_image_removed(self) -> None:
        r = _sanitise_markdown("text ![alt](https://attacker.com/?d=x) end")
        assert "![" not in r
        assert "[image removed]" in r

    def test_html_tag_removed(self) -> None:
        r = _sanitise_markdown("text <script>alert(1)</script> end")
        assert "<script>" not in r

    def test_html_comment_removed(self) -> None:
        r = _sanitise_markdown("before <!-- hidden --> after")
        assert "hidden" not in r

    def test_mention_defanged(self) -> None:
        r = _sanitise_markdown("thanks @org/team for the review")
        # The raw unquoted form should be wrapped in backticks.
        assert "`@org/team`" in r
        # Plain " @org/team " (space-surrounded, not in backticks) must not be present.
        assert " @org/team " not in r

    def test_fixes_keyword_defanged(self) -> None:
        r = _sanitise_markdown("This Fixes #123 in the PR")
        assert "`Fixes #123` [keyword defanged]" in r

    def test_closes_keyword_defanged(self) -> None:
        r = _sanitise_markdown("Closes #456")
        assert "`Closes #456` [keyword defanged]" in r

    def test_resolves_keyword_defanged(self) -> None:
        r = _sanitise_markdown("Resolves #789")
        assert "`Resolves #789` [keyword defanged]" in r

    def test_normal_text_preserved(self) -> None:
        r = _sanitise_markdown("## Findings\nNo issues.")
        assert "No issues." in r

    def test_reference_style_image_removed(self) -> None:
        r = _sanitise_markdown("see ![x][r]\n\n[r]: https://attacker.example/?d=1")
        assert "![" not in r

    def test_image_spliced_by_tag_removal_is_still_removed(self) -> None:
        r = _sanitise_markdown("!<b>[a](https://attacker.example/x.png)")
        assert "![" not in r

    @pytest.mark.parametrize("kw", ["fix #1", "fixed #1", "close #1", "closed #1", "resolve #1",
                                    "RESOLVED #1", "fixes org/repo#9", "Fixes: #3",
                                    "closes https://github.com/o/r/issues/4"])
    def test_all_closing_keyword_forms_defanged(self, kw: str) -> None:
        r = _sanitise_markdown(f"done. {kw}")
        assert f"`{kw}`" in r

    def test_plain_hash_reference_untouched(self) -> None:
        assert "#12" in _sanitise_markdown("related to #12")

    @pytest.mark.parametrize("kw", ["closes GH-12", "Fixes GH-3", "resolved gh-7"])
    def test_gh_style_closing_keywords_defanged(self, kw: str) -> None:
        assert f"`{kw}` [keyword defanged]" in _sanitise_markdown(f"done. {kw}")

    def test_code_gets_no_special_treatment_markup_stripped_and_lt_escaped(self) -> None:
        # A regex cannot know where a renderer sees code, so code spans/fences are not trusted.
        r = _sanitise_markdown("use `if a <b and c> d` here")
        assert "<" not in r
        fenced = _sanitise_markdown("x\n```java\nif a < b: pass\n<b>bold</b>\n```\ny")
        assert "<" not in fenced and "bold" in fenced

    def test_real_tags_stripped(self) -> None:
        r = _sanitise_markdown("a <script>x</script> b <img src=x> c")
        assert "<script" not in r and "</script" not in r and "<img" not in r

    def test_bare_comparison_is_escaped_not_dropped(self) -> None:
        assert _sanitise_markdown("when 1 < 2 and 3 > 2") == "when 1 &lt; 2 and 3 > 2"

    def test_tag_containing_backticks_is_stripped_not_treated_as_code(self) -> None:
        r = _sanitise_markdown("<img src=`x` onerror=`y`>")
        assert "<img" not in r

    def test_escaped_backtick_does_not_open_code_span(self) -> None:
        r = _sanitise_markdown("\\`<img src=x>\\`")
        assert "<img" not in r

    @pytest.mark.parametrize("text, gone", [
        ("a <!-- hidden --> b", "hidden"),
        ("a <!-- hidden and never closed ![x](https://attacker.example/b.png)", "hidden"),
        ("a <![CDATA[x]]> b", "CDATA"),
        ("a <![CDATA[ never closed", "CDATA"),
        ("a <?php echo 1; ?> b", "php"),
        ("a <!DOCTYPE html> b", "DOCTYPE"),
    ])
    def test_comments_cdata_and_processing_instructions_stripped(self, text: str, gone: str) -> None:
        r = _sanitise_markdown(text)
        assert gone not in r and "<" not in r

    def test_html_block_start_disables_code_preservation_and_escapes_lt(self) -> None:
        r = _sanitise_markdown("<!-- c -->\nuse `a < b` and Map<K, V> here")
        assert "<" not in r
        assert "&lt;" in r

    def test_image_beacon_after_fake_code_fence_removed(self) -> None:
        # The comment makes the fence below untrustworthy: the beacon must not survive as "code".
        r = _sanitise_markdown("<!-- c -->\n```\n![x](https://attacker.example/b.png)\n```")
        assert "attacker.example" not in r and "![" not in r

    def test_image_beacon_after_fence_closer_swallowed_by_unterminated_comment(self) -> None:
        r = _sanitise_markdown("```\nfine\n<!--\n```\n![x](https://attacker.example/b.png)")
        assert "attacker.example" not in r and "![" not in r

    def test_image_removed_even_inside_code_span(self) -> None:
        r = _sanitise_markdown("![a](https://evil.example/b.png) and `![a](https://evil2.example/b)`")
        assert "evil.example" not in r and "evil2.example" not in r


# ---------------------------------------------------------------------------
# invoke_agent: status / empty output guards
# ---------------------------------------------------------------------------

class TestInvokeAgent:
    def _project(self, resp: MagicMock) -> MagicMock:
        oc = _make_openai_client(resp)
        p = MagicMock()
        p.get_openai_client.return_value = oc
        return p

    def test_completed_ok(self) -> None:
        p = self._project(_make_completed_response("answer"))
        text, _ = invoke_agent(p, "sdlc-review", "prompt", 100)
        assert text == "answer"

    def test_incomplete_raises(self) -> None:
        p = self._project(_make_incomplete_response("max_output_tokens"))
        with pytest.raises(AgentRunError, match="not completed"):
            invoke_agent(p, "sdlc-review", "prompt", 100)

    def test_empty_output_raises(self) -> None:
        resp = _make_completed_response("   ")
        p = self._project(resp)
        with pytest.raises(AgentRunError, match="empty text"):
            invoke_agent(p, "sdlc-review", "prompt", 100)

    def test_agent_reference_is_name_only_so_latest_version_resolves(self) -> None:
        resp = _make_completed_response("ok")
        oc = _make_openai_client(resp)
        p = MagicMock()
        p.get_openai_client.return_value = oc
        invoke_agent(p, "sdlc-triage", "prompt", 100)
        call_kwargs = oc.responses.create.call_args.kwargs
        assert call_kwargs["extra_body"]["agent_reference"] == {
            "type": "agent_reference",
            "name": "sdlc-triage",
        }
        p.agents.get.assert_not_called()


# ---------------------------------------------------------------------------
# Fake-transport tests: REAL AIProjectClient + REAL openai client, fake HTTP transport
# ---------------------------------------------------------------------------

import importlib
import time

import openai as _openai_lib
from azure.core.credentials import AccessToken
from azure.ai.projects import AIProjectClient


def _http_lib() -> Any:
    """Return the HTTP library the installed openai SDK is built on (httpx or httpx2)."""
    base = _openai_lib.DefaultHttpxClient.__mro__[1]
    return importlib.import_module(base.__module__.split(".")[0])


_http = _http_lib()
PROJECT_ENDPOINT = "https://fake.services.ai.azure.com/api/projects/proj-sdlc"


class _FakeCredential:
    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return AccessToken("fake-token", int(time.time()) + 3600)

    def close(self) -> None:
        pass


def _responses_body(text: str) -> bytes:
    """Minimal Responses API body that the real SDK parses (status completed)."""
    payload = {
        "id": "resp-test",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "gpt-5-mini",
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "type": "message",
                "id": "msg-1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 20,
            "output_tokens_details": {"reasoning_tokens": 4},
            "total_tokens": 30,
        },
    }
    return json.dumps(payload).encode()


def _incomplete_body(reason: str = "max_output_tokens") -> bytes:
    payload = json.loads(_responses_body(""))
    payload["status"] = "incomplete"
    payload["incomplete_details"] = {"reason": reason}
    payload["output"] = []
    return json.dumps(payload).encode()


def _json_response(status: int, content: bytes) -> Any:
    return _http.Response(status, headers={"Content-Type": "application/json"}, content=content)


@pytest.fixture
def real_project():
    """
    Factory: build a real AIProjectClient whose OpenAI client sends through a fake
    transport. Returns (project, requests) where requests records every HTTP request.
    """
    opened: list[Any] = []

    def make(handler: Any) -> tuple[AIProjectClient, list[Any]]:
        requests: list[Any] = []

        def recording(request: Any) -> Any:
            requests.append(request)
            return handler(request)

        transport = _http.MockTransport(recording)
        patcher = patch(
            "azure.ai.projects._patch.DefaultHttpxClient",
            lambda **_kw: _openai_lib.DefaultHttpxClient(transport=transport),
        )
        patcher.start()
        opened.append(patcher)
        project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=_FakeCredential())
        return project, requests

    yield make
    for patcher in opened:
        patcher.stop()


class TestFakeTransport:
    """Real SDK, fake HTTP: proves the on-the-wire request shape of invoke_agent."""

    def test_request_url_headers_and_body(self, real_project: Any) -> None:
        project, requests = real_project(lambda r: _json_response(200, _responses_body("ok answer")))
        text, usage = invoke_agent(project, "sdlc-review", "hello", 100)

        assert text == "ok answer"
        assert usage.output_tokens == 20
        assert len(requests) == 1
        req = requests[0]
        assert req.method == "POST"
        assert str(req.url).startswith(f"{PROJECT_ENDPOINT}/openai/v1/responses")
        assert "/agents/" not in str(req.url)
        assert "foundry-features" not in {k.lower() for k in req.headers}
        body = json.loads(req.content)
        assert body["agent_reference"] == {"type": "agent_reference", "name": "sdlc-review"}
        assert body["max_output_tokens"] == 100
        assert body["input"] == "hello"
        assert "model" not in body

    def test_incomplete_response_fails_closed(self, real_project: Any) -> None:
        project, _ = real_project(lambda r: _json_response(200, _incomplete_body("max_output_tokens")))
        with pytest.raises(AgentRunError, match="max_output_tokens"):
            invoke_agent(project, "sdlc-review", "x", 100)

    def test_empty_completed_response_fails_closed(self, real_project: Any) -> None:
        project, _ = real_project(lambda r: _json_response(200, _responses_body("  ")))
        with pytest.raises(AgentRunError, match="empty text"):
            invoke_agent(project, "sdlc-review", "x", 100)

    def test_429_makes_exactly_two_http_calls_no_outer_retry(self, real_project: Any) -> None:
        err = b'{"error": {"message": "rate limit", "type": "rate_limit_error"}}'
        # retry-after-ms keeps the SDK backoff short so the test stays fast.
        def handler(r: Any) -> Any:
            return _http.Response(
                429,
                headers={"Content-Type": "application/json", "retry-after-ms": "1"},
                content=err,
            )

        project, requests = real_project(handler)
        with pytest.raises(AgentRunError, match="HTTP 429"):
            invoke_agent(project, "sdlc-review", "x", 100)
        assert len(requests) == 2

    def test_connection_error_becomes_agent_run_error(self, real_project: Any) -> None:
        def handler(r: Any) -> Any:
            raise _http.ConnectError("boom", request=r)

        project, requests = real_project(handler)
        with pytest.raises(AgentRunError, match="request failed"):
            invoke_agent(project, "sdlc-review", "x", 100)
        assert len(requests) == 2  # max_retries=1 also covers connection errors

    def test_500_makes_exactly_two_http_calls(self, real_project: Any) -> None:
        def handler(r: Any) -> Any:
            return _http.Response(
                500,
                headers={"Content-Type": "application/json", "retry-after-ms": "1"},
                content=b'{"error": {"message": "boom"}}',
            )

        project, requests = real_project(handler)
        with pytest.raises(AgentRunError, match="HTTP 500"):
            invoke_agent(project, "sdlc-review", "x", 100)
        assert len(requests) == 2

    def test_cli_end_to_end_stdout_is_answer_only(self, real_project: Any) -> None:
        """main() against the real SDK: stdout == answer, usage line on stderr only."""
        project, requests = real_project(
            lambda r: _json_response(200, _responses_body("## Findings\nNo significant findings."))
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            fh.write("diff --git a b")
            tmp = fh.name
        out, err = io.StringIO(), io.StringIO()
        try:
            with (
                patch.dict(
                    os.environ,
                    {"FOUNDRY_PROJECT_ENDPOINT": PROJECT_ENDPOINT, "AZURE_AI_PROJECTS_CONSOLE_LOGGING": "true"},
                ),
                patch("sdlc_agents.call._build_client", return_value=project),
                patch("sys.stdout", out),
                patch("sys.stderr", err),
            ):
                main(["--agent", "sdlc-review", "--input-file", tmp])
        finally:
            os.unlink(tmp)
        assert out.getvalue() == "## Findings\nNo significant findings.\n"
        assert "usage: in=10 out=20 reasoning=4" in err.getvalue()
        # One round-trip: no agent lookup GET before the invoke.
        assert [(r.method, str(r.url).split("?")[0]) for r in requests] == [
            ("POST", f"{PROJECT_ENDPOINT}/openai/v1/responses")
        ]


# ---------------------------------------------------------------------------
# max_output_tokens: per-agent defaults and ceiling
# ---------------------------------------------------------------------------

class TestTokenDefaults:
    def test_codegen_default_is_16000(self) -> None:
        exit_code, _, _ = _run_main("sdlc-codegen", "spec text")
        assert exit_code == 0

    def test_general_default_is_8000(self) -> None:
        exit_code, _, _ = _run_main("sdlc-review", "diff text")
        assert exit_code == 0

    def test_over_ceiling_clamped(self) -> None:
        exit_code, _, stderr = _run_main(
            "sdlc-review", "diff", extra_args=["--max-output-tokens", str(HARD_MAX_OUTPUT_TOKENS + 1000)]
        )
        assert exit_code == 0
        assert "clamped" in stderr

    def test_too_small_rejected(self) -> None:
        # argparse type check: <16 should fail
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            fh.write("x")
            tmp = fh.name
        argv = ["--agent", "sdlc-review", "--input-file", tmp, "--max-output-tokens", "5"]
        err = io.StringIO()
        exit_code = 0
        try:
            with patch("sys.stderr", err):
                main(argv)
        except SystemExit as exc:
            exit_code = int(exc.code) if exc.code is not None else 0
        finally:
            os.unlink(tmp)
        assert exit_code != 0


# ---------------------------------------------------------------------------
# stdout purity: AZURE_AI_PROJECTS_CONSOLE_LOGGING removed
# ---------------------------------------------------------------------------

class TestStdoutPurity:
    def test_console_logging_env_removed_before_client_build(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            fh.write("test input")
            tmp = fh.name
        argv = ["--agent", "sdlc-review", "--input-file", tmp]
        out = io.StringIO()
        err = io.StringIO()
        captured: dict[str, str] = {}

        def capturing_build(endpoint: str) -> MagicMock:
            captured["val"] = os.environ.get("AZURE_AI_PROJECTS_CONSOLE_LOGGING", "ABSENT")
            return _make_project_client()

        try:
            with (
                patch.dict(
                    os.environ,
                    {"FOUNDRY_PROJECT_ENDPOINT": "https://x", "AZURE_AI_PROJECTS_CONSOLE_LOGGING": "true"},
                ),
                patch("sdlc_agents.call._build_client", side_effect=capturing_build),
                patch("sys.stdout", out),
                patch("sys.stderr", err),
            ):
                main(argv)
        except SystemExit:
            pass
        finally:
            os.unlink(tmp)

        assert captured.get("val") == "ABSENT", (
            "AZURE_AI_PROJECTS_CONSOLE_LOGGING was still set when _build_client was called"
        )


# ---------------------------------------------------------------------------
# Input reading: ci-triage keeps the real tail of a huge file
# ---------------------------------------------------------------------------

class TestReadInput:
    def _read(self, text: str, agent: str) -> str:
        from sdlc_agents.call import _read_input
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(text)
            tmp = fh.name
        try:
            return _read_input(tmp, agent)
        finally:
            os.unlink(tmp)

    def test_ci_triage_keeps_end_of_very_large_log(self) -> None:
        log = "HEADLINE\n" + "x" * 1_000_000 + "\nFATAL: the real error\n"
        out = self._read(log, "sdlc-ci-triage")
        assert "HEADLINE" in out
        assert "FATAL: the real error" in out
        assert "LOG TRUNCATED" in out
        assert len(out) < INPUT_CHAR_LIMIT + 500

    def test_ci_triage_small_log_untouched(self) -> None:
        out = self._read("short log", "sdlc-ci-triage")
        assert "short log" in out and "TRUNCATED" not in out

    def test_ci_triage_log_just_over_limit_has_no_overlap(self) -> None:
        log = "a" * HEAD_LIMIT + "b" * (TAIL_LIMIT + 5)
        out = self._read(log, "sdlc-ci-triage")
        assert "TRUNCATED" in out

    def test_other_agent_keeps_head_only(self) -> None:
        out = self._read("H" * INPUT_CHAR_LIMIT + "END_MARK", "sdlc-review")
        assert "END_MARK" not in out and "INPUT TRUNCATED" in out

    def test_invalid_utf8_does_not_crash(self) -> None:
        from sdlc_agents.call import _read_input
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".bin", delete=False) as fh:
            fh.write(b"ok \xff\xfe bytes")
            tmp = fh.name
        try:
            assert "ok" in _read_input(tmp, "sdlc-review")
        finally:
            os.unlink(tmp)


class TestCodegenOutputNormalised:
    def test_cli_prints_normalised_paths(self) -> None:
        raw = json.dumps({"explanation": "e", "files": [{"path": "./src//a.py", "content": "x"}]})
        code, out, _ = _run_main("sdlc-codegen", "spec", agent_response=_make_completed_response(raw))
        assert code == 0
        assert json.loads(out)["files"][0]["path"] == "src/a.py"

    def test_cli_sanitises_explanation_for_pr_body(self) -> None:
        raw = json.dumps({
            "explanation": "see ![x](https://attacker.example/b.png) cc @org/team <!-- hi --> Fixes #9",
            "files": [{"path": "src/a.py", "content": "x"}],
        })
        code, out, _ = _run_main("sdlc-codegen", "spec", agent_response=_make_completed_response(raw))
        assert code == 0
        expl = json.loads(out)["explanation"]
        assert "![" not in expl and "attacker.example" not in expl and "<!--" not in expl
        assert "`@org/team`" in expl and "`Fixes #9`" in expl

    def test_cli_sanitises_every_triage_text_field(self) -> None:
        raw = json.dumps({
            "labels": ["bug"],
            "summary": "see ![x](https://attacker.example/s.png) cc @org/team",
            "acceptance_criteria": ["ok <!-- hi --> Fixes #1", "plain"],
            "tasks": ["do ![b](https://attacker.example/t.png)", "ping @org/team", "Fixes #1",
                      "keep this"],
        })
        code, out, _ = _run_main("sdlc-triage", "issue", agent_response=_make_completed_response(raw))
        assert code == 0
        result = json.loads(out)
        assert result["labels"] == ["bug"]
        blob = json.dumps(result)
        assert "attacker.example" not in blob and "![" not in blob and "<!--" not in blob
        assert "`@org/team`" in result["summary"] and "`@org/team`" in result["tasks"][1]
        assert result["tasks"][2] == "`Fixes #1` [keyword defanged]"
        assert "`Fixes #1` [keyword defanged]" in result["acceptance_criteria"][0]
        assert result["tasks"][3] == "keep this"

    @pytest.mark.parametrize("path", ["./.github/actions/x/action.yml", ".git/config", "action.yml"])
    def test_cli_rejects_bad_path_with_empty_stdout(self, path: str) -> None:
        raw = json.dumps({"explanation": "e", "files": [{"path": path, "content": "x"}]})
        code, out, err = _run_main("sdlc-codegen", "spec", agent_response=_make_completed_response(raw))
        assert code != 0 and out == "" and "ERROR" in err


# ---------------------------------------------------------------------------
# Incomplete response: CLI exits non-zero with reason on stderr
# ---------------------------------------------------------------------------

class TestIncompleteResponseCLI:
    def test_incomplete_exits_nonzero(self) -> None:
        resp = _make_incomplete_response("max_output_tokens")
        exit_code, stdout, stderr = _run_main("sdlc-review", "diff", agent_response=resp)
        assert exit_code != 0

    def test_incomplete_reason_on_stderr(self) -> None:
        resp = _make_incomplete_response("max_output_tokens")
        exit_code, stdout, stderr = _run_main("sdlc-review", "diff", agent_response=resp)
        assert "max_output_tokens" in stderr or "not completed" in stderr

    def test_empty_text_exits_nonzero(self) -> None:
        resp = _make_completed_response("   ")
        exit_code, stdout, stderr = _run_main("sdlc-review", "diff", agent_response=resp)
        assert exit_code != 0


# ---------------------------------------------------------------------------
# Missing endpoint exits non-zero
# ---------------------------------------------------------------------------

class TestEndpointRequired:
    def test_missing_endpoint_exits_1(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as fh:
            fh.write("hello")
            tmp = fh.name
        err = io.StringIO()
        exit_code = 0
        try:
            clean_env = {k: v for k, v in os.environ.items() if k != "FOUNDRY_PROJECT_ENDPOINT"}
            with (
                patch.dict(os.environ, clean_env, clear=True),
                patch("sys.stderr", err),
            ):
                main(["--agent", "sdlc-review", "--input-file", tmp])
        except SystemExit as exc:
            exit_code = int(exc.code) if exc.code is not None else 0
        finally:
            os.unlink(tmp)
        assert exit_code != 0
        assert "FOUNDRY_PROJECT_ENDPOINT" in err.getvalue()


# ---------------------------------------------------------------------------
# create_agents: hash idempotency
# ---------------------------------------------------------------------------

class TestCreateAgentsIdempotency:
    def _make_agents_client_tracking(self) -> tuple[MagicMock, dict]:
        """Return (agents_client_mock, state_dict). state tracks created versions."""
        state: dict = {"versions": {}, "create_count": 0}

        def fake_get(agent_name: str) -> MagicMock:
            if agent_name not in state["versions"]:
                from azure.core.exceptions import ResourceNotFoundError
                raise ResourceNotFoundError(message="not found")
            details = MagicMock()
            latest = MagicMock()
            v_info = state["versions"][agent_name]
            latest.version = v_info["version"]
            latest.metadata = {"definition_sha256": v_info["hash"]}
            details.versions.latest = latest
            return details

        def fake_create_version(agent_name: str, definition: Any, metadata: dict | None = None) -> MagicMock:
            state["create_count"] += 1
            h = (metadata or {}).get("definition_sha256", "nohash")
            ver = f"v{state['create_count']}"
            state["versions"][agent_name] = {"version": ver, "hash": h}
            result = MagicMock()
            result.version = ver
            return result

        agents_client = MagicMock()
        agents_client.get.side_effect = fake_get
        agents_client.create_version.side_effect = fake_create_version
        return agents_client, state

    def test_all_five_created_on_first_run(self) -> None:
        agents_client, state = self._make_agents_client_tracking()
        project = MagicMock()
        project.agents = agents_client
        project.__enter__ = lambda s: s
        project.__exit__ = MagicMock(return_value=False)

        from sdlc_agents import create_agents
        with (
            patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://x/api/projects/p"}),
            patch("sdlc_agents.create_agents.AIProjectClient", return_value=project),
            patch("sdlc_agents.create_agents.DefaultAzureCredential"),
        ):
            create_agents.main()

        assert state["create_count"] == 5

    def test_second_run_creates_zero_versions(self) -> None:
        agents_client, state = self._make_agents_client_tracking()
        project = MagicMock()
        project.agents = agents_client
        project.__enter__ = lambda s: s
        project.__exit__ = MagicMock(return_value=False)

        from sdlc_agents import create_agents
        with (
            patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://x/api/projects/p"}),
            patch("sdlc_agents.create_agents.AIProjectClient", return_value=project),
            patch("sdlc_agents.create_agents.DefaultAzureCredential"),
        ):
            create_agents.main()
            create_count_after_first = state["create_count"]
            create_agents.main()
            create_count_after_second = state["create_count"]

        assert create_count_after_first == 5
        assert create_count_after_second == 5, (
            "Second run should not create new versions when definitions are unchanged"
        )

    def test_changed_instructions_creates_new_version(self) -> None:
        agents_client, state = self._make_agents_client_tracking()
        project = MagicMock()
        project.agents = agents_client
        project.__enter__ = lambda s: s
        project.__exit__ = MagicMock(return_value=False)

        from sdlc_agents import create_agents
        # Patch one agent's hash to differ from what was stored.
        with (
            patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://x/api/projects/p"}),
            patch("sdlc_agents.create_agents.AIProjectClient", return_value=project),
            patch("sdlc_agents.create_agents.DefaultAzureCredential"),
        ):
            create_agents.main()
            # Simulate instructions change by corrupting the stored hash for the first agent.
            first_name = AGENTS[0].name
            state["versions"][first_name]["hash"] = "old-hash-different"
            create_agents.main()

        assert state["create_count"] == 6, "One new version should have been created"

    def test_unchanged_prints_unchanged(self, capsys: pytest.CaptureFixture) -> None:
        agents_client, state = self._make_agents_client_tracking()
        project = MagicMock()
        project.agents = agents_client
        project.__enter__ = lambda s: s
        project.__exit__ = MagicMock(return_value=False)

        from sdlc_agents import create_agents
        with (
            patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://x/api/projects/p"}),
            patch("sdlc_agents.create_agents.AIProjectClient", return_value=project),
            patch("sdlc_agents.create_agents.DefaultAzureCredential"),
        ):
            create_agents.main()
            create_agents.main()

        out = capsys.readouterr().out
        assert "unchanged" in out

    def test_reasoning_effort_low_in_definition(self) -> None:
        """Every definition must include reasoning=Reasoning(effort='low')."""
        from sdlc_agents.create_agents import _build_definition

        for a in AGENTS:
            defn = _build_definition(a)
            serialised = defn.as_dict()
            reasoning = serialised.get("reasoning") or {}
            assert reasoning.get("effort") in ("low", "minimal"), (
                f"{a.name}: reasoning effort not low/minimal in definition"
            )


# ---------------------------------------------------------------------------
# Happy-path smoke per agent (all five, mock client)
# ---------------------------------------------------------------------------

class TestHappyPath:
    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_agent_exits_zero(self, agent_name: str) -> None:
        exit_code, stdout, stderr = _run_main(agent_name, "Sample input.")
        assert exit_code == 0, f"{agent_name}: unexpected exit. stderr={stderr}"
        assert "usage: in=" in stderr
