from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
import tomllib

FAN_MODES = ("auto", "manual", "off")
IDLE_BEHAVIORS = ("min_duty", "off")
PWM_BACKENDS = ("hardware", "onoff")

# Derived from the hardware PWM listening test (tools/pwm_hoertest_hw_20261118-161729.csv):
# below 30 % the fan whines, 30-60 % is quiet, 80 % is as loud as 100 %.
DEFAULT_CURVE: list[list[float]] = [[50.0, 30.0], [60.0, 45.0], [70.0, 65.0], [75.0, 100.0]]


@dataclass(slots=True)
class ServerConfig:
    host: str
    port: int
    auth_token: str


@dataclass(slots=True)
class FanConfig:
    gpio_pin: int
    temp_on_c: float
    temp_off_c: float
    poll_interval_seconds: int
    min_allowed_temp_c: float
    max_allowed_temp_c: float
    initial_mode: str = "auto"
    # auto mode: "min_duty" keeps the fan running at min_duty_percent when cool,
    # "off" switches it off below temp_off_c (on again at temp_on_c).
    idle_behavior: str = "min_duty"
    min_duty_percent: float = 30.0
    manual_duty_percent: float = 50.0
    kick_duty_percent: float = 50.0
    kick_seconds: float = 1.0
    curve: list[list[float]] = field(default_factory=lambda: [p[:] for p in DEFAULT_CURVE])


@dataclass(slots=True)
class PwmConfig:
    backend: str = "hardware"
    frequency_hz: int = 20000
    chip: int = 0
    channel: int = 0


@dataclass(slots=True)
class TemperatureConfig:
    command: Sequence[str]


@dataclass(slots=True)
class LoggingConfig:
    level: str


@dataclass(slots=True)
class AppConfig:
    server: ServerConfig
    fan: FanConfig
    pwm: PwmConfig
    temperature: TemperatureConfig
    logging: LoggingConfig


def validate_thresholds(
    temp_on_c: float,
    temp_off_c: float,
    min_allowed_temp_c: float,
    max_allowed_temp_c: float,
) -> None:
    """Raise ValueError if the hysteresis thresholds are inconsistent or out of range."""
    if temp_off_c >= temp_on_c:
        raise ValueError("temp_off_c must be lower than temp_on_c")
    if not (min_allowed_temp_c <= temp_off_c <= max_allowed_temp_c):
        raise ValueError(
            f"temp_off_c outside allowed range [{min_allowed_temp_c}, {max_allowed_temp_c}]"
        )
    if not (min_allowed_temp_c <= temp_on_c <= max_allowed_temp_c):
        raise ValueError(
            f"temp_on_c outside allowed range [{min_allowed_temp_c}, {max_allowed_temp_c}]"
        )


def _check_percent(name: str, value: float, low: float = 0.0) -> None:
    if not (low <= value <= 100.0):
        raise ValueError(f"{name} must be between {low:g} and 100")


def validate_fan(fan: FanConfig) -> None:
    validate_thresholds(
        fan.temp_on_c, fan.temp_off_c, fan.min_allowed_temp_c, fan.max_allowed_temp_c
    )
    if fan.initial_mode not in FAN_MODES:
        raise ValueError(f"initial_mode must be one of {', '.join(FAN_MODES)}")
    if fan.idle_behavior not in IDLE_BEHAVIORS:
        raise ValueError(f"idle_behavior must be one of {', '.join(IDLE_BEHAVIORS)}")
    _check_percent("min_duty_percent", fan.min_duty_percent)
    _check_percent("manual_duty_percent", fan.manual_duty_percent, low=1.0)
    _check_percent("kick_duty_percent", fan.kick_duty_percent)
    if fan.kick_seconds < 0:
        raise ValueError("kick_seconds must not be negative")
    if fan.poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")

    if not fan.curve:
        raise ValueError("curve needs at least one [temp_c, duty_percent] point")
    prev_temp: float | None = None
    for point in fan.curve:
        if len(point) != 2:
            raise ValueError("each curve point must be [temp_c, duty_percent]")
        temp, duty = point
        _check_percent("curve duty", duty)
        if prev_temp is not None and temp <= prev_temp:
            raise ValueError("curve temperatures must be strictly increasing")
        prev_temp = temp


def validate_pwm(pwm: PwmConfig) -> None:
    if pwm.backend not in PWM_BACKENDS:
        raise ValueError(f"backend must be one of {', '.join(PWM_BACKENDS)}")
    if not (1 <= pwm.frequency_hz <= 100_000):
        raise ValueError("frequency_hz must be between 1 and 100000")


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))

    server = ServerConfig(**data["server"])
    fan_data = dict(data["fan"])
    if "curve" in fan_data:
        fan_data["curve"] = [[float(t), float(d)] for t, d in fan_data["curve"]]
    fan = FanConfig(**fan_data)
    pwm = PwmConfig(**data.get("pwm", {}))
    temperature = TemperatureConfig(**data["temperature"])
    logging = LoggingConfig(**data["logging"])

    for section, validate, value in (("fan", validate_fan, fan), ("pwm", validate_pwm, pwm)):
        try:
            validate(value)
        except ValueError as exc:
            raise ValueError(f"invalid [{section}] config: {exc}") from exc

    return AppConfig(
        server=server,
        fan=fan,
        pwm=pwm,
        temperature=temperature,
        logging=logging,
    )
