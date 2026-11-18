# Umbau auf Hardware-PWM (GPIO 18) – Anleitung & Übergabe

Stand: 2026-11-18. Diese Datei dient zwei Zwecken: Nachlesen während des Umbaus (Pi ist aus) und **Übergabe an einen neuen Claude-Chat** – der bisherige Chatverlauf steht danach nicht mehr zur Verfügung, diese Datei ist die vollständige Wissensbasis.

## Ablauf auf einen Blick

1. Pi herunterfahren, Draht umstecken, 1N4007 einbauen (Abschnitt 1).
2. Pi starten, kurz prüfen, ob der Service läuft (Abschnitt 1, „Prüfen“).
3. Hardware-Hörtest durchführen (Abschnitt 2), danach Transistor/Diode auf Wärme prüfen.
4. Neuen Claude-Chat im Repo öffnen und den Prompt aus Abschnitt 5 einfügen.

## 1. Umbau-Schritte

1. Pi herunterfahren: `sudo shutdown -h now`, warten bis die grüne LED aus ist, Strom abziehen.
2. Draht vom Basiswiderstand von **Pin 11 (GPIO 17)** auf **Pin 12 (GPIO 18)** umstecken.
   - Pin 11 = innere Reihe, 6. Pin; Pin 12 = äußere Reihe, direkt gegenüber.
   - Lüfter rot (5 V) und Transistor-Emitter (GND) bleiben, wo sie sind.
3. **Freilaufdiode 1N4007** parallel zum Lüfter einbauen (Entscheidung: trotz Einschränkung einbauen).
   - **Ring (Kathode) → roter Draht / 5 V**, anderes Ende (Anode) → schwarzer Draht (= Transistor-Collector).
   - Falsch herum = Kurzschluss von 5 V über den Transistor, sobald er einschaltet → **Polung doppelt prüfen**.
   - Warum 1N4007 trotzdem: bis ca. 1 kHz problemlos; bei 25 kHz ist sie eigentlich zu langsam (Sperrverzögerung), bei dem kleinen Lüfterstrom (~0,1–0,2 A) entstehen aber nur wenige Milliwatt Verlust. Der Schutz des Transistors vor Abschaltspitzen überwiegt.
   - Besser wäre später eine **1N5819** (Schottky) oder **1N4148** – nur nötig, wenn die Kontrolle nach dem Test (Abschnitt 2) Auffälligkeiten zeigt.
4. Pi einschalten. Der Service steuert den Lüfter dann wie bisher an/aus, aber über GPIO 18 (Config ist bereits umgestellt).

Prüfen nach dem Start:

```bash
systemctl status dynamic-pi4b-fan --no-pager
pinctrl get 18        # erwartet: "op" (Output) – wird vom Service gesetzt
```

## 2. Hörtest Hardware-PWM

```bash
cd ~/Projects/Private/dynamic-pi4b-fan
sudo .venv/bin/python tools/pwm_hoertest.py --hw
```

- Stoppt den Service, testet 100 Hz … 25 kHz bei 50 %, dann Tastgrade 80 → 15 % bei der gewählten Frequenz, dann Anlauf aus dem Stillstand ohne Anlaufstoß.
- Startet den Service am Ende wieder (auch bei Strg+C). Abbruch automatisch bei ≥ 75 °C.
- Ergebnis: `tools/pwm_hoertest_hw_<zeitstempel>.csv`.
- Ruhige Umgebung, Ohr nah ans Gehäuse. Besonders auf das „ungesunde Fiepen“ achten (neue Frage im Test).
- **Direkt nach dem Test** (Service läuft wieder): Transistor und Diode kurz mit dem Finger antippen. Lauwarm = ok. Heiß = Diode bei nächster Gelegenheit ausbauen bzw. durch 1N5819 ersetzen. Ergebnis für den neuen Chat notieren.

## 3. Falls etwas schiefgeht

- **Umbau verschoben, aber Pi neu gestartet** → Lüfter bleibt aus. Zurück auf GPIO 17:
  ```bash
  sudo sed -i 's/^gpio_pin = 18$/gpio_pin = 17/' /etc/dynamic-pi4b-fan/config.toml
  sudo systemctl restart dynamic-pi4b-fan
  ```
- **Lüfter läuft nach Umbau gar nicht** → Pin 12 korrekt? `journalctl -u dynamic-pi4b-fan -n 30`. Test ohne Service: `sudo systemctl stop dynamic-pi4b-fan; pinctrl set 18 op dh` (an), `pinctrl set 18 op dl` (aus), danach `sudo systemctl start dynamic-pi4b-fan`.
- **Auch 25 kHz klingt schlecht** → Plan C: 5-V-4-Pin-PWM-Lüfter (z. B. Noctua NF-A4x10 5V PWM): PWM-Eingang direkt an GPIO 18, Tacho-Signal für Drehzahl in HA möglich.

## 4. Stand für einen neuen Chat

### Erledigt
- **1.0.2** released (Tag + Push): einheitliche Version (nur `pyproject.toml`), 422 statt 500 bei ungültigen Schwellwerten, Startmodus greift sofort, schneller Shutdown, Timeout für `vcgencmd`, README (Hardware, Rechte, Update).
- `/etc/dynamic-pi4b-fan/` auf root beschränkt (`750`/`600`).
- **Home Assistant** (`~/homeassistant/config/`, Container `homeassistant`, `network_mode: host`):
  - API über `http://127.0.0.1:8081`, Token in `secrets.yaml` als `pi_fan_api_auth`.
  - Slider-Lag behoben (`homeassistant.update_entity` nach jeder Änderung).
  - Altlasten entfernt (input_number/input_select/Skripte, doppeltes `script:`). Backup: `~/homeassistant/config/backup-pi-fan-*`.
  - Vorlagen im Repo unter `homeassistant/` (committet + gepusht).
  - Verwaiste Entität `fan.pi4b_fan` (unique_id `pi4b_fan`) **behalten** – wird in 1.1.0 als Template-Fan neu belebt; HomeKit-Bridge exportiert die ganze `fan`-Domain.
- `goris-pi4b-backup`: README-Verweis korrigiert (gepusht). `~/docker/README.md`: Hinweis auf Lüfter-Service ergänzt.

### Offen / nicht committet
- `tools/pwm_hoertest.py` (Software- und Hardware-Modus, `--hw`), `.gitignore`-Eintrag für `tools/pwm_hoertest_*.csv`, diese Datei → kommen mit 1.1.0 ins Repo (`git status` zeigt sie).
- Produktiv-Config `/etc/dynamic-pi4b-fan/config.toml` steht auf `gpio_pin = 18` (Service schaltet damit bis 1.1.0 weiter nur an/aus).
- Freilaufdiode: 1N4007 eingebaut, Umbau am 2026-11-18 erledigt. Nach dem Start geprüft: Service läuft, `pinctrl get 18` = `op`, Lüfter schaltet hörbar.

### Verdrahtung nach dem Umbau (Abweichung von Abschnitt 1)
- Rotes Lüfterkabel (+5 V) von **Pin 2 auf Pin 4** umgesteckt (beides 5 V, elektrisch gleich).
- **Pin 2** → Female-Male-Jumper → **„+“-Schiene des Breadboards** (sonst nichts auf dieser Schiene).
- **1N4007:** Kathode (Ring) in der „+“-Schiene nahe dem 5-V-Kabel, Anode in der Breadboard-Reihe mit schwarzem Lüfterkabel + Transistor-Collector (gleiche Seite der Mittelrille). Damit parallel zum Lüfter.
- Graues Steuerkabel auf **Pin 12 (GPIO 18)**. Braunes GND-Kabel, Transistor und Widerstand unverändert.

### Hardware
- 2-Pin-5-V-Lüfter, NPN-Transistor als Low-Side-Schalter (Collector = Lüfter schwarz, Basis über Widerstand an GPIO, Emitter = GND). GPIO HIGH = an.
- Hardware-PWM: `dtoverlay pwm pin=18 func=2` (zur Laufzeit ladbar, kein Reboot nötig), sysfs `/sys/class/pwm/pwmchip0/pwm0`. Kein Konflikt mit Analog-Audio (Pi 4 nutzt dafür den zweiten PWM-Controller).

### Ergebnisse Software-PWM (GPIO 17, `tools/pwm_hoertest_20261118-141714.csv`)
- 100 % = laut (3/3). Lüfter regelbar: bei 200 Hz läuft er bis 15 %, startet ab 30 % ohne Anlaufstoß.
- Durchgehend undefinierbares „ungesundes“ Fiepen; 500/1000 Hz deutliches Pfeifen. Vermutung: Jitter der Software-PWM + hörbare Taktfrequenz.

### Plan 1.1.0 (nach Auswertung des HW-Tests festzurren)
- Lüfterkurve in der Config (Temperatur→Tastgrad, linear interpoliert), Mindest-Tastgrad, Anlaufstoß, Hysterese für Aus.
- PWM-Backend Hardware (sysfs) mit Frequenz aus Test; Overlay-Handling im Service bzw. `config.txt` (`dtoverlay=pwm,pin=18,func=2`).
- Modi: `auto` (Kurve), `manual` (fester Tastgrad %), `off`; API um `duty_percent` erweitern.
- HA: Template-Fan `fan.pi4b_fan` mit An/Aus, Prozent-Slider, Preset „auto“ → ersetzt Großteil der Helfer, erscheint automatisch in HomeKit.
- Unit-Tests (pytest, GPIO/PWM gemockt). Hardware-Selbsttest per Konsole → 1.2.0.

### Wichtige Pfade
- Repo: `~/Projects/Private/dynamic-pi4b-fan` (GitHub `Gori24/dynamic-pi4b-fan`, Tags ohne Präfix, Version nur in `pyproject.toml`)
- Produktiv-Config: `/etc/dynamic-pi4b-fan/config.toml` (root, `600`)
- HA-Config: `~/homeassistant/config/` (Dateien root-owned → `sudo`), Prüfen: `docker exec homeassistant python -m homeassistant --script check_config -c /config`
- Infra-Doku: `~/docker/README.md` (nicht in Git); Backup-Repo: `~/Projects/Private/goris-pi4b-backup` (komplettes SD-Image)

## 5. Prompt für den neuen Chat

Nach dem Test in VS Code im Repo einen neuen Claude-Chat öffnen und einfügen (Platzhalter ausfüllen):

> Lies zuerst `docs/umbau-hw-pwm.md` im Repo – das ist die vollständige Übergabe aus einem vorherigen Chat, dessen Verlauf nicht mehr verfügbar ist. Stand: Umbau auf GPIO 18 ist erledigt, Freilaufdiode 1N4007 ist eingebaut. Der Hardware-PWM-Hörtest liegt unter `tools/pwm_hoertest_hw_*.csv`. Wärmekontrolle nach dem Test: <lauwarm / heiß / nicht geprüft>. Sonstige Beobachtungen: <…>. Werte den Test (auch im Vergleich zu `tools/pwm_hoertest_20261118-141714.csv`) aus, schlag mir eine konkrete Definition für Version 1.1.0 vor und frag nach, bevor du implementierst.

## 6. Ergebnis HW-Test und Umsetzung 1.1.0 (2026-11-18)

- Hörtest `tools/pwm_hoertest_hw_20261118-161729.csv`: 20/25 kHz unhörbar, 100 Hz–10 kHz fiept. Bei 20 kHz: < 30 % Fiepen, 30–60 % leise, 80 % so laut wie 100 %. Anlauf ab 30 % ohne Stoß.
- Wärmekontrolle: Transistor und Diode nach dem Test unauffällig (nicht warm) → 1N4007 bleibt.
- Entscheidungen: 20 kHz, Mindest-Tastgrad 30 %, Kurve `[[50,30],[60,45],[70,65],[75,100]]` (Endpunkte aus dem Test, 60/70 °C interpoliert, im Alltag bestätigen), Anlaufstoß 1 s bei 50 %, Dauerlauf (`idle_behavior = "min_duty"`) zur Probe – bei Nichtgefallen auf `"off"` umstellen.
- Umgesetzt: Hardware-PWM-Backend (sysfs) + `onoff`-Fallback, Modi `auto`/`manual`/`off`, `duty_percent` in der API, Template-Fan `fan.pi4b_fan` in HA, pytest-Suite (`tests/`).
- HA-Dateien eingespielt, Backup: `~/homeassistant/config/backup-pi-fan-1.1.0-20261118/`.
- Boot-Config: `dtoverlay=pwm,pin=18,func=2` in `/boot/firmware/config.txt` (Backup `config.txt.bak-pi-fan-20261118`).
