import fcntl
import time
from pathlib import Path

import pytest
from test_contracts import sample
from test_wal import record

from gridguard.rotation import recover_retired, rotate_committed
from gridguard.store import Store
from gridguard.wal import consume_available


def test_rotation_requires_committed_bytes_and_no_writer(tmp_path: Path) -> None:
    path = tmp_path / "edge.wal"
    path.write_bytes(record(sample().model_dump_json().encode()))
    store = Store(tmp_path / "store.sqlite")
    with pytest.raises(ValueError, match="uncommitted"):
        rotate_committed(store, path)
    consume_available(store, path)
    with path.open("rb") as writer:
        fcntl.flock(writer.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            rotate_committed(store, path)
    rotate_committed(store, path)
    assert not path.exists()
    assert not list(tmp_path.glob("*.retired-*"))
    reopened = Store(store.path)
    assert reopened.pending_count() == 1
    path.write_bytes(record(sample(int(time.time() * 1000) + 1).model_dump_json().encode()))
    assert consume_available(reopened, path) == 1
    assert reopened.count() == 2


def test_rotation_recovers_cleanup_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "edge.wal"
    path.write_bytes(record(sample().model_dump_json().encode()))
    store = Store(tmp_path / "store.sqlite")
    consume_available(store, path)
    unlink = Path.unlink

    def interrupted(target: Path, missing_ok: bool = False) -> None:
        if ".retired-" in target.name:
            raise OSError("injected cleanup crash")
        unlink(target, missing_ok=missing_ok)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupted)
        with pytest.raises(OSError, match="injected"):
            rotate_committed(store, path)
    assert not path.exists()
    assert len(list(tmp_path.glob("*.retired-*"))) == 1
    reopened = Store(store.path)
    recover_retired(reopened, path)
    assert not list(tmp_path.glob("*.retired-*"))
    assert reopened.pending_count() == 1
