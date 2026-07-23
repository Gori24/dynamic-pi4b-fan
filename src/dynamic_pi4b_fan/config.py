from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import tomllib


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
    initial_mode: str


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
    temperature: TemperatureConfig
    logging: LoggingConfig


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))

    server = ServerConfig(**data["server"])
    fan = FanConfig(**data["fan"])
    temperature = TemperatureConfig(**data["temperature"])
    logging = LoggingConfig(**data["logging"])

    if fan.temp_off_c >= fan.temp_on_c:
        raise ValueError("fan.temp_off_c must be lower than fan.temp_on_c")

    if not (fan.min_allowed_temp_c <= fan.temp_off_c <= fan.max_allowed_temp_c):
        raise ValueError("fan.temp_off_c outside allowed range")

    if not (fan.min_allowed_temp_c <= fan.temp_on_c <= fan.max_allowed_temp_c):
        raise ValueError("fan.temp_on_c outside allowed range")

    if fan.initial_mode not in {"auto", "forced_on", "forced_off"}:
        raise ValueError("fan.initial_mode must be auto, forced_on or forced_off")

    return AppConfig(
        server=server,
        fan=fan,
        temperature=temperature,
        logging=logging,
    )
