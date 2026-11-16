"""The referee cog end to end, with a fake Mini App session instead of the network."""

import json
from types import SimpleNamespace

import pytest

from vectiq.cogs.games import Games
from vectiq.config import Config
from vectiq.db import Database
from vectiq.games import Player, create_game
from vectiq.stores import Stores

G = "guild1"


class FakeSession:
    def __init__(self):
        self.sent = []
        self.channel = SimpleNamespace(community=SimpleNamespace(id=G))
        self.app = SimpleNamespace(message_id="msg1")

    async def send_json(self, obj):
        self.sent.append(obj)


def event(msg, sender="npubA", verified=True, name="Ann"):
    author = SimpleNamespace(display_name=name, name=name, id=sender)
    return SimpleNamespace(json=lambda: msg, verified_sender=sender if verified else None, direct=verified,
                           peer=SimpleNamespace(npub=sender), author=author if verified else None)


@pytest.fixture
async def rig(tmp_path):
    cfg = Config.load("config.yaml", env={"VECTIQ_DATA_DIR": str(tmp_path)})
    db = await Database(":memory:").connect()
    stores = Stores(db)
    bot = SimpleNamespace(config=cfg, stores=stores, get_guild=lambda _id: None, get_user=lambda _id: None,
                          emit=lambda *a, **k: None)
    cog = Games(bot)
    yield cog, stores, FakeSession(), cfg
    await db.close()


async def play(cog, session, game, *events):
    for ev in events:
        await cog._on_data(session, game, G, ev)


async def test_a_won_game_pays_coins_and_records_stats(rig):
    cog, stores, session, cfg = rig
    game = create_game("tictactoe", _bank(cog), cfg["games"])
    moves = [("npubA", "Ann", 0), ("npubB", "Bob", 3), ("npubA", "Ann", 1), ("npubB", "Bob", 4), ("npubA", "Ann", 2)]
    await play(cog, session, game, event({"t": "join", "addr": "a"}, "npubA", name="Ann"),
               event({"t": "join", "addr": "b"}, "npubB", name="Bob"))
    for npub, name, i in moves:
        await play(cog, session, game, event({"t": "move", "i": i, "addr": npub}, npub, name=name))
    last = session.sent[-1]
    assert last["winner"] == "X" and last["line"] == [0, 1, 2]
    start = cfg["economy"]["start_balance"]
    assert (await stores.economy.wallet(G, "npubA", start=start)).balance == start + cfg["games"]["winner_coins"]
    assert (await stores.economy.wallet(G, "npubB", start=start)).balance == start
    won = {r["user_id"]: r["won"] for r in await stores.db.all("SELECT user_id, won FROM game_stats")}
    assert won == {"npubA": 1, "npubB": 0}


def _bank(cog):
    from vectiq.cogs.games import GameBank

    return GameBank(cog.bot.stores.economy, G, cog.cfg.get("economy.start_balance", 0))


async def test_unverified_players_are_asked_to_retry_not_trusted(rig):
    cog, _stores, session, cfg = rig
    game = create_game("tictactoe", _bank(cog), cfg["games"])
    await play(cog, session, game, event({"t": "join", "addr": "a"}, "npubA", verified=False))
    assert session.sent[-1]["retry"] is True and game.seats["X"] is None
    await play(cog, session, game, event({"t": "hello", "addr": "a"}, "npubA", verified=False))
    assert session.sent[-1]["t"] == "state"                       # watching is always allowed


async def test_allow_unverified_is_a_testing_switch(rig):
    cog, _stores, session, cfg = rig
    cfg.data["games"]["allow_unverified"] = True
    game = create_game("tictactoe", _bank(cog), cfg["games"])
    await play(cog, session, game, event({"t": "join", "addr": "a"}, "npubA", verified=False))
    assert game.seats["X"].npub == "npubA"


async def test_slots_spin_moves_the_real_wallet(rig):
    cog, stores, session, cfg = rig
    game = create_game("slots", _bank(cog), cfg["games"])
    start = cfg["economy"]["start_balance"]
    await play(cog, session, game, event({"t": "spin", "bet": 50, "addr": "a"}, "npubA"))
    state = session.sent[-1]
    balance = (await stores.economy.wallet(G, "npubA", start=start)).balance
    assert state["balance"] == balance == start - 50 + state["won"]
    assert (await stores.db.one("SELECT played FROM game_stats WHERE game='slots'"))["played"] == 1


async def test_garbage_and_hostile_frames_are_survivable(rig):
    cog, _stores, session, cfg = rig
    game = create_game("connect4", _bank(cog), cfg["games"])
    bad = SimpleNamespace(json=lambda: (_ for _ in ()).throw(ValueError()), verified_sender="x", direct=True,
                          peer=SimpleNamespace(npub="x"), author=None)
    await cog._on_data(session, game, G, bad)                                    # not JSON
    await play(cog, session, game, event(["not", "a", "dict"]), event({"t": "move", "col": "'; DROP TABLE wallets;--"}),
               event({"t": "nonsense", "addr": "x" * 5000}))
    # the non-JSON and non-object frames are dropped silently; the two real-but-wrong messages get an error back
    assert all(m["t"] == "error" for m in session.sent) and len(session.sent) == 2
    assert json.dumps(session.sent)                                              # still serialisable


async def test_trivia_pays_by_correct_answers(rig):
    cog, stores, session, cfg = rig
    game = create_game("trivia", _bank(cog), cfg["games"])
    out = await game.handle(Player("npubA", "Ann", "a"), {"t": "join"})
    assert out.error is None
    await cog._settle(game, G, SimpleNamespace(player=SimpleNamespace(npub="npubA", label="Ann"), coins=30, won=True,
                                               drawn=False, score=3, note="3/8 correct"))
    assert (await stores.economy.wallet(G, "npubA", start=cfg["economy"]["start_balance"])).balance == \
        cfg["economy"]["start_balance"] + 30
