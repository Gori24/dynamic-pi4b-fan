#!/usr/bin/env python3
"""Interaktiver PWM-Hörtest für den Lüfter.

Aufruf (aus dem Repo-Verzeichnis):

    sudo .venv/bin/python tools/pwm_hoertest.py          # Software-PWM auf GPIO 17
    sudo .venv/bin/python tools/pwm_hoertest.py --hw     # Hardware-PWM auf GPIO 18

Das Skript stoppt den Service dynamic-pi4b-fan, fährt verschiedene Frequenzen und
Tastgrade durch, fragt nach jedem Schritt deine Einschätzung ab und startet den
Service am Ende (auch bei Abbruch mit Strg+C) wieder. Ergebnisse landen als CSV
in tools/.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SERVICE = "dynamic-pi4b-fan.service"
MAX_TEMP_C = 75.0
KICK_SECONDS = 1.0

SW_PIN = 17
SW_FREQS_HZ = [10, 25, 50, 100, 200, 500, 1000]

HW_PIN = 18
HW_FREQS_HZ = [100, 200, 1000, 5000, 10000, 20000, 25000]
PWMCHIP = Path("/sys/class/pwm/pwmchip0")

DUTIES = [80, 60, 50, 40, 30, 20, 15]
START_DUTIES = [60, 50, 40, 30]


class SoftwarePwm:
    """RPi.GPIO software PWM (thread-based, with timing jitter)."""

    def __init__(self, pin: int) -> None:
        import RPi.GPIO as GPIO

        self._gpio = GPIO
        self.pin = pin
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        self._pwm = GPIO.PWM(pin, 100)
        self._running = False

    def set(self, freq_hz: int, duty: float) -> None:
        self._pwm.ChangeFrequency(freq_hz)
        if self._running:
            self._pwm.ChangeDutyCycle(duty)
        else:
            self._pwm.start(duty)
            self._running = True

    def off(self) -> None:
        if self._running:
            self._pwm.stop()
            self._running = False
        self._gpio.output(self.pin, self._gpio.LOW)

    def close(self) -> None:
        self.off()
        self._gpio.cleanup()


class HardwarePwm:
    """BCM2711 hardware PWM0 on GPIO 18 via the pwm overlay and sysfs."""

    def __init__(self, pin: int) -> None:
        self.pin = pin
        subprocess.run(["dtoverlay", "pwm", f"pin={pin}", "func=2"], check=True)
        for _ in range(20):
            if PWMCHIP.exists():
                break
            time.sleep(0.1)
        if not (PWMCHIP / "pwm0").exists():
            (PWMCHIP / "export").write_text("0")
            time.sleep(0.3)
        self._ch = PWMCHIP / "pwm0"
        self._period = 0

    def _write(self, name: str, value: int) -> None:
        (self._ch / name).write_text(str(value))

    def set(self, freq_hz: int, duty: float) -> None:
        period = round(1e9 / freq_hz)
        if period != self._period:
            # duty_cycle must never exceed period, so lower it first
            self._write("duty_cycle", 0)
            self._write("period", period)
            self._period = period
        self._write("duty_cycle", round(period * duty / 100))
        self._write("enable", 1)

    def off(self) -> None:
        if self._period:
            self._write("duty_cycle", 0)

    def close(self) -> None:
        try:
            self.off()
            self._write("enable", 0)
            (PWMCHIP / "unexport").write_text("0")
        finally:
            subprocess.run(["dtoverlay", "-r", "pwm"])


results: list[dict] = []


def temp_c() -> float:
    out = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True).stdout
    return float(out.strip().replace("temp=", "").replace("'C", ""))


def check_temp() -> None:
    t = temp_c()
    if t >= MAX_TEMP_C:
        raise RuntimeError(f"Temperatur {t:.1f} °C >= {MAX_TEMP_C} °C, Abbruch zur Sicherheit")


def ask(prompt: str, allowed: set[str] | None = None) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if allowed is None or answer in allowed:
            return answer
        print(f"  Bitte eines von: {', '.join(sorted(allowed))}")


def rate(backend: str, phase: str, freq: int, duty: int, kick: bool, question: str) -> None:
    check_temp()
    runs = ask(f"  {question} [j/n]: ", {"j", "n"})
    noise = ask("  Geräusch 0-3 (0 unhörbar, 1 leise, 2 deutlich, 3 störend): ", {"0", "1", "2", "3"})
    whine = ask("  Fiepen/Ticken/'ungesundes' Geräusch hörbar? [j/n]: ", {"j", "n"})
    speed = input("  Drehzahl subjektiv ggü. 100 % (z. B. 'gleich', 'halb', 'kaum'), Enter = leer: ").strip()
    note = input("  Notiz, Enter = leer: ").strip()
    results.append(
        dict(backend=backend, phase=phase, freq_hz=freq, duty=duty, kick=kick, runs=runs,
             noise=noise, whine=whine, speed=speed, note=note, temp_c=f"{temp_c():.1f}")
    )


def run_test(pwm, backend: str, freqs: list[int]) -> None:
    print(f"Aktuelle Temperatur: {temp_c():.1f} °C\n")

    print("=== Phase 0: Referenz ===")
    pwm.set(freqs[-1], 100)
    print("Lüfter läuft jetzt dauerhaft mit 100 %. Merk dir Geräusch und Drehzahl.")
    rate(backend, "referenz", 0, 100, False, "Läuft er?")
    pwm.off()
    time.sleep(2)

    print("\n=== Phase 1: Frequenzen bei 50 % (mit 1 s Anlaufstoß) ===")
    for f in freqs:
        pwm.set(f, 100)
        time.sleep(KICK_SECONDS)
        pwm.set(f, 50)
        time.sleep(2)
        print(f"\n-> {f} Hz, 50 %")
        rate(backend, "frequenz", f, 50, True, "Dreht er gleichmäßig?")
        pwm.off()
        time.sleep(2)

    freq = int(ask(f"\nWelche Frequenz war am besten? {freqs}: ", {str(f) for f in freqs}))

    print(f"\n=== Phase 2: Tastgrad bei {freq} Hz, absteigend ohne Stopp ===")
    pwm.set(freq, 100)
    time.sleep(KICK_SECONDS)
    for d in DUTIES:
        pwm.set(freq, d)
        time.sleep(3)  # Drehzahl einpendeln lassen
        print(f"\n-> {freq} Hz, {d} %")
        rate(backend, "tastgrad", freq, d, False, "Dreht er noch?")
    pwm.off()

    print(f"\n=== Phase 3: Anlauf aus dem Stillstand bei {freq} Hz, OHNE Anlaufstoß ===")
    for d in START_DUTIES:
        pwm.off()
        print("\nLüfter steht 5 s ...")
        time.sleep(5)
        pwm.set(freq, d)
        time.sleep(4)
        print(f"-> Start direkt mit {d} %")
        rate(backend, "anlauf", freq, d, False, "Ist er angelaufen?")
    pwm.off()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hw", action="store_true", help="Hardware-PWM auf GPIO 18 statt Software-PWM auf GPIO 17")
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("Bitte mit sudo starten: sudo .venv/bin/python tools/pwm_hoertest.py [--hw]")
        return 1

    backend = "hw" if args.hw else "sw"
    print(f"Stoppe {SERVICE} ...")
    subprocess.run(["systemctl", "stop", SERVICE], check=True)
    pwm = None
    try:
        if args.hw:
            print(f"Hardware-PWM auf GPIO {HW_PIN} (Pin 12)")
            pwm = HardwarePwm(HW_PIN)
            run_test(pwm, backend, HW_FREQS_HZ)
        else:
            print(f"Software-PWM auf GPIO {SW_PIN} (Pin 11)")
            pwm = SoftwarePwm(SW_PIN)
            run_test(pwm, backend, SW_FREQS_HZ)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
    except RuntimeError as exc:
        print(f"\n{exc}")
    finally:
        if pwm is not None:
            pwm.close()
        print(f"Starte {SERVICE} wieder ...")
        subprocess.run(["systemctl", "start", SERVICE])

    if results:
        out = Path(__file__).with_name(f"pwm_hoertest_{backend}_{datetime.now():%Y%m%d-%H%M%S}.csv")
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        os.chown(out, int(os.environ.get("SUDO_UID", 0)), int(os.environ.get("SUDO_GID", 0)))
        print(f"\nErgebnisse: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
