from __future__ import annotations

import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from . import __version__
from .config import AppConfig, load_config
from .controller import FanController, FanMode

DEFAULT_CONFIG_PATH = Path("/etc/dynamic-pi4b-fan/config.toml")


class FanModeRequest(BaseModel):
    mode: FanMode


class ThresholdRequest(BaseModel):
    temp_on_c: float
    temp_off_c: float


def get_config_path() -> Path:
    return Path(os.environ.get("DYNAMIC_PI4B_FAN_CONFIG", DEFAULT_CONFIG_PATH))


def build_app(config: AppConfig) -> FastAPI:
    controller = FanController(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        controller.setup()
        controller.start()
        try:
            yield
        finally:
            controller.stop()

    app = FastAPI(title="dynamic-pi4b-fan", version=__version__, lifespan=lifespan)

    def verify_token(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {config.server.auth_token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    @app.get("/api/status", dependencies=[Depends(verify_token)])
    def get_status():
        return controller.get_state().model_dump()

    @app.get("/api/temperature", dependencies=[Depends(verify_token)])
    def get_temperature():
        return {"temperature_c": controller.get_temperature()}

    @app.get("/api/fan", dependencies=[Depends(verify_token)])
    def get_fan():
        state = controller.get_state()
        return {"fan_on": state.fan_on, "mode": state.mode}

    @app.get("/api/thresholds", dependencies=[Depends(verify_token)])
    def get_thresholds():
        state = controller.get_state()
        return {"temp_on_c": state.temp_on_c, "temp_off_c": state.temp_off_c}

    @app.post("/api/fan", dependencies=[Depends(verify_token)])
    def set_fan(payload: FanModeRequest):
        return controller.set_mode(payload.mode).model_dump()

    @app.post("/api/thresholds", dependencies=[Depends(verify_token)])
    def set_thresholds(payload: ThresholdRequest):
        try:
            state = controller.set_thresholds(payload.temp_on_c, payload.temp_off_c)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
        return state.model_dump()

    return app


config = load_config(get_config_path())
app = build_app(config)
