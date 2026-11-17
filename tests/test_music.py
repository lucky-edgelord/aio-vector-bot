"""Music: the queue rules, time parsing, the ffmpeg command and the streaming source."""

import random
import shutil
import subprocess

import pytest

from vectiq.music.queue import Queue, Track, clock, parse_time
from vectiq.music.sources import FILTERS, FFmpegStream, ffmpeg_args, scale


def tracks(n):
    return [Track(f"t{i}", f"https://x.test/{i}", duration=60, requester=f"u{i % 2}") for i in range(1, n + 1)]


def test_queue_order_loops_and_history():
    q = Queue()
    q.add(tracks(3))
    assert q.advance().title == "t1" and len(q) == 2
    q.loop = "track"
    assert q.advance().title == "t1"                      # track loop repeats...
    assert q.advance(skipped=True).title == "t2"          # ...unless skipped
    q.loop = "queue"
    assert q.advance().title == "t3" and [t.title for t in q.tracks] == ["t2"]
    q.loop = "off"
    assert q.back().title == "t2" and q.advance().title == "t2"


def test_queue_editing():
    q = Queue(max_size=5)
    assert q.add(tracks(7)) == 5
    q.move(5, 1)
    assert [t.title for t in q.tracks][:2] == ["t5", "t1"]
    assert q.remove(1).title == "t5"
    q.skip_to(3)
    assert q.tracks[0].title == "t3"
    q.add([Track("dup", "https://x.test/3")], front=True)
    assert q.dedupe() == 1 and [t.title for t in q.tracks] == ["dup", "t4"]
    assert q.remove_by("u0") == 1 and [t.title for t in q.tracks] == ["dup"]
    q.add(tracks(3))
    q.shuffle(random.Random(1))
    assert sorted(t.title for t in q.tracks) == ["dup", "t1", "t2", "t3"]
    assert q.clear() == 4 and len(q) == 0
    with pytest.raises(IndexError):
        q.remove(1)


def test_pages_and_totals():
    q = Queue()
    q.add(tracks(23))
    assert len(q.page(3)) == 3 and q.page(3)[0][0] == 21
    assert q.total_seconds() == 23 * 60 and clock(3725) == "1:02:05" and clock(65) == "1:05"


def test_parse_time():
    assert parse_time("90") == 90 and parse_time("1:30") == 90 and parse_time("1:02:03") == 3723
    assert parse_time("1m30s") == 90 and parse_time("2h") == 7200
    for bad in ("abc", "5x", "1m30"):
        with pytest.raises(ValueError):
            parse_time(bad)


def test_ffmpeg_command():
    args = ffmpeg_args("https://cdn.test/a", headers={"User-Agent": "x"}, start=12.5, filter_name="nightcore")
    assert "-reconnect" in args and args[args.index("-ss") + 1] == "12.50"
    assert args[args.index("-af") + 1] == FILTERS["nightcore"]
    assert args[-6:] == ["-f", "s16le", "-ar", "48000", "-ac", "1", "pipe:1"][-6:]
    assert "-af" not in ffmpeg_args("/tmp/a.mp3")


def test_volume_scaling_clips():
    import array

    pcm = array.array("h", [100, -20000, 30000]).tobytes()
    assert array.array("h", scale(pcm, 2.0)).tolist() == [200, -32768, 32767]
    assert scale(pcm, 1.0) is pcm


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
async def test_stream_reads_frames_and_tracks_position(tmp_path):
    src = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(src)],
                   check=True)
    s = FFmpegStream(ffmpeg_args(str(src), start=0.5), start=0.5)
    await s.load()
    n = 0
    while s.read():
        n += 1
    s.cleanup()
    assert 70 <= n <= 80 and abs(s.position - 2.0) < 0.1
