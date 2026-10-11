"""Issue and PR comments that are written once per marker and updated in place afterwards."""

from __future__ import annotations

from .ghcli import Runner, api_list, api_send

BOT = "github-actions[bot]"


def upsert_comment(run: Runner, repo: str, number: int, marker: str, body: str) -> str:
    """Post `body` (which must start with `marker`) or update the comment that already has it.

    Only this workflow's own comments count: on a public repository anyone can post a comment that
    contains a marker, and that must neither be edited nor hide the real one."""
    existing = next(
        (
            c
            for c in api_list(run, f"repos/{repo}/issues/{number}/comments?per_page=100")
            if (c.get("user") or {}).get("login") == BOT
            and (c.get("body") or "").startswith(marker)
        ),
        None,
    )
    if existing is None:
        api_send(run, "POST", f"repos/{repo}/issues/{number}/comments", {"body": body})
        return "created"
    if existing["body"] == body:
        return "unchanged"
    api_send(run, "PATCH", f"repos/{repo}/issues/comments/{existing['id']}", {"body": body})
    return "updated"
