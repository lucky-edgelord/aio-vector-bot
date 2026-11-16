"""Rank and leaderboard images in a Vector-messenger look: near-black canvas, soft cards, one green accent.

Pure Pillow, no network. Everything is drawn at 2x and scaled down so edges stay smooth.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
SS = 2                                    # supersampling factor

BG = (11, 11, 12)
CARD = (21, 21, 23)
CARD_HI = (24, 30, 28)
LINE = (38, 38, 42)
TEXT = (242, 242, 243)
DIM = (140, 142, 148)
TRACK = (36, 36, 40)
ACCENT = (89, 252, 179)                   # Vector green
ACCENT_DK = (34, 160, 112)
MEDALS = {1: (245, 196, 81), 2: (196, 203, 214), 3: (208, 138, 84)}


@dataclass
class Entry:
    position: int
    name: str
    level: int
    xp: int
    into: int = 0                         # XP gained inside the current level
    span: int = 1                         # XP the current level needs in total
    messages: int = 0
    avatar: bytes | None = None
    ident: str = ""                       # stable id, used to colour the initials badge

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, self.into / self.span)) if self.span else 0.0


@lru_cache(maxsize=32)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    name = {"regular": "Inter-Regular.otf", "semi": "Inter-SemiBold.otf", "bold": "Inter-Bold.otf"}[weight]
    try:
        return ImageFont.truetype(str(FONTS / name), size * SS)
    except OSError:                       # the bundled font is missing: keep working with Pillow's default
        return ImageFont.load_default(size * SS)


def s(v: float) -> int:
    return int(round(v * SS))


def fit(draw: ImageDraw.ImageDraw, text: str, weight: str, size: int, max_w: int) -> str:
    f, limit = font(weight, size), s(max_w)
    if draw.textlength(text, font=f) <= limit:
        return text
    while text and draw.textlength(text + "…", font=f) > limit:
        text = text[:-1]
    return text + "…"


def text(draw, xy, value, weight, size, fill, anchor="la"):
    draw.text((s(xy[0]), s(xy[1])), value, font=font(weight, size), fill=fill, anchor=anchor)


def motif(draw, x, y, size=18, color=ACCENT, n=4):
    """The ◤◢ strip Vector's community names use, drawn as triangles."""
    for i in range(n):
        ox = x + i * size * 1.05
        if i % 2 == 0:
            pts = [(ox, y), (ox + size, y), (ox, y + size)]
        else:
            pts = [(ox + size, y), (ox + size, y + size), (ox, y + size)]
        draw.polygon([(s(a), s(b)) for a, b in pts], fill=color)


def rounded(draw, box, radius, fill=None, outline=None, width=1):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([s(x0), s(y0), s(x1), s(y1)], radius=s(radius), fill=fill, outline=outline, width=s(width))


def initials(name: str) -> str:
    words = [w for w in name.replace("…", " ").split() if w[:1].isalnum()]
    return ("".join(w[0] for w in words[:2]) or name[:1] or "?").upper()


def hue_colour(ident: str) -> tuple[int, int, int]:
    h = int(hashlib.sha256(ident.encode()).hexdigest()[:6], 16)
    palette = [(52, 120, 246), (160, 90, 230), (240, 120, 90), (60, 190, 170), (225, 170, 60), (220, 90, 150)]
    r, g, b = palette[h % len(palette)]
    return (r * 6 // 10, g * 6 // 10, b * 6 // 10)


def avatar_image(entry: Entry, size: int) -> Image.Image:
    px = s(size)
    img = None
    if entry.avatar:
        try:
            img = Image.open(io.BytesIO(entry.avatar)).convert("RGB")
            w, h = img.size
            side = min(w, h)
            img = img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2)).resize((px, px), Image.LANCZOS)
        except Exception:  # noqa: BLE001 - a broken image just falls back to initials
            img = None
    if img is None:
        img = Image.new("RGB", (px, px), hue_colour(entry.ident or entry.name))
        d = ImageDraw.Draw(img)
        d.text((px / 2, px / 2), initials(entry.name), font=font("bold", int(size * 0.42)), fill=(255, 255, 255), anchor="mm")
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, px - 1, px - 1], fill=255)
    out = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def paste_avatar(canvas: Image.Image, entry: Entry, x: float, y: float, size: float, ring=None, ring_w=3):
    if ring:
        d = ImageDraw.Draw(canvas)
        d.ellipse([s(x - ring_w - 2), s(y - ring_w - 2), s(x + size + ring_w + 2), s(y + size + ring_w + 2)],
                  outline=ring, width=s(ring_w))
    canvas.paste(avatar_image(entry, int(size)), (s(x), s(y)), avatar_image(entry, int(size)))


def bar(draw, x, y, w, h, progress, fill=ACCENT):
    rounded(draw, (x, y, x + w, y + h), h / 2, fill=TRACK)
    if progress > 0:
        rounded(draw, (x, y, x + max(h, w * progress), y + h), h / 2, fill=fill)


def finish(canvas: Image.Image, width: int, height: int) -> bytes:
    out = io.BytesIO()
    canvas.convert("RGB").resize((width, height), Image.LANCZOS).save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------------------------------------------------------------

def leaderboard_card(entries: list[Entry], *, community: str = "", title: str = "LEADERBOARD", page: int = 1) -> bytes:
    """A ranked list: position badge, avatar, name, level pill and a progress bar to the next level."""
    W, ROW, GAP, HEAD, FOOT = 960, 92, 12, 148, 56
    H = HEAD + len(entries) * (ROW + GAP) + FOOT
    canvas = Image.new("RGB", (s(W), s(H)), BG)
    d = ImageDraw.Draw(canvas)

    motif(d, 40, 38)
    text(d, (40, 70), title, "bold", 38, TEXT)
    text(d, (40, 116), (community or "Vectiq") + "  ·  by XP", "regular", 20, DIM)
    rounded(d, (W - 170, 52, W - 40, 92), 20, fill=CARD, outline=LINE)
    text(d, (W - 105, 72), f"PAGE {page}", "semi", 16, DIM, "mm")

    y = HEAD
    for e in entries:
        top = e.position == 1
        rounded(d, (28, y, W - 28, y + ROW), 26, fill=CARD_HI if top else CARD, outline=ACCENT_DK if top else LINE,
                width=2 if top else 1)
        # position badge
        medal = MEDALS.get(e.position)
        cx, cy = 80, y + ROW / 2
        if medal:
            d.ellipse([s(cx - 22), s(cy - 22), s(cx + 22), s(cy + 22)], fill=medal)
            text(d, (cx, cy + 1), str(e.position), "bold", 24, (20, 20, 22), "mm")
        else:
            d.ellipse([s(cx - 22), s(cy - 22), s(cx + 22), s(cy + 22)], fill=TRACK)
            text(d, (cx, cy + 1), str(e.position), "semi", 20, DIM, "mm")
        paste_avatar(canvas, e, 124, y + 15, 62, ring=medal or None, ring_w=3)
        name = fit(d, e.name, "semi", 26, 380)
        text(d, (208, y + 18), name, "semi", 26, TEXT)
        text(d, (208, y + 52), f"{e.xp:,} XP  ·  {e.messages:,} msgs", "regular", 17, DIM)
        bar(d, 208, y + ROW - 17, 400, 7, e.progress)
        # level pill
        rounded(d, (W - 232, y + 22, W - 52, y + ROW - 22), 24, fill=(18, 40, 32), outline=ACCENT_DK)
        text(d, (W - 142, y + ROW / 2 - 12), "LEVEL", "semi", 13, ACCENT_DK, "mm")
        text(d, (W - 142, y + ROW / 2 + 11), str(e.level), "bold", 28, ACCENT, "mm")
        y += ROW + GAP

    text(d, (W / 2, H - 28), "Vectiq  ·  chat to earn XP", "regular", 15, (90, 92, 98), "mm")
    return finish(canvas, W, H)


def rank_card(e: Entry, *, community: str = "") -> bytes:
    """One member's card: big avatar, level, rank and a progress bar."""
    W, H = 960, 316
    canvas = Image.new("RGB", (s(W), s(H)), BG)
    d = ImageDraw.Draw(canvas)
    rounded(d, (24, 24, W - 24, H - 24), 34, fill=CARD, outline=LINE)
    motif(d, W - 150, 46, 14, ACCENT_DK)

    paste_avatar(canvas, e, 62, 62, 176, ring=ACCENT, ring_w=4)
    text(d, (282, 66), fit(d, e.name, "bold", 40, 520), "bold", 40, TEXT)
    text(d, (282, 118), community or "Vectiq", "regular", 20, DIM)

    # stat chips
    chips = [("RANK", f"#{e.position}"), ("LEVEL", str(e.level)), ("MESSAGES", f"{e.messages:,}")]
    x = 282
    for label, value in chips:
        w = 150 if label != "MESSAGES" else 190
        rounded(d, (x, 154, x + w, 214), 20, fill=(18, 40, 32) if label == "LEVEL" else (28, 28, 31),
                outline=ACCENT_DK if label == "LEVEL" else LINE)
        text(d, (x + 18, 168), label, "semi", 12, ACCENT_DK if label == "LEVEL" else DIM)
        text(d, (x + 18, 186), value, "bold", 24, ACCENT if label == "LEVEL" else TEXT)
        x += w + 14

    bar(d, 282, 232, 600, 14, e.progress)
    text(d, (282, 266), f"{e.into:,} / {e.span:,} XP to level {e.level + 1}", "regular", 16, DIM)
    text(d, (882, 266), f"{e.xp:,} XP total", "semi", 16, TEXT, "ra")
    return finish(canvas, W, H)
