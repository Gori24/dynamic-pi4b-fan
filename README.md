# dynamic-pi4b-fan

REST-API-Service zur temperaturgesteuerten Lüftersteuerung eines Raspberry Pi 4B via GPIO. Der Service liest periodisch die CPU-Temperatur aus, schaltet den Lüfter anhand konfigurierbarer Schwellwerte und stellt Status sowie Steuerung über HTTP bereit.

## Zweck

Ziel ist ein einfacher, robuster Hintergrunddienst, der den Lüfter automatisch an- und abschaltet, sobald definierte Temperaturschwellen über- bzw. unterschritten werden (Hysterese). Zusätzlich lässt sich der Lüfter über eine authentifizierte REST-API manuell erzwingen (immer an/aus) oder auf Automatikbetrieb zurückstellen.

## Architekturentscheidung: Host statt Docker

Der Service läuft direkt auf dem Host, nicht in Docker. Für den GPIO-Zugriff auf den Lüfter-Pin sowie den Aufruf von `vcgencmd measure_temp` ist der direkte Hostzugriff einfacher und zuverlässiger als eine Containerisierung, die zusätzliche Device-Passthrough-Komplexität ohne fachlichen Mehrwert einführen würde.

## Hardware

Der Lüfter ist ein einfacher 2-Pin-Lüfter (5 V), der über einen NPN-Transistor als Low-Side-Schalter an GPIO 17 hängt:

```
 Pi 5V (Pin 2/4) ───────────── Lüfter rot (+)
                               Lüfter schwarz (−)
                                    │
                                    C
 GPIO 17 (Pin 11) ──[ R ]──── B   NPN
                                    E
                                    │
 Pi GND (Pin 6) ────────────────────┘
```

- **GPIO 17 = HIGH** → Basisstrom fließt, Transistor leitet, Lüfter **an**.
- **GPIO 17 = LOW** (oder Pin noch nicht konfiguriert, z. B. beim Booten) → Lüfter **aus**.
- Der Basiswiderstand (typisch ca. 1 kΩ) begrenzt den Strom aus dem GPIO-Pin.

Die Logik im Code (`HIGH` = an, Initialzustand `LOW`) passt zu dieser Schaltung.

Empfehlung: Parallel zum Lüfter eine Freilaufdiode (z. B. 1N4148 oder 1N4007, Kathode an 5 V) schützt den Transistor vor Spannungsspitzen beim Abschalten des Motors. Bei einfachem An/Aus ist das unkritisch, bei häufigem Schalten (PWM) wird es wichtiger.

## Verzeichnislayout

- `src/dynamic_pi4b_fan/` - Anwendungscode (API, Steuerlogik, Konfiguration)
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

3. Eine produktive Konfiguration anlegen (Vorlage: `config/example.toml`) und `auth_token` auf einen zufälligen Wert setzen, z. B. mit `openssl rand -hex 32`. Da die Datei das Token im Klartext enthält und nur der Service (als `root`) sie lesen muss, wird sie auf `root` beschränkt:

```bash
sudo install -d -m 750 /etc/dynamic-pi4b-fan
sudo install -m 600 config/example.toml /etc/dynamic-pi4b-fan/config.toml
sudoedit /etc/dynamic-pi4b-fan/config.toml
```

4. Die systemd-Datei nach `/etc/systemd/system/` kopieren und aktivieren (liegt das Repository nicht unter `/home/gori/Projects/Private/dynamic-pi4b-fan`, vorher `WorkingDirectory` und `ExecStart` anpassen):

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

Wenn du die Anwendung unabhängig von der Unit testen willst, setze die Umgebungsvariable `DYNAMIC_PI4B_FAN_CONFIG` auf einen alternativen Konfigurationspfad und starte mit `python -m dynamic_pi4b_fan`.

## Konfiguration

Die Beispielkonfiguration liegt in `config/example.toml`.

Wichtige Felder:

- `server.host` / `server.port`: Bind-Adresse und Port der API
- `server.auth_token`: Bearer-Token zur Authentifizierung aller API-Endpunkte
- `fan.gpio_pin`: BCM-Pin-Nummer, an dem der Lüfter hängt
- `fan.temp_on_c` / `fan.temp_off_c`: Ein- bzw. Ausschaltschwelle (Hysterese, `temp_off_c` muss kleiner als `temp_on_c` sein)
- `fan.poll_interval_seconds`: Abfrageintervall der Temperatur
- `fan.min_allowed_temp_c` / `fan.max_allowed_temp_c`: Gültigkeitsbereich für Schwellwerte (auch bei Laufzeitänderung über die API)
- `fan.initial_mode`: Startmodus (`auto`, `forced_on` oder `forced_off`, optional, Standard `auto`). Er greift sofort beim Start: Vor dem Hochfahren der API wird einmal die Temperatur gemessen und der Modus angewendet.
- `temperature.command`: Befehl zur Temperaturmessung, standardmäßig `vcgencmd measure_temp`
- `logging.level`: Log-Level des Services

## systemd-Einrichtung

Der Service läuft als `root`, da GPIO-Zugriff dies zuverlässig voraussetzt. `Restart=on-failure` sorgt für automatischen Neustart bei Abstürzen. Der Service startet nach `network-online.target`, da die API netzwerkabhängig ist.

## API

Alle Endpunkte erfordern den Header `Authorization: Bearer <auth_token>`.

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/status` | Vollständiger Zustand (Temperatur, Lüfterstatus, Modus, Schwellwerte, Zeitstempel) |
| GET | `/api/temperature` | Aktuelle CPU-Temperatur |
| GET | `/api/fan` | Lüfterstatus und aktueller Modus |
| GET | `/api/thresholds` | Aktuelle Ein-/Ausschaltschwellen |
| POST | `/api/fan` | Modus setzen (`auto`, `forced_on`, `forced_off`) |
| POST | `/api/thresholds` | Schwellwerte zur Laufzeit ändern |

Fehlerfälle:

- `401`: fehlendes oder falsches Token
- `422`: ungültiger Request, z. B. unbekannter Modus, `temp_off_c >= temp_on_c` oder Schwellwert außerhalb von `min_allowed_temp_c`/`max_allowed_temp_c`. Die Begründung steht im Feld `detail`.

`temperature_c` ist `0.0`, solange noch keine Messung erfolgreich war (z. B. wenn `vcgencmd` beim Start fehlschlägt).

## Home-Assistant-Integration

Vorlagen liegen in `homeassistant/`. Home Assistant läuft auf demselben Pi mit `network_mode: host` und spricht die API daher über `http://127.0.0.1:8081` an.

| Datei | Inhalt |
|---|---|
| `fan_sensors.yaml` | REST-Sensor `sensor.pi_fan_status` (pollt `/api/status` alle 15 s, Rest als Attribute) |
| `fan_rest_command.yaml` | `rest_command.set_pi_fan_mode` und `rest_command.set_pi_fan_thresholds` |
| `fan_template.yaml` | `select.pi_fan_mode`, `number.pi_fan_temp_on`, `number.pi_fan_temp_off` |
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

Nach jeder Änderung über `select`/`number` wird `sensor.pi_fan_status` sofort aktualisiert (`homeassistant.update_entity`), damit die UI nicht bis zum nächsten Poll den alten Wert zeigt. Ungültige Kombinationen (`temp_on <= temp_off`) werden in HA auf einen Abstand von 0,5 °C begrenzt.

## Steuerlogik

Im Modus `auto` schaltet der Lüfter bei Erreichen von `temp_on_c` ein und bleibt an, bis `temp_off_c` unterschritten wird (Hysterese verhindert Flattern nahe der Schwelle). Die Modi `forced_on` und `forced_off` überschreiben die Automatik dauerhaft, bis wieder auf `auto` zurückgestellt wird. Ein Hintergrundthread pollt die Temperatur im konfigurierten Intervall und wendet die Logik jeweils erneut an.

## Manueller Testlauf

Status abrufen:

```bash
curl -H "Authorization: Bearer <auth_token>" http://localhost:8081/api/status
```

Modus manuell setzen:

```bash
curl -X POST -H "Authorization: Bearer <auth_token>" -H "Content-Type: application/json" \
  -d '{"mode": "forced_on"}' http://localhost:8081/api/fan
```

## Annahmen und Grenzen

- Die Temperaturmessung erfolgt über `vcgencmd measure_temp`, was eine funktionierende Raspberry-Pi-Firmware voraussetzt.
- Es gibt keine TLS-Terminierung im Service selbst; bei Zugriff außerhalb des lokalen Netzes sollte ein Reverse Proxy mit TLS vorgeschaltet werden.
- Das Bearer-Token liegt im Klartext in der Konfigurationsdatei und muss entsprechend geschützt werden.
- Schwellwert- und Modusänderungen über die API sind bewusst nicht persistent. Nach einem Neustart des Services gelten wieder die Werte aus der Konfigurationsdatei.

## Vorschläge, nicht automatisch umgesetzt

- Rate-Limiting für die API-Endpunkte.
- Metriken-Export (z. B. Prometheus) für Temperaturverlauf und Schaltzyklen.

## Versionierung

Die Version wird ausschließlich in `pyproject.toml` gepflegt. Paket (`dynamic_pi4b_fan.__version__`) und API (`/openapi.json`, `/docs`) lesen sie aus den installierten Paket-Metadaten. Git-Tags tragen dieselbe Nummer ohne Präfix (z. B. `1.0.2`).
