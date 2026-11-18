"""Output backends that turn a duty cycle (0-100 %) into a fan signal."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Protocol

from .config import AppConfig

SYSFS_PWM = Path("/sys/class/pwm")


class FanBackend(Protocol):
    def setup(self) -> None: ...

    def set_duty(self, duty_percent: float) -> None: ...

    def close(self) -> None: ...


class HardwarePwmBackend:
    """BCM2711 hardware PWM via sysfs.

    Requires the overlay ``dtoverlay=pwm,pin=18,func=2`` in /boot/firmware/config.txt
    (GPIO 18 = PWM0 channel 0). The pin is chosen by the overlay, not by gpio_pin.
    """

    def __init__(self, chip: int, channel: int, frequency_hz: int, root: Path = SYSFS_PWM) -> None:
        self._chip_dir = root / f"pwmchip{chip}"
        self._channel = channel
        self._ch_dir = self._chip_dir / f"pwm{channel}"
        self._period_ns = round(1e9 / frequency_hz)
        self._logger = logging.getLogger("dynamic_pi4b_fan.backends")

    def setup(self) -> None:
        if not self._chip_dir.exists():
            raise RuntimeError(
                f"{self._chip_dir} not found - add 'dtoverlay=pwm,pin=18,func=2' to "
                "/boot/firmware/config.txt and reboot (or load it now with "
                "'sudo dtoverlay pwm pin=18 func=2'), or set [pwm] backend = \"onoff\""
            )
        if not self._ch_dir.exists():
            (self._chip_dir / "export").write_text(str(self._channel))
            # the kernel creates the channel directory asynchronously
            for _ in range(20):
                if (self._ch_dir / "period").exists():
                    break
                time.sleep(0.05)
        # duty_cycle must never exceed period, so lower it first
        self._write("enable", 0)
        self._write("duty_cycle", 0)
        self._write("period", self._period_ns)
        self._write("enable", 1)
        self._logger.info(
            "Hardware PWM ready: %s, %.0f Hz", self._ch_dir, 1e9 / self._period_ns
        )

    def set_duty(self, duty_percent: float) -> None:
        self._write("duty_cycle", round(self._period_ns * duty_percent / 100))

    def close(self) -> None:
        try:
            self._write("duty_cycle", 0)
            self._write("enable", 0)
            (self._chip_dir / "unexport").write_text(str(self._channel))
        except OSError:
            self._logger.exception("Hardware PWM cleanup failed")

    def _write(self, name: str, value: int) -> None:
        (self._ch_dir / name).write_text(str(value))


class OnOffGpioBackend:
    """Plain GPIO switching: any duty > 0 means fully on (behaviour of 1.0.x)."""

    def __init__(self, pin: int) -> None:
        self._pin = pin
        self._gpio = None

    def setup(self) -> None:
        import RPi.GPIO as GPIO  # imported lazily: only needed for this backend

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._pin, GPIO.OUT, initial=GPIO.LOW)

    def set_duty(self, duty_percent: float) -> None:
        assert self._gpio is not None
        self._gpio.output(self._pin, self._gpio.HIGH if duty_percent > 0 else self._gpio.LOW)

    def close(self) -> None:
        if self._gpio is not None:
            self._gpio.output(self._pin, self._gpio.LOW)
            self._gpio.cleanup()


def create_backend(config: AppConfig) -> FanBackend:
    pwm = config.pwm
    if pwm.backend == "hardware":
        return HardwarePwmBackend(pwm.chip, pwm.channel, pwm.frequency_hz)
    return OnOffGpioBackend(config.fan.gpio_pin)
