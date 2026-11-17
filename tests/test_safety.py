"""Link safety lists and the image guard's picture matching."""

import io

from PIL import Image, ImageDraw

from vectiq.cogs.linksafety import Blocklists, domains_in, listed, parse_list
from vectiq.imagecheck import Detector, dhash
from vectiq.stores.safety import hamming


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
