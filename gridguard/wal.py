import time
import zlib
from pathlib import Path

from gridguard.schema import Sample
from gridguard.store import Store


def consume_available(store: Store, path: Path) -> int:
    """Checkpoint and validated sample are committed in one SQLite transaction."""
    consumed = 0
    with path.open("rb") as stream:
        status = path.stat()
        source = f"{path.resolve()}:{status.st_dev}:{status.st_ino}"
        offset = store.checkpoint(source)
        if offset > status.st_size:
            raise ValueError("WAL shrank behind its checkpoint")
        stream.seek(offset)
        while True:
            line = stream.readline(8193)
            if not line:
                return consumed
            if len(line) > 8192:
                raise ValueError("WAL oversized record")
            if not line.endswith(b"\n"):
                return consumed  # Concurrent append or torn tail: never checkpoint a fragment.
            crc, payload = line.rstrip(b"\n").split(b"\t", 1)
            if len(crc) != 8 or int(crc, 16) != zlib.crc32(payload):
                raise ValueError("WAL checksum mismatch")
            sample = Sample.model_validate_json(payload)
            store.insert(sample, (source, stream.tell()))
            consumed += 1


def wait_for_wal(path: Path, deadline_s: float = 5) -> None:
    deadline = time.monotonic() + deadline_s
    while not path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError("edge did not create its WAL")
        time.sleep(0.05)
