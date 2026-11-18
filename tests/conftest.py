from __future__ import annotations

import os
from pathlib import Path

import pytest

# api.py loads its config at import time; point it at the example config.
os.environ.setdefault(
    "DYNAMIC_PI4B_FAN_CONFIG", str(Path(__file__).parent.parent / "config" / "example.toml")
)

from dynamic_pi4b_fan.config import load_config  # noqa: E402

EXAMPLE = Path(__file__).parent.parent / "config" / "example.toml"


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[float] = []
        self.closed = False

    def setup(self) -> None:
        pass

    def set_duty(self, duty_percent: float) -> None:
        self.calls.append(duty_percent)

    def close(self) -> None:
        self.closed = True

    @property
    def duty(self) -> float:
        return self.calls[-1]


@pytest.fixture
def config():
    cfg = load_config(EXAMPLE)
    cfg.fan.kick_seconds = 0  # no sleeping in tests unless a test wants it
    return cfg


@pytest.fixture
def backend():
    return FakeBackend()
