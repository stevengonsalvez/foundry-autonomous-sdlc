"""
Run a command with a hard timeout and cooperative cancel.

Each command gets its own process group so a timeout or cancel also kills the children
(npm spawns vitest, agy spawns helpers). Output is stdout and stderr combined, tail-truncated.
No command outlives its timeout by more than KILL_GRACE_S: after SIGKILL the wait is bounded too.
Where /proc exists the group's memory is sampled while it runs (`take_memory()`), so a step
the kernel OOM-killed shows how close it came.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdlc_agents.ports import CommandResult

TIMEOUT_RC = 124
ABORTED_RC = 125
CANCELLED_RC = 130
NOT_FOUND_RC = 127
DEFAULT_MAX_OUTPUT = 200_000
KILL_GRACE_S = 60     # after SIGKILL: a process stuck in the kernel is abandoned, never waited on forever
_POLL_S = 0.25
_MEMORY_EVERY_S = 1.0
_PROC = Path("/proc")
_local = threading.local()


@dataclass(frozen=True)
class MemoryPeak:
    group_kib: int      # highest sampled sum of resident memory over the process group
    largest_kib: int    # highest VmHWM (peak resident) of any single process in it

    def describe(self) -> str:
        return f"peak group RSS {self.group_kib // 1024} MiB, largest process {self.largest_kib // 1024} MiB"


def take_memory() -> MemoryPeak | None:
    """Memory of the latest run() in this thread, once; None where /proc is missing (not Linux)."""
    peak, _local.memory = getattr(_local, "memory", None), None
    return peak


def cgroup_memory(root: Path = Path("/sys/fs/cgroup")) -> str:
    """The container's memory limit and peak (cgroup v2), or "" where there is none."""
    parts = []
    for name in ("memory.max", "memory.peak"):
        try:
            value = (root / name).read_text().strip()
        except OSError:
            continue
        parts.append(f"{name} {int(value) // 2**20} MiB" if value.isdigit() else f"{name} {value}")
    return f"cgroup {', '.join(parts)}" if parts else ""


def group_memory_kib(pgid: int, *, proc_root: Path = _PROC) -> tuple[int, int]:
    """(sum of VmRSS, max VmHWM) in KiB over the processes of group `pgid`."""
    total = largest = 0
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return 0, 0
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != pgid:     # after "(comm)": state ppid pgrp
                continue
            status = (entry / "status").read_text()
        except (OSError, IndexError, ValueError):
            continue   # exited between listing and reading
        values = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
        total += _kib(values.get("VmRSS", ""))
        largest = max(largest, _kib(values.get("VmHWM", "")))
    return total, largest


def _kib(field: str) -> int:
    words = field.split()
    return int(words[0]) if words and words[0].isdigit() else 0


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
    sample = _PROC.is_dir()
    peak = [0, 0]
    next_sample = 0.0
    while proc.poll() is None:
        if sample and time.monotonic() >= next_sample:
            group, largest = group_memory_kib(proc.pid)
            peak = [max(peak[0], group), max(peak[1], largest)]
            next_sample = time.monotonic() + _MEMORY_EVERY_S
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

    _local.memory = MemoryPeak(*peak) if sample else None
    _kill_group(proc)   # on a stop, and also children left behind (daemons, watchers) after a normal exit
    try:
        proc.wait(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        stopped = (TIMEOUT_RC, f"[process did not exit {KILL_GRACE_S}s after SIGKILL; abandoned]")
    reader.join(timeout=5)
    with lock:
        text = buffer.decode("utf-8", errors="replace")
    if stopped:
        text += f"\n{stopped[1]}\n"
    if len(text) > max_output:
        text = text[-max_output:]
    return CommandResult(stopped[0] if stopped else proc.returncode, text)


def capture(args: list[str], *, cwd: Path | str, env: dict[str, str] | None, timeout_s: float) -> tuple[int, str, str]:
    """Run `args` with stdout and stderr kept apart; on timeout the whole group is killed and the drain
    is bounded, so a grandchild holding the pipes (git's credential or transport helpers) cannot hang it."""
    proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,  # noqa: S603
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout_s)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=KILL_GRACE_S)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        code = TIMEOUT_RC
    _kill_group(proc)
    return code, out or "", err or ""


def _kill_group(proc: subprocess.Popen[Any]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):  # group already gone or reused
        os.killpg(proc.pid, signal.SIGKILL)
