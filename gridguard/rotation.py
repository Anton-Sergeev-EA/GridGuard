"""Stopped-writer handoff: SQLite FULL commit precedes retiring the redundant spool."""

import fcntl
import os
from pathlib import Path

from gridguard.store import Store


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def recover_retired(store: Store, path: Path) -> None:
    for retired in path.parent.glob(path.name + ".retired-*"):
        descriptor = os.open(retired, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            status = os.fstat(descriptor)
            expected_name = f"{path.name}.retired-{status.st_dev}-{status.st_ino}"
            source = f"{path.resolve()}:{status.st_dev}:{status.st_ino}"
            if retired.name != expected_name:
                raise ValueError("retired WAL is not fully committed; retained for investigation")
            with store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                receipt = db.execute(
                    "SELECT size FROM retired_wals WHERE source=?", (source,)
                ).fetchone()
                checkpoint = db.execute(
                    "SELECT offset FROM checkpoints WHERE source=?", (source,)
                ).fetchone()
                if not (
                    (receipt and receipt[0] == status.st_size)
                    or (checkpoint and checkpoint[0] == status.st_size)
                ):
                    raise ValueError("retired WAL has no durable handoff proof")
                db.execute(
                    "INSERT INTO retired_wals(source,size) VALUES (?,?) "
                    "ON CONFLICT(source) DO UPDATE SET size=excluded.size",
                    (source, status.st_size),
                )
                # Receipt survives cleanup crash; removing offset prevents inode-reuse confusion.
                db.execute("DELETE FROM checkpoints WHERE source=?", (source,))
            retired.unlink()
            sync_directory(path.parent)
            with store.connect() as db:
                db.execute("DELETE FROM retired_wals WHERE source=?", (source,))
        finally:
            os.close(descriptor)


def rotate_committed(store: Store, path: Path) -> None:
    """Caller stops and joins writer first. Never discard an uncommitted byte."""
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status = os.fstat(descriptor)
        source = f"{path.resolve()}:{status.st_dev}:{status.st_ino}"
        if store.checkpoint(source) != status.st_size:
            raise ValueError("WAL has uncommitted records or a torn tail")
        retired = path.with_name(f"{path.name}.retired-{status.st_dev}-{status.st_ino}")
        if retired.exists():
            raise ValueError("retired WAL collision")
        path.rename(retired)
        sync_directory(path.parent)
    finally:
        os.close(descriptor)
    recover_retired(store, path)
