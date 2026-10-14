"""Hermetic test configuration for evals suite.

Blocks network socket creation to guarantee completely offline and deterministic execution.
"""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_network_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure zero network socket calls can be made during offline evaluation."""

    def guarded_socket(*args: object, **kwargs: object) -> socket.socket:
        raise RuntimeError("Network socket call blocked in hermetic offline evaluation")

    monkeypatch.setattr(socket, "socket", guarded_socket)
