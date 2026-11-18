from __future__ import annotations

import pytest

from dynamic_pi4b_fan.backends import HardwarePwmBackend


def fake_sysfs(tmp_path):
    chip = tmp_path / "pwmchip0"
    ch = chip / "pwm0"
    ch.mkdir(parents=True)
    for name in ("export", "unexport"):
        (chip / name).write_text("")
    for name in ("enable", "duty_cycle", "period"):
        (ch / name).write_text("0")
    return ch


def test_hardware_pwm_writes_sysfs(tmp_path):
    ch = fake_sysfs(tmp_path)
    pwm = HardwarePwmBackend(0, 0, 20000, root=tmp_path)
    pwm.setup()
    assert (ch / "period").read_text() == "50000"
    assert (ch / "enable").read_text() == "1"
    pwm.set_duty(30)
    assert (ch / "duty_cycle").read_text() == "15000"
    pwm.close()
    assert (ch / "duty_cycle").read_text() == "0"
    assert (ch / "enable").read_text() == "0"
    assert (tmp_path / "pwmchip0" / "unexport").read_text() == "0"


def test_missing_overlay_has_clear_error(tmp_path):
    with pytest.raises(RuntimeError, match="dtoverlay=pwm"):
        HardwarePwmBackend(0, 0, 20000, root=tmp_path).setup()
