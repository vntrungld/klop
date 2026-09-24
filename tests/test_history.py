from klop.history import HistoryEntry, HistoryStore


def test_record_appends_and_entries_reads_back(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    e = store.record("file", "a.png", "/tmp/a.png", 1000, 400, backup_id="b1")
    assert e.saved_bytes == 600
    assert e.undone is False
    assert e.undoable is True
    got = store.entries()
    assert len(got) == 1
    assert got[0].name == "a.png"
    assert got[0].backup_id == "b1"


def test_clipboard_entry_is_view_only(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    e = store.record("clipboard", "Clipboard image", None, 500, 200)
    assert e.path is None
    assert e.backup_id is None
    assert e.undoable is False


def test_entries_newest_first(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    store.record("file", "first.png", "/tmp/first.png", 10, 5, backup_id="b1")
    store.record("file", "second.png", "/tmp/second.png", 10, 5, backup_id="b2")
    names = [e.name for e in store.entries()]
    assert names == ["second.png", "first.png"]


def test_ids_are_unique(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    ids = {store.record("file", f"f{i}.png", f"/tmp/f{i}.png", 10, 5, backup_id=f"b{i}").id for i in range(5)}
    assert len(ids) == 5


def test_ids_unique_across_instances(tmp_path):
    # Two separate HistoryStore instances (mirrors CLI + daemon as distinct
    # processes) must not collide on their first record.
    p = tmp_path / "h.jsonl"
    a = HistoryStore(p).record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    b = HistoryStore(p).record("file", "b.png", "/tmp/b.png", 10, 5, backup_id="b2")
    assert a.id != b.id


def test_prune_caps_at_max(tmp_path):
    from klop.history import _MAX

    store = HistoryStore(tmp_path / "h.jsonl")
    for i in range(_MAX + 5):
        store.record("file", f"f{i}.png", f"/tmp/f{i}.png", 10, 5, backup_id=f"b{i}")
    rows = store.entries()
    assert len(rows) == _MAX
    # newest kept, oldest pruned
    assert rows[0].name == f"f{_MAX + 4}.png"
    assert all(e.name != "f0.png" for e in rows)


def test_mark_undone_flips_matching_row(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    store.record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    store.record("file", "c.png", "/tmp/c.png", 10, 5, backup_id="b2")
    assert store.mark_undone("b1") is True
    by_id = {e.backup_id: e for e in store.entries()}
    assert by_id["b1"].undone is True
    assert by_id["b1"].undoable is False
    assert by_id["b2"].undone is False


def test_mark_undone_unknown_is_false(tmp_path):
    store = HistoryStore(tmp_path / "h.jsonl")
    store.record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    assert store.mark_undone("nope") is False


def test_mark_undone_missing_file_is_false(tmp_path):
    store = HistoryStore(tmp_path / "missing.jsonl")
    assert store.mark_undone("b1") is False


def test_entries_skips_corrupt_trailing_line(tmp_path):
    p = tmp_path / "h.jsonl"
    store = HistoryStore(p)
    store.record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")  # torn write
    rows = store.entries()
    assert len(rows) == 1
    assert rows[0].name == "a.png"


def test_to_dict_from_dict_roundtrip_and_missing_undone(tmp_path):
    e = HistoryEntry("id1", "file", "a.png", "/tmp/a.png", 10, 5, "b1", 123.0, undone=True)
    assert HistoryEntry.from_dict(e.to_dict()) == e
    d = e.to_dict()
    del d["undone"]
    assert HistoryEntry.from_dict(d).undone is False


def test_missing_file_reads_empty(tmp_path):
    assert HistoryStore(tmp_path / "nope.jsonl").entries() == []


def test_default_history_file_uses_env_override(monkeypatch, tmp_path):
    from klop.history import _default_history_file

    target = tmp_path / "custom.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(target))
    assert _default_history_file() == target


def test_default_history_file_falls_back_to_home(monkeypatch):
    from pathlib import Path

    from klop.history import _default_history_file

    monkeypatch.delenv("KLOP_HISTORY_FILE", raising=False)
    assert (
        _default_history_file()
        == Path.home() / ".local" / "share" / "klop" / "history.jsonl"
    )


def test_store_without_path_uses_env_default(monkeypatch, tmp_path):
    from klop.history import HistoryStore

    target = tmp_path / "envstore.jsonl"
    monkeypatch.setenv("KLOP_HISTORY_FILE", str(target))
    store = HistoryStore()  # no explicit path -> resolves via env
    store.record("file", "a.png", "/tmp/a.png", 10, 5, backup_id="b1")
    assert target.exists()
    assert store.entries()[0].name == "a.png"
