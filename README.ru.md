# GridGuard — лаборатория цифровой подстанции и мониторинга состояния

Лабораторная реализация платформы цифровой подстанции и предиктивного обслуживания:
синтетический IED на C++20, клиент отчётов IEC 61850 MMS на C++20, Python-конвейер
мониторинга состояния, постоянная локальная очередь, экспорт PostgreSQL и дашборд FastAPI.
Мосты Modbus TCP, IEC-104, OPC UA и MQTT только для чтения используют адаптеры SCADA_Generator.
**Доказательства только лабораторные. Нет field validation, прогноза RUL или IEC-сертификации.**

**Русский** · [English](README.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md)

[Архитектурные решения](docs/ADRs.md), [безопасность и ограничения](docs/SECURITY.md),
[методика измерений](docs/BENCHMARKS.md). Это демонстрационный стенд, не промышленное внедрение.

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## Сборка и тесты

Нужны Linux, CMake ≥3.20, компилятор C++20, Ninja и Python ≥3.10.
Зафиксированные зависимости проверялись на CPython 3.12. CMake загружает точную
ревизию libIEC61850; `requirements.lock` фиксирует версии Python-пакетов без хешей.
Для первоначальной установки нужен доступ к сети.

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

Используйте изолированную PostgreSQL-базу, в которую разрешено записывать тестовые данные.
Интеграционные тесты требуют реальных C++ бинарников и PostgreSQL; отсутствие зависимостей
вызывает ошибку вместо пропуска. ASan/UBSan: отдельная сборка с `-DGRIDGUARD_SANITIZERS=ON`,
затем тот же набор с `GRIDGUARD_BUILD`, указывающим на её каталог. Инструментируются
приложение и IEC-стек. Результатов TSan и независимой совместимости оборудования нет.

## Локальный запуск

Задайте собственный `GRIDGUARD_TOKEN` длиной не менее 16 символов. Пустой токен запрещён.
Процессы запускаются из корня проекта в отдельных терминалах.

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

Откройте `http://127.0.0.1:8000` и введите токен сессии. `/health/live` проверяет
работу процесса; `/health/ready` возвращает 503 при отсутствующих, устаревших,
некорректных по времени или качеству данных. `/api/latest` и `/metrics` требуют bearer-токен.
По умолчанию readiness описывает локальное поступление данных и отдельно состояние архива.
`GRIDGUARD_REQUIRE_ARCHIVE=1` требует heartbeat экспортёра не старше 15 секунд,
но не подтверждает доставку каждого измерения. Проверяются все наблюдавшиеся активы;
`GRIDGUARD_EXPECTED_ASSETS=transformer-lab-1,second` добавляет ожидаемые, ещё не передававшие
данные активы. Автоматического удаления выведенного актива из архива нет.

Синхронизированные отчёты записываются в `work/gridguard.wal` с пределом 128 MiB.
Измерения и checkpoints атомарно сохраняются в `work/gridguard.sqlite`.
Supervisor должен оставаться запущенным; вне Compose сам себя он не перезапускает.
Перед экспортом примените `deploy/schema.sql` к архиву своими административными средствами.
`GRIDGUARD_PG_DSN` необязателен для локального режима. Переподключение экспортёра
не останавливает поступление новых данных в WAL.

## Compose и подтверждённые проверки

`compose.yml` содержит IED, edge, API и TimescaleDB. Задайте `GRIDGUARD_TOKEN`,
`GRIDGUARD_PG_PASSWORD` и `GRIDGUARD_PG_DSN`; DSN использует хост `archive`,
базу/пользователя `gridguard` и ваш пароль. Запуск: `docker compose up --build`.
На loopback хоста опубликован только API.
Локально Compose не запускался из-за отсутствия Docker daemon. Hosted CI прошёл
мосты, Compose/TimescaleDB и восстановление архива/источника, сборки с ASan/UBSan и без
на head `c9d6a9a`: [запуск CI](https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37425956295).
Main `9768a96` проверен локально: 40 Python-тестов и 2 CTests. Это не доказательство
промышленного внедрения; новые ревизии требуют собственных успешных проверок.

## Реализованное и границы

Проверены loopback MMS/URCB, качество TEST, остановка/перезапуск, некорректный ввод,
авторизация API, SQLite replay и подавление дублей в реальном PostgreSQL.
Тепловая модель иллюстративна, ускорена и не откалибрована; остаток относительно
равновесия — признак, не вероятность отказа. Нет GOOSE, SV, SCL commissioning,
восстановления buffered reports, реальных промышленных датасетов, обученного предиктора,
высокой доступности или независимой multivendor/security validation.
GPLv3 обусловлена связью с libIEC61850; ревизия и лицензии указаны в ADR.

## Необязательные мосты протоколов только для чтения

```sh
.venv/bin/pip install -r requirements-bridges.lock
.venv/bin/python -m pytest tests/test_bridges.py -q
.venv/bin/python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic
```


Тесты используют реальные локальные серверы и клиенты всех четырёх протоколов,
а не mocked drivers. Для лаборатории источник `synthetic`, для внешних непроверенных
данных — `external-unvalidated`. [Соответствие полей и ограничения](docs/BRIDGES.md).
По умолчанию Compose использует MMS; Python-адаптеры не означают реализацию
этих протоколов внутри C++ gateway.

## Метрики и хранение

Метрики показывают ёмкость локального архива, WAL, прочитанные checkpoint-байты и время
наблюдения. Размер WAL — последнее наблюдение reader, а не атомарный снимок writer;
`-1` означает, что размер ещё не сообщён. Контролируйте возраст метрики. Предел — 128 MiB.
`GRIDGUARD_LOCAL_RETENTION_SECONDS` (по умолчанию `0`, выключено) освобождает историю
после успешного экспорта: только старые подтверждённые архивом записи. Последний sample
каждого актива, pending-записи и checkpoints сохраняются. Освобождаются повторно
используемые SQLite-страницы, не обязательно байты файловой системы. Политика PostgreSQL отдельная.

## Признаки и synthetic-оценка

Авторизованный `GET /api/features/{asset}?limit=128` возвращает mean, RMS, population
std, peak и endpoint slope ограниченного окна скалярной истории. Требуются возрастающие
timestamps и единый контракт источника/сбора. Невалидное качество вызывает отказ от оценки;
устаревшая история обозначена явно. Это не спектр исходной вибрации. RUL остаётся null.
Базовые определения совместимы с ARGUS-NEURO; FFT и обученные модели не перенесены,
поскольку в телеметрии нет waveform.

`python -m gridguard.evaluate --binary build/gridguard_synthetic --output work/evaluation`

Та же C++ физика, что в IED, генерирует четыре детерминированные трассы. Manifest
содержит хеши бинарника/трасс, фактические alert/abstention counts и время первой тревоги
в модельных секундах. Неисправность присутствует с первого шага. Это не независимая
отложенная популяция или field validation. `synthetic-replay` использует фиксированные
исторические часы и нормализованное качество, не доказывая протокольную совместимость.

## Контролируемая ротация WAL

`GRIDGUARD_WAL_ROTATION_BYTES` (по умолчанию `0`, выключено; порог 4096 байт–64 MiB)
останавливает writer и ждёт его завершения, сохраняет полные записи в SQLite FULL,
затем надёжно переименовывает и выводит из использования избыточный WAL.
Устойчивая receipt в SQLite обеспечивает восстановление после сбоя cleanup и очистку
старых inode checkpoints перед повторным использованием. Незавершённые сегменты и
работающий writer блокируют удаление WAL. Данные остаются в SQLite до archive ACK
и настроенной retention. Ротация перезапускает URCB-клиент: отчёты в паузе могут
теряться; диагностика это указывает. Проверено восстановление после сбоя процесса,
не физического отключения питания.
