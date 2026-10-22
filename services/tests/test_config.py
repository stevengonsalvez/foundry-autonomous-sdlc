from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from sdlc_agents import definitions

from sdlc_factory.config import (
    ConfigError,
    FactoryConfig,
    HumanGates,
    load_factory,
    split_frontmatter,
)

ROOT = Path(__file__).resolve().parents[2]
FACTORY_DIR = ROOT / "factory"
FACTORY_YAML = FACTORY_DIR / "factory.yaml"
GENERATOR = ROOT / "services" / "scripts" / "gen_factory_agents.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_factory_agents", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def factory_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the factory tree that a test may corrupt."""
    dest = tmp_path / "factory"
    shutil.copytree(FACTORY_DIR, dest)
    return dest


def _edit_frontmatter(path: Path, **changes: object) -> None:
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"), path)
    meta.update(changes)
    path.write_text(f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")


# --- loading ---------------------------------------------------------------------------------------


def test_loads_factory_yaml():
    cfg = load_factory(FACTORY_YAML)

    assert isinstance(cfg, FactoryConfig)
    assert cfg.name
    assert cfg.schema_version == "v1alpha1"
    assert [(r.owner, r.name) for r in cfg.repositories] == [("stevengonsalvez", "foundry-autonomous-sdlc")]
    assert cfg.repositories[0].full_name == "stevengonsalvez/foundry-autonomous-sdlc"


def test_human_gates_are_off_for_this_deployment():
    cfg = load_factory(FACTORY_YAML)

    assert cfg.human_gates.merge is False
    assert cfg.human_gates.spec is False


def test_human_gates_default_to_off_when_omitted():
    assert HumanGates() == HumanGates(spec=False, merge=False)


def test_agent_defaults_and_engine_section():
    cfg = load_factory(FACTORY_YAML)

    assert cfg.agent_defaults.engine == "agy"
    assert cfg.agent_defaults.timeout_s > 0
    assert "agy" in cfg.engines


def test_runners_reference_existing_files():
    cfg = load_factory(FACTORY_YAML)

    assert set(cfg.runners) == {"coder", "foreman"}
    for path in cfg.runners.values():
        assert path.is_file()


def test_coder_runner_is_isolated():
    runner = yaml.safe_load((FACTORY_DIR / "runners" / "coder.yaml").read_text(encoding="utf-8"))

    assert runner["image"]
    assert runner["network"] == "internal"
    assert runner["capDrop"] == ["ALL"]
    assert "DAC_OVERRIDE" in runner["capAdd"]


# --- agents ----------------------------------------------------------------------------------------


def test_every_definition_agent_is_present_with_matching_instructions_and_schema():
    cfg = load_factory(FACTORY_YAML)

    assert len(definitions.AGENTS) == 9
    for d in definitions.AGENTS:
        agent = cfg.agent(d.name)
        assert agent.name == d.name
        assert agent.instructions.strip() == d.instructions.strip()
        assert agent.schema == d.schema
        assert agent.read_only is True
        assert agent.engine == "agy"
        assert agent.timeout_s > 0
        assert (FACTORY_DIR / "agents" / d.name / "agent.md").is_file()
        if d.schema is not None:
            assert json.loads((FACTORY_DIR / "agents" / d.name / "schema.json").read_text()) == d.schema


def test_markdown_agent_has_no_schema():
    assert load_factory(FACTORY_YAML).agent("sdlc-release-notes").schema is None


def test_foreman_and_coder_agents():
    cfg = load_factory(FACTORY_YAML)

    foreman, coder = cfg.agent("foreman"), cfg.agent("coder")
    assert foreman.agent_type == "FOREMAN"
    assert coder.agent_type == "IMPLEMENT"
    assert coder.read_only is False
    assert foreman.instructions and coder.instructions


def test_unknown_agent_name_raises_config_error():
    with pytest.raises(ConfigError, match="no-such-agent"):
        load_factory(FACTORY_YAML).agent("no-such-agent")


def test_agents_inherit_agent_defaults_when_frontmatter_omits_a_key(factory_copy: Path):
    path = factory_copy / "agents" / "sdlc-triage" / "agent.md"
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"), path)
    del meta["timeoutS"]
    path.write_text(f"---\n{yaml.safe_dump(meta, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")

    cfg = load_factory(factory_copy / "factory.yaml")

    assert cfg.agent("sdlc-triage").timeout_s == cfg.agent_defaults.timeout_s


# --- generator -------------------------------------------------------------------------------------


def test_committed_agent_files_equal_generator_output():
    gen = _load_generator()

    expected = gen.render_all()

    assert any(rel.startswith("agents/sdlc-req-gate/") for rel in expected)
    for rel, text in expected.items():
        assert (FACTORY_DIR / rel).read_text(encoding="utf-8") == text, rel


def test_generator_is_idempotent(tmp_path: Path):
    gen = _load_generator()

    assert gen.render_all() == gen.render_all()
    first = gen.write_all(tmp_path)
    second = gen.write_all(tmp_path)
    assert first == second
    assert {p.relative_to(tmp_path).as_posix() for p in first} == set(gen.render_all())
    assert gen.check(tmp_path) == []


def test_generator_check_reports_drift(tmp_path: Path):
    gen = _load_generator()
    gen.write_all(tmp_path)
    victim = tmp_path / "agents" / "sdlc-triage" / "schema.json"
    victim.write_text("{}\n", encoding="utf-8")

    assert gen.check(tmp_path) == ["agents/sdlc-triage/schema.json"]


# --- automations and placeholders ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "every"),
    [("github-issues-poll", "1m"), ("simulated-po-intake", "4h")],
)
def test_automations_are_schedules(name: str, every: str):
    path = FACTORY_DIR / "automations" / name / "automation.md"
    meta, _ = split_frontmatter(path.read_text(encoding="utf-8"), path)

    assert meta["trigger"] == {"type": "schedule", "every": every}


def test_poll_automation_is_owner_only():
    path = FACTORY_DIR / "automations" / "github-issues-poll" / "automation.md"
    meta, _ = split_frontmatter(path.read_text(encoding="utf-8"), path)

    assert meta["ownerOnly"] is True


@pytest.mark.parametrize("folder", ["skills", "scorers"])
def test_placeholder_readmes_exist(folder: str):
    assert (FACTORY_DIR / folder / "README.md").is_file()


def test_scorers_readme_says_phase_2():
    assert "phase 2" in (FACTORY_DIR / "scorers" / "README.md").read_text(encoding="utf-8").lower()


# --- budget math -----------------------------------------------------------------------------------


def test_budget_rates_are_positive_and_caps_cover_ports_budget():
    from sdlc_agents.ports import Budget

    budget = load_factory(FACTORY_YAML).budget

    assert budget.call_usd > 0
    assert budget.minute_usd > 0
    assert budget.per_issue_max_calls > 0
    assert budget.per_issue_max_minutes > 0
    assert budget.issue_cap_usd() == pytest.approx(Budget().usd_cap_issue)
    # the deployment may raise the total above the upstream default, never lower it (live runs need room)
    assert budget.total_cap_usd() >= Budget().usd_cap_total


# --- validation errors name file and key -----------------------------------------------------------


def test_unknown_engine_in_agent_raises_naming_file_and_key(factory_copy: Path):
    path = factory_copy / "agents" / "sdlc-triage" / "agent.md"
    _edit_frontmatter(path, engine="skynet")

    with pytest.raises(ConfigError) as err:
        load_factory(factory_copy / "factory.yaml")

    assert str(path) in str(err.value)
    assert "engine" in str(err.value)
    assert "skynet" in str(err.value)


def test_unknown_engine_in_defaults_raises(factory_copy: Path):
    yaml_path = factory_copy / "factory.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["agentDefaults"]["engine"] = "skynet"
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ConfigError) as err:
        load_factory(yaml_path)

    assert str(yaml_path) in str(err.value)
    assert "agentDefaults.engine" in str(err.value)


def test_bad_agent_type_names_file_and_key(factory_copy: Path):
    path = factory_copy / "agents" / "coder" / "agent.md"
    _edit_frontmatter(path, agentType="WIZARD")

    with pytest.raises(ConfigError) as err:
        load_factory(factory_copy / "factory.yaml")

    assert str(path) in str(err.value)
    assert "agentType" in str(err.value)


def test_non_positive_timeout_names_file_and_key(factory_copy: Path):
    path = factory_copy / "agents" / "sdlc-reviewer" / "agent.md"
    _edit_frontmatter(path, timeoutS=0)

    with pytest.raises(ConfigError) as err:
        load_factory(factory_copy / "factory.yaml")

    assert str(path) in str(err.value)
    assert "timeoutS" in str(err.value)


def test_json_agent_without_schema_file_raises(factory_copy: Path):
    schema = factory_copy / "agents" / "sdlc-triage" / "schema.json"
    schema.unlink()

    with pytest.raises(ConfigError) as err:
        load_factory(factory_copy / "factory.yaml")

    assert str(schema) in str(err.value)


def test_malformed_schema_json_raises(factory_copy: Path):
    schema = factory_copy / "agents" / "sdlc-triage" / "schema.json"
    schema.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError) as err:
        load_factory(factory_copy / "factory.yaml")

    assert str(schema) in str(err.value)


def test_non_positive_budget_rate_names_file_and_key(factory_copy: Path):
    yaml_path = factory_copy / "factory.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["budget"]["callUsd"] = 0
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ConfigError) as err:
        load_factory(yaml_path)

    assert str(yaml_path) in str(err.value)
    assert "budget.callUsd" in str(err.value)


def test_missing_repository_name_names_file_and_key(factory_copy: Path):
    yaml_path = factory_copy / "factory.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    del data["repositories"][0]["name"]
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ConfigError) as err:
        load_factory(yaml_path)

    assert str(yaml_path) in str(err.value)
    assert "repositories[0].name" in str(err.value)


def test_missing_runner_file_names_file_and_key(factory_copy: Path):
    (factory_copy / "runners" / "coder.yaml").unlink()

    with pytest.raises(ConfigError) as err:
        load_factory(factory_copy / "factory.yaml")

    assert "runners.coder" in str(err.value)
    assert "coder.yaml" in str(err.value)


def test_missing_factory_file_raises_config_error(tmp_path: Path):
    with pytest.raises(ConfigError, match=r"nope\.yaml"):
        load_factory(tmp_path / "nope.yaml")


def test_unsupported_schema_version_raises(factory_copy: Path):
    yaml_path = factory_copy / "factory.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    data["schemaVersion"] = "v9"
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ConfigError, match="schemaVersion"):
        load_factory(yaml_path)


def test_ticket_label_marks_work_as_the_independent_factory_and_can_be_overridden(tmp_path):
    assert load_factory(FACTORY_YAML).ticket_label == "factory:independent"
    text = FACTORY_YAML.read_text().replace("ticketLabel: factory:independent", "ticketLabel: factory:other")
    copy = tmp_path / "factory.yaml"
    copy.write_text(text)
    for sub in ("agents", "runners"):
        (tmp_path / sub).symlink_to(FACTORY_YAML.parent / sub)
    assert load_factory(copy).ticket_label == "factory:other"
