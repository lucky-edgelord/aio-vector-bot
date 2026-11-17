"""Automod rules, link safety lists and the image guard's picture matching."""

import io

from PIL import Image, ImageDraw

from vectiq.cogs.automod import Rules
from vectiq.cogs.linksafety import Blocklists, domains_in, listed, parse_list
from vectiq.config import DEFAULTS
from vectiq.imagecheck import Detector, dhash
from vectiq.stores.safety import hamming


def rules(**over):
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS["automod"].items()}
    for k, v in over.items():
        cfg[k] = {**cfg.get(k, {}), **v}
    return Rules(cfg)


def test_automod_rules():
    r = rules(words={"enabled": True, "list": ["darn"]}, links={"enabled": True, "allow": ["github.com"]},
              zalgo={"enabled": True})
    assert r.check("hello there") is None
    assert r.check("THIS IS ALL SHOUTING TODAY")[0] == "caps"
    assert r.check("@a @b @c @d @e @f @g")[0] == "mentions"
    assert r.check("well darn it")[0] == "words" and r.check("darned") is None
    assert r.check("join https://discord.gg/abc")[0] == "invites"
    assert r.check("come to https://vectorapp.io/invite/xyz")[0] == "invites"
    assert r.check("see https://evil.example/x")[0] == "links"
    assert r.check("see https://docs.github.com/x") is None
    assert r.check("z̷̛̛̛̛̛̛̛̛a̷̛̛̛̛̛̛̛̛̛l̷̛̛̛̛̛̛̛̛̛g̷̛̛̛̛̛̛̛")[0] == "zalgo"
    assert r.check("look", filenames=["free.exe"])[0] == "files"
    assert r.check("look", filenames=["cat.png"]) is None


def test_automod_rules_switch_off_one_by_one():
    r = rules(caps={"enabled": False}, invites={"enabled": False})
    assert r.check("THIS IS ALL SHOUTING TODAY") is None
    assert r.check("https://discord.gg/abc") is None


def test_flood_and_duplicates():
    r = rules()
    key = ("g", "u")
    hits = [r.check(f"msg {i}", key=key, now=100 + i * 0.5) for i in range(8)]
    assert hits[-1] and hits[-1][0] == "flood"
    r = rules(flood={"enabled": False})
    hits = [r.check("same", key=key, now=100 + i * 5) for i in range(5)]
    assert hits[2] is None and hits[3][0] == "duplicates"   # 3 repeats are fine, the 4th goes
    assert rules(flood={"enabled": False}).check("same", key=("g", "other"), now=200) is None


def test_blocklist_parsing_and_matching(tmp_path):
    text = "# oisd\nbad.example\n0.0.0.0 tracker.test\n||ads.test^\n*.wild.test\n\n! comment\n"
    blocked = parse_list(text)
    assert blocked == {"bad.example", "tracker.test", "ads.test", "wild.test"}
    assert listed("cdn.bad.example", blocked) == "bad.example"
    assert listed("bad.example.org", blocked) is None
    assert domains_in("go to HTTPS://www.Bad.Example/x or ads.test, not me@") == ["bad.example", "ads.test"]
    lists = Blocklists(tmp_path)
    (tmp_path).mkdir(exist_ok=True)
    lists.path("https://list.test/a").write_text(text)
    lists.load(["https://list.test/a"], download=False, max_age=1e9)
    assert len(lists.domains) == 4 and lists.sources == {"https://list.test/a": 4}


def picture(seed: int, size=(320, 240)) -> Image.Image:
    img = Image.new("RGB", size, (seed * 40 % 255, 90, 160))
    d = ImageDraw.Draw(img)
    for i in range(6):
        x, y = (20 + i * 37 * seed) % 200, (30 + i * 29 * seed) % 150
        d.ellipse((x, y, x + 60 + i * 5, y + 50), fill=(255 - i * 30, i * 40, seed * 9 % 255))
    return img


def jpeg(img, quality=85) -> bytes:
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality)
    return out.getvalue()


def test_dhash_survives_resizing_and_recompression():
    a = picture(1)
    same = dhash(jpeg(a.resize((160, 120)), quality=40))
    assert hamming(dhash(jpeg(a)), same) <= 6
    assert hamming(dhash(jpeg(a)), dhash(jpeg(picture(5)))) > 12


async def test_image_blocklist_store(stores):
    a = dhash(jpeg(picture(1)))
    bid = await stores.image_blocks.add("g", a, "spam", "mod")
    near = dhash(jpeg(picture(1).resize((200, 150)), quality=50))
    hit = await stores.image_blocks.match("g", near, 6)
    assert hit and hit["id"] == bid
    assert await stores.image_blocks.match("other", near, 6) is None
    assert await stores.image_blocks.remove("g", bid) and await stores.image_blocks.match("g", near, 6) is None


async def test_detectors_off_and_unavailable():
    assert await Detector({"detector": "off"}).score(picture(1)) == (0.0, "off")
    import pytest

    from vectiq.imagecheck import DetectorUnavailable
    with pytest.raises(DetectorUnavailable):
        cfg = {"detector": "sightengine", "sightengine": {"user_env": "NOPE_U", "secret_env": "NOPE_S"}}
        await Detector(cfg).score(picture(1))
    with pytest.raises(DetectorUnavailable):
        await Detector({"detector": "http", "http": {}}).score(picture(1))
