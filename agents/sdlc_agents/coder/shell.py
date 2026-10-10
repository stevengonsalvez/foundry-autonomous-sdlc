"""
Run a command with a hard timeout and cooperative cancel.

Each command gets its own process group so a timeout or cancel also kills the children
(npm spawns vitest, agy spawns helpers). Output is stdout and stderr combined, tail-truncated.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from sdlc_agents.ports import CommandResult

TIMEOUT_RC = 124
ABORTED_RC = 125
CANCELLED_RC = 130
NOT_FOUND_RC = 127
DEFAULT_MAX_OUTPUT = 200_000
_POLL_S = 0.25


def run(cmd: list[str] | str, *, cwd: Path | str, timeout_s: float, env: dict[str, str] | None = None,
        cancel: threading.Event | None = None, max_output: int = DEFAULT_MAX_OUTPUT,
        user: int | None = None, group: int | None = None,
        abort_on: Callable[[str], str | None] | None = None) -> CommandResult:
    """Run `cmd`, streaming its output.

    `user`/`group` drop privileges for the child with supplementary groups cleared (root only);
    `env` is the child's complete environment. `abort_on` sees the output so far and returns a
    reason to kill the command early (a CLI that blocks on a login prompt), or None.
    """
    drop: dict[str, object] = {}
    if user is not None:
        drop = {"user": user, "group": group}
        if os.geteuid() == 0:
            drop["extra_groups"] = []   # setgroups needs root; a non-root caller has nothing to drop
    try:
        proc = subprocess.Popen(  # noqa: S603  running job commands is this module's purpose
            cmd, cwd=cwd, env=env, shell=isinstance(cmd, str), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, **drop,
        )
    except (FileNotFoundError, PermissionError) as exc:
        return CommandResult(NOT_FOUND_RC, f"cannot run {cmd!r}: {exc}")

    buffer = bytearray()
    lock = threading.Lock()

    def pump() -> None:
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read1(65536), b""):  # type: ignore[union-attr]
            with lock:
                buffer.extend(chunk)
                if len(buffer) > 4 * max_output:
                    del buffer[:-2 * max_output]

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    deadline = time.monotonic() + max(timeout_s, 0)
    stopped: tuple[int, str] | None = None
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            stopped = (CANCELLED_RC, "[cancelled]")
        elif time.monotonic() >= deadline:
            stopped = (TIMEOUT_RC, f"[timed out after {timeout_s:.0f}s]")
        elif abort_on is not None:
            with lock:
                seen = buffer.decode("utf-8", errors="replace")
            reason = abort_on(seen)
            if reason:
                stopped = (ABORTED_RC, f"[aborted: {reason}]")
        if stopped:
            break
        time.sleep(_POLL_S)

    _kill_group(proc)   # on a stop, and also children left behind (daemons, watchers) after a normal exit
    proc.wait()
    reader.join(timeout=5)
    with lock:
        text = buffer.decode("utf-8", errors="replace")
    if stopped:
        text += f"\n{stopped[1]}\n"
    if len(text) > max_output:
        text = text[-max_output:]
    return CommandResult(stopped[0] if stopped else proc.returncode, text)


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):  # group already gone or reused
        os.killpg(proc.pid, signal.SIGKILL)
