"""
Versioning and publishing (docs/architecture.md, "Release").

Tags are vMAJOR.MINOR.PATCH; a feature bumps minor, a bugfix or maintenance change bumps patch,
and the first tag is v0.1.0. Publishing is idempotent: if the tag already exists the release is
not created again. Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sdlc_agents.ports import REPO, GitHubPort
from sdlc_agents.sanitise import one_line, sanitise_markdown

FIRST_VERSION = "v0.1.0"
_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def bump_for(object_type: str) -> str:
    return "minor" if object_type == "feature" else "patch"


def next_version(tags: Iterable[str], bump: str) -> str:
    versions = [tuple(int(g) for g in m.groups()) for t in tags if (m := _TAG_RE.match(t))]
    if not versions:
        return FIRST_VERSION
    major, minor, patch = max(versions)
    if bump == "minor":
        return f"v{major}.{minor + 1}.0"
    if bump == "patch":
        return f"v{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump {bump!r}")


def plain_notes(title: str, commit_messages: Iterable[str]) -> str:
    """Release notes without a model, used once a spend cap is reached."""
    lines = ["### Highlights", f"- {sanitise_markdown(one_line(title, 120))}", "", "### Changes"]
    lines += [f"- {sanitise_markdown(one_line(m, 120))}" for m in commit_messages if not m.startswith("Merge ")]
    return "\n".join(lines)


def release_url(tag: str) -> str:
    return f"https://github.com/{REPO}/releases/tag/{tag}"


def publish(github: GitHubPort, *, tag: str, target_sha: str, name: str, notes: str) -> str:
    """Create the tag and GitHub Release on target_sha unless the tag already exists; return the URL."""
    if tag in github.list_tags():
        return release_url(tag)
    return github.create_release(tag=tag, target_sha=target_sha, name=name, body=notes)
