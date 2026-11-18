from __future__ import annotations

import logging
import subprocess
import threading
from datetime import datetime
from typing import Literal

import RPi.GPIO as GPIO
from pydantic import BaseModel

from .config import AppConfig, validate_thresholds

FanMode = Literal["auto", "forced_on", "forced_off"]


class FanState(BaseModel):
    temperature_c: float
    fan_on: bool
    mode: FanMode
    temp_on_c: float
    temp_off_c: float
    updated_at: str


class FanController:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._logger = logging.getLogger("dynamic_pi4b_fan.controller")
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._mode: FanMode = config.fan.initial_mode  # type: ignore[assignment]
        self._fan_on = False
        self._temperature_c = 0.0
        self._updated_at = datetime.now().isoformat(timespec="seconds")

    def setup(self) -> None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._config.fan.gpio_pin, GPIO.OUT, initial=GPIO.LOW)
        self._apply_output(False)

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
            self._apply_output(False)
        GPIO.cleanup()

    def get_state(self) -> FanState:
        with self._lock:
            return FanState(
                temperature_c=self._temperature_c,
                fan_on=self._fan_on,
                mode=self._mode,
                temp_on_c=self._config.fan.temp_on_c,
                temp_off_c=self._config.fan.temp_off_c,
                updated_at=self._updated_at,
            )

    def set_mode(self, mode: FanMode) -> FanState:
        with self._lock:
            self._mode = mode
            if mode == "forced_on":
                self._apply_output(True)
            elif mode == "forced_off":
                self._apply_output(False)
            else:
                self._apply_auto_logic_locked(self._temperature_c)
            self._touch_locked()
            self._logger.info("Mode changed to %s", mode)
            return self.get_state()

    def set_thresholds(self, temp_on_c: float, temp_off_c: float) -> FanState:
        fan_cfg = self._config.fan
        validate_thresholds(
            temp_on_c, temp_off_c, fan_cfg.min_allowed_temp_c, fan_cfg.max_allowed_temp_c
        )

        with self._lock:
            fan_cfg.temp_on_c = temp_on_c
            fan_cfg.temp_off_c = temp_off_c
            if self._mode == "auto":
                self._apply_auto_logic_locked(self._temperature_c)
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
            if self._mode == "auto":
                self._apply_auto_logic_locked(temp)
            elif self._mode == "forced_on":
                self._apply_output(True)
            elif self._mode == "forced_off":
                self._apply_output(False)
            self._touch_locked()

    def _apply_auto_logic_locked(self, temp: float) -> None:
        if not self._fan_on and temp >= self._config.fan.temp_on_c:
            self._apply_output(True)
        elif self._fan_on and temp < self._config.fan.temp_off_c:
            self._apply_output(False)

    def _apply_output(self, enabled: bool) -> None:
        GPIO.output(self._config.fan.gpio_pin, GPIO.HIGH if enabled else GPIO.LOW)
        if self._fan_on != enabled:
            self._logger.info("Fan %s", "ON" if enabled else "OFF")
        self._fan_on = enabled

    def _touch_locked(self) -> None:
        self._updated_at = datetime.now().isoformat(timespec="seconds")
