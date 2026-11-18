from __future__ import annotations

import logging
import subprocess
import threading
import time
from datetime import datetime
from typing import Literal, Sequence

from pydantic import BaseModel

from .backends import FanBackend, create_backend
from .config import AppConfig, validate_thresholds

FanMode = Literal["auto", "manual", "off"]


class FanState(BaseModel):
    temperature_c: float
    fan_on: bool
    duty_percent: int
    mode: FanMode
    temp_on_c: float
    temp_off_c: float
    idle_behavior: str
    pwm_backend: str
    pwm_frequency_hz: int
    updated_at: str


def duty_from_curve(curve: Sequence[Sequence[float]], temp_c: float) -> float:
    """Linear interpolation between curve points, clamped to the first/last duty."""
    if temp_c <= curve[0][0]:
        return curve[0][1]
    for (t0, d0), (t1, d1) in zip(curve, curve[1:]):
        if temp_c <= t1:
            return d0 + (d1 - d0) * (temp_c - t0) / (t1 - t0)
    return curve[-1][1]


class FanController:
    def __init__(self, config: AppConfig, backend: FanBackend | None = None) -> None:
        self._config = config
        self._backend = backend if backend is not None else create_backend(config)
        self._logger = logging.getLogger("dynamic_pi4b_fan.controller")
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._mode: FanMode = config.fan.initial_mode  # type: ignore[assignment]
        self._manual_duty = self._clamp_duty(config.fan.manual_duty_percent)
        self._duty = 0
        # hysteresis state for idle_behavior = "off"
        self._auto_running = False
        self._temperature_c = 0.0
        self._updated_at = datetime.now().isoformat(timespec="seconds")

    def setup(self) -> None:
        self._backend.setup()
        self._backend.set_duty(0)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._stop_event.clear()
            # Run the first control step synchronously so the configured mode
            # takes effect (and a real temperature is available) before the API
            # starts serving requests.
            self._tick()
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        with self._lock:
            self._set_duty(0)
        self._backend.close()

    def get_state(self) -> FanState:
        with self._lock:
            fan = self._config.fan
            return FanState(
                temperature_c=self._temperature_c,
                fan_on=self._duty > 0,
                duty_percent=self._duty,
                mode=self._mode,
                temp_on_c=fan.temp_on_c,
                temp_off_c=fan.temp_off_c,
                idle_behavior=fan.idle_behavior,
                pwm_backend=self._config.pwm.backend,
                pwm_frequency_hz=self._config.pwm.frequency_hz,
                updated_at=self._updated_at,
            )

    def set_mode(self, mode: FanMode, duty_percent: float | None = None) -> FanState:
        with self._lock:
            if duty_percent is not None:
                if mode != "manual":
                    raise ValueError("duty_percent is only allowed with mode 'manual'")
                if not (1 <= duty_percent <= 100):
                    raise ValueError("duty_percent must be between 1 and 100")
                self._manual_duty = self._clamp_duty(duty_percent)
            self._mode = mode
            self._apply_mode_locked()
            self._touch_locked()
            self._logger.info("Mode changed to %s (duty %d %%)", mode, self._duty)
            return self.get_state()

    def set_thresholds(self, temp_on_c: float, temp_off_c: float) -> FanState:
        fan_cfg = self._config.fan
        validate_thresholds(
            temp_on_c, temp_off_c, fan_cfg.min_allowed_temp_c, fan_cfg.max_allowed_temp_c
        )

        with self._lock:
            fan_cfg.temp_on_c = temp_on_c
            fan_cfg.temp_off_c = temp_off_c
            self._apply_mode_locked()
            self._touch_locked()
            self._logger.info(
                "Thresholds updated: temp_on_c=%.1f temp_off_c=%.1f",
                temp_on_c,
                temp_off_c,
            )
            return self.get_state()

    def get_temperature(self) -> float:
        result = subprocess.run(
            self._config.temperature.command,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        temp_str = result.stdout.strip()
        return float(temp_str.replace("temp=", "").replace("'C", ""))

    def _run_loop(self) -> None:
        interval = self._config.fan.poll_interval_seconds
        while not self._stop_event.wait(interval):
            self._tick()

    def _tick(self) -> None:
        """Read the temperature once and apply the current mode."""
        try:
            temp = self.get_temperature()
        except Exception:
            self._logger.exception("Temperature read failed")
            return

        with self._lock:
            self._temperature_c = temp
            self._apply_mode_locked()
            self._touch_locked()

    def _apply_mode_locked(self) -> None:
        if self._mode == "manual":
            self._set_duty(self._manual_duty)
        elif self._mode == "off":
            self._set_duty(0)
        else:
            self._set_duty(self._auto_duty_locked(self._temperature_c))

    def _auto_duty_locked(self, temp: float) -> int:
        fan = self._config.fan
        if fan.idle_behavior == "off":
            if not self._auto_running and temp >= fan.temp_on_c:
                self._auto_running = True
            elif self._auto_running and temp < fan.temp_off_c:
                self._auto_running = False
            if not self._auto_running:
                return 0
        return self._clamp_duty(duty_from_curve(fan.curve, temp))

    def _clamp_duty(self, duty: float) -> int:
        """Round to whole percent; anything that runs is lifted to min_duty_percent."""
        if duty <= 0:
            return 0
        return round(min(100.0, max(duty, self._config.fan.min_duty_percent)))

    def _set_duty(self, duty: int) -> None:
        if duty == self._duty:
            return
        fan = self._config.fan
        if self._duty == 0 and 0 < duty < fan.kick_duty_percent and fan.kick_seconds > 0:
            # start-up kick from standstill; blocks briefly while holding the lock
            self._backend.set_duty(fan.kick_duty_percent)
            time.sleep(fan.kick_seconds)
        self._backend.set_duty(duty)
        if (self._duty == 0) != (duty == 0):
            self._logger.info("Fan %s", "ON" if duty else "OFF")
        self._logger.debug("Duty %d %% -> %d %%", self._duty, duty)
        self._duty = duty

    def _touch_locked(self) -> None:
        self._updated_at = datetime.now().isoformat(timespec="seconds")
