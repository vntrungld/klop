import shutil
import subprocess

import pytest

from klop.ffprogress import parse_duration, parse_out_time, progress_command, run_ffmpeg


def test_progress_command_puts_progress_flags_after_the_binary():
    assert progress_command(["ffmpeg", "-y", "-i", "in.mkv", "out.mp4"]) == [
        "ffmpeg", "-progress", "pipe:1", "-nostats", "-y", "-i", "in.mkv", "out.mp4",
    ]


def test_parse_duration_reads_the_banner_line():
    assert parse_duration("  Duration: 01:02:03.50, start: 0.000000, bitrate: 1 kb/s") == 3723.5
    assert parse_duration("Input #0, matroska,webm, from 'a.mkv':") is None


def test_parse_out_time_reads_microseconds():
    assert parse_out_time("out_time_us=2500000\n") == 2.5
    assert parse_out_time("out_time_us=N/A") is None
    assert parse_out_time("out_time_ms=2500000") is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_run_ffmpeg_reports_progress_on_a_real_encode(tmp_path):
    src = tmp_path / "in.mkv"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=25",
         "-c:v", "libx264", "-preset", "ultrafast", str(src)],
        check=True,
    )
    seen = []
    code = run_ffmpeg(
        ["ffmpeg", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "ultrafast",
         str(tmp_path / "out.mp4")],
        seen.append,
    )

    assert code == 0
    assert seen and all(0.0 <= f <= 1.0 for f in seen)
    assert seen == sorted(seen)
    assert seen[-1] > 0.9
