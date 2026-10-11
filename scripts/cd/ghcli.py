"""The `gh` CLI as an injectable function, plus the small helpers every CD script shares."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

Runner = Callable[[list[str], str | None], str]


class GhError(RuntimeError):
    def __init__(self, args: list[str], stderr: str) -> None:
        super().__init__(f"gh {' '.join(args[:4])} failed: {stderr.strip()[:300]}")
        self.stderr = stderr

    @property
    def not_found(self) -> bool:
        return "HTTP 404" in self.stderr

    @property
    def unprocessable(self) -> bool:
        return "HTTP 422" in self.stderr


def gh(args: list[str], stdin: str | None = None) -> str:
    done = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=False)
    if done.returncode:
        raise GhError(args, done.stderr)
    return done.stdout


def api_get(run: Runner, path: str) -> Any:
    return json.loads(run(["api", path], None))


def api_send(run: Runner, method: str, path: str, body: dict[str, Any]) -> Any:
    out = run(["api", "-X", method, path, "--input", "-"], json.dumps(body))
    return json.loads(out) if out.strip() else None


def api_list(run: Runner, path: str) -> list[Any]:
    """Every item of a paginated list endpoint (`gh api --paginate --slurp` returns the pages)."""
    pages = json.loads(run(["api", "--paginate", "--slurp", path], None))
    return [item for page in pages for item in page]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def optional_int(text: str) -> int | None:
    """A CLI argument that is a number or empty (an output of a job that had nothing to say)."""
    return int(text) if text.strip() else None


def set_output(name: str, value: object) -> None:
    """Print `name=value` and, inside a workflow step, add it to the step outputs."""
    text = "" if value is None else str(value)
    if "\n" in text:
        raise ValueError(f"output {name} must be a single line")
    print(f"{name}={text}")
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={text}\n")


def fail(message: str) -> int:
    sys.stderr.write(f"error: {message}\n")
    return 1
