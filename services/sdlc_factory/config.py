"""Factory definition loader: `factory/factory.yaml` plus `factory/agents/<name>/agent.md` (Warp style).

Every validation failure raises ConfigError carrying the offending file and the dotted key, so a bad
edit is fixable from the message alone.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = "v1alpha1"
KNOWN_ENGINES = frozenset({"agy"})
AGENT_TYPES = frozenset({"FOREMAN", "TRIAGE", "SPEC", "IMPLEMENT", "REVIEW", "VERIFY", "CUSTOM"})
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
OUTPUT_KINDS = frozenset({"json", "markdown"})

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)(.*)\Z", re.DOTALL)


class ConfigError(ValueError):
    """The factory definition is invalid. The message names the file and the key."""


def _fail(path: Path, key: str, problem: str) -> ConfigError:
    return ConfigError(f"{path}: {key}: {problem}")


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class HumanGates:
    spec: bool = False
    merge: bool = False


@dataclass(frozen=True)
class AgentDefaults:
    engine: str
    model: str
    timeout_s: int
    effort: str


@dataclass(frozen=True)
class BudgetConfig:
    """Calls and wall-clock minutes, priced by surrogate rates so they map onto the USD caps in
    sdlc_agents.ports.Budget."""

    per_issue_max_calls: int
    per_issue_max_minutes: int
    total_max_calls: int
    call_usd: float
    minute_usd: float

    def issue_cap_usd(self) -> float:
        return round(self.per_issue_max_calls * self.call_usd, 6)

    def total_cap_usd(self) -> float:
        return round(self.total_max_calls * self.call_usd, 6)


@dataclass(frozen=True)
class AgentConfig:
    name: str
    description: str
    agent_type: str
    engine: str
    model: str
    effort: str
    timeout_s: int
    read_only: bool
    output_kind: str
    instructions: str
    schema: dict[str, Any] | None


DEFAULT_TICKET_LABEL = "factory:independent"


@dataclass(frozen=True)
class FactoryConfig:
    name: str
    schema_version: str
    repositories: tuple[Repository, ...]
    agent_defaults: AgentDefaults
    human_gates: HumanGates
    budget: BudgetConfig
    engines: Mapping[str, Mapping[str, Any]]
    runners: Mapping[str, Path]
    agents: Mapping[str, AgentConfig]
    ticket_label: str = DEFAULT_TICKET_LABEL   # added to every issue or PR this factory runs

    def agent(self, name: str) -> AgentConfig:
        try:
            return self.agents[name]
        except KeyError:
            raise ConfigError(f"unknown agent {name!r}; defined: {', '.join(sorted(self.agents))}") from None


# --- typed readers: each takes the file and the dotted key so errors can name both -------------------


def _mapping(value: Any, path: Path, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(path, key, f"expected a mapping, got {type(value).__name__}")
    return value


def _required(data: Mapping[str, Any], name: str, path: Path, prefix: str) -> Any:
    if name not in data:
        raise _fail(path, f"{prefix}{name}", "required key is missing")
    return data[name]


def _str(value: Any, path: Path, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(path, key, "expected a non-empty string")
    return value


def _bool(value: Any, path: Path, key: str) -> bool:
    if not isinstance(value, bool):
        raise _fail(path, key, "expected true or false")
    return value


def _positive(value: Any, path: Path, key: str, kind: type[int] | type[float]) -> Any:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise _fail(path, key, "expected a positive number")
    if kind is int and not isinstance(value, int):
        raise _fail(path, key, "expected a positive integer")
    return kind(value)


def _choice(value: Any, allowed: frozenset[str], path: Path, key: str) -> str:
    if value not in allowed:
        raise _fail(path, key, f"{value!r} is not one of {sorted(allowed)}")
    return value


def _read_yaml(path: Path) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    return _mapping(data, path, "<document>")


def split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    """Split a markdown file into its YAML frontmatter mapping and its stripped body."""
    match = _FRONTMATTER.match(text)
    if match is None:
        raise _fail(path, "<frontmatter>", "file must start with a '---' delimited YAML block")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise _fail(path, "<frontmatter>", f"invalid YAML: {exc}") from exc
    return dict(_mapping(meta, path, "<frontmatter>")), match.group(2).strip()


# --- sections ---------------------------------------------------------------------------------------


def _engine(value: Any, path: Path, key: str) -> str:
    return _choice(value, KNOWN_ENGINES, path, key)


def _repositories(data: Mapping[str, Any], path: Path) -> tuple[Repository, ...]:
    raw = _required(data, "repositories", path, "")
    if not isinstance(raw, list) or not raw:
        raise _fail(path, "repositories", "expected a non-empty list")
    repos = []
    for i, item in enumerate(raw):
        entry = _mapping(item, path, f"repositories[{i}]")
        repos.append(
            Repository(
                owner=_str(_required(entry, "owner", path, f"repositories[{i}]."), path, f"repositories[{i}].owner"),
                name=_str(_required(entry, "name", path, f"repositories[{i}]."), path, f"repositories[{i}].name"),
            )
        )
    return tuple(repos)


def _defaults(data: Mapping[str, Any], path: Path) -> AgentDefaults:
    raw = _mapping(_required(data, "agentDefaults", path, ""), path, "agentDefaults")
    p = "agentDefaults."
    return AgentDefaults(
        engine=_engine(_required(raw, "engine", path, p), path, f"{p}engine"),
        model=_str(_required(raw, "model", path, p), path, f"{p}model"),
        timeout_s=_positive(_required(raw, "timeoutS", path, p), path, f"{p}timeoutS", int),
        effort=_choice(_required(raw, "effort", path, p), EFFORTS, path, f"{p}effort"),
    )


def _gates(data: Mapping[str, Any], path: Path) -> HumanGates:
    raw = _mapping(data.get("humanGates", {}), path, "humanGates")
    return HumanGates(
        spec=_bool(raw.get("spec", False), path, "humanGates.spec"),
        merge=_bool(raw.get("merge", False), path, "humanGates.merge"),
    )


def _budget(data: Mapping[str, Any], path: Path) -> BudgetConfig:
    raw = _mapping(_required(data, "budget", path, ""), path, "budget")
    per_issue = _mapping(_required(raw, "perIssue", path, "budget."), path, "budget.perIssue")
    total = _mapping(_required(raw, "total", path, "budget."), path, "budget.total")
    return BudgetConfig(
        per_issue_max_calls=_positive(
            _required(per_issue, "maxCalls", path, "budget.perIssue."), path, "budget.perIssue.maxCalls", int
        ),
        per_issue_max_minutes=_positive(
            _required(per_issue, "maxMinutes", path, "budget.perIssue."), path, "budget.perIssue.maxMinutes", int
        ),
        total_max_calls=_positive(
            _required(total, "maxCalls", path, "budget.total."), path, "budget.total.maxCalls", int
        ),
        call_usd=_positive(_required(raw, "callUsd", path, "budget."), path, "budget.callUsd", float),
        minute_usd=_positive(_required(raw, "minuteUsd", path, "budget."), path, "budget.minuteUsd", float),
    )


def _engines(data: Mapping[str, Any], path: Path) -> dict[str, Mapping[str, Any]]:
    raw = _mapping(_required(data, "engines", path, ""), path, "engines")
    return {
        _choice(name, KNOWN_ENGINES, path, "engines"): _mapping(conf or {}, path, f"engines.{name}")
        for name, conf in raw.items()
    }


def _runners(data: Mapping[str, Any], path: Path) -> dict[str, Path]:
    raw = _mapping(_required(data, "runners", path, ""), path, "runners")
    runners = {}
    for name, rel in raw.items():
        target = path.parent / _str(rel, path, f"runners.{name}")
        if not target.is_file():
            raise _fail(path, f"runners.{name}", f"file not found: {target}")
        _read_yaml(target)
        runners[name] = target
    return runners


def _agent(directory: Path, defaults: AgentDefaults) -> AgentConfig:
    md_path = directory / "agent.md"
    meta, body = split_frontmatter(_read_text(md_path), md_path)
    output_kind = _choice(meta.get("outputKind", "json"), OUTPUT_KINDS, md_path, "outputKind")
    schema = _agent_schema(directory) if output_kind == "json" else None
    return AgentConfig(
        name=directory.name,
        description=_str(_required(meta, "description", md_path, ""), md_path, "description"),
        agent_type=_choice(_required(meta, "agentType", md_path, ""), AGENT_TYPES, md_path, "agentType"),
        engine=_engine(meta.get("engine", defaults.engine), md_path, "engine"),
        model=_str(meta.get("model", defaults.model), md_path, "model"),
        effort=_choice(meta.get("effort", defaults.effort), EFFORTS, md_path, "effort"),
        timeout_s=_positive(meta.get("timeoutS", defaults.timeout_s), md_path, "timeoutS", int),
        read_only=_bool(meta.get("readOnly", True), md_path, "readOnly"),
        output_kind=output_kind,
        instructions=_str(body, md_path, "<body>"),
        schema=schema,
    )


def _agent_schema(directory: Path) -> dict[str, Any]:
    schema_path = directory / "schema.json"
    if not schema_path.is_file():
        raise _fail(schema_path, "<file>", "outputKind is json but schema.json is missing")
    try:
        schema = json.loads(_read_text(schema_path))
    except json.JSONDecodeError as exc:
        raise _fail(schema_path, "<document>", f"invalid JSON: {exc}") from exc
    return dict(_mapping(schema, schema_path, "<document>"))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read file: {exc.strerror or exc}") from exc


def _agents(
    root: Path, defaults: AgentDefaults, engines: Mapping[str, Any], factory_path: Path
) -> dict[str, AgentConfig]:
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        raise _fail(factory_path, "agents", f"directory not found: {agents_dir}")
    agents = {}
    for directory in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
        agent = _agent(directory, defaults)
        if agent.engine not in engines:
            problem = f"{agent.engine!r} is not configured under engines in {factory_path}"
            raise _fail(directory / "agent.md", "engine", problem)
        agents[agent.name] = agent
    return agents


def load_factory(path: str | Path) -> FactoryConfig:
    """Load and validate a factory definition tree rooted at the directory holding `path`."""
    path = Path(path)
    data = _read_yaml(path)
    version = _required(data, "schemaVersion", path, "")
    if version != SCHEMA_VERSION:
        raise _fail(path, "schemaVersion", f"{version!r} is unsupported, expected {SCHEMA_VERSION!r}")
    defaults = _defaults(data, path)
    engines = _engines(data, path)
    if defaults.engine not in engines:
        raise _fail(path, "agentDefaults.engine", f"{defaults.engine!r} is not configured under engines")
    return FactoryConfig(
        name=_str(_required(data, "name", path, ""), path, "name"),
        schema_version=version,
        repositories=_repositories(data, path),
        agent_defaults=defaults,
        human_gates=_gates(data, path),
        budget=_budget(data, path),
        engines=engines,
        runners=_runners(data, path),
        agents=_agents(path.parent, defaults, engines, path),
        ticket_label=_str(data.get("ticketLabel", DEFAULT_TICKET_LABEL), path, "ticketLabel"),
    )
