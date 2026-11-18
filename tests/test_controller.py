from __future__ import annotations

import pytest

from dynamic_pi4b_fan.config import DEFAULT_CURVE
from dynamic_pi4b_fan.controller import FanController, duty_from_curve


def make(config, backend, temps):
    ctl = FanController(config, backend)
    it = iter(temps)
    ctl.get_temperature = lambda: next(it)  # type: ignore[method-assign]
    ctl.setup()
    return ctl


@pytest.mark.parametrize(
    ("temp", "duty"),
    [(20, 30), (50, 30), (55, 37.5), (60, 45), (65, 55), (70, 65), (72.5, 82.5), (75, 100), (90, 100)],
)
def test_curve_interpolation(temp, duty):
    assert duty_from_curve(DEFAULT_CURVE, temp) == pytest.approx(duty)


def test_auto_min_duty_runs_continuously(config, backend):
    ctl = make(config, backend, [40.0, 65.0, 41.0])
    ctl._tick()
    assert ctl.get_state().duty_percent == 30
    ctl._tick()
    assert ctl.get_state().duty_percent == 55
    ctl._tick()
    assert ctl.get_state().duty_percent == 30
    assert ctl.get_state().fan_on


def test_auto_off_uses_hysteresis(config, backend):
    config.fan.idle_behavior = "off"
    ctl = make(config, backend, [55.0, 60.0, 55.0, 49.9, 55.0])
    duties = []
    for _ in range(5):
        ctl._tick()
        duties.append(ctl.get_state().duty_percent)
    # off until 60, on (curve) until below 50, then off again
    assert duties == [0, 45, 38, 0, 0]


def test_min_duty_is_enforced_for_curve_and_manual(config, backend):
    config.fan.curve = [[40.0, 10.0], [80.0, 100.0]]
    ctl = make(config, backend, [41.0])
    ctl._tick()
    assert ctl.get_state().duty_percent == 30
    assert ctl.set_mode("manual", 5).duty_percent == 30
    assert ctl.set_mode("manual", 70).duty_percent == 70


def test_manual_keeps_last_duty_and_off_stops(config, backend):
    ctl = make(config, backend, [45.0, 80.0])
    ctl._tick()
    ctl.set_mode("manual", 60)
    ctl._tick()  # temperature must not influence manual mode
    assert ctl.get_state().duty_percent == 60
    assert ctl.set_mode("off").duty_percent == 0
    assert not ctl.get_state().fan_on
    assert ctl.set_mode("manual").duty_percent == 60


def test_duty_only_with_manual(config, backend):
    ctl = make(config, backend, [])
    with pytest.raises(ValueError):
        ctl.set_mode("auto", 50)


def test_kick_from_standstill(config, backend, monkeypatch):
    sleeps = []
    monkeypatch.setattr("dynamic_pi4b_fan.controller.time.sleep", sleeps.append)
    config.fan.kick_seconds = 1.0
    ctl = make(config, backend, [40.0, 65.0])
    ctl._tick()
    assert backend.calls == [0, 50, 30]
    assert sleeps == [1.0]
    ctl._tick()  # already running: no kick
    assert backend.calls[-1] == 55
    assert sleeps == [1.0]


def test_no_kick_when_target_above_kick(config, backend, monkeypatch):
    monkeypatch.setattr("dynamic_pi4b_fan.controller.time.sleep", lambda s: None)
    config.fan.kick_seconds = 1.0
    ctl = make(config, backend, [80.0])
    ctl._tick()
    assert backend.calls == [0, 100]


def test_stop_switches_off_and_closes(config, backend):
    ctl = make(config, backend, [65.0])
    ctl.start()
    ctl.stop()
    assert backend.duty == 0
    assert backend.closed
