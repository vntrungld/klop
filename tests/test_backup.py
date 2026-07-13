import json
from pathlib import Path

import pytest

from clop_kde.backup import BackupStore


def test_backup_then_restore_roundtrip(tmp_path):
    original = tmp_path / "photo.png"
    original.write_bytes(b"ORIGINAL-BYTES")
    store = BackupStore(tmp_path / "backups")

    backup_id = store.backup(original)
    # Simulate the optimizer overwriting the original.
    original.write_bytes(b"OPTIMIZED-SMALLER")

    restored = store.restore(backup_id)
    assert restored == original
    assert original.read_bytes() == b"ORIGINAL-BYTES"


def test_backup_writes_meta(tmp_path):
    original = tmp_path / "photo.png"
    original.write_bytes(b"X")
    store = BackupStore(tmp_path / "backups")
    backup_id = store.backup(original)

    meta = json.loads((tmp_path / "backups" / backup_id / "meta.json").read_text())
    assert meta["original_path"] == str(original)


def test_restore_unknown_id_raises(tmp_path):
    store = BackupStore(tmp_path / "backups")
    with pytest.raises(KeyError):
        store.restore("does-not-exist")


def test_prune_by_age(tmp_path):
    original = tmp_path / "a.png"
    original.write_bytes(b"data")
    store = BackupStore(tmp_path / "backups")
    bid = store.backup(original)

    # now is far in the future so the backup is older than max_age_days.
    future = 10**12  # seconds; way past the 1970-based backup timestamp
    removed = store.prune(max_age_days=1, max_bytes=10**9, now=future)
    assert removed == 1
    assert not (tmp_path / "backups" / bid).exists()


def test_prune_by_size_keeps_newest(tmp_path):
    store = BackupStore(tmp_path / "backups")
    ids = []
    for i in range(3):
        f = tmp_path / f"f{i}.bin"
        f.write_bytes(b"Z" * 1000)
        ids.append(store.backup(f))

    # Budget fits only one ~1000-byte backup; oldest two removed.
    removed = store.prune(max_age_days=9999, max_bytes=1500, now=None)
    assert removed == 2
    assert (tmp_path / "backups" / ids[-1]).exists()
    assert not (tmp_path / "backups" / ids[0]).exists()
