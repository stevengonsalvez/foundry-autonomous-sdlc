"""
CliFoundry: `sdlc_agents.ports.FoundryPort` over local CLI engines (decision D4).

Prompt agents
- The agent comes from FactoryConfig (factory/agents/<name>/agent.md). The prompt is its
  instructions followed by the input text run_agent built (untrusted sections already nonce-wrapped).
- Each call runs the agent's engine read-only (agy plan mode) in a fresh empty cwd with a fresh HOME
  holding only a 0600 copy of the token file; both are deleted after the call.
- JSON agents: fences and prose are stripped with extract_json and the answer is checked against the
  agent's schema; a failure gets ONE internal repair call. Whatever comes back is returned as compact
  JSON text (raw text when nothing parsed), because run_agent owns validation, its own repair and
  AgentOutputError. Markdown agents: the text as the engine returned it.
- AgentResult tokens come from the engine Usage; thinking tokens count as output.
- agy takes no image input and no output token limit: image URLs are listed in the prompt as text and
  max_output_tokens is ignored.

Failures map onto what tick and run_agent already handle (AgentRunError attributes):
- TIMEOUT, EMPTY, FAILED: transient, so the object defers and nothing counts against it.
- DENIED (the model reached for a tool in plan mode): a real agent failure, not transient.
- AUTH: not transient, with a message that names the token and never the device-login URL.
- QUOTA: QuotaError, transient with a retry hint longer than any tick, so call_with_retry gives up
  at once and the object defers; `quota_hit` turns true so the caller can escalate agent-quota, and
  for QUOTA_HOLD_S later calls raise QuotaError without spawning the engine.
- AUTH: AuthError (non-transient). A binary that cannot run, a missing token file, an unknown agent
  or a refused argv: plain non-transient AgentRunError, so a setup fault is never deferred as transient.

Budget (decision D7)
Every engine call (repairs included) and its wall minutes are counted, thread-safe, across all issues.
`usage_summary()` snapshots them; `surrogate_usd(calls, minutes)` prices them as
calls * budget.callUsd + minutes * budget.minuteUsd. The token counts in AgentResult are NOT a price
here. How C7 maps this onto the existing USD caps without touching cost.py: one activity runs one
issue (the foreman queue is serialized, D6), so it takes `usage_summary()` before and after the step
and charges `surrogate_usd(delta calls, delta minutes)` to the issue and the tick total; the caps in
factory.yaml are chosen so perIssue.maxCalls * callUsd equals ports.Budget.usd_cap_issue.

Hosted agents
- sdlc-coder: POST JSON to `{coder_url}/invoke`, `?agent_session_id=` when a session is known; the
  session id comes back in the `x-agent-session-id` header (docs/architecture.md "Coder contract").
  Errors are classified exactly like FoundryClient.invoke_hosted, so tick's lease, adopt and
  session_not_accessible logic runs unchanged.
- any other agent (sdlc-ledger): an injected `ledger_handler(agent, body, session_id)`, else an error.
"""

from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdlc_agents import schema_check
from sdlc_agents.foundry import SESSION_HEADER, AgentRunError, is_transient_status
from sdlc_agents.ports import AgentResult
from sdlc_agents.transport import HttpRequest, HttpResponse, Transport

from sdlc_factory.config import AgentConfig, ConfigError, FactoryConfig, load_factory
from sdlc_factory.engines import (
    _REPAIR_OVERHEAD_CHARS,
    MAX_PROMPT_CHARS,
    NOT_FOUND_RC,
    AgyEngine,
    CliEngine,
    EngineResult,
    JsonExtractError,
    Outcome,
    Runner,
    Usage,
    _repair_prompt,
    extract_json,
    run_engine,
    subprocess_runner,
)

CODER_AGENT = "sdlc-coder"
DEFAULT_FACTORY_CONFIG = "factory/factory.yaml"
QUOTA_RETRY_AFTER_S = 6 * 3600.0    # longer than any tick deadline: never retried inside one
QUOTA_HOLD_S = 900.0                # after a quota hit, calls fail fast for this long instead of spawning
PROMPT_MODE = "plan"
_TRANSIENT_OUTCOMES = frozenset({Outcome.TIMEOUT, Outcome.EMPTY, Outcome.FAILED})

EngineFactory = Callable[[AgentConfig], CliEngine]
# (agent, body, session_id) -> (reply, session_id). Failures must raise AgentRunError, classified like
# invoke_hosted's, since tick reads only its transient, ambiguous and http_status attributes.
LedgerHandler = Callable[[str, dict[str, Any], str | None], tuple[dict[str, Any], str]]


class QuotaError(AgentRunError):
    """The engine account's quota is spent. Transient for the object; the owner rotates or waits."""


class AuthError(AgentRunError):
    """The engine token is missing or expired. Not transient; an owner problem, not the object's."""


@dataclass(frozen=True)
class _Answer:
    text: str
    usage: Usage


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_transport(request: HttpRequest) -> HttpResponse:
    """urllib without redirects, like sdlc_agents.transport, but plain http is allowed: the coder is a
    service on the private compose network."""
    if urllib.parse.urlparse(request.url).scheme not in ("http", "https"):
        raise ValueError(f"refusing non-http URL: {request.url}")
    req = urllib.request.Request(request.url, data=request.body, method=request.method, headers=request.headers)
    try:
        with _OPENER.open(req, timeout=request.timeout_s) as resp:
            return HttpResponse(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return HttpResponse(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, body)


def default_engine_factory(config: FactoryConfig) -> EngineFactory:
    """agy for every agent. agy 1.4.2 has no model or effort flag, so those settings are not passed."""

    def build(agent: AgentConfig) -> CliEngine:
        if agent.engine != "agy":
            raise ConfigError(f"agent {agent.name}: engine {agent.engine!r} has no CliEngine")
        binary = str(config.engines["agy"].get("binary", "agy"))
        return AgyEngine(binary=Path(shutil.which(binary) or binary))

    return build


class CliFoundry:
    def __init__(self, config: FactoryConfig, *, token_path: str | Path, coder_url: str | None = None,
                 engine_factory: EngineFactory | None = None, runner: Runner = subprocess_runner,
                 transport: Transport = http_transport, ledger_handler: LedgerHandler | None = None,
                 coder_token: str | None = None, monotonic: Callable[[], float] = time.monotonic):
        if coder_url is not None and urllib.parse.urlparse(coder_url).scheme not in ("http", "https"):
            raise ValueError(f"coder_url must be an http(s) URL, got {coder_url!r}")
        self._config = config
        self._token_path = Path(token_path)
        self._coder_url = coder_url.rstrip("/") if coder_url else None
        self._coder_token = coder_token or None
        self._engine_factory = engine_factory or default_engine_factory(config)
        self._runner = runner
        self._transport = transport
        self._ledger_handler = ledger_handler
        self._monotonic = monotonic
        mode = config.engines.get("agy", {}).get("promptMode", PROMPT_MODE)
        if mode != PROMPT_MODE:   # prompt agents never edit: no config value may widen that
            raise ConfigError(f"engines.agy.promptMode must be {PROMPT_MODE!r}, got {mode!r}")
        self._lock = threading.Lock()
        self._calls = 0
        self._seconds = 0.0
        self._quota_hit = False
        self._quota_until = float("-inf")

    @classmethod
    def from_env(cls, **kw: Any) -> CliFoundry:
        """FACTORY_CONFIG (default factory/factory.yaml), AGY_TOKEN_FILE (required), CODER_URL (optional)."""
        token = os.environ.get("AGY_TOKEN_FILE", "").strip()
        if not token:
            raise ValueError("AGY_TOKEN_FILE is not set: it must name the agy login token file")
        config = load_factory(os.environ.get("FACTORY_CONFIG") or DEFAULT_FACTORY_CONFIG)
        return cls(config, token_path=token, coder_url=os.environ.get("CODER_URL") or None,
                   coder_token=os.environ.get("CODER_SERVICE_TOKEN") or None, **kw)

    # ------------------------------------------------------------------------------ budget (D7)

    @property
    def quota_hit(self) -> bool:
        with self._lock:
            return self._quota_hit

    def surrogate_usd(self, calls: int, minutes: float) -> float:
        budget = self._config.budget
        return round(calls * budget.call_usd + minutes * budget.minute_usd, 6)

    def usage_summary(self) -> dict[str, Any]:
        with self._lock:
            calls, minutes, quota = self._calls, self._seconds / 60, self._quota_hit
        return {"calls": calls, "minutes": round(minutes, 4), "usd": self.surrogate_usd(calls, minutes),
                "quota_hit": quota}

    def _count(self, seconds: float, *, quota: bool = False) -> None:
        with self._lock:
            self._calls += 1
            self._seconds += max(seconds, 0.0)
            if quota:
                self._quota_hit = True
                self._quota_until = self._monotonic() + QUOTA_HOLD_S

    def _quota_held(self) -> bool:
        with self._lock:
            return self._monotonic() < self._quota_until

    # ---------------------------------------------------------------------------- prompt agents

    def call_prompt_agent(self, agent: str, input_text: str, *, image_urls: list[str] | None = None,
                          max_output_tokens: int = 8000) -> AgentResult:
        del max_output_tokens   # agy has no output token limit
        conf = self._agent(agent)
        prompt = f"{conf.instructions}\n\n{input_text}"
        if image_urls:
            prompt += "\n\n## image_urls\n" + "\n".join(f"- {url}" for url in image_urls)
        room = MAX_PROMPT_CHARS - (_REPAIR_OVERHEAD_CHARS if conf.schema is not None else 0)
        if len(prompt) > room:
            raise AgentRunError(f"{agent}: prompt is {len(prompt)} chars, over the {room} the engine takes")
        if self._quota_held():   # the account quota is spent: do not spawn a call that cannot succeed
            raise QuotaError(f"{agent}: quota hit within the last {QUOTA_HOLD_S:.0f} s (agent-quota)",
                             transient=True, retry_after=QUOTA_RETRY_AFTER_S, ambiguous=False)
        try:
            engine = self._engine_factory(conf)
        except (ConfigError, OSError, ValueError) as exc:
            raise AgentRunError(f"{agent}: no engine: {exc}", ambiguous=False) from None
        if conf.schema is None:
            result = self._run(engine, conf, prompt, Usage())
            answer = _Answer(result.text, result.usage)
        else:
            answer = self._json_answer(engine, conf, prompt)
        return AgentResult(answer.text, answer.usage.input_tokens,
                           answer.usage.output_tokens + answer.usage.thinking_tokens)

    def _agent(self, name: str) -> AgentConfig:
        try:
            conf = self._config.agent(name)
        except ConfigError as exc:
            raise AgentRunError(str(exc)) from None
        if not conf.read_only:
            raise AgentRunError(f"{name}: not a read-only prompt agent (readOnly is false)")
        return conf

    def _json_answer(self, engine: CliEngine, conf: AgentConfig, prompt: str) -> _Answer:
        assert conf.schema is not None
        usage, ask, text = Usage(), prompt, ""
        for _ in range(2):     # the answer, then at most one repair
            result = self._run(engine, conf, ask, usage)
            usage += result.usage
            try:
                parsed = extract_json(result.text)
                text = json.dumps(parsed, separators=(",", ":"))
                schema_check.check(conf.schema, parsed, f"{conf.name} output")
            except ValueError as exc:   # JsonExtractError included
                if isinstance(exc, JsonExtractError):
                    text = result.text
                ask = _repair_prompt(prompt, str(exc))
                continue
            return _Answer(text, usage)
        return _Answer(text, usage)    # still invalid: run_agent reports it and repairs once more

    def _run(self, engine: CliEngine, conf: AgentConfig, prompt: str, spent: Usage) -> EngineResult:
        """One engine call in a throwaway cwd and HOME. Raises AgentRunError unless the outcome is OK;
        the error carries `spent` plus this call's usage so run_agent can bill it."""
        with tempfile.TemporaryDirectory(prefix="cli-agent-") as tmp:
            cwd, home = Path(tmp) / "cwd", Path(tmp) / "home"
            cwd.mkdir(mode=0o700)
            home.mkdir(mode=0o700)
            try:
                engine.provision(home, self._token_path)
            except (OSError, ValueError) as exc:
                raise AgentRunError(f"{conf.name}: cannot provision the {engine.name} token from "
                                    f"{self._token_path}: {type(exc).__name__}", ambiguous=False) from None
            started = self._monotonic()
            result: EngineResult | None = None
            try:
                result = run_engine(engine, prompt, cwd=cwd, home=home, mode=PROMPT_MODE, schema=conf.schema,
                                    timeout_s=conf.timeout_s, runner=self._runner)
            except (OSError, ValueError) as exc:   # argv refused the call, or the schema file failed
                raise AgentRunError(f"{conf.name}: {engine.name} call not started: {exc}",
                                    ambiguous=False) from None
            finally:
                self._count(self._monotonic() - started,
                            quota=result is not None and result.outcome is Outcome.QUOTA)
        if result.returncode == NOT_FOUND_RC:
            raise AgentRunError(f"{conf.name}: {engine.name} binary cannot be run: {result.stderr[:200]}",
                                ambiguous=False)
        if result.outcome is Outcome.OK:
            return result
        raise _engine_error(conf.name, engine.name, result, spent + result.usage)

    # ------------------------------------------------------------------------------ hosted agents

    def invoke_hosted(self, agent: str, body: dict[str, Any], *, session_id: str | None = None,
                      timeout_s: int = 240) -> tuple[dict[str, Any], str]:
        if agent != CODER_AGENT:
            if self._ledger_handler is None:
                raise AgentRunError(f"{agent}: no hosted handler configured for this agent", ambiguous=False)
            return self._ledger_handler(agent, body, session_id)
        if self._coder_url is None:
            raise AgentRunError(f"{agent}: CODER_URL is not configured", ambiguous=False)
        url = f"{self._coder_url}/invoke"
        if session_id:
            url += "?" + urllib.parse.urlencode({"agent_session_id": session_id})
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._coder_token:
            headers["x-factory-token"] = self._coder_token
        request = HttpRequest("POST", url, headers, json.dumps(body).encode(), float(timeout_s))
        try:
            resp = self._transport(request)
        except OSError as exc:   # URLError, timeouts, resets
            raise AgentRunError(f"{agent}: invocation failed: {type(exc).__name__}", transient=True,
                                ambiguous=not _never_sent(exc)) from exc
        except http.client.HTTPException as exc:   # a reply cut short (IncompleteRead, bad status line)
            raise AgentRunError(f"{agent}: invocation failed: {type(exc).__name__}", transient=True) from exc
        if resp.status not in (200, 201, 202):
            raise AgentRunError(f"{agent}: invocation returned HTTP {resp.status}: {resp.text()[:200]}",
                                transient=is_transient_status(resp.status), retry_after=_retry_after(resp),
                                ambiguous=resp.status != 429, http_status=resp.status)
        try:
            data = json.loads(resp.body)
        except ValueError as exc:
            raise AgentRunError(f"{agent}: invocation returned a body that is not JSON") from exc
        if not isinstance(data, dict):
            raise AgentRunError(f"{agent}: invocation returned {type(data).__name__}, expected an object")
        body_session = data.get("session_id") if isinstance(data.get("session_id"), str) else None
        return data, resp.headers.get(SESSION_HEADER) or body_session or session_id or ""


def _engine_error(agent: str, engine: str, result: EngineResult, usage: Usage) -> AgentRunError:
    tokens = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens + usage.thinking_tokens}
    outcome = result.outcome
    if outcome is Outcome.QUOTA:
        return QuotaError(f"{agent}: {engine} quota or rate limit reached (agent-quota)", **tokens,
                          transient=True, retry_after=QUOTA_RETRY_AFTER_S, ambiguous=False)
    if outcome is Outcome.AUTH:
        # stderr holds a device-login URL and code: never in the message.
        return AuthError(f"{agent}: {engine} authentication required: the token in AGY_TOKEN_FILE is "
                             "missing or expired", **tokens, ambiguous=False)
    return AgentRunError(f"{agent}: {engine} call ended {outcome} (rc {result.returncode})", **tokens,
                         transient=outcome in _TRANSIENT_OUTCOMES)


def _retry_after(resp: HttpResponse) -> float | None:
    try:
        value = resp.headers.get("retry-after")
        return max(float(value), 0.0) if value is not None else None
    except (TypeError, ValueError):
        return None


def _never_sent(exc: OSError) -> bool:
    """True when the request provably never reached the service (refused or unresolvable)."""
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ConnectionRefusedError | socket.gaierror)
