# GridGuard — laboratorio de subestación digital y monitorización de condición

Implementación de laboratorio: IED sintético C++20, cliente de informes IEC 61850 MMS,
procesamiento Python, cola local persistente, exportación PostgreSQL y panel FastAPI.
Los puentes de solo lectura Modbus TCP, IEC-104, OPC UA y MQTT reutilizan SCADA_Generator.
**Solo evidencia de laboratorio: sin validación de campo, RUL ni certificación IEC.**

[Русский](README.ru.md) · [English](README.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · **Español** · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md)

[Decisiones](docs/ADRs.md), [seguridad](docs/SECURITY.md), [método de benchmark](docs/BENCHMARKS.md).
El proyecto es un demostrador, no una instalación de producción.

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## Compilación y pruebas

Linux, CMake ≥3.20, compilador C++20, Ninja y Python ≥3.10. Dependencias comprobadas
con CPython 3.12. CMake descarga una revisión exacta de libIEC61850; `requirements.lock`
fija versiones sin hashes. La instalación inicial requiere red.

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

Use una base PostgreSQL aislada donde pueda escribir. Los binarios C++ y PostgreSQL
son obligatorios: las dependencias ausentes provocan error. ASan/UBSan: otro directorio
con `-DGRIDGUARD_SANITIZERS=ON`; indique ese directorio mediante `GRIDGUARD_BUILD`.
Se instrumentan aplicación y pila IEC. No se declara resultado TSan ni interoperabilidad independiente.

## Ejecución local

Defina su propio `GRIDGUARD_TOKEN`, mínimo 16 caracteres; no se permite vacío.
Inicie cada proceso desde la raíz en un terminal independiente.

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

Abra `http://127.0.0.1:8000` e introduzca el token. `/health/live` comprueba el proceso;
`/health/ready` devuelve 503 con datos ausentes, antiguos, reloj inválido o mala calidad.
`/api/latest` y `/metrics` requieren bearer. La disponibilidad refleja ingestión local;
el archivo se informa por separado. `GRIDGUARD_REQUIRE_ARCHIVE=1` exige heartbeat
correcto del exportador en 15 segundos, no confirma cada muestra. Se comprueban todos
los activos observados y los configurados en `GRIDGUARD_EXPECTED_ASSETS` aunque no
hayan informado. No se eliminan automáticamente los activos retirados del archivo.

Informes sincronizados: `work/gridguard.wal`, límite 128 MiB. Muestras y checkpoints:
`work/gridguard.sqlite`. El supervisor debe seguir ejecutándose; fuera de Compose no
se reinicia solo. Aplique `deploy/schema.sql` antes de exportar. `GRIDGUARD_PG_DSN`
es opcional en modo local. La reconexión de exportación no detiene la ingestión WAL.

## Compose y evidencia

`compose.yml`: IED, edge, API, TimescaleDB. Configure `GRIDGUARD_TOKEN`,
`GRIDGUARD_PG_PASSWORD`, `GRIDGUARD_PG_DSN` (host `archive`, base/usuario `gridguard`,
su contraseña). Ejecute `docker compose up --build`; solo la API se publica en loopback.
Compose no se ejecutó localmente por falta de daemon Docker. CI alojado pasó puentes,
Compose/TimescaleDB, recuperación y builds con/sin ASan/UBSan en `c9d6a9a`:
[CI](https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37425956295).
Main `9768a96`: 40 pruebas Python y 2 CTests locales. No demuestra despliegue industrial;
cada nueva revisión debe superar sus comprobaciones.

## Alcance y límites

Pruebas de MMS/URCB loopback, calidad TEST, reinicio, rechazo de entrada, API,
replay SQLite y deduplicación PostgreSQL. Modelo térmico ilustrativo, acelerado y
sin calibrar: el residual de equilibrio es una característica, no probabilidad de fallo.
No hay GOOSE, SV, commissioning SCL, recuperación buffered reports, datos industriales,
predictor entrenado, alta disponibilidad ni validación multivendor/seguridad independiente.
GPLv3 por libIEC61850; revisión y licencias en ADR.

## Puentes opcionales de solo lectura

```sh
.venv/bin/pip install -r requirements-bridges.lock
.venv/bin/python -m pytest tests/test_bridges.py -q
.venv/bin/python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic
```


Pruebas con servidores/clientes locales reales, no drivers simulados mediante mocks.
Use `synthetic` en laboratorio; `external-unvalidated` para datos externos sin validación.
[Mapeo y límites](docs/BRIDGES.md). Compose usa MMS. Los adaptadores Python no implican
implementación de esos protocolos en el gateway C++.

## Métricas y retención

Capacidad del archivo local, tamaño WAL, bytes checkpoint consumidos y hora de observación.
El tamaño es la última observación del lector, no una instantánea atómica del escritor;
`-1` significa que todavía no se ha informado. Compruebe la antigüedad; límite 128 MiB.
`GRIDGUARD_LOCAL_RETENTION_SECONDS` (`0`, desactivado) libera solo registros antiguos
confirmados por el archivo después de exportación. Conserva últimas muestras por activo,
pendientes y checkpoints. Libera páginas SQLite reutilizables, no necesariamente bytes
del sistema de archivos. La retención PostgreSQL es una política aparte.

## Características y evaluación sintética

`GET /api/features/{asset}?limit=128` autenticado: media, RMS, desviación poblacional,
pico y pendiente entre extremos. Exige timestamps crecientes y contrato de adquisición/
fuente uniforme; calidad inválida causa abstención y datos antiguos se marcan.
Son indicadores escalares, no espectros de vibración. RUL es null. Definiciones básicas
compatibles con ARGUS-NEURO; sin reutilización de FFT/modelos porque no hay waveform.

`python -m gridguard.evaluate --binary build/gridguard_synthetic --output work/evaluation`

Misma física C++ que el IED: cuatro trazas deterministas. Manifest con hashes,
alertas/abstenciones reales y primera alerta en segundos del modelo. Fallos desde el
primer paso, no población independiente ni validación de campo. `synthetic-replay`
usa reloj histórico fijo y calidad normalizada; no acredita interoperabilidad de red.

## Rotación WAL

`GRIDGUARD_WAL_ROTATION_BYTES` (`0`, desactivado; 4096 bytes–64 MiB) detiene/espera al
escritor, confirma registros completos en SQLite FULL y renombra/retira WAL redundante.
Un recibo durable permite recuperación de fallo de limpieza y elimina checkpoints de
inodos antiguos antes de reutilizar. Segmentos incompletos o escritor activo bloquean
retirada. SQLite conserva datos hasta ACK del archivo y retención configurada.
Reiniciar URCB puede perder informes durante la pausa; se informa de este riesgo.
Se prueba fallo de proceso, no pérdida física de alimentación.
