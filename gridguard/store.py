import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from gridguard.condition import assess
from gridguard.schema import Sample


class Store:
    """Per-call connections allow FastAPI threads and WAL concurrent readers."""

    def __init__(self, path: Path, capacity: int = 100_000) -> None:
        self.path = path
        self.capacity = capacity
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS samples (
                id TEXT PRIMARY KEY, asset TEXT NOT NULL, sample_ms INTEGER NOT NULL,
                payload TEXT NOT NULL, assessment TEXT NOT NULL,
                exported INTEGER NOT NULL DEFAULT 0)
            """)
            db.execute(
                "CREATE TABLE IF NOT EXISTS checkpoints "
                "(source TEXT PRIMARY KEY, offset INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS runtime (name TEXT PRIMARY KEY, value REAL NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS samples_asset_time ON samples(asset, sample_ms)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS retired_wals "
                "(source TEXT PRIMARY KEY, size INTEGER NOT NULL)"
            )

    def retain_exported(self, before_ms: int, limit: int = 1000) -> int:
        """Reclaim remote-acknowledged history, preserving each asset's latest snapshot."""
        if before_ms < 0 or limit < 1 or limit > 10_000:
            raise ValueError("invalid retention bounds")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "DELETE FROM samples WHERE id IN ("
                "SELECT old.id FROM samples AS old "
                "WHERE old.exported=1 AND old.sample_ms < ? "
                "AND EXISTS (SELECT 1 FROM samples AS newer WHERE newer.asset=old.asset "
                "AND (newer.sample_ms > old.sample_ms "
                "OR (newer.sample_ms=old.sample_ms AND newer.rowid > old.rowid))) "
                "ORDER BY old.sample_ms LIMIT ?)",
                (before_ms, limit),
            )
            return result.rowcount

    def set_runtime(self, name: str, value: float) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO runtime(name,value) VALUES (?,?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                (name, value),
            )

    def runtime(self) -> dict[str, float]:
        with self.connect() as db:
            return dict(db.execute("SELECT name,value FROM runtime").fetchall())

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def insert(self, sample: Sample, checkpoint: tuple[str, int] | None = None) -> tuple[str, bool]:
        if sample.sample_ms > time.time_ns() // 1_000_000 + 1000:
            raise ValueError("future source timestamp")
        payload = sample.model_dump_json()
        identity = hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = not db.execute("SELECT 1 FROM samples WHERE id = ?", (identity,)).fetchone()
            if inserted:
                if db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] >= self.capacity:
                    raise OverflowError("local archive capacity reached; ingest stopped")
                previous = db.execute(
                    "SELECT sample_ms FROM samples WHERE asset=? ORDER BY sample_ms DESC LIMIT 1",
                    (sample.asset,),
                ).fetchone()
                if previous and sample.sample_ms < previous[0]:
                    raise ValueError("out-of-order sample")
                db.execute(
                    "INSERT INTO samples(id, asset, sample_ms, payload, assessment) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (identity, sample.asset, sample.sample_ms, payload, json.dumps(assess(sample))),
                )
            if checkpoint is not None:
                db.execute(
                    "INSERT INTO checkpoints(source, offset) VALUES (?, ?) "
                    "ON CONFLICT(source) DO UPDATE SET offset=max(offset, excluded.offset)",
                    checkpoint,
                )
        return identity, bool(inserted)

    def checkpoint(self, source: str) -> int:
        with self.connect() as db:
            row = db.execute("SELECT offset FROM checkpoints WHERE source=?", (source,)).fetchone()
            return row[0] if row else 0

    def latest(self) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT id, payload, assessment FROM samples "
                "ORDER BY sample_ms DESC, rowid DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "sample": json.loads(row[1]), "assessment": json.loads(row[2])}

    def latest_assets(self) -> dict[str, dict[str, object]]:
        """Return one consistent latest snapshot per observed asset."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT asset, id, payload, assessment FROM ("
                "SELECT asset, id, payload, assessment, "
                "ROW_NUMBER() OVER (PARTITION BY asset "
                "ORDER BY sample_ms DESC, rowid DESC) AS rank "
                "FROM samples) WHERE rank=1"
            ).fetchall()
        return {
            row[0]: {"id": row[1], "sample": json.loads(row[2]), "assessment": json.loads(row[3])}
            for row in rows
        }

    def pending(self, limit: int = 100) -> list[tuple[str, int, str, str]]:
        with self.connect() as db:
            return db.execute(
                "SELECT id, sample_ms, payload, assessment FROM samples "
                "WHERE exported=0 ORDER BY rowid LIMIT ?",
                (limit,),
            ).fetchall()

    def history(self, asset: str, limit: int = 128) -> list[Sample]:
        if not 2 <= limit <= 1024:
            raise ValueError("history limit must be between 2 and 1024")
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM samples WHERE asset=? "
                "ORDER BY sample_ms DESC, rowid DESC LIMIT ?",
                (asset, limit),
            ).fetchall()
        return [Sample.model_validate_json(row[0]) for row in reversed(rows)]

    def ack(self, identity: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE samples SET exported=1 WHERE id=?", (identity,))

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]

    def pending_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM samples WHERE exported=0").fetchone()[0]
