"""AgentDef is the single source for schema, output kind, checks and the triage label list."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from sdlc_agents import codegen_policy, schema_check
from sdlc_agents.definitions import AGENT_BY_NAME, AGENTS, ALLOWED_LABELS, TRIAGE_SCHEMA


def test_json_agents_carry_schema_and_check_markdown_agents_carry_neither() -> None:
    kinds = {a.name: a.output_kind for a in AGENTS}
    assert kinds == {
        "sdlc-triage": "json", "sdlc-codegen": "json", "sdlc-review": "markdown",
        "sdlc-ci-triage": "markdown", "sdlc-release-notes": "markdown",
    }
    for a in AGENTS:
        assert (a.schema is not None) == (a.output_kind == "json"), a.name
        assert (a.check is not None) == (a.output_kind == "json"), a.name


def test_markdown_agent_has_no_json_to_validate() -> None:
    with pytest.raises(TypeError):
        AGENT_BY_NAME["sdlc-review"].validate_output({})


def test_triage_labels_schema_enum_and_instructions_agree() -> None:
    triage = AGENT_BY_NAME["sdlc-triage"]
    assert triage.allowed_labels == ALLOWED_LABELS
    assert set(TRIAGE_SCHEMA["properties"]["labels"]["items"]["enum"]) == set(ALLOWED_LABELS)
    assert ", ".join(ALLOWED_LABELS) in triage.instructions
    assert not any(label.startswith("agent:") for label in ALLOWED_LABELS)
    assert all(not a.allowed_labels for a in AGENTS if a.name != "sdlc-triage")


def test_codegen_schema_and_instructions_use_the_policy_limits() -> None:
    codegen = AGENT_BY_NAME["sdlc-codegen"]
    files = codegen.schema["properties"]["files"]
    assert files["maxItems"] == codegen_policy.MAX_FILES
    assert files["items"]["properties"]["content"]["maxLength"] == codegen_policy.MAX_CONTENT_BYTES
    assert files["items"]["properties"]["path"]["maxLength"] == codegen_policy.MAX_PATH_LENGTH
    assert f"under {codegen_policy.allowed_roots_text()} only" in codegen.instructions
    assert f"1 to {codegen_policy.MAX_FILES} files" in codegen.instructions


def test_codegen_validation_normalises_paths_in_place() -> None:
    data = {"explanation": "e", "files": [{"path": "./src//a.py", "content": "x"}]}
    AGENT_BY_NAME["sdlc-codegen"].validate_output(data)
    assert data["files"][0]["path"] == "src/a.py"


def test_codegen_content_bytes_limit_counts_utf8_not_chars() -> None:
    # Within the schema's char limit, over the byte limit once encoded.
    content = "é" * (codegen_policy.MAX_CONTENT_BYTES // 2 + 1)
    data = {"explanation": "e", "files": [{"path": "src/a.py", "content": content}]}
    with pytest.raises(ValueError, match="exceeds limit"):
        AGENT_BY_NAME["sdlc-codegen"].validate_output(data)


def test_codegen_rejects_lone_surrogate_content() -> None:
    data = {"explanation": "e", "files": [{"path": "src/a.py", "content": "a\ud800b"}]}
    with pytest.raises(ValueError, match="not valid UTF-8"):
        AGENT_BY_NAME["sdlc-codegen"].validate_output(data)


@pytest.mark.parametrize("value, message", [
    ("x", "expected object"),
    ({"labels": "bug", "summary": "s", "acceptance_criteria": ["a"], "tasks": ["t"]}, "expected array"),
    ({"labels": [1], "summary": "s", "acceptance_criteria": ["a"], "tasks": ["t"]}, "expected string"),
    ({"labels": ["bug"], "summary": "s", "acceptance_criteria": ["x" * 301], "tasks": ["t"]},
     r"acceptance_criteria\[0\]: exceeds 300 chars"),
])
def test_schema_check_reports_where_it_failed(value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        schema_check.check(TRIAGE_SCHEMA, value, "sdlc-triage")


def test_schema_check_refuses_keywords_it_does_not_implement() -> None:
    with pytest.raises(TypeError, match="unsupported"):
        schema_check.check({"type": "string", "pattern": "^a"}, "a", "x")


def test_schema_check_refuses_types_it_does_not_implement() -> None:
    with pytest.raises(TypeError, match="unsupported type"):
        schema_check.check({"type": "integer"}, 1, "x")


def test_every_agent_schema_uses_only_supported_keywords() -> None:
    samples = {
        "sdlc-triage": {"labels": ["bug"], "summary": "s", "acceptance_criteria": ["a"], "tasks": ["t"]},
        "sdlc-codegen": {"explanation": "e", "files": [{"path": "src/a.py", "content": "x"}]},
    }
    for a in AGENTS:
        if a.schema is not None:
            a.validate_output(samples[a.name])


# ---------------------------------------------------------------------------
# create_agents: Azure errors are reported per agent, bugs are not swallowed
# ---------------------------------------------------------------------------

def _project(agents_client: MagicMock) -> MagicMock:
    project = MagicMock()
    project.agents = agents_client
    project.__enter__ = lambda s: s
    project.__exit__ = MagicMock(return_value=False)
    return project


def _run_create(project: MagicMock) -> None:
    from sdlc_agents import create_agents
    with (
        patch.dict(os.environ, {"FOUNDRY_PROJECT_ENDPOINT": "https://x/api/projects/p"}),
        patch("sdlc_agents.create_agents.AIProjectClient", return_value=project),
        patch("sdlc_agents.create_agents.DefaultAzureCredential"),
    ):
        create_agents.main()


def test_azure_error_on_one_agent_still_registers_the_rest_then_exits_1(
    capsys: pytest.CaptureFixture,
) -> None:
    def fake_get(name: str) -> None:
        if name == "sdlc-review":
            raise HttpResponseError(message="boom")
        raise ResourceNotFoundError(message="not found")

    client = MagicMock()
    client.get.side_effect = fake_get
    client.create_version.return_value = MagicMock(version="1")

    with pytest.raises(SystemExit) as exc:
        _run_create(_project(client))

    assert exc.value.code == 1
    assert client.create_version.call_count == 4
    assert "ERROR registering sdlc-review" in capsys.readouterr().err


def test_non_azure_error_propagates_instead_of_being_swallowed() -> None:
    client = MagicMock()
    client.get.side_effect = KeyError("bug in our code")

    with pytest.raises(KeyError):
        _run_create(_project(client))
