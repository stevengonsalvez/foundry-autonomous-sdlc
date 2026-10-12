"""verify_egress against fake ARM, Foundry and probe replies. No Azure access."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts import verify_egress as ve

# Taken from the module under test: importing it is what puts agents/ on sys.path, and it is the one
# DeployError and Config class verify_egress sees.
da = ve.da
HttpRequest = da.HttpRequest
HttpResponse = ve.HttpResponse

SUB = "9c5f866c-0000-4000-8000-000000000000"
ENDPOINT = "https://aif-fsdlcd.services.ai.azure.com/api/projects/proj-sdlc"
POLICY = (
    f"/subscriptions/{SUB}/resourceGroups/rg-fsdlcd-demo/providers/Microsoft.CognitiveServices/"
    "accounts/aif-fsdlcd/raiPolicies/sdlc-coder-egress"
)
CONFIG = da.Config(
    project_endpoint=ENDPOINT,
    key_vault_uri="https://kv-x.vault.azure.net/",
    subscription_id=SUB,
    resource_group="rg-fsdlcd-demo",
    egress_policy_id=POLICY,
)

OK = {"url": "https://registry.npmjs.org/", "status": 200, "issuer": "CA"}
OPEN = {"url": "https://example.com/", "status": 200, "issuer": "CA"}
REFUSED = {
    "url": "https://example.com/",
    "status": 403,
    "issuer": "CA",
    "deny_reason": "example.com:GET",
}
ORIGIN_403 = {"url": "https://example.com/", "status": 403, "issuer": "CA"}  # a CDN's own refusal
DNS = {"url": "https://example.com/", "error": "URLError"}


@pytest.mark.parametrize(
    ("mode", "allowed", "blocked", "passes"),
    [
        ("Enforced", OK, REFUSED, True),
        ("Enforced", OK, OPEN, False),  # the policy let an unlisted host through
        ("Enforced", OK, DNS, False),  # a DNS failure is not a proxy denial
        ("Enforced", OK, ORIGIN_403, False),  # a 403 without the proxy's x-deny-reason is not proof
        ("Enforced", {**OK, "status": 403}, REFUSED, False),  # the allow rule did not apply
        ("Enforced", {}, REFUSED, False),  # no status at all is not an answer
        ("Enforced", {**OK, "status": "200"}, REFUSED, False),
        ("Enforced", {**OK, "status": True}, REFUSED, False),
        ("Enforced", {**OK, "status": 199}, REFUSED, False),
        (
            "Enforced",
            {**OK, "status": 399},
            REFUSED,
            True,
        ),  # a redirect is an answer (none are followed)
        ("Enforced", {**OK, "status": 404}, REFUSED, False),
        ("Audit", OK, OPEN, True),
        ("Audit", OK, REFUSED, False),  # Audit must only log
        ("Audit", OK, ORIGIN_403, False),
        ("Audit", OK, {}, False),
        ("Audit", {**OK, "error": "TimeoutError", "status": None}, OPEN, False),
        ("enforced", OK, OPEN, False),  # an unknown mode never passes
        (None, OK, OPEN, False),
        ("Enforced", "oops", REFUSED, False),  # a malformed reply never passes
        ("Enforced", OK, None, False),
    ],
)
def test_judge(mode: str | None, allowed: Any, blocked: Any, passes: bool) -> None:
    assert (ve.judge(mode, allowed, blocked) == []) is passes


class Foundry:
    """The slice of FoundryOps verify uses, recording the order of calls."""

    def __init__(
        self,
        *,
        coder_policy: str | None = POLICY,
        coder_fingerprint: str | None = None,
        stale_probe: bool = False,
        probe_status: str = "active",
        attach_as: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.agents: dict[str, dict[str, str]] = {}
        self.versions: dict[tuple[str, str], dict[str, Any]] = {}
        self.probe_status, self.attach_as = probe_status, attach_as
        self.coder_fingerprint = coder_fingerprint
        if coder_policy is not None:
            self.agents[da.CODER] = {"latest_version": "7"}
            self.versions[(da.CODER, "7")] = {
                "status": "active",
                "error": None,
                "rai_policy": coder_policy,
                "env": {},
            }
        if stale_probe:
            self.agents[ve.PROBE] = {"latest_version": "0"}

    def get_agent(self, name: str) -> dict[str, Any] | None:
        return self.agents.get(name)

    def create_hosted_version(self, name: str, *, rai_policy: str = "", **_: Any) -> str:
        self.calls.append(("create", name))
        self.agents[name] = {"latest_version": "1"}
        self.versions[(name, "1")] = {
            "status": self.probe_status,
            "error": {"message": "boom"} if self.probe_status == "failed" else None,
            "rai_policy": self.attach_as if self.attach_as is not None else rai_policy,
            "env": {},
        }
        return "1"

    def get_version(self, name: str, version: str) -> dict[str, Any]:
        return self.versions[(name, version)]

    def delete_agent(self, name: str) -> None:
        self.calls.append(("delete", name))
        self.agents.pop(name, None)


class Http:
    def __init__(
        self,
        *,
        egress: dict[str, Any] | None = None,
        reply: Any = None,
        status: int = 200,
        raises: bool = False,
        conflicts: int = 0,
    ) -> None:
        self.conflicts = conflicts
        self.egress = (
            egress
            if egress is not None
            else {"mode": "Audit", "defaultAction": "Deny", "rules": []}
        )
        self.reply = reply if reply is not None else {"allowed": OK, "blocked": OPEN}
        self.status, self.raises = status, raises

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.method == "GET" and "/raiPolicies/" in request.url:
            return HttpResponse(
                200, {}, json.dumps({"properties": {"egressPolicy": self.egress}}).encode()
            )
        op = json.loads(request.body or b"{}").get("op")
        if self.conflicts > 0:
            self.conflicts -= 1
            return HttpResponse(409, {}, b'{"error": {"code": "agent_version_failed"}}')
        if op == "caps":
            return HttpResponse(200, {}, b'{"euid": 0}')
        if self.raises:
            raise RuntimeError("connection reset")
        body = self.reply if isinstance(self.reply, bytes) else json.dumps(self.reply).encode()
        return HttpResponse(self.status, {}, body)


def run(http: Http, foundry: Foundry, **kw: Any) -> int:
    return ve.verify(
        config=CONFIG,
        policy_id=POLICY,
        foundry=foundry,
        http=http,
        token=lambda _: "t",
        sleep=lambda _: None,
        **kw,
    )


def fingerprint_of(http: Http) -> str:
    return da.read_egress_policy(http, "t", POLICY).fingerprint


def attached_foundry(http: Http, **kw: Any) -> Foundry:
    foundry = Foundry(**kw)
    foundry.versions[(da.CODER, "7")]["env"] = {"EGRESS_FINGERPRINT": fingerprint_of(http)}
    return foundry


def test_audit_passes_when_both_answer_and_everything_is_attached(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http = Http()
    foundry = attached_foundry(http)
    assert run(http, foundry) == 0
    assert "PASS Audit" in capsys.readouterr().out
    assert foundry.calls == [("create", ve.PROBE), ("delete", ve.PROBE)]


def test_enforced_passes_only_when_the_blocked_host_gets_403(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http = Http(
        egress={"mode": "Enforced", "defaultAction": "Deny", "rules": []},
        reply={"allowed": OK, "blocked": REFUSED},
    )
    assert run(http, attached_foundry(http)) == 0
    assert "PASS Enforced" in capsys.readouterr().out
    http.reply = {"allowed": OK, "blocked": OPEN}
    assert run(http, attached_foundry(http)) == 1
    assert "FAIL Enforced: blocked URL was not refused" in capsys.readouterr().out


@pytest.mark.parametrize(
    "http",
    [
        Http(status=500),  # the probe call fails
        Http(reply=b"not json"),  # malformed reply
        Http(reply={"allowed": OK}),  # a field is missing
        Http(reply={"allowed": "ok", "blocked": OPEN}),  # a field is not an object
        Http(reply={"allowed": OK, "blocked": REFUSED}),  # Audit saw a refusal: judge fails
    ],
)
def test_every_failing_exit_still_deletes_the_probe(
    http: Http, capsys: pytest.CaptureFixture[str]
) -> None:
    foundry = attached_foundry(http)
    assert run(http, foundry) == 1
    assert "FAIL" in capsys.readouterr().out
    assert foundry.calls[-1] == ("delete", ve.PROBE)


def test_an_exception_while_probing_still_deletes_the_probe() -> None:
    http = Http(raises=True)
    foundry = attached_foundry(http)
    with pytest.raises(RuntimeError):
        run(http, foundry)
    assert foundry.calls[-1] == ("delete", ve.PROBE)


def test_a_probe_version_that_fails_is_reported_and_deleted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http = Http()
    foundry = attached_foundry(http, probe_status="failed")
    assert run(http, foundry) == 1
    assert "FAIL probe version failed" in capsys.readouterr().out
    assert foundry.calls[-1] == ("delete", ve.PROBE)


def test_a_probe_version_without_the_policy_fails_even_in_audit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http = Http()  # Audit: both URLs answer, which looks exactly like no policy at all
    foundry = attached_foundry(http, attach_as="")
    assert run(http, foundry) == 1
    assert "probe version carries rai_policy ''" in capsys.readouterr().out
    assert foundry.calls[-1] == ("delete", ve.PROBE)


def test_a_stale_probe_is_deleted_before_a_new_one_is_created() -> None:
    http = Http()
    foundry = attached_foundry(http, stale_probe=True)
    assert run(http, foundry) == 0
    assert foundry.calls == [("delete", ve.PROBE), ("create", ve.PROBE), ("delete", ve.PROBE)]


def test_keep_leaves_the_probe_deployed() -> None:
    http = Http()
    foundry = attached_foundry(http)
    assert run(http, foundry, keep=True) == 0
    assert ("delete", ve.PROBE) not in foundry.calls


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"coder_policy": ""}, "carries egress policy none, not sdlc-coder-egress"),
        ({"coder_policy": "/other/raiPolicies/x"}, "carries egress policy /other/raiPolicies/x"),
        ({"coder_policy": None}, "sdlc-coder is not deployed"),
    ],
)
def test_the_live_coder_must_carry_the_policy(
    kwargs: dict[str, Any], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    http = Http()
    foundry = (
        attached_foundry(http, **kwargs)
        if kwargs.get("coder_policy") is not None
        else Foundry(**kwargs)
    )
    assert run(http, foundry) == 1
    assert message in capsys.readouterr().out


def test_a_coder_deployed_against_an_older_policy_state_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    http = Http()
    foundry = attached_foundry(http)
    http.egress = {
        "mode": "Enforced",
        "defaultAction": "Deny",
        "rules": [],
    }  # the mode changed since
    http.reply = {"allowed": OK, "blocked": REFUSED}
    assert run(http, foundry) == 1
    assert "was deployed against 'Audit-" in capsys.readouterr().out


def test_no_coder_check_verifies_the_policy_alone() -> None:
    http = Http()
    assert run(http, Foundry(coder_policy=None), check_coder=False) == 0


@pytest.mark.parametrize(
    "egress",
    [
        {"mode": "Audit", "defaultAction": "Allow", "rules": []},
        {"mode": "Nope", "defaultAction": "Deny", "rules": []},
        {},
    ],
)
def test_a_malformed_policy_fails_before_anything_is_deployed(
    egress: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    foundry = Foundry()
    assert run(Http(egress=egress), foundry) == 1
    assert "FAIL egress policy sdlc-coder-egress" in capsys.readouterr().out
    assert foundry.calls == []


def test_a_policy_from_another_account_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    foundry = Foundry()
    stale = POLICY.replace("accounts/aif-fsdlcd/", "accounts/aif-other/")
    assert (
        ve.verify(config=CONFIG, policy_id=stale, foundry=foundry, http=Http(), token=lambda _: "t")
        == 1
    )
    assert "belongs to account aif-other" in capsys.readouterr().out
    assert foundry.calls == []


def test_a_transient_409_on_the_first_call_is_retried(capsys: pytest.CaptureFixture[str]) -> None:
    http = Http(conflicts=2)
    assert run(http, attached_foundry(http)) == 0
    assert capsys.readouterr().out.count("retrying") == 2


def test_a_persistent_409_fails_after_the_retries_and_still_deletes_the_probe() -> None:
    http = Http(conflicts=99)
    foundry = attached_foundry(http)
    assert run(http, foundry) == 1
    assert foundry.calls[-1] == ("delete", ve.PROBE)
