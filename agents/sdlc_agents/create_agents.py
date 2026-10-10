"""
Idempotent registration of every SDLC prompt agent against FOUNDRY_PROJECT_ENDPOINT.

Each version stores a SHA-256 of its serialised definition in metadata; when the latest version
already carries the same hash it is reused ('unchanged'), otherwise a new version is created.
Agents with `uses_mcp` get the GitHub MCP tool through the `github-mcp` project connection (which
holds the PAT), restricted to read-only tools and never asking for approval.

Usage:
    python -m sdlc_agents.create_agents

Prints one line per agent: "<name>  version=<version>  [unchanged|created]". Exits 1 if any agent
failed to register (the others are still attempted). Requires the Foundry User role.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    MCPTool,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    Reasoning,
    TextResponseFormatJsonSchema,
)
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential

from sdlc_agents.definitions import (
    AGENTS,
    MCP_CONNECTION_ID,
    MCP_READ_ONLY_TOOLS,
    MCP_SERVER_LABEL,
    MCP_SERVER_URL,
    MODEL_DEPLOYMENT,
    AgentDef,
)


def github_mcp_tool() -> MCPTool:
    return MCPTool(
        server_label=MCP_SERVER_LABEL,
        server_url=MCP_SERVER_URL,
        project_connection_id=MCP_CONNECTION_ID,
        require_approval="never",
        allowed_tools=list(MCP_READ_ONLY_TOOLS),
    )


def build_definition(agent: AgentDef) -> PromptAgentDefinition:
    """PromptAgentDefinition with reasoning=low, the agent's strict JSON schema and its tools."""
    text = None
    if agent.schema is not None:
        text = PromptAgentDefinitionTextOptions(
            format=TextResponseFormatJsonSchema(name="output", schema=agent.schema, strict=True)
        )
    kwargs: dict[str, Any] = {}
    if agent.uses_mcp:
        kwargs["tools"] = [github_mcp_tool()]
    return PromptAgentDefinition(
        model=MODEL_DEPLOYMENT,
        instructions=agent.instructions,
        reasoning=Reasoning(effort="low"),
        text=text,
        **kwargs,
    )


def definition_hash(definition: PromptAgentDefinition) -> str:
    canonical = json.dumps(definition.as_dict(), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def ensure_version(client: AIProjectClient, name: str, definition: PromptAgentDefinition) -> tuple[str, str]:
    """Register or reuse a version. Returns (version, 'unchanged' | 'created')."""
    digest = definition_hash(definition)
    try:
        details = client.agents.get(name)
        latest = getattr(getattr(details, "versions", None), "latest", None)
        if latest is not None and (getattr(latest, "metadata", None) or {}).get("definition_sha256") == digest:
            return str(latest.version), "unchanged"
    except ResourceNotFoundError:
        pass  # first registration
    # Any other error propagates: minting a version on an unreadable state defeats idempotency.
    result = client.agents.create_version(agent_name=name, definition=definition,
                                          metadata={"definition_sha256": digest})
    return str(result.version), "created"


def _client() -> AIProjectClient:
    os.environ.pop("AZURE_AI_PROJECTS_CONSOLE_LOGGING", None)
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not endpoint:
        print("ERROR: FOUNDRY_PROJECT_ENDPOINT is not set.", file=sys.stderr)
        sys.exit(1)
    return AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())


def main() -> None:
    errors: list[str] = []
    with _client() as client:
        for agent in AGENTS:
            try:
                version, action = ensure_version(client, agent.name, build_definition(agent))
                print(f"{agent.name}  version={version}  {action}")
            except AzureError as exc:
                # Service and credential errors: report and try the remaining agents.
                msg = f"ERROR registering {agent.name}: {exc}"
                print(msg, file=sys.stderr)
                errors.append(msg)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
