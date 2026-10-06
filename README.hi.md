# GridGuard — डिजिटल सबस्टेशन और स्थिति निगरानी प्रयोगशाला

प्रयोगशाला कार्यान्वयन: C++20 सिंथेटिक IED, IEC 61850 MMS रिपोर्ट क्लाइंट,
Python स्थिति-निगरानी पाइपलाइन, स्थायी स्थानीय कतार, PostgreSQL निर्यात और FastAPI डैशबोर्ड।
केवल-पठन Modbus TCP, IEC-104, OPC UA और MQTT ब्रिज SCADA_Generator अडैप्टर उपयोग करते हैं।
**केवल प्रयोगशाला प्रमाण: फील्ड सत्यापन, RUL पूर्वानुमान या IEC प्रमाणन नहीं।**

[Русский](README.ru.md) · [English](README.md) · [中文](README.zh.md) · **हिन्दी** · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md)

[आर्किटेक्चर निर्णय](docs/ADRs.md), [सुरक्षा और सीमाएँ](docs/SECURITY.md),
[बेंचमार्क विधि](docs/BENCHMARKS.md)। यह डेमो है, उत्पादन तैनाती नहीं।

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## बिल्ड और परीक्षण

Linux, CMake ≥3.20, C++20 कंपाइलर, Ninja और Python ≥3.10 आवश्यक हैं।
लॉक की गई निर्भरताएँ CPython 3.12 पर जाँची गईं। CMake libIEC61850 का सटीक संशोधन
डाउनलोड करता है; `requirements.lock` में संस्करण हैं, पैकेज हैश नहीं। प्रथम सेटअप के लिए नेटवर्क चाहिए।

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

अलग PostgreSQL परीक्षण डेटाबेस उपयोग करें जिसमें लिखने की अनुमति हो। वास्तविक C++ बाइनरी
और PostgreSQL आवश्यक हैं; गायब निर्भरता पर परीक्षण विफल होते हैं, चुपचाप छोड़े नहीं जाते।
ASan/UBSan: दूसरी डायरेक्टरी में `-DGRIDGUARD_SANITIZERS=ON`, फिर `GRIDGUARD_BUILD`
उस पर सेट करें। एप्लिकेशन और IEC स्टैक दोनों instrumented हैं। TSan या स्वतंत्र interoperability परिणाम नहीं।

## स्थानीय संचालन

अपना `GRIDGUARD_TOKEN` कम से कम 16 अक्षरों का सेट करें; खाली टोकन स्वीकार नहीं है।
हर प्रक्रिया रिपॉज़िटरी रूट से अलग टर्मिनल में शुरू करें।

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000` खोलकर टोकन दें। `/health/live` प्रक्रिया जाँचता है;
`/health/ready` गायब, पुराने, गलत समय या गुणवत्ता वाले डेटा पर 503 देता है।
`/api/latest` और `/metrics` में bearer प्रमाणीकरण चाहिए। Readiness मुख्यतः स्थानीय
ingestion बताती है; संग्रह स्थिति अलग है। `GRIDGUARD_REQUIRE_ARCHIVE=1` पिछले
15 सेकंड में सफल exporter heartbeat माँगता है, हर sample की डिलीवरी सिद्ध नहीं करता।
सभी देखे गए assets और `GRIDGUARD_EXPECTED_ASSETS` में घोषित कभी न रिपोर्ट करने वाले
assets भी जाँचे जाते हैं। सेवानिवृत्त asset को संग्रह से स्वतः हटाना लागू नहीं है।

सिंक रिपोर्ट: `work/gridguard.wal`, सीमा 128 MiB। Samples/checkpoints:
`work/gridguard.sqlite` में atomic commit। Supervisor चालू रहना चाहिए; Compose के बाहर
स्वयं पुनः शुरू नहीं होता। Export से पहले प्रशासनिक तरीके से `deploy/schema.sql` लागू करें।
केवल स्थानीय उपयोग में `GRIDGUARD_PG_DSN` वैकल्पिक है। Export reconnect के दौरान WAL ingestion जारी है।

## Compose और प्रमाण

`compose.yml`: IED, edge, API, TimescaleDB। `GRIDGUARD_TOKEN`, `GRIDGUARD_PG_PASSWORD`,
`GRIDGUARD_PG_DSN` सेट करें: host `archive`, database/user `gridguard`, अपना password।
`docker compose up --build`; केवल API host loopback पर प्रकाशित होती है।
स्थानीय Docker daemon नहीं था, इसलिए स्थानीय Compose नहीं चला। Hosted CI ने `c9d6a9a`
पर bridges, Compose/TimescaleDB, archive/source recovery तथा ASan/UBSan सहित/रहित builds पास किए:
[CI](https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37425956295)।
Main `9768a96`: स्थानीय 40 Python tests और 2 CTests पास। इससे उत्पादन तैनाती सिद्ध नहीं होती;
हर नई revision को अपने checks पास करने होंगे।

## कार्यान्वयन और सीमाएँ

Loopback MMS/URCB, TEST गुणवत्ता, kill/restart, गलत input, API, SQLite replay और
वास्तविक PostgreSQL deduplication के परीक्षण हैं। तापीय मॉडल उदाहरणात्मक, तेज़ और
अकैलिब्रेटेड है; equilibrium residual एक feature है, fault probability नहीं।
GOOSE, SV, SCL commissioning, buffered report recovery, औद्योगिक dataset, प्रशिक्षित
predictor, high availability या स्वतंत्र multivendor/security validation उपलब्ध नहीं।
libIEC61850 से लिंक होने के कारण GPLv3; revision/license ADR में हैं।

## वैकल्पिक केवल-पठन ब्रिज

```sh
.venv/bin/pip install -r requirements-bridges.lock
.venv/bin/python -m pytest tests/test_bridges.py -q
.venv/bin/python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic
```


चारों अडैप्टर वास्तविक स्थानीय server/client से जाँचे जाते हैं, mock drivers से नहीं।
लैब में `synthetic`, बिना फील्ड सत्यापन वाले बाहरी डेटा में `external-unvalidated` चुनें।
[मैपिंग और सीमाएँ](docs/BRIDGES.md)। Compose में MMS है; Python अडैप्टर का अर्थ C++ gateway में वही protocol नहीं।

## मेट्रिक्स और retention

स्थानीय क्षमता, WAL आकार, consumed checkpoint bytes और observation time उपलब्ध हैं।
WAL आकार reader का अंतिम observation है, writer के साथ atomic snapshot नहीं।
`-1` का अर्थ अभी रिपोर्ट नहीं हुआ; observation की उम्र देखें। सीमा 128 MiB है।
`GRIDGUARD_LOCAL_RETENTION_SECONDS` डिफ़ॉल्ट `0` (बंद): सफल export के बाद केवल पुराने
archive-ACK samples reclaim होते हैं। हर asset का नवीनतम sample, pending samples और
checkpoints रहते हैं। SQLite pages पुनः उपयोग योग्य बनते हैं; filesystem bytes घटना आवश्यक नहीं।
PostgreSQL retention अलग नीति है।

## Features और सिंथेटिक मूल्यांकन

प्रमाणित `GET /api/features/{asset}?limit=128`: mean, RMS, population std, peak,
endpoint slope। बढ़ते timestamps और एक source/acquisition contract आवश्यक हैं।
खराब गुणवत्ता पर abstention, पुराने history पर स्पष्ट निशान। ये scalar trends हैं,
raw vibration spectra नहीं। RUL null है। मूल definitions ARGUS-NEURO से संगत हैं;
waveform न होने से FFT या trained models reuse नहीं होते।

`python -m gridguard.evaluate --binary build/gridguard_synthetic --output work/evaluation`

IED जैसी C++ physics से चार deterministic traces बनती हैं। Manifest में binary/trace
hashes, वास्तविक alert/abstention counts और model seconds में पहला alert है।
Fault पहले step से मौजूद है; यह independent held-out population या field validation नहीं।
`synthetic-replay` fixed historical clock और normalized quality उपयोग करता है, wire interoperability सिद्ध नहीं करता।

## WAL rotation

`GRIDGUARD_WAL_ROTATION_BYTES` डिफ़ॉल्ट `0` (बंद), सीमा 4096 bytes–64 MiB।
Supervisor writer रोककर उसके समाप्त होने की प्रतीक्षा करता है, पूर्ण records SQLite FULL
में commit करता है, फिर redundant WAL rename/retire करता है। Durable receipt से cleanup-crash
recovery और reuse से पहले पुराने inode checkpoints साफ होते हैं। अधूरे segments या active
writer retirement रोकते हैं। SQLite में records archive ACK और configured retention तक रहते हैं।
URCB restart की pause में source reports खो सकती हैं; diagnostics यह बताता है।
Process-crash recovery जाँची गई है, भौतिक power-loss नहीं।
