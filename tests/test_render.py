import io

from PIL import Image

from vectiq.render import Entry, leaderboard_card, rank_card


def png(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def entries(n=3):
    return [Entry(i + 1, f"member {i}", 10 - i, 1000 - i * 100, 50, 200, 100 + i, None, f"id{i}") for i in range(n)]


def test_leaderboard_is_a_png_sized_to_its_rows():
    short, tall = png(leaderboard_card(entries(2))), png(leaderboard_card(entries(8)))
    assert short.format == "PNG" and short.width == tall.width == 960 and tall.height > short.height


def test_rank_card_size():
    img = png(rank_card(entries(1)[0], community="Somewhere"))
    assert img.size == (960, 316)


def test_hostile_input_does_not_crash():
    nasty = [Entry(1, "x" * 500, 999, 10**9, 5, 0, 10**7, b"not an image", ""),
             Entry(2, "", 0, 0, 0, 1, 0, None, ""), Entry(3, "<b>&‮ rtl ✨ 日本語", 5, 1, -5, 10, 1, None, "z")]
    assert png(leaderboard_card(nasty)).width == 960
    assert png(rank_card(nasty[0])).width == 960


def test_progress_is_clamped():
    assert Entry(1, "a", 1, 1, into=500, span=100).progress == 1.0
    assert Entry(1, "a", 1, 1, into=-5, span=100).progress == 0.0
    assert Entry(1, "a", 1, 1, into=5, span=0).progress == 0.0


def test_a_real_avatar_is_used():
    base = Image.new("RGB", (64, 64), (255, 0, 0))
    buf = io.BytesIO()
    base.save(buf, "PNG")
    with_av = png(rank_card(Entry(1, "a", 1, 1, 1, 10, 1, buf.getvalue(), "a")))
    without = png(rank_card(Entry(1, "a", 1, 1, 1, 10, 1, None, "a")))
    assert with_av.getpixel((150, 150)) != without.getpixel((150, 150))


def test_embed_timestamp_goes_to_the_footer():
    from vectiq.utils.embeds import embed

    plain, stamped = embed("t", footer="Page 1"), embed("t", footer="Page 1", timestamp=True)
    assert "<t:" not in plain.to_markdown() and "<t:" in stamped.to_markdown(part="footer")
    assert "Page 1" in stamped.to_markdown(part="footer")


def test_rank_and_leaderboard_embeds_are_timestamped():
    import inspect

    from vectiq.cogs import leveling

    src = inspect.getsource(leveling.Leveling)
    assert src.count("timestamp=True") == 2          # the rank card embed and the leaderboard embed
