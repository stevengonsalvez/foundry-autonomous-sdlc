"""verify_egress.judge: the verdict for each policy mode. No Azure access."""

from __future__ import annotations

import pytest
from scripts import verify_egress as ve

OK = {"url": "https://registry.npmjs.org/", "status": 200}
OPEN = {"url": "https://example.com/", "status": 200}
REFUSED = {"url": "https://example.com/", "status": 403}
DNS = {"url": "https://example.com/", "error": "URLError"}


@pytest.mark.parametrize(("mode", "allowed", "blocked", "passes"), [
    ("Enforced", OK, REFUSED, True),
    ("Enforced", OK, OPEN, False),            # the policy let an unlisted host through
    ("Enforced", OK, DNS, False),             # a DNS failure is not a proxy denial
    ("Enforced", {**OK, "status": 403}, REFUSED, False),  # the allow rule did not apply
    ("Audit", OK, OPEN, True),
    ("Audit", OK, REFUSED, False),            # Audit must only log
    ("Audit", {**OK, "error": "TimeoutError"}, OPEN, False),
])
def test_judge(mode: str, allowed: dict, blocked: dict, passes: bool) -> None:
    assert (ve.judge(mode, allowed, blocked) == []) is passes
