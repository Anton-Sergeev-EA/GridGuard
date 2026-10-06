# GridGuard — laboratorio di sottostazione digitale e monitoraggio delle condizioni

Implementazione di laboratorio: IED sintetico C++20, client report IEC 61850 MMS,
pipeline Python, coda locale persistente, esportazione PostgreSQL e dashboard FastAPI.
Ponti di sola lettura Modbus TCP, IEC-104, OPC UA e MQTT riutilizzano SCADA_Generator.
**Solo evidenza di laboratorio: nessuna validazione sul campo, RUL o certificazione IEC.**

[Русский](README.ru.md) · [English](README.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · **Italiano**

[Decisioni](docs/ADRs.md), [sicurezza](docs/SECURITY.md), [metodo benchmark](docs/BENCHMARKS.md).
Dimostratore, non un'installazione di produzione.

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## Compilazione e test

Linux, CMake ≥3.20, compilatore C++20, Ninja e Python ≥3.10. Dipendenze verificate su
CPython 3.12. CMake scarica una revisione precisa di libIEC61850; `requirements.lock`
fissa versioni senza hash dei pacchetti. Rete necessaria per la prima installazione.

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

Usare PostgreSQL isolato con autorizzazione di scrittura. Binari C++ e PostgreSQL reali
sono obbligatori; dipendenze mancanti causano errore. ASan/UBSan: altra directory con
`-DGRIDGUARD_SANITIZERS=ON`, poi `GRIDGUARD_BUILD` verso di essa. Applicazione e stack
IEC strumentati. Nessun risultato TSan o interoperabilità indipendente dichiarato.

## Esecuzione locale

Impostare il proprio `GRIDGUARD_TOKEN`, almeno 16 caratteri; token vuoto rifiutato.
Avviare ogni processo dalla radice in un terminale separato.

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

Aprire `http://127.0.0.1:8000` e inserire il token. `/health/live` verifica il processo;
`/health/ready` restituisce 503 per dati mancanti, vecchi, tempo o qualità invalidi.
`/api/latest` e `/metrics` richiedono bearer. Readiness indica ingestione locale;
archivio separato. `GRIDGUARD_REQUIRE_ARCHIVE=1` richiede heartbeat esportatore entro
15 secondi, non consegna di ogni campione. Verifica tutti gli asset osservati e quelli
in `GRIDGUARD_EXPECTED_ASSETS`, anche mai ricevuti. Nessuna rimozione automatica di
asset ritirati dall'archivio.

Report sincronizzati: `work/gridguard.wal`, limite 128 MiB. Campioni/checkpoint:
`work/gridguard.sqlite`. Supervisor sempre attivo; fuori Compose non si riavvia da solo.
Applicare `deploy/schema.sql` prima dell'export. `GRIDGUARD_PG_DSN` facoltativo in locale.
La riconnessione esportatore non ferma nuovi dati WAL.

## Compose ed evidenza

`compose.yml`: IED, edge, API, TimescaleDB. Impostare `GRIDGUARD_TOKEN`,
`GRIDGUARD_PG_PASSWORD`, `GRIDGUARD_PG_DSN` (host `archive`, database/utente `gridguard`,
propria password). `docker compose up --build`; solo API pubblicata su loopback.
Compose non eseguito localmente senza daemon Docker. CI hosted superato per ponti,
Compose/TimescaleDB, recupero e build con/senza ASan/UBSan su `c9d6a9a`:
[CI](https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37425956295).
Main `9768a96`: 40 test Python e 2 CTests locali. Non prova un deployment industriale;
ciascuna nuova revisione richiede controlli propri.

## Ambito e limiti

Test di MMS/URCB loopback, qualità TEST, riavvio, input errati, API, replay SQLite e
rimozione duplicati PostgreSQL. Modello termico illustrativo, accelerato e non calibrato:
il residuo di equilibrio è una caratteristica, non probabilità di guasto.
Niente GOOSE, SV, commissioning SCL, recupero buffered reports, dataset industriali,
predittore addestrato, alta disponibilità o validazione multivendor/sicurezza indipendente.
GPLv3 per libIEC61850; revisione e licenze in ADR.

## Ponti opzionali di sola lettura

```sh
.venv/bin/pip install -r requirements-bridges.lock
.venv/bin/python -m pytest tests/test_bridges.py -q
.venv/bin/python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic
```


Server/client locali reali, non driver mock. `synthetic` per laboratorio,
`external-unvalidated` per dati esterni senza validazione. [Mappatura e limiti](docs/BRIDGES.md).
Compose usa MMS; gli adattatori Python non implementano quei protocolli nel gateway C++.

## Metriche e conservazione

Capacità locale, dimensione WAL, byte checkpoint consumati e istante di osservazione.
Dimensione: ultima osservazione lettore, non snapshot atomico scrittore; `-1` significa
non ancora comunicata. Considerare l'età; limite 128 MiB.
`GRIDGUARD_LOCAL_RETENTION_SECONDS` (`0`, disabilitato) libera solo vecchi record
confermati dopo export riuscito. Conserva ultimi campioni per asset, pendenti e
checkpoint. Libera pagine SQLite riutilizzabili, non necessariamente byte filesystem.
La retention PostgreSQL è separata.

## Caratteristiche e valutazione sintetica

`GET /api/features/{asset}?limit=128` autenticato: media, RMS, deviazione standard
popolazione, picco e pendenza estremi. Timestamp crescenti, unico contratto sorgente/
acquisizione; qualità invalida → astensione, storia obsoleta indicata.
Indicatori scalari, non spettri di vibrazione grezza. RUL null. Definizioni base
compatibili ARGUS-NEURO; nessuna FFT/modello riutilizzato perché manca waveform.

`python -m gridguard.evaluate --binary build/gridguard_synthetic --output work/evaluation`

Stessa fisica C++ dell'IED: quattro tracce deterministiche. Manifest con hash,
conteggi reali allarmi/astensioni e primo allarme in secondi del modello. Guasti dal
primo passo; non popolazione indipendente o validazione sul campo. `synthetic-replay`
usa orologio storico fisso e qualità normalizzata, non prova interoperabilità sul filo.

## Rotazione WAL

`GRIDGUARD_WAL_ROTATION_BYTES` (`0`, disabilitato; 4096 byte–64 MiB) ferma/attende
scrittore, conferma record completi in SQLite FULL, rinomina/ritira WAL ridondante.
Ricevuta durevole per recupero da crash di pulizia e rimozione vecchi checkpoint inode
prima del riuso. Segmenti incompleti o scrittore attivo bloccano ritiro. SQLite conserva
fino ad ACK archivio e retention. Riavvio URCB: possibili perdite di report nella pausa,
rischio dichiarato dalla diagnostica. Test di crash processo, non interruzione fisica di alimentazione.
