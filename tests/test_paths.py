from klop.paths import dedup


def test_dedup_returns_path_when_free(tmp_path):
    p = tmp_path / "a.jpg"
    assert dedup(p) == p


def test_dedup_suffixes_when_taken(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    assert dedup(tmp_path / "a.jpg") == tmp_path / "a-1.jpg"


def test_dedup_skips_multiple_collisions(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "a-1.jpg").write_bytes(b"x")
    assert dedup(tmp_path / "a.jpg") == tmp_path / "a-2.jpg"
