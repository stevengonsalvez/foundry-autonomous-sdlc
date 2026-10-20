"""Prompt agent definitions: schemas, output checks, instructions, schema_check, sanitise and paths."""

from __future__ import annotations

import copy
import json
from typing import Any

import jsonschema
import pytest

from sdlc_agents import paths, schema_check
from sdlc_agents.definitions import (
    AGENT_BY_NAME,
    AGENT_NAMES,
    AGENTS,
    CRITERIA,
    MCP_READ_ONLY_TOOLS,
    PO_LABEL,
)
from sdlc_agents.sanitise import (
    INPUT_CHAR_LIMIT,
    encode_marker_json,
    parse_json_strict,
    sanitise_markdown,
    wrap_untrusted,
)

VALID: dict[str, dict[str, Any]] = {
    "sdlc-req-gate": {"criteria": dict.fromkeys(CRITERIA, 20), "score": 80, "summary": "s",
                      "acceptance_criteria": ["a"], "questions": []},
    "sdlc-product-owner": {"answers": [{"question": "q", "answer": f"{PO_LABEL} a"}]},
    "sdlc-feasibility": {"suitable": True, "reasons": ["r"], "risk": "low", "affected_paths": []},
    "sdlc-test-designer": {"tests": [{"path": "app/web/tests/a.test.tsx", "content": "import { it } from 'vitest'"}],
                           "rationale": "r"},
    "sdlc-reviewer": {"verdict": "approve", "head": "abcdef1", "findings": [], "summary": "s"},
    "sdlc-triage": {"severity": "s2", "owner": "web", "summary": "s", "suspected_area": "a", "rationale": "r"},
    "sdlc-ci-triage": {"cause": "stale-test", "explanation": "e", "test_files": ["app/web/src/Home.test.tsx"]},
    "sdlc-ui-tester": {
        "verdict": "pass",
        "findings": [],
        "summary": "No visual UI anomalies detected across viewports.",
    },
}


def test_the_prompt_agents_from_the_architecture_table_exist() -> None:
    assert AGENT_NAMES == ["sdlc-req-gate", "sdlc-product-owner", "sdlc-feasibility", "sdlc-test-designer",
                           "sdlc-reviewer", "sdlc-triage", "sdlc-ci-triage", "sdlc-release-notes", "sdlc-ui-tester"]
    assert {a.name for a in AGENTS if a.output_kind == "markdown"} == {"sdlc-release-notes"}


def test_only_feasibility_test_designer_and_reviewer_get_the_mcp_tool() -> None:
    assert {a.name for a in AGENTS if a.uses_mcp} == {"sdlc-feasibility", "sdlc-test-designer", "sdlc-reviewer"}
    assert MCP_READ_ONLY_TOOLS == ("get_file_contents",)    # each tool schema is billed on every call
    assert "create_or_update_file" not in MCP_READ_ONLY_TOOLS and "merge_pull_request" not in MCP_READ_ONLY_TOOLS
    for agent in AGENTS:
        assert ("GITHUB TOOLS" in agent.instructions) == agent.uses_mcp
        assert ("TOOL BUDGET (hard rule)" in agent.instructions) == agent.uses_mcp
    for name in ("sdlc-feasibility", "sdlc-reviewer"):
        assert "at most TWICE in total" in AGENT_BY_NAME[name].instructions
    designer = AGENT_BY_NAME["sdlc-test-designer"].instructions
    assert "at most FOUR times" in designer and "repo_files" in designer and "never on a directory" in designer


@pytest.mark.parametrize("agent", [a for a in AGENTS if a.schema is not None], ids=lambda a: a.name)
def test_every_schema_is_valid_json_schema_and_follows_strict_mode(agent: Any) -> None:
    jsonschema.Draft202012Validator.check_schema(agent.schema)

    def walk(node: dict[str, Any], where: str) -> None:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False, where
            assert sorted(node["required"]) == sorted(node["properties"]), where
            for key, sub in node["properties"].items():
                walk(sub, f"{where}.{key}")
        if node.get("type") == "array":
            walk(node["items"], f"{where}[]")

    walk(agent.schema, agent.name)
    sample = copy.deepcopy(VALID[agent.name])
    jsonschema.validate(sample, agent.schema)
    agent.validate_output(sample)


@pytest.mark.parametrize("agent", AGENTS, ids=lambda a: a.name)
def test_every_instruction_has_the_security_preamble_and_no_em_dash(agent: Any) -> None:
    assert agent.instructions.startswith("SECURITY RULES")
    assert "DATA" in agent.instructions and "prompt injection attempt" in agent.instructions
    assert "\u2014" not in agent.instructions


def test_markdown_agent_has_no_json_to_validate() -> None:
    with pytest.raises(TypeError):
        AGENT_BY_NAME["sdlc-release-notes"].validate_output({})


def test_req_gate_score_is_the_sum_and_questions_follow_the_threshold() -> None:
    gate = AGENT_BY_NAME["sdlc-req-gate"]
    data = {**VALID["sdlc-req-gate"], "score": 12, "questions": ["q"]}
    gate.validate_output(data)
    assert data["score"] == 80 and data["questions"] == []
    low = {**VALID["sdlc-req-gate"], "criteria": dict.fromkeys(CRITERIA, 5), "questions": []}
    with pytest.raises(ValueError, match="no questions"):
        gate.validate_output(low)
    too_many = {**low, "questions": ["q"] * 6}
    with pytest.raises(ValueError, match="0-5 items"):
        gate.validate_output(too_many)
    over = {**VALID["sdlc-req-gate"], "criteria": {**dict.fromkeys(CRITERIA, 5), "edge_cases": 26}}
    with pytest.raises(ValueError, match="above the maximum 25"):
        gate.validate_output(over)


def test_req_gate_rubric_and_product_owner_context_are_in_the_instructions() -> None:
    gate = AGENT_BY_NAME["sdlc-req-gate"].instructions
    for name in CRITERIA:
        assert name in gate
    assert "score < 80" in gate and "1 to 5 short questions" in gate and "WORKED EXAMPLE 2" in gate
    po = AGENT_BY_NAME["sdlc-product-owner"].instructions
    for text in ("filter the parcel list on the home page by status", "label_created, in_transit, "
                 "out_for_delivery, delivered, exception", "status=<value>", "keyboard accessible",
                 "No API change", "SECONDARY: show the estimated delivery date",
                 f"must start with the exact label {PO_LABEL}"):
        assert text in po
    feas = AGENT_BY_NAME["sdlc-feasibility"].instructions
    for text in ("production credentials", "external contracts", "legal, commercial", "infrastructure", "outside app/"):
        assert text in feas


def test_product_owner_label_is_enforced() -> None:
    data = {"answers": [{"question": "q", "answer": "  Filter it."}, {"question": "q2", "answer": f"{PO_LABEL} yes"}]}
    AGENT_BY_NAME["sdlc-product-owner"].validate_output(data)
    assert [a["answer"] for a in data["answers"]] == [f"{PO_LABEL} Filter it.", f"{PO_LABEL} yes"]


@pytest.mark.parametrize("path, error", [
    ("app/e2e/tests/a.test.ts", "not app/e2e"),
    ("app/web/tests/a.tsx", "must be app/<workspace>/tests"),
    ("app/web/src/a.test.tsx", "must be app/<workspace>/tests"),
    ("src/a.test.ts", "outside app/"),
    ("app/../.github/a.test.ts", "absolute or '..'"),
    ("app/web/.hidden/a.test.ts", "forbidden segment"),
])
def test_test_designer_paths_are_vitest_files_under_app(path: str, error: str) -> None:
    data = {"tests": [{"path": path, "content": "import 'vitest'"}], "rationale": "r"}
    with pytest.raises(ValueError, match=error):
        AGENT_BY_NAME["sdlc-test-designer"].validate_output(data)


def test_test_designer_rejects_duplicates_missing_vitest_nul_and_oversize() -> None:
    designer = AGENT_BY_NAME["sdlc-test-designer"]
    dup = {"tests": [{"path": "app/web/tests/a.test.ts", "content": "vitest"},
                     {"path": "./app/web/tests/A.test.ts", "content": "vitest"}],
           "rationale": "r"}
    with pytest.raises(ValueError, match="duplicate"):
        designer.validate_output(dup)
    with pytest.raises(ValueError, match="does not import from vitest"):
        designer.validate_output({"tests": [{"path": "app/web/tests/a.test.ts", "content": "jest"}], "rationale": "r"})
    with pytest.raises(ValueError, match="NUL"):
        designer.validate_output({"tests": [{"path": "app/web/tests/a.test.ts", "content": "vitest\x00"}],
                                  "rationale": "r"})
    big = "vitest" + "x" * 14_000
    with pytest.raises(ValueError, match="tests total"):
        designer.validate_output({"tests": [{"path": f"app/web/tests/{i}.test.ts", "content": big} for i in range(3)],
                                  "rationale": "r"})


def test_reviewer_cannot_approve_with_a_blocking_finding() -> None:
    data = {**VALID["sdlc-reviewer"], "findings": [{"severity": "critical", "area": "security", "detail": "eval"}]}
    AGENT_BY_NAME["sdlc-reviewer"].validate_output(data)
    assert data["verdict"] == "request-changes"
    with pytest.raises(ValueError, match="does not match"):
        AGENT_BY_NAME["sdlc-reviewer"].validate_output({**VALID["sdlc-reviewer"], "head": "not-a-sha"})


def test_ci_triage_needs_test_files_for_a_stale_test_and_only_test_paths() -> None:
    ci = AGENT_BY_NAME["sdlc-ci-triage"]
    with pytest.raises(ValueError, match="at least one test file"):
        ci.validate_output({"cause": "stale-test", "explanation": "e", "test_files": []})
    with pytest.raises(ValueError, match="test glob"):
        ci.validate_output({"cause": "stale-test", "explanation": "e", "test_files": ["app/web/src/Home.tsx"]})
    ci.validate_output({"cause": "real-bug", "explanation": "e", "test_files": []})


def test_triage_enums_reject_off_list_values() -> None:
    with pytest.raises(ValueError, match="not in allowed set"):
        AGENT_BY_NAME["sdlc-triage"].validate_output({**VALID["sdlc-triage"], "owner": "security"})


def test_ui_tester_overrides_pass_when_critical_or_high_findings() -> None:
    tester = AGENT_BY_NAME["sdlc-ui-tester"]
    data = {
        "verdict": "pass",
        "findings": [
            {
                "route": "home",
                "viewport": "desktop",
                "issue": "Primary button clipped",
                "severity": "high",
            }
        ],
        "summary": "Layout issue found.",
    }
    tester.validate_output(data)
    assert data["verdict"] == "concerns"

    # Low severity does not override pass
    data_low = {
        "verdict": "pass",
        "findings": [
            {
                "route": "home",
                "viewport": "desktop",
                "issue": "Minor padding",
                "severity": "low",
            }
        ],
        "summary": "Minor spacing.",
    }
    tester.validate_output(data_low)
    assert data_low["verdict"] == "pass"


# ---------------------------------------------------------------------------
# schema_check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("schema, value, message", [
    ({"type": "integer"}, True, "expected integer"),
    ({"type": "integer"}, 1.5, "expected integer"),
    ({"type": "number"}, "1", "expected number"),
    ({"type": "boolean"}, 0, "expected boolean"),
    ({"type": "null"}, 0, "expected null"),
    ({"type": ["string", "null"]}, 3, "expected string|null"),
    ({"type": "number", "minimum": 0}, -1, "below the minimum"),
    ({"type": "string", "minLength": 2}, "a", "shorter than 2"),
    ({"type": "string", "maxLength": 1}, "ab", "exceeds 1"),
    ({"type": "string", "pattern": "^a"}, "b", "does not match"),
    ({"type": "array", "minItems": 1}, [], "at least 1"),
    ({"type": "object", "required": ["a"]}, {}, "missing keys"),
    ({"type": "object", "properties": {}, "additionalProperties": False}, {"x": 1}, "unexpected keys"),
])
def test_schema_check_reports_violations(schema: dict[str, Any], value: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        schema_check.check(schema, value, "x")


def test_schema_check_accepts_valid_values_and_refuses_unknown_keywords_and_types() -> None:
    schema_check.check({"type": ["integer", "null"], "minimum": 0}, None, "x")
    schema_check.check({"type": "number", "maximum": 2}, 1.5, "x")
    schema_check.check({"type": "boolean"}, False, "x")
    with pytest.raises(TypeError, match="unsupported keywords"):
        schema_check.check({"format": "date"}, "x", "x")
    with pytest.raises(TypeError, match="unsupported type"):
        schema_check.check({"type": "tuple"}, 1, "x")


# ---------------------------------------------------------------------------
# sanitise and paths
# ---------------------------------------------------------------------------

def test_strict_json_rejects_duplicates_and_nan() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        parse_json_strict('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match="NaN"):
        parse_json_strict('{"a": NaN}')


def test_marker_json_cannot_close_an_html_comment() -> None:
    value = {"q": "--> <script>&"}
    encoded = encode_marker_json(value)
    assert "-->" not in encoded and "<" not in encoded and ">" not in encoded and "&" not in encoded
    assert json.loads(encoded) == value


def test_wrap_untrusted_truncates_head_or_keeps_the_log_tail() -> None:
    text = "H" * 10 + "x" * INPUT_CHAR_LIMIT + "TAIL"
    wrapped = wrap_untrusted("issue", text, "n1")
    assert "INPUT TRUNCATED" in wrapped and "TAIL" not in wrapped and wrapped.endswith("</untrusted_input nonce=n1>")
    log = wrap_untrusted("log", text, "n1", keep_tail=True)
    assert "LOG TRUNCATED nonce=n1" in log and "TAIL\n</untrusted_input" in log
    assert wrap_untrusted("s", "short", "n1") == "<untrusted_input nonce=n1 name=s>\nshort\n</untrusted_input nonce=n1>"


def test_markdown_sanitiser_strips_images_html_mentions_and_closing_keywords() -> None:
    out = sanitise_markdown("hi @bob ![t](http://x/p.png) <b>bold</b> <!-- hidden Fixes #4 and closes #5")
    assert out == "hi `@bob` [image removed] bold "
    assert sanitise_markdown("resolves GH-12 now") == "`resolves GH-12` [keyword defanged] now"
    assert sanitise_markdown("!<b>[a](http://x)") == "[image removed]"
    assert sanitise_markdown("a < b") == "a &lt; b"


@pytest.mark.parametrize("path, is_test", [
    ("app/web/src/a.test.tsx", True), ("app/api/src/x.spec.ts", True), ("app/e2e/home.ts", True),
    ("app/api/tests/helper.ts", True), ("app/core/__fixtures__/s.json", True), ("app/web/src/tests.ts", False),
    ("app/web/src/Home.tsx", False), ("", False),
])
def test_test_globs(path: str, is_test: bool) -> None:
    assert paths.is_test_path(path) is is_test


@pytest.mark.parametrize("path", [None, "", " app/a.ts", "app/a\\b.ts", "app/é.ts", "app/x/", "/app/a.ts",
                                  "app/node_modules/x.ts", "app/" + "a" * 260])
def test_unsafe_paths_are_rejected(path: Any) -> None:
    with pytest.raises(ValueError, match="path rejected"):
        paths.normalise_app_path(path)


def test_paths_normalise() -> None:
    assert paths.normalise_app_path("./app//web/a.ts") == "app/web/a.ts"


def _designer_prompt() -> str:
    return " ".join(AGENT_BY_NAME["sdlc-test-designer"].instructions.split())


def test_designer_prompt_forbids_throwing_mocks_and_nested_vi_mock() -> None:
    prompt = _designer_prompt()
    assert "never mock a component to throw" in prompt
    assert "Put vi.mock only at the top level of a file, never inside describe or it" in prompt


def test_designer_prompt_tells_it_to_omit_an_unprovable_test_not_skip_it() -> None:
    prompt = _designer_prompt()
    assert "omit that test and say so in the rationale" in prompt
    assert "no .only or .skip" in prompt          # the rule an instruction to "skip" would contradict
    assert "skip that test" not in prompt
