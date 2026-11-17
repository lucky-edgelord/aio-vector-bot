"""Finding tracks with yt-dlp and streaming them through ffmpeg.

yt-dlp is imported the first time something is looked up, so the bot starts fast and runs without it when
music is off. Stream links expire, so they are resolved just before a track plays, not when it is queued.
"""

from __future__ import annotations

import array
import asyncio
import queue
import re
import shlex
import subprocess
import threading
from typing import Any

from .queue import Track

URL = re.compile(r"^https?://", re.IGNORECASE)

# ffmpeg audio filters. Names follow what people know from the big Discord music bots.
FILTERS: dict[str, str] = {
    "bassboost": "bass=g=10,dynaudnorm=f=200",
    "nightcore": "asetrate=48000*1.25,aresample=48000,atempo=1.0",
    "vaporwave": "asetrate=48000*0.8,aresample=48000,atempo=1.0",
    "slowed": "atempo=0.85",
    "speed": "atempo=1.25",
    "8d": "apulsator=hz=0.08",
    "karaoke": "stereotools=mlev=0.03",
    "treble": "treble=g=5",
    "soft": "lowpass=f=3000",
    "loud": "dynaudnorm=f=150:g=15",
    "mono": "pan=mono|c0=.5*c0+.5*c1",
}


class MusicUnavailable(RuntimeError):
    pass


def _ytdl(extra: dict | None = None, cookies: str = ""):
    try:
        import yt_dlp
    except ImportError as exc:
        raise MusicUnavailable('music needs yt-dlp: pip install "vectiq[music]"') from exc
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "default_search": "ytsearch",
            "format": "bestaudio[acodec=opus]/bestaudio/best", "skip_download": True, "extract_flat": False,
            "source_address": "0.0.0.0", "cachedir": False}
    if cookies:
        opts["cookiefile"] = cookies           # YouTube asks servers in data centres to sign in
    opts.update(extra or {})
    return yt_dlp.YoutubeDL(opts)


def _track(info: dict[str, Any], requester: str = "", requester_name: str = "") -> Track:
    url = info.get("webpage_url") or info.get("original_url") or info.get("url") or ""
    if not URL.match(url) and info.get("id") and (info.get("ie_key") or "").lower().startswith("youtube"):
        url = f"https://www.youtube.com/watch?v={info['id']}"
    thumbs = [t.get("url") for t in info.get("thumbnails") or [] if isinstance(t, dict) and t.get("url")]
    return Track(title=info.get("title") or url, url=url, duration=int(info.get("duration") or 0),
                 uploader=info.get("uploader") or info.get("channel") or info.get("artist") or "",
                 thumbnail=info.get("thumbnail") or (thumbs[-1] if thumbs else ""), requester=requester,
                 requester_name=requester_name, live=bool(info.get("is_live")))


YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/)([\w-]{11})")


def thumbnail_url(track: Track) -> str:
    if track.thumbnail:
        return track.thumbnail
    m = YT_ID.search(track.url)
    return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg" if m else ""


def fetch_bytes(url: str, limit: int = 4 * 1024 * 1024) -> bytes | None:
    """Blocking. A small download (cover art); None when it fails."""
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Vectiq"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read(limit)
    except Exception:  # noqa: BLE001
        return None


def search(query: str, *, limit: int = 1, playlist: bool = True, max_playlist: int = 100, site: str = "ytsearch",
           requester: str = "", requester_name: str = "", cookies: str = "") -> list[Track]:
    """Blocking. A link (video, playlist, SoundCloud, Bandcamp, direct audio...) or search words -> tracks.

    Searches and playlists are read "flat" (titles and links only), which is fast; the audio itself is looked up
    just before each track plays."""
    is_url = bool(URL.match(query))
    target = query if is_url else f"{site}{limit}:{query}"
    with _ytdl({"noplaylist": not playlist, "extract_flat": "in_playlist", "playlistend": max_playlist},
               cookies) as ydl:
        info = ydl.extract_info(target, download=False)
    if not info:
        return []
    entries = info.get("entries")
    if entries is None:
        return [_track(info, requester, requester_name)]
    out = []
    for e in entries:
        if e and len(out) < (max_playlist if is_url else limit):
            out.append(_track(e, requester, requester_name))
    return out


def stream_url(track: Track, cookies: str = "") -> tuple[str, dict[str, str]]:
    """Blocking. The direct audio link for a track (and any HTTP headers ffmpeg must send)."""
    with _ytdl(cookies=cookies) as ydl:
        info = ydl.extract_info(track.url, download=False)
    if info.get("entries"):
        info = next(e for e in info["entries"] if e)
    if not track.duration and info.get("duration"):
        track.duration = int(info["duration"])
    if not track.thumbnail and info.get("thumbnail"):
        track.thumbnail = info["thumbnail"]
    if not track.uploader:
        track.uploader = info.get("uploader") or info.get("channel") or ""
    if info.get("webpage_url") and "api.soundcloud.com" in track.url:
        track.url = info["webpage_url"]
    track.live = track.live or bool(info.get("is_live"))
    return info["url"], dict(info.get("http_headers") or {})


def ffmpeg_args(url: str, *, headers: dict | None = None, start: float = 0, volume: float = 1.0,
                filter_name: str = "", ffmpeg: str = "ffmpeg") -> list[str]:
    """The ffmpeg command that turns ``url`` into 48 kHz mono 16-bit PCM on stdout."""
    args = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if URL.match(url):
        args += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]
    if headers:
        args += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    if start > 0:
        args += ["-ss", f"{start:.2f}"]
    args += ["-i", url, "-vn"]
    chain = [FILTERS[filter_name]] if filter_name in FILTERS else []
    if abs(volume - 1.0) > 1e-3:
        chain.append(f"volume={volume:.2f}")
    if chain:
        args += ["-af", ",".join(chain)]
    return args + ["-f", "s16le", "-ar", "48000", "-ac", "1", "pipe:1"]


def scale(pcm: bytes, volume: float) -> bytes:
    """Change the loudness of 16-bit PCM (clipped, never wrapped)."""
    if abs(volume - 1.0) < 1e-3:
        return pcm
    a = array.array("h", pcm)
    a = array.array("h", [max(-32768, min(32767, int(x * volume))) for x in a])
    return a.tobytes()


class FFmpegStream:
    """An AudioSource that streams through an ffmpeg process instead of decoding the whole file into memory.

    A reader thread keeps a few seconds of audio buffered, so the voice player (which calls ``read`` on the
    event loop) never waits on the network unless the stream really stalls."""

    FRAME_BYTES = 1920          # 20 ms of 48 kHz mono s16le
    BUFFER_FRAMES = 500         # 10 s
    PREBUFFER_FRAMES = 50       # 1 s before playback starts

    def __init__(self, args: list[str], start: float = 0.0):
        self.args = args
        self.proc: subprocess.Popen | None = None
        self.frames = 0
        self.start = start
        self._buf: queue.Queue[bytes] = queue.Queue(self.BUFFER_FRAMES)
        self._done = threading.Event()
        self.volume = 1.0                       # live: changing it takes effect on the next frame

    @property
    def position(self) -> float:
        """Seconds into the track."""
        return self.start + self.frames * 0.02

    def _pump(self) -> None:
        proc = self.proc
        try:
            while proc is not None and proc.stdout is not None:
                data = proc.stdout.read(self.FRAME_BYTES)
                if len(data) < self.FRAME_BYTES:
                    break
                while not self._done.is_set():
                    try:
                        self._buf.put(data, timeout=0.5)
                        break
                    except queue.Full:
                        continue
                if self._done.is_set():
                    break
        finally:
            self._done.set()

    async def load(self) -> None:
        def spawn():
            return subprocess.Popen(self.args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL)
        self.proc = await asyncio.to_thread(spawn)
        threading.Thread(target=self._pump, name="vectiq-music-ffmpeg", daemon=True).start()
        for _ in range(100):                     # up to 10 s for the first second of audio
            if self._buf.qsize() >= self.PREBUFFER_FRAMES or self._done.is_set():
                break
            await asyncio.sleep(0.1)

    def read(self) -> bytes:
        while True:
            try:
                data = self._buf.get(timeout=0.25)
                self.frames += 1
                return scale(data, self.volume)
            except queue.Empty:
                if self._done.is_set() and self._buf.empty():
                    return b""

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        self._done.set()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            try:
                self.proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        self.proc = None

    def __repr__(self) -> str:
        return f"<FFmpegStream {shlex.join(self.args[:3])}...>"
