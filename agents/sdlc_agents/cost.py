"""
Spend accounting: prompt agent tokens, coder compute and coder model spend per object, and the
orchestrator's own compute per tick.

Prices (USD):
- gpt-5-mini, Global Standard: 0.25 per 1M input tokens, 2.00 per 1M output tokens. Reasoning
  tokens are billed as output and are included in the output count the Responses API reports.
- Hosted agent compute, UK South, Azure Retail Prices API (productName 'Foundry Agents', skuName
  'Hosted', queried 2026-10-10), billed only while a session is active:
    'Hosted vCPU Usage'   0.10934 per vCPU hour
    'Hosted Memory Usage' 0.01298 per GiB hour
  Query: https://prices.azure.com/api/retail/prices?$filter=productName eq 'Foundry Agents'
  and armRegionName eq 'uksouth'
- Coder: 2 vCPU, 4 GiB (scripts/deploy_agents.py), so 0.2706 USD per hour, charged per second of
  job time the coder reports (elapsed_s), plus the model spend it reports for its fallback engine.
- Orchestrator: 1 vCPU, 2 GiB with a 2 minute idle timeout, so each tick costs
  (tick seconds + 120) / 3600 * 0.13530 USD. It belongs to no object and is added to totals.usd.

Stdlib only.
"""

from __future__ import annotations

from sdlc_agents.state import State

INPUT_USD_PER_MTOK = 0.25
OUTPUT_USD_PER_MTOK = 2.00

HOSTED_VCPU_USD_PER_HOUR = 0.10934
HOSTED_GIB_USD_PER_HOUR = 0.01298


def hosted_usd_per_hour(vcpu: float, gib: float) -> float:
    return vcpu * HOSTED_VCPU_USD_PER_HOUR + gib * HOSTED_GIB_USD_PER_HOUR


CODER_VCPU, CODER_GIB = 2.0, 4.0
CODER_USD_PER_SECOND = hosted_usd_per_hour(CODER_VCPU, CODER_GIB) / 3600
ORCHESTRATOR_VCPU, ORCHESTRATOR_GIB = 1.0, 2.0
ORCHESTRATOR_IDLE_S = 120
ORCHESTRATOR_USD_PER_SECOND = hosted_usd_per_hour(ORCHESTRATOR_VCPU, ORCHESTRATOR_GIB) / 3600

# The call list lives in the state comment (65,536 char limit): older calls fold into one entry.
MAX_CALL_ENTRIES = 40
EARLIER = "earlier-calls"


def token_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * INPUT_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK) / 1_000_000


def coder_usd(seconds: int) -> float:
    return seconds * CODER_USD_PER_SECOND


def orchestrator_tick_usd(tick_seconds: float) -> float:
    return (max(tick_seconds, 0.0) + ORCHESTRATOR_IDLE_S) * ORCHESTRATOR_USD_PER_SECOND


def _recompute(state: State) -> None:
    cost = state.data["cost"]
    model = sum(call["usd"] for call in cost["calls"])
    cost["coder_usd"] = round(coder_usd(cost["coder_seconds"]), 6)
    cost["usd"] = round(model + cost["coder_usd"] + float(cost.get("coder_model_usd", 0.0)), 6)


def record_call(state: State, agent: str, input_tokens: int, output_tokens: int) -> float:
    """Append one model call to the object's cost and return its USD."""
    usd = round(token_usd(input_tokens, output_tokens), 8)
    calls = state.data["cost"]["calls"]
    calls.append({"agent": agent, "in": input_tokens, "out": output_tokens, "usd": usd})
    if len(calls) > MAX_CALL_ENTRIES:
        fold = calls[: len(calls) - MAX_CALL_ENTRIES + 1]
        calls[: len(fold)] = [{
            "agent": EARLIER, "in": sum(c["in"] for c in fold), "out": sum(c["out"] for c in fold),
            "usd": round(sum(c["usd"] for c in fold), 8), "count": sum(int(c.get("count", 1)) for c in fold),
        }]
    _recompute(state)
    return usd


def call_count(state: State) -> int:
    return sum(int(c.get("count", 1)) for c in state.data["cost"]["calls"])


def set_coder_spend(state: State, seconds: int, model_usd: float = 0.0) -> float:
    """Set cumulative coder seconds and coder model spend; return the USD added since the last update."""
    before = state.usd
    state.data["cost"]["coder_seconds"] = max(int(seconds), 0)
    state.data["cost"]["coder_model_usd"] = round(max(float(model_usd), 0.0), 6)
    _recompute(state)
    return state.usd - before


def model_usd(state: State) -> float:
    return round(sum(call["usd"] for call in state.data["cost"]["calls"]), 6)
