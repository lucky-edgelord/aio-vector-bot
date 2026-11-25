import random

import pytest

from vectiq.db.migrations import MIGRATIONS
from vectiq.stores import InsufficientFunds, level_for_xp, xp_for_level


async def test_migrations_apply_once(db):
    assert db.version == len(MIGRATIONS) == 11
    assert await db.migrate() == len(MIGRATIONS)


def test_level_curve_roundtrip():
    for level in range(40):
        assert level_for_xp(xp_for_level(level)) == level
        assert level_for_xp(xp_for_level(level + 1) - 1) == level


async def test_xp_cooldown_and_levelup(stores):
    s = stores.levels
    r, up = await s.award("g", "u", xp_min=100, xp_max=100, cooldown=60, now=1000)
    assert r.xp == 100 and up and r.level == 1
    assert await s.award("g", "u", xp_min=100, xp_max=100, cooldown=60, now=1030) is None
    r, _ = await s.award("g", "u", xp_min=100, xp_max=100, cooldown=60, now=1061)
    assert r.xp == 200 and (await s.rank("g", "u")).messages == 3


async def test_leaderboard_and_positions(stores):
    s = stores.levels
    for uid, xp in (("a", 50), ("b", 300), ("c", 120)):
        await s.add_xp("g", uid, xp)
    board = await s.leaderboard("g")
    assert [r.user_id for r in board] == ["b", "c", "a"] and (await s.rank("g", "a")).position == 3
    assert (await s.add_xp("g", "a", -999)).xp == 0


async def test_level_rewards_crud(stores):
    await stores.levels.set_reward("g", 5, "role1")
    await stores.levels.set_reward("g", 5, "role2")
    assert await stores.levels.rewards("g") == {5: "role2"}
    assert await stores.levels.remove_reward("g", 5) and not await stores.levels.remove_reward("g", 5)


async def test_wallet_never_goes_negative(stores):
    e = stores.economy
    assert await e.adjust("g", "u", 50, "t") == 50
    with pytest.raises(InsufficientFunds):
        await e.adjust("g", "u", -51, "t")
    assert (await e.wallet("g", "u")).balance == 50


async def test_transfer_is_atomic(stores):
    e = stores.economy
    await e.adjust("g", "a", 100, "seed")
    await e.transfer("g", "a", "b", 60)
    assert (await e.wallet("g", "a")).balance == 40 and (await e.wallet("g", "b")).balance == 60
    with pytest.raises(InsufficientFunds):
        await e.transfer("g", "a", "b", 41)
    assert (await e.wallet("g", "a")).balance == 40 and (await e.wallet("g", "b")).balance == 60
    with pytest.raises(ValueError):
        await e.transfer("g", "a", "a", 1)


async def test_bank_moves(stores):
    e = stores.economy
    await e.adjust("g", "u", 100, "seed")
    await e.deposit("g", "u", 70)
    w = await e.wallet("g", "u")
    assert (w.balance, w.bank) == (30, 70)
    with pytest.raises(InsufficientFunds):
        await e.withdraw("g", "u", 71)
    await e.withdraw("g", "u", 70)
    assert (await e.wallet("g", "u")).balance == 100


async def test_daily_streak(stores):
    e = stores.economy
    kw = dict(amount=200, bonus=25, cap=10)
    paid, streak = await e.claim_daily("g", "u", now=1_000_000, **kw)
    assert (paid, streak) == (200, 1)
    paid, wait = await e.claim_daily("g", "u", now=1_000_000 + 3600, **kw)
    assert paid is None and wait == 86400 - 3600
    assert await e.claim_daily("g", "u", now=1_000_000 + 90000, **kw) == (225, 2)
    assert await e.claim_daily("g", "u", now=1_000_000 + 90000 + 3 * 86400, **kw) == (200, 1)


async def test_work_cooldown(stores):
    e = stores.economy
    paid, _ = await e.claim_work("g", "u", low=50, high=50, cooldown=600, now=100)
    assert paid == 50
    assert (await e.claim_work("g", "u", low=50, high=50, cooldown=600, now=200))[0] is None


async def test_shop_purchase(stores):
    e = stores.economy
    await e.add_item("g", "VIP", 100, "gold", role_id="r", stock=1)
    with pytest.raises(InsufficientFunds):
        await e.buy("g", "u", "vip")
    await e.adjust("g", "u", 250, "seed")
    item = await e.buy("g", "u", "vip")
    assert item.role_id == "r" and (await e.wallet("g", "u")).balance == 150
    with pytest.raises(LookupError):
        await e.buy("g", "u", "VIP")
    with pytest.raises(KeyError):
        await e.buy("g", "u", "nothing")
    assert [(r["name"], r["quantity"]) for r in await e.inventory("g", "u")] == [("VIP", 1)]


async def test_moderation_cases(stores):
    m = stores.moderation
    w1 = await m.add("g", "u", "mod", "warn", "a")
    await m.add("g", "u", "mod", "warn", "b")
    await m.add("g", "u", "mod", "tempban", "c", expires_at=100)
    assert len(await m.warnings("g", "u")) == 2
    assert await m.deactivate("g", w1.id) and not await m.deactivate("g", w1.id)
    assert await m.clear_warnings("g", "u") == 1
    assert [c.action for c in await m.due_expiries(now=200)] == ["tempban"]
    assert await m.due_expiries(now=50) == []


async def test_settings_roundtrip(stores):
    s = stores.settings
    await s.set("g", "slowmode:c", 5)
    assert await s.get("g", "slowmode:c") == 5 and await s.get("g", "x", "d") == "d"
    await s.unset("g", "slowmode:c")
    assert await s.all("g") == {}


async def test_verification_flow(stores):
    v = stores.verification
    assert await v.attempt("g", "u", "1", 3) == "none"
    await v.start("g", "u")
    answer = (await stores.db.one("SELECT answer FROM verifications"))["answer"]
    assert await v.attempt("g", "u", "nope", 2) == "wrong"
    assert await v.attempt("g", "u", "nope", 2) == "locked"
    assert await v.attempt("g", "u", answer, 2) == "locked"
    await v.start("g", "u")
    answer = (await stores.db.one("SELECT answer FROM verifications"))["answer"]
    assert await v.attempt("g", "u", f" {answer} ", 3) == "ok" and await v.pending("g", "u") is None


async def test_role_menu(stores):
    m = stores.role_menus
    menu = await m.create("g", "c", "msg1", "Pick")
    await m.add_option(menu.id, "🎮", "role1", "Gamer")
    await m.add_option(menu.id, "🎮", "role2", "Gamer")
    assert await m.role_for("msg1", "🎮") == "role2" and await m.role_for("msg1", "🎨") is None
    assert await m.delete("g", menu.id) and await m.role_for("msg1", "🎮") is None


async def test_giveaway_draw_is_once_and_unique(stores):
    g = stores.giveaways
    gw = await g.create("g", "c", "host", "prize", 2, ends_at=10)
    for u in "abc":
        await g.enter(gw.id, u)
    assert not await g.enter(gw.id, "a")
    assert [x.id for x in await g.due(now=11)] == [gw.id]
    winners = await g.finish(gw.id, rng=random.Random(1))
    assert len(winners) == 2 and len(set(winners)) == 2
    assert await g.finish(gw.id) == [] and await g.due(now=11) == []


async def test_tickets(stores):
    t = stores.tickets
    one = await t.create("g", "u", "help")
    await t.set_channel(one.id, "chan")
    assert (await t.by_channel("chan")).id == one.id and await t.open_count("g", "u") == 1
    assert await t.claim(one.id, "staff") and not await t.claim(one.id, "other")
    await t.log(one.id, "u", "hello")
    assert [r["content"] for r in await t.transcript(one.id)] == ["hello"]
    assert await t.close(one.id, "staff") and not await t.close(one.id, "staff")
    assert await t.open_count("g", "u") == 0


async def test_game_stats_and_activity(stores):
    await stores.games.record("g", "u", "tictactoe", won=True)
    await stores.games.record("g", "u", "tictactoe", drawn=True)
    row = (await stores.games.for_user("g", "u"))[0]
    assert (row["played"], row["won"], row["drawn"]) == (2, 1, 1)
    await stores.activity.bump("g", "c1", messages=3, day="2026-01-01")
    await stores.activity.bump("g", "c1", messages=2, joins=1, day="2026-01-01")
    day = (await stores.activity.daily("g"))[0]
    assert (day["m"], day["j"]) == (5, 1)


async def test_closing_waits_for_a_running_query():
    """Closing while a query runs in a worker thread used to crash sqlite3 (seen as a rare segfault in the tests)."""
    import asyncio

    from vectiq.db import Database

    db = await Database(":memory:").connect()
    slow = asyncio.ensure_future(db.one(
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 2000000) SELECT count(*) FROM n"))
    await asyncio.sleep(0.01)
    await db.close()
    assert (await slow)[0] == 2000000
