"""Music cards: "Now playing" with cover art and a progress bar, and the queue. Same look as the rank cards."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter

from .cards import ACCENT, BG, CARD, DIM, LINE, SS, TEXT, finish, fit, font, hue_colour, motif, rounded, s, text


@dataclass
class CardTrack:
    title: str
    artist: str = ""
    duration: int = 0
    live: bool = False
    requester: str = ""
    cover: bytes | None = None
    ident: str = ""

    def length(self) -> str:
        return "LIVE" if self.live else (clock(self.duration) if self.duration else "–:––")


@dataclass
class PlayerState:
    position: float = 0.0
    paused: bool = False
    volume: int = 100
    loop: str = "off"
    filter: str = ""
    up_next: int = 0
    queue_seconds: int = 0
    next_title: str = ""
    extra: list[str] = field(default_factory=list)


def clock(seconds: float) -> str:
    sec = int(max(0, seconds))
    h, rem = divmod(sec, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02}:{sec:02}" if h else f"{m}:{sec:02}"


def cover_image(t: CardTrack, size: float, radius: float = 18) -> Image.Image:
    """The cover art cropped to a rounded square, or a coloured tile with a note when there is none."""
    px = s(size)
    img = None
    if t.cover:
        try:
            img = Image.open(io.BytesIO(t.cover)).convert("RGB")
            w, h = img.size
            side = min(w, h)                         # YouTube thumbnails are 16:9: take the middle square
            img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
            img = img.resize((px, px), Image.LANCZOS)
        except Exception:  # noqa: BLE001 - a broken picture falls back to the tile
            img = None
    if img is None:
        base = hue_colour(t.ident or t.title)
        img = Image.new("RGB", (px, px), base)
        d = ImageDraw.Draw(img)
        light = tuple(min(255, c + 90) for c in base)
        # a quaver: two heads, two stems and a beam
        u = px / 10
        d.ellipse([u * 2.6, u * 5.9, u * 4.6, u * 7.5], fill=light)
        d.ellipse([u * 5.6, u * 5.1, u * 7.6, u * 6.7], fill=light)
        d.rectangle([u * 4.15, u * 2.6, u * 4.6, u * 6.7], fill=light)
        d.rectangle([u * 7.15, u * 1.8, u * 7.6, u * 5.9], fill=light)
        d.polygon([(u * 4.15, u * 2.6), (u * 7.6, u * 1.8), (u * 7.6, u * 2.7), (u * 4.15, u * 3.5)], fill=light)
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, px - 1, px - 1], radius=s(radius), fill=255)
    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _backdrop(canvas: Image.Image, t: CardTrack, w: int, h: int) -> None:
    """A heavily blurred, darkened copy of the cover behind everything, like a phone's lock-screen player."""
    if not t.cover:
        return
    try:
        art = Image.open(io.BytesIO(t.cover)).convert("RGB").resize((s(w) // 8, s(h) // 8))
        art = art.filter(ImageFilter.GaussianBlur(6)).resize((s(w), s(h)), Image.LANCZOS)
        canvas.paste(Image.blend(art, Image.new("RGB", art.size, BG), 0.78), (0, 0))
    except Exception:  # noqa: BLE001
        pass


def _chip(draw, x: float, y: float, label: str, *, on: bool = False) -> float:
    f = font("semi", 14)
    w = draw.textlength(label, font=f) / SS + 22
    rounded(draw, (x, y, x + w, y + 28), 14, fill=(30, 52, 44) if on else (32, 32, 36))
    text(draw, (x + 11, y + 6), label, "semi", 14, ACCENT if on else DIM)
    return x + w + 8


def now_playing_card(t: CardTrack, st: PlayerState, *, community: str = "") -> bytes:
    w, h = 900, 300
    canvas = Image.new("RGB", (s(w), s(h)), BG)
    _backdrop(canvas, t, w, h)
    d = ImageDraw.Draw(canvas)
    cover = cover_image(t, 236)
    canvas.paste(cover, (s(32), s(32)), cover)

    x0, right = 296, w - 36
    motif(d, x0, 38, size=11, n=4)
    label = ("PAUSED" if st.paused else "NOW PLAYING") + (f"  ·  {community.upper()}" if community else "")
    text(d, (x0 + 56, 35), fit(d, label, "bold", 15, right - x0 - 56), "bold", 15, ACCENT)

    # title over up to two lines
    words, lines, cur = t.title.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font("bold", 32)) <= s(right - x0) or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    lines = [fit(d, ln, "bold", 32, right - x0) for ln in lines[:2]]
    y = 64
    for ln in lines:
        text(d, (x0, y), ln, "bold", 32, TEXT)
        y += 40
    if t.artist:
        text(d, (x0, y + 2), fit(d, t.artist, "regular", 19, right - x0), "regular", 19, DIM)

    # progress
    by = 214
    pos = min(st.position, t.duration) if t.duration else st.position
    rounded(d, (x0, by, right, by + 8), 4, fill=(48, 48, 54))
    if t.live:
        rounded(d, (x0, by, right, by + 8), 4, fill=(236, 72, 88))
        text(d, (x0, by + 16), clock(pos), "semi", 15, DIM)
        text(d, (right, by + 16), "● LIVE", "bold", 15, (236, 72, 88), anchor="ra")
    else:
        prog = max(0.0, min(1.0, pos / t.duration)) if t.duration else 0.0
        if prog > 0:
            rounded(d, (x0, by, x0 + max(8, (right - x0) * prog), by + 8), 4, fill=ACCENT)
        kx = x0 + (right - x0) * prog
        d.ellipse([s(kx - 8), s(by - 4), s(kx + 8), s(by + 12)], fill=TEXT)
        text(d, (x0, by + 16), clock(pos), "semi", 15, DIM)
        text(d, (right, by + 16), t.length(), "semi", 15, DIM, anchor="ra")

    # chips
    cx = x0
    cy = 262
    cx = _chip(d, cx, cy, f"Vol {st.volume}%")
    if st.loop != "off":
        cx = _chip(d, cx, cy, f"Loop {st.loop}", on=True)
    if st.filter:
        cx = _chip(d, cx, cy, st.filter, on=True)
    if st.up_next:
        cx = _chip(d, cx, cy, f"{st.up_next} up next")
    if t.requester and cx < right - 120:
        _chip(d, cx, cy, fit(d, f"by {t.requester}", "semi", 14, right - cx - 24))
    return finish(canvas, w, h)


def queue_card(current: CardTrack | None, st: PlayerState, rows: list[tuple[int, CardTrack]], *, page: int = 1,
               pages: int = 1, community: str = "") -> bytes:
    w = 900
    head_h = 150 if current else 84
    row_h = 58
    h = head_h + max(1, len(rows)) * row_h + 70
    canvas = Image.new("RGB", (s(w), s(h)), BG)
    d = ImageDraw.Draw(canvas)
    motif(d, 32, 30, size=12, n=4)
    text(d, (92, 26), "QUEUE" + (f"  ·  {community.upper()}" if community else ""), "bold", 18, TEXT)
    if pages > 1:
        text(d, (w - 32, 28), f"Page {page}/{pages}", "semi", 16, DIM, anchor="ra")

    y = 66
    if current:
        rounded(d, (24, y, w - 24, y + 70), 14, fill=(24, 30, 28), outline=(44, 80, 66), width=1)
        art = cover_image(current, 50, radius=10)
        canvas.paste(art, (s(36), s(y + 10)), art)
        text(d, (100, y + 12), "Paused" if st.paused else "Now playing", "semi", 13, ACCENT)
        text(d, (100, y + 32), fit(d, current.title, "bold", 19, 600), "bold", 19, TEXT)
        text(d, (w - 40, y + 26), f"{clock(st.position)} / {current.length()}", "semi", 16, DIM, anchor="ra")
        y += 84

    if not rows:
        text(d, (40, y + 18), "Nothing up next. Add songs with play.", "regular", 18, DIM)
    for i, (n, t) in enumerate(rows):
        ry = y + i * row_h
        if i % 2 == 0:
            rounded(d, (24, ry, w - 24, ry + row_h - 6), 12, fill=CARD)
        text(d, (52, ry + 15), str(n), "bold", 18, DIM, anchor="ma")
        art = cover_image(t, 38, radius=8)
        canvas.paste(art, (s(80), s(ry + 7)), art)
        text(d, (132, ry + 7), fit(d, t.title, "semi", 18, 560), "semi", 18, TEXT)
        sub = " · ".join(x for x in (t.artist, f"by {t.requester}" if t.requester else "") if x)
        text(d, (132, ry + 30), fit(d, sub, "regular", 14, 560), "regular", 14, DIM)
        text(d, (w - 40, ry + 16), t.length(), "semi", 16, DIM, anchor="ra")

    fy = h - 52
    d.line([s(24), s(fy), s(w - 24), s(fy)], fill=LINE, width=s(1))
    foot = f"{st.up_next} songs · {clock(st.queue_seconds)}" + (f" · loop {st.loop}" if st.loop != "off" else "")
    text(d, (32, fy + 16), foot, "semi", 16, DIM)
    if st.next_title:
        text(d, (w - 32, fy + 16), fit(d, f"Next: {st.next_title}", "semi", 16, 420), "semi", 16, DIM, anchor="ra")
    return finish(canvas, w, h)
