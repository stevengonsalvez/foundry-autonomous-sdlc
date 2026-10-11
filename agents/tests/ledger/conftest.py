from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sdlc_agents.ledger import events, model

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-10-11T20:00:00Z"


def history() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "history.json").read_text())


def ticket_of(item: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return model.ticket(
        number=item["number"],
        kind="pr" if item["is_pr"] else "issue",
        title=item["title"],
        author=item["author"],
        opened_at=item["created_at"],
        closed_at=item["closed_at"],
        labels=tuple(item["labels"]),
        state_data=item["state_data"],
        comment_ids=item["comment_ids"],
        **extra,
    )


def ticket_event(item: dict[str, Any], **extra: Any) -> dict[str, Any]:
    t = ticket_of(item, **extra)
    return events.make("ticket.updated", t["updated_at"], {"ticket": t}, issue=t["issue"])


@pytest.fixture(scope="session")
def real() -> dict[int, dict[str, Any]]:
    """The 22 real owner objects of the 2026-10-10 run, captured from GitHub (state comments as written)."""
    return {h["number"]: h for h in history()}
