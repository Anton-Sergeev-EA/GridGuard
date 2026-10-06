import json
import subprocess
import time
import zlib
from pathlib import Path

import pytest
from test_contracts import sample

from gridguard.store import Store
from gridguard.wal import consume_available


def record(payload: bytes) -> bytes:
    return f"{zlib.crc32(payload):08x}".encode() + b"\t" + payload + b"\n"


def test_checkpoint_atomic_replay_and_torn_tail(tmp_path: Path) -> None:
    wal = tmp_path / "edge.wal"
    payload = sample().model_dump_json().encode()
    complete = record(payload)
    wal.write_bytes(complete + b"1234\tunfinished")
    store = Store(tmp_path / "spool.sqlite")
    assert consume_available(store, wal) == 1
    assert Store(store.path).count() == 1
    assert consume_available(Store(store.path), wal) == 0
    assert store.pending_count() == 1


def test_crc_failure_does_not_advance_or_drop(tmp_path: Path) -> None:
    wal = tmp_path / "edge.wal"
    wal.write_bytes(b"00000000\t" + sample().model_dump_json().encode() + b"\n")
    store = Store(tmp_path / "spool.sqlite")
    with pytest.raises(ValueError, match="checksum"):
        consume_available(store, wal)
    assert store.count() == 0
    assert store.checkpoint("unknown") == 0


def test_cpp_wal_survives_edge_kill(ied: tuple[Path, int], tmp_path: Path) -> None:
    edge, port = ied
    path = tmp_path / "edge.wal"
    client = subprocess.Popen(
        [str(edge), "127.0.0.1", str(port), "--wal", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if path.exists() and b"\n" in path.read_bytes():
                break
            assert client.poll() is None
            time.sleep(0.05)
        assert path.exists() and b"\n" in path.read_bytes()
        client.kill()
        client.wait(timeout=5)
        # The first record was synced by C++ before any Python store existed.
        store = Store(tmp_path / "spool.sqlite")
        assert consume_available(store, path) >= 1
        snapshot = store.latest()
        assert snapshot["sample"]["source"] == "synthetic"
        assert all(q & 2048 for q in snapshot["sample"]["quality"])
        assert consume_available(Store(store.path), path) == 0
        json.loads(path.read_bytes().splitlines()[0].split(b"\t", 1)[1])
    finally:
        if client.poll() is None:
            client.terminate()
            client.wait(timeout=5)
