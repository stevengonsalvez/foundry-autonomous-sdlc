"""Hermetic test configuration for evals suite.

Blocks network socket creation to guarantee completely offline and deterministic execution.
"""

from __future__ import annotations

import _socket
import socket

import pytest


def _blocked_socket(*args: object, **kwargs: object) -> None:
    raise RuntimeError("Network socket call blocked in hermetic offline evaluation")


def pytest_configure(config: pytest.Config) -> None:
    """Block socket creation before test collection begins."""
    socket.socket = _blocked_socket  # type: ignore[assignment]
    _socket.socket = _blocked_socket  # type: ignore[assignment]


