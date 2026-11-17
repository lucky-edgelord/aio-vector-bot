"""The queue: pure logic, no audio, so every rule is easy to test."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

LOOP_MODES = ("off", "track", "queue")


@dataclass
class Track:
    title: str
    url: str                       # the page (YouTube, SoundCloud...), or a direct audio link
    duration: int = 0              # seconds; 0 = unknown or live
    uploader: str = ""
    thumbnail: str = ""
    requester: str = ""            # member id
    requester_name: str = ""
    live: bool = False

    def length(self) -> str:
        return "live" if self.live else (clock(self.duration) if self.duration else "?")


def clock(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def parse_time(text: str) -> int:
    """'90', '1:30', '1:02:03', '1m30s', '2m' -> seconds. Raises ValueError."""
    text = text.strip().lower()
    if ":" in text:
        total = 0
        for part in text.split(":"):
            total = total * 60 + int(part)
        return total
    if text.isdigit():
        return int(text)
    total, num = 0, ""
    for ch in text:
        if ch.isdigit():
            num += ch
        elif ch in "hms" and num:
            total += int(num) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
        else:
            raise ValueError(text)
    if num:
        raise ValueError(text)
    return total


@dataclass
class Queue:
    max_size: int = 500
    tracks: deque[Track] = field(default_factory=deque)
    history: deque[Track] = field(default_factory=lambda: deque(maxlen=50))
    current: Track | None = None
    loop: str = "off"

    def __len__(self) -> int:
        return len(self.tracks)

    def add(self, tracks: list[Track], *, front: bool = False) -> int:
        """Add tracks (at the end, or next up). Returns how many fit."""
        room = max(0, self.max_size - len(self.tracks))
        tracks = tracks[:room]
        if front:
            self.tracks.extendleft(reversed(tracks))
        else:
            self.tracks.extend(tracks)
        return len(tracks)

    def advance(self, *, skipped: bool = False) -> Track | None:
        """Move to the next track and return it. Track loop repeats unless the track was skipped."""
        prev = self.current
        if prev is not None:
            if self.loop == "track" and not skipped:
                return prev
            self.history.append(prev)
            if self.loop == "queue":
                self.tracks.append(prev)
        self.current = self.tracks.popleft() if self.tracks else None
        return self.current

    def back(self) -> Track | None:
        """Go back to the previous track (the current one goes to the front of the queue)."""
        if not self.history:
            return None
        if self.current is not None:
            self.tracks.appendleft(self.current)
        self.current = None
        self.tracks.appendleft(self.history.pop())
        return self.tracks[0]

    def skip_to(self, position: int) -> None:
        """Drop everything before ``position`` (1 = next up), so it plays next."""
        if not 1 <= position <= len(self.tracks):
            raise IndexError(position)
        for _ in range(position - 1):
            t = self.tracks.popleft()
            if self.loop == "queue":
                self.tracks.append(t)

    def remove(self, position: int) -> Track:
        if not 1 <= position <= len(self.tracks):
            raise IndexError(position)
        t = self.tracks[position - 1]
        del self.tracks[position - 1]
        return t

    def move(self, src: int, dest: int) -> Track:
        if not (1 <= src <= len(self.tracks) and 1 <= dest <= len(self.tracks)):
            raise IndexError((src, dest))
        t = self.remove(src)
        self.tracks.insert(dest - 1, t)
        return t

    def shuffle(self, rng: random.Random | None = None) -> None:
        items = list(self.tracks)
        (rng or random).shuffle(items)
        self.tracks = deque(items)

    def clear(self) -> int:
        n = len(self.tracks)
        self.tracks.clear()
        return n

    def dedupe(self) -> int:
        seen, out = set(), deque()
        for t in self.tracks:
            if t.url not in seen:
                seen.add(t.url)
                out.append(t)
        removed = len(self.tracks) - len(out)
        self.tracks = out
        return removed

    def remove_by(self, requester: str) -> int:
        before = len(self.tracks)
        self.tracks = deque(t for t in self.tracks if t.requester != requester)
        return before - len(self.tracks)

    def total_seconds(self) -> int:
        return sum(t.duration for t in self.tracks)

    def page(self, n: int, size: int = 10) -> list[tuple[int, Track]]:
        start = (n - 1) * size
        return [(start + i + 1, t) for i, t in enumerate(list(self.tracks)[start:start + size])]
