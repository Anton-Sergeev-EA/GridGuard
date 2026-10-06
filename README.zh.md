# GridGuard — 数字变电站与状态监测实验平台

实验室实现：C++20 合成 IED、IEC 61850 MMS 报告客户端、Python 状态监测流水线、
持久化本地队列、PostgreSQL 导出及 FastAPI 仪表板。
只读 Modbus TCP、IEC-104、OPC UA 和 MQTT 桥接复用 SCADA_Generator 适配器。
**仅有实验室证据：无现场验证、RUL 预测或 IEC 认证。**

[Русский](README.ru.md) · [English](README.md) · **中文** · [हिन्दी](README.hi.md) · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Italiano](README.it.md)

[架构决策](docs/ADRs.md)、[安全与限制](docs/SECURITY.md)、[基准方法](docs/BENCHMARKS.md)。
本项目是实验演示平台，不是生产部署。

```text
Physics-informed synthetic IED (libIEC61850, test quality bit)
    → actual MMS/URCB reports → C++20 edge (RAII, reconnect/backoff/jitter)
    → CRC/sync C++ WAL → Python supervisor → SQLite WAL/FULL → PostgreSQL (idempotent replay)
    → FastAPI / readiness / Prometheus endpoint → static browser dashboard
```

## 构建与测试

需要 Linux、CMake ≥3.20、C++20 编译器、Ninja、Python ≥3.10。
锁定依赖在 CPython 3.12 上验证。CMake 下载指定 libIEC61850 修订；
`requirements.lock` 固定 Python 包版本但不包含包哈希。首次安装需要网络。

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

使用允许写入的隔离 PostgreSQL 测试数据库。需要真实 C++ 二进制及数据库；
缺少集成依赖会失败，而不是静默跳过。ASan/UBSan：使用另一构建目录并配置
`-DGRIDGUARD_SANITIZERS=ON`，随后将 `GRIDGUARD_BUILD` 指向该目录。
应用与 IEC 协议栈均被插桩。尚无 TSan 或独立设备互操作性验证结果。

## 本地运行

设置自己的 `GRIDGUARD_TOKEN`，至少 16 个字符；拒绝空令牌。
各进程从仓库根目录在独立终端启动。

```sh
./build/gridguard_ied 8102
# Optional IED scenario: ./build/gridguard_ied 8102 cooling-fault
# Also available: bearing-fault / sensor-fault; see docs/TELEMETRY.md.
.venv/bin/python -m gridguard.worker
# GRIDGUARD_PG_DSN is optional for local-only use; set it to enable remote export.
.venv/bin/python -m uvicorn gridguard.api:app_factory --factory --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000` 并输入会话令牌。`/health/live` 检查进程；
`/health/ready` 在数据缺失、过时、时钟或质量无效时返回 503。
`/api/latest`、`/metrics` 要求 bearer 认证。默认 readiness 表示本地采集，
另行报告归档状态。`GRIDGUARD_REQUIRE_ARCHIVE=1` 要求导出心跳在 15 秒内成功，
并不证明每个样本已送达。检查所有已观察资产；`GRIDGUARD_EXPECTED_ASSETS`
也检查配置但从未上报的资产。退役资产不会自动从归档删除。

同步报告保存于 `work/gridguard.wal`，上限 128 MiB。样本与检查点原子提交至
`work/gridguard.sqlite`。Supervisor 必须保持运行；Compose 之外不能自行重启。
导出前用数据库管理流程应用 `deploy/schema.sql`。纯本地使用可不设 `GRIDGUARD_PG_DSN`。
导出重连与新数据写入 WAL 独立。

## Compose 与验证证据

`compose.yml` 包含 IED、edge、API、TimescaleDB。设置 `GRIDGUARD_TOKEN`、
`GRIDGUARD_PG_PASSWORD`、`GRIDGUARD_PG_DSN`：主机 `archive`，数据库/用户 `gridguard`，
使用自己的密码。执行 `docker compose up --build`；仅 API 发布到主机 loopback。
因无 Docker daemon，未在本地执行 Compose。托管 CI 在 `c9d6a9a` 上通过桥接、
Compose/TimescaleDB、归档/源恢复及带/不带 ASan/UBSan 的构建：
[CI 运行](https://github.com/Anton-Sergeev-EA/GridGuard/actions/runs/37425956295)。
Main `9768a96` 本地通过 40 项 Python 测试、2 项 CTests。
这不是生产部署证据；新版本必须重新通过相应检查。

## 已实现与限制

本地环回 MMS/URCB、TEST 质量、终止/重启、无效输入拒绝、API 授权、SQLite 重放、
真实 PostgreSQL 去重均有测试。热模型仅为加速、未标定的示例；平衡残差是特征，
不是故障概率。未实现 GOOSE、SV、SCL 调试、缓冲报告恢复、工业设备数据集、
学习式预测模型、高可用性或独立多厂商/安全验证。
因链接 libIEC61850 采用 GPLv3；修订与许可证见 ADR。

## 可选只读协议桥接

```sh
.venv/bin/pip install -r requirements-bridges.lock
.venv/bin/python -m pytest tests/test_bridges.py -q
.venv/bin/python -m gridguard.bridge --config YOUR_CONFIG.json --source synthetic
```


测试采用四种适配器的真实本地服务器与客户端，不是 mocked drivers。
实验源选 `synthetic`；未验证外部数据选 `external-unvalidated`。
[映射与限制](docs/BRIDGES.md)。Compose 默认 MMS；Python 桥接不代表 C++ 网关实现这些协议。

## 指标与保留策略

指标包括本地归档容量、WAL 大小、已消费检查点字节及观察时间。
WAL 大小为 reader 上次观察值，不是与 writer 同步的原子快照；`-1` 表示尚未报告。
必须检查观察时间；WAL 上限仍为 128 MiB。
`GRIDGUARD_LOCAL_RETENTION_SECONDS` 默认 `0`（关闭），导出成功后仅回收
过期且已获归档确认的样本。保留每个资产最新样本、待导出样本及检查点。
回收可复用 SQLite 页，不保证缩小文件系统字节。PostgreSQL 保留策略单独配置。

## 特征与合成评估

认证的 `GET /api/features/{asset}?limit=128` 返回均值、RMS、总体标准差、峰值及
两端斜率。要求递增时间戳和统一采集/来源契约；无效质量导致弃权，过时历史明确标记。
这些是标量趋势，不是原始振动频谱。RUL 为 null。基础定义与 ARGUS-NEURO 一致；
因数据不包含波形，不复用 FFT 或训练模型。

`python -m gridguard.evaluate --binary build/gridguard_synthetic --output work/evaluation`

使用 IED 相同 C++ 物理模型产生四条确定性轨迹。Manifest 记录二进制/轨迹哈希、
实际告警/弃权数及模型秒计首次告警时间。故障从第一步存在，不构成独立留出群体或
现场验证。`synthetic-replay` 使用固定历史时钟和归一化质量，不证明线级协议互操作性。

## WAL 受控轮换

`GRIDGUARD_WAL_ROTATION_BYTES` 默认 `0`（关闭），阈值 4096 字节–64 MiB。
Supervisor 停止并等待 writer，把所有完整记录提交 SQLite FULL，再持久化重命名并
退役冗余 WAL。SQLite 交接凭证用于清理崩溃恢复，并在复用前清除旧 inode 检查点。
未提交/破损尾段或活动 writer 会阻止退役。样本在 SQLite 保留至 archive ACK 与
配置保留期限。轮换会重启 URCB；间隙报告可能丢失，诊断会明确提示。
测试验证进程崩溃恢复，未验证物理断电。
