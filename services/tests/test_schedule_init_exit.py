"""schedule-init exits hard after logging, so a lingering SDK thread cannot keep the container up."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sdlc_factory import schedule_init

SERVICES = Path(__file__).resolve().parents[1]
AGENTS = SERVICES.parent / "agents"


def test_finish_flushes_and_exits_with_the_rc() -> None:
    exits: list[int] = []
    schedule_init.finish(3, exit=exits.append)
    assert exits == [3]


@pytest.mark.parametrize("rc", [0, 1])
def test_the_process_exits_with_the_rc_even_with_a_non_daemon_thread_alive(rc: int) -> None:
    code = (
        "import logging, threading\n"
        "from sdlc_factory import schedule_init\n"
        "logging.basicConfig(level=logging.INFO)\n"
        "threading.Thread(target=threading.Event().wait).start()\n"   # would block a normal interpreter exit
        "logging.getLogger('sdlc_factory.schedule_init').info('logged-before-exit')\n"
        f"schedule_init.finish({rc})\n"
    )
    env = {**os.environ, "PYTHONPATH": f"{SERVICES}{os.pathsep}{AGENTS}"}
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60,
                          check=False)
    assert proc.returncode == rc, proc.stderr
    assert "logged-before-exit" in proc.stderr


def test_main_module_exits_through_finish_even_when_main_raises(monkeypatch) -> None:
    exits: list[int] = []

    async def boom() -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(schedule_init, "main", boom)
    monkeypatch.setattr(schedule_init, "finish", lambda rc, **_: exits.append(rc))
    with pytest.raises(KeyboardInterrupt):
        schedule_init.run_main()
    assert exits == [1]
