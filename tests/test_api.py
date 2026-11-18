from __future__ import annotations

from fastapi.testclient import TestClient

from dynamic_pi4b_fan.api import build_app

AUTH = {"Authorization": "Bearer changeme8"}


def client(config, backend):
    config.temperature.command = ["echo", "temp=45.0'C"]
    return TestClient(build_app(config, backend))


def test_requires_token(config, backend):
    with client(config, backend) as c:
        assert c.get("/api/status").status_code == 401


def test_status_and_manual_duty(config, backend):
    with client(config, backend) as c:
        status = c.get("/api/status", headers=AUTH).json()
        assert status["mode"] == "auto"
        assert status["duty_percent"] == 30
        assert status["pwm_frequency_hz"] == 20000

        r = c.post("/api/fan", headers=AUTH, json={"mode": "manual", "duty_percent": 55})
        assert r.status_code == 200
        assert r.json()["duty_percent"] == 55
        assert backend.duty == 55

        assert c.get("/api/fan", headers=AUTH).json() == {
            "fan_on": True,
            "mode": "manual",
            "duty_percent": 55,
        }


def test_invalid_requests_return_422(config, backend):
    with client(config, backend) as c:
        for payload in (
            {"mode": "forced_on"},
            {"mode": "manual", "duty_percent": 0},
            {"mode": "manual", "duty_percent": 101},
            {"mode": "auto", "duty_percent": 50},
        ):
            assert c.post("/api/fan", headers=AUTH, json=payload).status_code == 422, payload
        r = c.post("/api/thresholds", headers=AUTH, json={"temp_on_c": 50, "temp_off_c": 55})
        assert r.status_code == 422
