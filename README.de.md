# GridGuard — Labor für digitale Umspannwerke und Zustandsüberwachung

Laborimplementierung: synthetisches C++20-IED, IEC-61850-MMS-Reportclient,
Python-Verarbeitung, persistente lokale Warteschlange, PostgreSQL-Export, FastAPI-Dashboard.
Nur lesende Modbus-TCP-, IEC-104-, OPC-UA- und MQTT-Brücken nutzen SCADA_Generator.
**Nur Laborbelege: keine Feldvalidierung, RUL oder IEC-Zertifizierung.**

[Русский](README.ru.md) · [English](README.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [Español](README.es.md) · [Français](README.fr.md) · **Deutsch** · [Italiano](README.it.md)

[Entscheidungen](docs/ADRs.md), [Sicherheit](docs/SECURITY.md), [Messmethodik](docs/BENCHMARKS.md).
Demonstrator, kein Produktionseinsatz.

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## Build und Tests

Linux, CMake ≥3.20, C++20-Compiler, Ninja, Python ≥3.10. Abhängigkeiten unter CPython 3.12
geprüft. CMake lädt die genaue libIEC61850-Revision; `requirements.lock` fixiert Versionen
ohne Paket-Hashes. Netzwerk bei Erstinstallation erforderlich.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Debug
cmake --build build --target gridguard_ied gridguard_edge gridguard_synthetic gridguard_wal_tests gridguard_physics_tests -j2
ctest --test-dir build --output-on-failure
# Supply an isolated PostgreSQL test database you are allowed to write to:
export GRIDGUARD_TEST_PG='your-test-database-connection-string'
GRIDGUARD_BUILD=build .venv/bin/python -m pytest -q --ignore=tests/test_bridges.py
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Isolierte PostgreSQL-Testdatenbank mit Schreibberechtigung verwenden. Echte C++-Binärdateien
und PostgreSQL erforderlich; fehlende Abhängigkeiten führen zum Fehler. ASan/UBSan:
separates Verzeichnis mit `-DGRIDGUARD_SANITIZERS=ON`, `GRIDGUARD_BUILD` darauf setzen.
Anwendung und IEC-Stack instrumentiert. Kein TSan-Ergebnis oder unabhängiger Interoperabilitätsnachweis.

## Lokaler Betrieb

Eigenes `GRIDGUARD_TOKEN` mit mindestens 16 Zeichen setzen; leerer Token wird abgelehnt.
Jeden Prozess vom Projektwurzelverzeichnis in einem eigenen Terminal starten.

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000` öffnen, Sitzungstoken eingeben. `/health/live` prüft den Prozess;
`/health/ready` liefert 503 bei fehlenden, alten, zeitlich ungültigen oder schlechten Daten.
`/api/latest` und `/metrics` benötigen bearer. Readiness beschreibt lokale Erfassung;
Archivstatus separat. `GRIDGUARD_REQUIRE_ARCHIVE=1` verlangt Exporter-Heartbeat innerhalb
15 Sekunden, bestätigt aber nicht jede Messung. Alle beobachteten und mit
`GRIDGUARD_EXPECTED_ASSETS` erwarteten Assets werden geprüft, auch ohne bisherige Meldung.
Ausgemusterte Assets werden nicht automatisch aus dem Archiv entfernt.

Synchronisierte Reports: `work/gridguard.wal`, Grenze 128 MiB. Messungen/Checkpoints:
`work/gridguard.sqlite`. Supervisor muss laufen; außerhalb Compose kein Selbstneustart.
Vor Export `deploy/schema.sql` administrativ anwenden. `GRIDGUARD_PG_DSN` im lokalen
Modus optional. Export-Reconnect blockiert neue WAL-Erfassung nicht.

## Compose und Nachweise

`compose.yml`: IED, edge, API, TimescaleDB. `GRIDGUARD_TOKEN`, `GRIDGUARD_PG_PASSWORD`,
`GRIDGUARD_PG_DSN` setzen (Host `archive`, Datenbank/Benutzer `gridguard`, eigenes Passwort).
`docker compose up --build`; nur API über Host-Loopback veröffentlicht.
Lokal kein Compose-Lauf mangels Docker-Daemon. Hosted CI bestand Brücken,
Compose/TimescaleDB, Wiederherstellung und Builds mit/ohne ASan/UBSan bei `c9d6a9a`:
[CI](https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37425956295).
Main `9768a96`: lokal 40 Python-Tests und 2 CTests. Kein Produktionsnachweis;
jede neue Revision benötigt eigene erfolgreiche Prüfungen.

## Umfang und Grenzen

Loopback MMS/URCB, TEST-Qualität, Neustart, Eingabeabwehr, API, SQLite-Replay und
PostgreSQL-Deduplizierung getestet. Thermisches Modell illustrativ, beschleunigt,
unkalibriert; Gleichgewichtsresiduum ist Merkmal, keine Ausfallwahrscheinlichkeit.
Kein GOOSE, SV, SCL-Commissioning, Buffered-Report-Recovery, industrieller Datensatz,
gelernter Prädiktor, Hochverfügbarkeit oder unabhängige Multivendor-/Sicherheitsvalidierung.
GPLv3 wegen libIEC61850; Revision/Lizenzen in ADR.

## Optionale nur lesende Protokollbrücken

```sh
.venv/bin/pip install -r requirements-bridges.lock
.venv/bin/python -m pytest tests/test_bridges.py -q
.venv/bin/python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic
```


Echte lokale Server/Clients, keine gemockten Treiber. Laborquelle `synthetic`, externe
unvalidierte Daten `external-unvalidated`. [Mapping und Grenzen](docs/BRIDGES.md).
Compose nutzt MMS. Python-Adapter bedeuten keine Protokollimplementierung im C++-Gateway.

## Metriken und Aufbewahrung

Lokale Kapazität, WAL-Größe, konsumierte Checkpoint-Bytes, Beobachtungszeit.
Größe ist letzte Leserbeobachtung, kein atomarer Schreibersnapshot; `-1` heißt noch
nicht gemeldet. Alter berücksichtigen; Grenze 128 MiB.
`GRIDGUARD_LOCAL_RETENTION_SECONDS` (`0`, deaktiviert) gibt alte archivbestätigte
Datensätze nach erfolgreichem Export frei. Letzte Messung jedes Assets, ausstehende
Daten und Checkpoints bleiben. Wiederverwendbare SQLite-Seiten, nicht zwingend
Dateisystembytes. PostgreSQL-Aufbewahrung separat.

## Merkmale und synthetische Bewertung

Authentifiziertes `GET /api/features/{asset}?limit=128`: Mittelwert, RMS,
Populationsstandardabweichung, Peak, Endpunktsteigung. Steigende Timestamps, einheitlicher
Quell-/Erfassungsvertrag; ungültige Qualität → Enthaltung, veraltete Historie markiert.
Skalare Indikatoren, keine Rohvibrationsspektren. RUL null. Basisdefinitionen kompatibel
mit ARGUS-NEURO; keine FFT-/Modellübernahme mangels Waveform.

`python -m gridguard.evaluate --binary build/gridguard_synthetic --output work/evaluation`

Gleiche C++-Physik wie IED: vier deterministische Traces. Manifest mit Hashes,
Alert-/Enthaltungszahlen und erster Alarmzeit in Modellsekunden. Fehler ab erstem Schritt;
keine unabhängige Testpopulation/Feldvalidierung. `synthetic-replay`: feste historische
Uhr, normalisierte Qualität, kein Wire-Interoperabilitätsbeleg.

## WAL-Rotation

`GRIDGUARD_WAL_ROTATION_BYTES` (`0`, deaktiviert; 4096 Bytes–64 MiB) stoppt/wartet auf
Schreiber, bestätigt vollständige Datensätze in SQLite FULL, benennt redundantes WAL um
und nimmt es außer Betrieb. Dauerhafter Übergabebeleg erlaubt Recovery bei Cleanup-Absturz
und entfernt alte Inode-Checkpoints vor Wiederverwendung. Unvollständige Segmente/aktiver
Schreiber blockieren Stilllegung. SQLite hält bis Archiv-ACK und Retention.
URCB-Neustart kann Reports während der Pause verlieren; Diagnose nennt das Risiko.
Prozessabsturz-Recovery getestet, kein physischer Stromausfall.
