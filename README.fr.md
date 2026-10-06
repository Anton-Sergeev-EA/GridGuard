# GridGuard — laboratoire de sous-station numérique et de surveillance d’état

Implémentation de laboratoire : IED synthétique C++20, client de rapports IEC 61850 MMS,
traitement Python, file locale persistante, export PostgreSQL et tableau de bord FastAPI.
Passerelles en lecture seule Modbus TCP, IEC-104, OPC UA et MQTT issues de SCADA_Generator.
**Preuves de laboratoire uniquement : aucune validation terrain, RUL ou certification IEC.**

[Русский](README.ru.md) · [English](README.md) · [中文](README.zh.md) · [हिन्दी](README.hi.md) · [Español](README.es.md) · **Français** · [Deutsch](README.de.md) · [Italiano](README.it.md)

[Décisions](docs/ADRs.md), [sécurité](docs/SECURITY.md), [mesures](docs/BENCHMARKS.md).
Démonstrateur, pas un déploiement industriel.

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## Compilation et tests

Linux, CMake ≥3.20, compilateur C++20, Ninja, Python ≥3.10. Dépendances vérifiées sous
CPython 3.12. CMake télécharge une révision précise de libIEC61850 ; `requirements.lock`
fixe les versions sans hashes. Réseau nécessaire à la première installation.

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

Utilisez une base PostgreSQL isolée autorisée en écriture. Binaires C++ et PostgreSQL
obligatoires ; les dépendances absentes font échouer les tests. ASan/UBSan : autre répertoire
avec `-DGRIDGUARD_SANITIZERS=ON`, puis `GRIDGUARD_BUILD` vers celui-ci.
Application et pile IEC instrumentées. Aucun résultat TSan ni interopérabilité indépendante.

## Exécution locale

Définissez votre `GRIDGUARD_TOKEN` d’au moins 16 caractères ; jeton vide refusé.
Chaque processus démarre à la racine dans un terminal séparé.

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

Ouvrez `http://127.0.0.1:8000` et saisissez le jeton. `/health/live` vérifie le processus ;
`/health/ready` renvoie 503 si données absentes, anciennes, horloge ou qualité invalides.
`/api/latest` et `/metrics` exigent bearer. Readiness décrit l’ingestion locale ;
l’archive est signalée séparément. `GRIDGUARD_REQUIRE_ARCHIVE=1` exige heartbeat de
l’exporteur dans les 15 secondes, pas la livraison de chaque mesure. Tous les actifs
observés et ceux de `GRIDGUARD_EXPECTED_ASSETS` sont vérifiés, même jamais reçus.
La suppression des actifs retirés de l’archive n’est pas automatisée.

Rapports synchronisés : `work/gridguard.wal`, plafond 128 MiB. Mesures/checkpoints :
`work/gridguard.sqlite`. Le superviseur doit rester actif ; hors Compose, pas d’auto-redémarrage.
Appliquez `deploy/schema.sql` avant export. `GRIDGUARD_PG_DSN` est facultatif en mode local.
La reconnexion de l’exporteur ne bloque pas l’ingestion WAL.

## Compose et preuves

`compose.yml` : IED, edge, API, TimescaleDB. Définissez `GRIDGUARD_TOKEN`,
`GRIDGUARD_PG_PASSWORD`, `GRIDGUARD_PG_DSN` (hôte `archive`, base/utilisateur `gridguard`,
votre mot de passe). `docker compose up --build` ; seule l’API est publiée en loopback.
Pas d’exécution Compose locale sans daemon Docker. CI hébergé : passerelles,
Compose/TimescaleDB, récupération, builds avec/sans ASan/UBSan réussis à `c9d6a9a` :
[CI](https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37425956295).
Main `9768a96` : 40 tests Python et 2 CTests locaux. Pas une preuve de déploiement ;
chaque nouvelle révision doit réussir ses tests.

## Périmètre et limites

MMS/URCB loopback, qualité TEST, redémarrage, rejet d’entrée, API, replay SQLite et
déduplication PostgreSQL testés. Modèle thermique illustratif, accéléré et non calibré :
le résidu d’équilibre est une caractéristique, pas une probabilité de panne.
Pas de GOOSE, SV, commissioning SCL, reprise buffered reports, données industrielles,
prédicteur appris, haute disponibilité ou validation multivendeur/sécurité indépendante.
GPLv3 liée à libIEC61850 ; révision/licences dans ADR.

## Passerelles facultatives en lecture seule

```sh
.venv/bin/pip install -r requirements-bridges.lock
.venv/bin/python -m pytest tests/test_bridges.py -q
.venv/bin/python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic
```


Tests avec vrais serveurs/clients locaux, pas des drivers mockés. Source `synthetic`
pour laboratoire ; `external-unvalidated` pour données externes non validées.
[Correspondance et limites](docs/BRIDGES.md). Compose utilise MMS ; ces adaptateurs
Python ne prouvent pas l’implémentation des protocoles dans le gateway C++.

## Métriques et rétention

Capacité locale, taille WAL, octets checkpoint consommés et instant d’observation.
Taille WAL : dernière observation lecteur, pas un instantané atomique écrivain ;
`-1` indique aucune observation. Surveillez son âge ; plafond 128 MiB.
`GRIDGUARD_LOCAL_RETENTION_SECONDS` (`0`, désactivé) libère les anciens enregistrements
acquittés après export réussi. Dernière mesure par actif, données en attente et
checkpoints conservés. Pages SQLite réutilisables libérées, pas nécessairement les octets
du système de fichiers. Rétention PostgreSQL séparée.

## Caractéristiques et évaluation synthétique

`GET /api/features/{asset}?limit=128` authentifié : moyenne, RMS, écart-type population,
pic et pente entre extrémités. Timestamps croissants, contrat source/acquisition unique ;
qualité invalide → abstention ; historique ancien indiqué. Indicateurs scalaires,
pas de spectre vibratoire. RUL null. Définitions de base compatibles ARGUS-NEURO ;
pas de FFT/modèles réutilisés, faute de waveform.

`python -m gridguard.evaluate --binary build/gridguard_synthetic --output work/evaluation`

Même physique C++ que l’IED : quatre traces déterministes. Manifest : hashes,
comptages alertes/abstentions et première alerte en secondes du modèle. Défauts dès
le premier pas ; pas de population indépendante ni validation terrain.
`synthetic-replay` : horloge historique fixe, qualité normalisée, sans preuve d’interopérabilité.

## Rotation WAL

`GRIDGUARD_WAL_ROTATION_BYTES` (`0`, désactivé ; 4096 octets–64 MiB) arrête/attend
l’écrivain, valide tous les enregistrements complets en SQLite FULL, renomme/retire le WAL.
Reçu durable pour reprise après panne de nettoyage et suppression d’anciens checkpoints
inode avant réutilisation. Segments incomplets ou écrivain actif bloquent le retrait.
SQLite conserve jusqu’à ACK archive et rétention configurée. Redémarrage URCB : des
rapports peuvent être perdus pendant la pause ; risque signalé. Test de panne de
processus, pas de coupure physique d’alimentation.
