from clop_kde.format import human_size, percent_saved


def test_human_bytes():
    assert human_size(500) == "500B"


def test_human_kilobytes():
    assert human_size(2048) == "2.0KB"


def test_human_kilobytes_fractional():
    assert human_size(1536) == "1.5KB"


def test_human_megabytes():
    assert human_size(1048576) == "1.0MB"


def test_human_gigabytes():
    assert human_size(3 * 1024**3) == "3.0GB"


def test_percent_saved_typical():
    assert percent_saved(8579, 3431) == 60


def test_percent_saved_zero_original():
    assert percent_saved(0, 0) == 0


def test_percent_saved_no_reduction():
    assert percent_saved(1000, 1000) == 0
