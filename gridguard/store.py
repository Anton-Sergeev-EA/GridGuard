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

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def insert(self, sample: Sample) -> tuple[str, bool]:
        if sample.sample_ms > time.time_ns() // 1_000_000 + 1000:
            raise ValueError("future source timestamp")
        payload = sample.model_dump_json()
        identity = hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM samples WHERE id = ?", (identity,)).fetchone():
                return identity, False
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
        return identity, True

    def latest(self) -> dict[str, object] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT id, payload, assessment FROM samples "
                "ORDER BY sample_ms DESC, rowid DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "sample": json.loads(row[1]), "assessment": json.loads(row[2])}

    def pending(self, limit: int = 100) -> list[tuple[str, int, str, str]]:
        with self.connect() as db:
            return db.execute(
                "SELECT id, sample_ms, payload, assessment FROM samples "
                "WHERE exported=0 ORDER BY rowid LIMIT ?",
                (limit,),
            ).fetchall()

    def ack(self, identity: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE samples SET exported=1 WHERE id=?", (identity,))

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]

    def pending_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM samples WHERE exported=0").fetchone()[0]
