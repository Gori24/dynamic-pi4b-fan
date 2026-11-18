# dynamic-pi4b-fan

REST-API-Service zur temperaturgesteuerten Lüftersteuerung eines Raspberry Pi 4B per Hardware-PWM. Der Service liest periodisch die CPU-Temperatur aus, stellt die Lüfterdrehzahl über eine konfigurierbare Kurve ein und stellt Status sowie Steuerung über HTTP bereit.

## Zweck

Ziel ist ein einfacher, robuster Hintergrunddienst, der den Lüfter so leise wie möglich und so schnell wie nötig laufen lässt. Über eine authentifizierte REST-API lässt sich ein fester Tastgrad vorgeben, der Lüfter abschalten oder auf Automatikbetrieb zurückstellen.

## Architekturentscheidung: Host statt Docker

Der Service läuft direkt auf dem Host, nicht in Docker. Für den GPIO-Zugriff auf den Lüfter-Pin sowie den Aufruf von `vcgencmd measure_temp` ist der direkte Hostzugriff einfacher und zuverlässiger als eine Containerisierung, die zusätzliche Device-Passthrough-Komplexität ohne fachlichen Mehrwert einführen würde.

## Hardware

Der Lüfter ist ein einfacher 2-Pin-Lüfter (5 V), der über einen NPN-Transistor als Low-Side-Schalter an GPIO 18 (Hardware-PWM0) hängt:

```
 Pi 5V (Pin 4) ───────────┬──── Lüfter rot (+)
                          │
                     1N4007 (Ring/Kathode oben)
                          │
                          └──── Lüfter schwarz (−)
                                    │
                                    C
 GPIO 18 (Pin 12) ──[ R ]──── B   NPN
                                    E
                                    │
 Pi GND (Pin 6) ────────────────────┘
```

- **Tastgrad > 0** → Transistor schaltet im PWM-Takt, der Lüfter dreht entsprechend langsamer.
- **GPIO 18 LOW** (oder Pin noch nicht konfiguriert, z. B. beim Booten) → Lüfter **aus**.
- Der Basiswiderstand (typisch ca. 1 kΩ) begrenzt den Strom aus dem GPIO-Pin.
- Die Freilaufdiode (Kathode an 5 V) schützt den Transistor vor Spannungsspitzen des Motors. Die 1N4007 ist für 20 kHz eigentlich zu langsam, bleibt bei dem kleinen Lüfterstrom aber kalt; eine 1N5819 (Schottky) wäre die saubere Wahl.

Hardware-PWM braucht das Overlay in `/boot/firmware/config.txt` (danach Neustart):

```
dtoverlay=pwm,pin=18,func=2
```

Ohne Overlay bricht der Service mit einer Fehlermeldung ab. Mit `[pwm] backend = "onoff"` lässt sich der Lüfter ohne PWM über `fan.gpio_pin` nur an/aus schalten (Verhalten von 1.0.x).

### Messwerte

Hörtest mit `tools/pwm_hoertest.py` (Ergebnisse in `tools/pwm_hoertest_*.csv`):

- 100 Hz bis 10 kHz: hörbares Fiepen bzw. Pfeifen der Schaltfrequenz. 20 und 25 kHz: unhörbar. Software-PWM (bis 1 kHz) erzeugt durchgehend Nebengeräusche.
- Tastgrad bei 20 kHz: unter 30 % fiept der Motor, 30 bis 60 % ist leise, 80 % ist so laut wie 100 %.
- Anlauf aus dem Stillstand gelingt ab 30 % ohne Anlaufstoß.

Daraus ergeben sich die Standardwerte: 20 kHz, Mindest-Tastgrad 30 %, Kurve bis 70 °C unter 70 %, 100 % erst ab 75 °C.

## Verzeichnislayout

- `src/dynamic_pi4b_fan/` - Anwendungscode (API, Steuerlogik, PWM-Backends, Konfiguration)
- `tests/` - Unit-Tests (pytest, ohne Hardware)
- `tools/pwm_hoertest.py` - interaktiver Hörtest für Frequenz und Tastgrad
- `config/example.toml` - Beispielkonfiguration
- `systemd/dynamic-pi4b-fan.service` - systemd-Service
- `homeassistant/` - Vorlagen für die Home-Assistant-Integration
- `/etc/dynamic-pi4b-fan/config.toml` - produktive Konfiguration
- `/etc/systemd/system/dynamic-pi4b-fan.service` - installierte Service-Unit

## Installation

1. Repository nach `~/Projects/Private/dynamic-pi4b-fan` legen.
2. Virtuelle Umgebung anlegen und Paket installieren:

```bash
cd ~/Projects/Private/dynamic-pi4b-fan
python3 -m venv .venv
.venv/bin/pip install -e .
```

3. Das PWM-Overlay in `/boot/firmware/config.txt` eintragen (siehe [Hardware](#hardware)) und neu starten.
4. Eine produktive Konfiguration anlegen (Vorlage: `config/example.toml`) und `auth_token` auf einen zufälligen Wert setzen, z. B. mit `openssl rand -hex 32`. Da die Datei das Token im Klartext enthält und nur der Service (als `root`) sie lesen muss, wird sie auf `root` beschränkt:

```bash
sudo install -d -m 750 /etc/dynamic-pi4b-fan
sudo install -m 600 config/example.toml /etc/dynamic-pi4b-fan/config.toml
sudoedit /etc/dynamic-pi4b-fan/config.toml
```

5. Die systemd-Datei nach `/etc/systemd/system/` kopieren und aktivieren (liegt das Repository nicht unter `/home/gori/Projects/Private/dynamic-pi4b-fan`, vorher `WorkingDirectory` und `ExecStart` anpassen):

```bash
sudo cp systemd/dynamic-pi4b-fan.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dynamic-pi4b-fan.service
```

### Update

```bash
cd ~/Projects/Private/dynamic-pi4b-fan
git pull
.venv/bin/pip install -e .   # aktualisiert u. a. die Versionsnummer in den Paket-Metadaten
sudo systemctl restart dynamic-pi4b-fan.service
```

Tests (ohne Hardware, PWM-Backend wird ersetzt):

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Wenn du die Anwendung unabhängig von der Unit testen willst, setze die Umgebungsvariable `DYNAMIC_PI4B_FAN_CONFIG` auf einen alternativen Konfigurationspfad und starte mit `python -m dynamic_pi4b_fan`.

## Konfiguration

Die Beispielkonfiguration liegt in `config/example.toml`.

Wichtige Felder:

- `server.host` / `server.port`: Bind-Adresse und Port der API
- `server.auth_token`: Bearer-Token zur Authentifizierung aller API-Endpunkte
- `fan.gpio_pin`: BCM-Pin-Nummer des Lüfters, nur für `backend = "onoff"` (bei Hardware-PWM legt das Overlay den Pin fest)
- `fan.curve`: Lüfterkurve als Liste `[Temperatur °C, Tastgrad %]`, dazwischen linear interpoliert, unter dem ersten bzw. über dem letzten Punkt konstant
- `fan.idle_behavior`: `min_duty` (Standard) lässt den Lüfter im Modus `auto` immer mindestens mit `min_duty_percent` laufen; `off` schaltet ihn unter `temp_off_c` ab und ab `temp_on_c` wieder ein
- `fan.temp_on_c` / `fan.temp_off_c`: Ein- bzw. Ausschaltschwelle (Hysterese, nur bei `idle_behavior = "off"`; `temp_off_c` muss kleiner als `temp_on_c` sein)
- `fan.min_duty_percent`: kleinster Tastgrad, wenn der Lüfter läuft (Standard 30); niedrigere Werte aus Kurve oder API werden angehoben
- `fan.manual_duty_percent`: Tastgrad im Modus `manual`, bis er über die API gesetzt wird (Standard 50)
- `fan.kick_duty_percent` / `fan.kick_seconds`: Anlaufstoß aus dem Stillstand (Standard 50 % für 1 s, `0` Sekunden = aus); nur wenn der Ziel-Tastgrad darunter liegt
- `fan.poll_interval_seconds`: Abfrageintervall der Temperatur
- `fan.min_allowed_temp_c` / `fan.max_allowed_temp_c`: Gültigkeitsbereich für Schwellwerte (auch bei Laufzeitänderung über die API)
- `fan.initial_mode`: Startmodus (`auto`, `manual` oder `off`, optional, Standard `auto`). Er greift sofort beim Start: Vor dem Hochfahren der API wird einmal die Temperatur gemessen und der Modus angewendet.
- `pwm.backend`: `hardware` (Standard, sysfs) oder `onoff`
- `pwm.frequency_hz`: PWM-Frequenz (Standard 20000)
- `pwm.chip` / `pwm.channel`: sysfs-Gerät `/sys/class/pwm/pwmchip<chip>/pwm<channel>` (Standard 0/0 = GPIO 18)

Alle `fan.*`-Felder außer den Schwellwerten und alle `pwm.*`-Felder sind optional, eine Konfiguration aus 1.0.x funktioniert unverändert (bis auf `initial_mode = "forced_on"`/`"forced_off"`).
- `temperature.command`: Befehl zur Temperaturmessung, standardmäßig `vcgencmd measure_temp`
- `logging.level`: Log-Level des Services

## systemd-Einrichtung

Der Service läuft als `root`, da GPIO- und sysfs-PWM-Zugriff dies zuverlässig voraussetzen. `Restart=on-failure` sorgt für automatischen Neustart bei Abstürzen. Der Service startet nach `network-online.target`, da die API netzwerkabhängig ist.

## API

Alle Endpunkte erfordern den Header `Authorization: Bearer <auth_token>`.

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/status` | Vollständiger Zustand (Temperatur, Lüfterstatus, Tastgrad, Modus, Schwellwerte, PWM-Frequenz, Zeitstempel) |
| GET | `/api/temperature` | Aktuelle CPU-Temperatur |
| GET | `/api/fan` | Lüfterstatus, Modus und Tastgrad |
| GET | `/api/thresholds` | Aktuelle Ein-/Ausschaltschwellen |
| POST | `/api/fan` | Modus setzen: `{"mode": "auto"}`, `{"mode": "off"}` oder `{"mode": "manual", "duty_percent": 45}` |
| POST | `/api/thresholds` | Schwellwerte zur Laufzeit ändern |

Fehlerfälle:

- `401`: fehlendes oder falsches Token
- `422`: ungültiger Request, z. B. unbekannter Modus, `duty_percent` außerhalb 1–100 oder ohne Modus `manual`, `temp_off_c >= temp_on_c` oder Schwellwert außerhalb von `min_allowed_temp_c`/`max_allowed_temp_c`. Die Begründung steht im Feld `detail`.

Bei `manual` ohne `duty_percent` gilt der zuletzt gesetzte Tastgrad. Werte unter `min_duty_percent` werden angehoben. `fan_on` ist `true`, sobald der Tastgrad über 0 liegt.

`temperature_c` ist `0.0`, solange noch keine Messung erfolgreich war (z. B. wenn `vcgencmd` beim Start fehlschlägt).

## Home-Assistant-Integration

Vorlagen liegen in `homeassistant/`. Home Assistant läuft auf demselben Pi mit `network_mode: host` und spricht die API daher über `http://127.0.0.1:8081` an.

| Datei | Inhalt |
|---|---|
| `fan_sensors.yaml` | REST-Sensor `sensor.pi_fan_status` (pollt `/api/status` alle 15 s, Rest als Attribute) |
| `fan_rest_command.yaml` | `rest_command.set_pi_fan_mode`, `rest_command.set_pi_fan_duty` und `rest_command.set_pi_fan_thresholds` |
| `fan_template.yaml` | `fan.pi4b_fan`, `select.pi_fan_mode`, `number.pi_fan_temp_on`, `number.pi_fan_temp_off` |
| `secrets.example.yaml` | Eintrag `pi_fan_api_auth` für `/config/secrets.yaml` |
| `configuration.snippet.yaml` | Includes für `/config/configuration.yaml` |

Einrichtung:

1. Die drei `fan_*.yaml` nach `/config/` (hier `~/homeassistant/config/`) kopieren.
2. `pi_fan_api_auth: "Bearer <auth_token>"` in `secrets.yaml` eintragen. Das Token muss zu `server.auth_token` passen.
3. Die Includes aus `configuration.snippet.yaml` übernehmen (jeden Top-Level-Schlüssel nur einmal).
4. Konfiguration prüfen und HA neu starten:

```bash
docker exec homeassistant python -m homeassistant --script check_config -c /config
docker restart homeassistant
```

`fan.pi4b_fan` ist die Hauptsteuerung (auch in HomeKit): Einschalten = `auto`, Ausschalten = `off`, Prozent-Slider = `manual` mit diesem Tastgrad, Preset `auto` = zurück zur Kurve.

Nach jeder Änderung über `fan`/`select`/`number` wird `sensor.pi_fan_status` sofort aktualisiert (`homeassistant.update_entity`), damit die UI nicht bis zum nächsten Poll den alten Wert zeigt. Ungültige Kombinationen (`temp_on <= temp_off`) werden in HA auf einen Abstand von 0,5 °C begrenzt.

## Steuerlogik

Im Modus `auto` berechnet der Service den Tastgrad aus `fan.curve` und hebt ihn mindestens auf `min_duty_percent`. Mit `idle_behavior = "min_duty"` läuft der Lüfter dadurch dauerhaft leise weiter; mit `idle_behavior = "off"` schaltet er bei `temp_on_c` ein und unter `temp_off_c` aus (Hysterese verhindert Flattern nahe der Schwelle). Läuft der Lüfter aus dem Stillstand an, gibt es vorher den Anlaufstoß. `manual` (fester Tastgrad) und `off` überschreiben die Automatik dauerhaft, bis wieder auf `auto` zurückgestellt wird. Ein Hintergrundthread pollt die Temperatur im konfigurierten Intervall und wendet die Logik jeweils erneut an.

## Manueller Testlauf

Status abrufen:

```bash
curl -H "Authorization: Bearer <auth_token>" http://localhost:8081/api/status
```

Modus manuell setzen:

```bash
curl -X POST -H "Authorization: Bearer <auth_token>" -H "Content-Type: application/json" \
  -d '{"mode": "manual", "duty_percent": 45}' http://localhost:8081/api/fan
```

## Annahmen und Grenzen

- Die Temperaturmessung erfolgt über `vcgencmd measure_temp`, was eine funktionierende Raspberry-Pi-Firmware voraussetzt.
- Es gibt keine TLS-Terminierung im Service selbst; bei Zugriff außerhalb des lokalen Netzes sollte ein Reverse Proxy mit TLS vorgeschaltet werden.
- Das Bearer-Token liegt im Klartext in der Konfigurationsdatei und muss entsprechend geschützt werden.
- Schwellwert- und Modusänderungen über die API sind bewusst nicht persistent. Nach einem Neustart des Services gelten wieder die Werte aus der Konfigurationsdatei.

## Vorschläge, nicht automatisch umgesetzt

- Rate-Limiting für die API-Endpunkte.
- Hardware-Selbsttest per Konsole (geplant für 1.2.0).
- Notlauf: in `manual`/`off` bei kritischer Temperatur automatisch auf 100 %.
- Metriken-Export (z. B. Prometheus) für Temperaturverlauf und Schaltzyklen.

## Versionierung

Die Version wird ausschließlich in `pyproject.toml` gepflegt. Paket (`dynamic_pi4b_fan.__version__`) und API (`/openapi.json`, `/docs`) lesen sie aus den installierten Paket-Metadaten. Git-Tags tragen dieselbe Nummer ohne Präfix (z. B. `1.1.0`).
