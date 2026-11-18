from __future__ import annotations

import pytest

from dynamic_pi4b_fan.config import load_config

BASE = """
[server]
host = "127.0.0.1"
port = 8081
auth_token = "x"

[fan]
gpio_pin = 18
temp_on_c = 60.0
temp_off_c = 50.0
poll_interval_seconds = 5
min_allowed_temp_c = 35.0
max_allowed_temp_c = 85.0
{extra}

[temperature]
command = ["true"]

[logging]
level = "INFO"
"""


def write(tmp_path, extra=""):
    path = tmp_path / "config.toml"
    path.write_text(BASE.format(extra=extra))
    return path


def test_1_0_config_gets_defaults(tmp_path):
    cfg = load_config(write(tmp_path))
    assert cfg.pwm.backend == "hardware"
    assert cfg.pwm.frequency_hz == 20000
    assert cfg.fan.idle_behavior == "min_duty"
    assert cfg.fan.min_duty_percent == 30
    assert cfg.fan.curve[0] == [50.0, 30.0]


@pytest.mark.parametrize(
    "extra",
    [
        'initial_mode = "forced_on"',
        'idle_behavior = "sometimes"',
        "curve = []",
        "curve = [[60, 30], [50, 40]]",
        "curve = [[60, 130]]",
        "min_duty_percent = 120",
        "kick_seconds = -1",
        "temp_off_c = 70.0\ntemp_on_c = 60.0",
    ],
)
def test_invalid_fan_config(tmp_path, extra):
    # temp_on/off overrides would duplicate keys, so rewrite them in BASE
    text = BASE.format(extra=extra)
    if "temp_off_c = 70.0" in extra:
        text = text.replace("temp_on_c = 60.0\ntemp_off_c = 50.0\n", "", 1)
    path = tmp_path / "config.toml"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_config(path)


def test_invalid_pwm_backend(tmp_path):
    path = write(tmp_path)
    path.write_text(path.read_text() + '\n[pwm]\nbackend = "software"\n')
    with pytest.raises(ValueError, match=r"\[pwm\]"):
        load_config(path)
