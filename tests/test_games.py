import random

import pytest

from vectiq.games import GAMES, Player, create_game, packager
from vectiq.games.connect4 import Connect4, find_four
from vectiq.games.slots import SYMBOLS, Slots, payout
from vectiq.games.tictactoe import TicTacToe
from vectiq.games.trivia import ANSWER_SECONDS, ROUNDS, Trivia

A, B, C = Player("a", "Ann", "addr-a"), Player("b", "Bob", "addr-b"), Player("c", "Cy", "addr-c")


async def seat(game):
    await game.handle(A, {"t": "join"})
    await game.handle(B, {"t": "join"})


async def test_ttt_full_game_x_wins(bank, settings):
    g = TicTacToe(bank, settings)
    await seat(g)
    for who, i in ((A, 0), (B, 3), (A, 1), (B, 4)):
        assert (await g.handle(who, {"t": "move", "i": i})).error is None
    up = await g.handle(A, {"t": "move", "i": 2})
    assert up.state["winner"] == "X" and up.state["line"] == [0, 1, 2]
    by = {o.player.npub: o for o in up.outcomes}
    assert by["a"].won and by["a"].coins == 50 and not by["b"].won and by["b"].coins == 0


async def test_ttt_rules(bank, settings):
    g = TicTacToe(bank, settings)
    assert (await g.handle(A, {"t": "move", "i": 0})).error                        # no seat
    await g.handle(A, {"t": "join"})
    assert "opponent" in (await g.handle(A, {"t": "move", "i": 0})).error
    await g.handle(B, {"t": "join"})
    assert "Both seats" in (await g.handle(C, {"t": "join"})).error
    assert "Not your turn" in (await g.handle(B, {"t": "move", "i": 0})).error
    assert (await g.handle(A, {"t": "move", "i": 4})).error is None
    assert "taken" in (await g.handle(B, {"t": "move", "i": 4})).error
    for bad in (-1, 9, "1", None, 1.5):
        assert (await g.handle(B, {"t": "move", "i": bad})).error
    assert (await g.handle(C, {"t": "move", "i": 0})).error                        # spectator


async def test_ttt_draw_and_rematch(bank, settings):
    g = TicTacToe(bank, settings)
    await seat(g)
    order = [(A, 0), (B, 1), (A, 2), (B, 4), (A, 3), (B, 5), (A, 7), (B, 6), (A, 8)]
    up = None
    for who, i in order:
        up = await g.handle(who, {"t": "move", "i": i})
    assert up.state["winner"] == "draw" and all(o.drawn and o.coins == 10 for o in up.outcomes)
    assert (await g.handle(A, {"t": "move", "i": 0})).error
    again = await g.handle(B, {"t": "rematch"})
    assert again.state["board"] == [""] * 9 and again.state["winner"] is None and g.turn == "X"


async def test_c4_gravity_and_win(bank, settings):
    g = Connect4(bank, settings)
    await seat(g)
    for _ in range(3):
        await g.handle(A, {"t": "move", "col": 0})
        await g.handle(B, {"t": "move", "col": 1})
    assert g.board[5][0] == "R" and g.board[3][0] == "R"
    up = await g.handle(A, {"t": "move", "col": 0})
    assert up.state["winner"] == "R" and len(up.state["line"]) == 4 and up.outcomes


async def test_c4_column_full_and_bounds(bank, settings):
    g = Connect4(bank, settings)
    await seat(g)
    for k in range(6):
        who = A if k % 2 == 0 else B
        await g.handle(who, {"t": "move", "col": 0})
    assert "full" in (await g.handle(A, {"t": "move", "col": 0})).error
    assert (await g.handle(A, {"t": "move", "col": 7})).error


def test_find_four_directions():
    def empty():
        return [[""] * 7 for _ in range(6)]
    b = empty()
    for i in range(4):
        b[5 - i][i] = "R"
    assert find_four(b, "R") and not find_four(b, "Y")
    b = empty()
    for i in range(4):
        b[5][3 - i] = "Y"
    assert find_four(b, "Y")


async def test_trivia_scoring_and_payout(bank, settings):
    now = [1000.0]
    g = Trivia(bank, settings, rng=random.Random(3), clock=lambda: now[0])
    for p in (A, B):
        await g.handle(p, {"t": "join"})
    assert (await g.handle(B, {"t": "start"})).error                               # only host
    await g.handle(A, {"t": "start"})
    for _ in range(ROUNDS):
        right = g.current["answer"]
        wrong = (right + 1) % 4
        await g.handle(A, {"t": "answer", "i": right})                            # instant, full bonus
        up = await g.handle(B, {"t": "answer", "i": wrong})
        assert up.state["phase"] == "reveal" and up.state["answer"] == right
        now[0] += 5
        assert (await g.tick(now[0])).state["phase"] in ("question", "done")
    assert g.finished and g.scores["a"] == ROUNDS * 200 and g.scores["b"] == 0
    out = {o.player.npub: o for o in g.outcomes()}
    assert out["a"].won and out["a"].coins == ROUNDS * 10 and not out["b"].won and out["b"].coins == 0


async def test_trivia_timeout_and_double_answer(bank, settings):
    now = [0.0]
    g = Trivia(bank, settings, rng=random.Random(1), clock=lambda: now[0])
    await g.handle(A, {"t": "join"})
    await g.handle(B, {"t": "join"})
    await g.handle(A, {"t": "start"})
    assert (await g.handle(C, {"t": "answer", "i": 0})).error                      # not a player
    assert "Pick" in (await g.handle(A, {"t": "answer", "i": 9})).error            # out of range
    assert (await g.handle(A, {"t": "answer", "i": 0})).error is None
    assert "Already" in (await g.handle(A, {"t": "answer", "i": 1})).error         # only one answer
    assert await g.tick(now[0] + 1) is None                                        # B still has time
    now[0] += ANSWER_SECONDS + 1
    assert (await g.tick(now[0])).state["phase"] == "reveal"                       # time ran out


async def test_trivia_hides_answer_until_reveal(bank, settings):
    g = Trivia(bank, settings, rng=random.Random(2), clock=lambda: 0.0)
    await g.handle(A, {"t": "join"})
    await g.handle(A, {"t": "start"})
    assert "answer" not in g.state() and "options" in g.state()


async def test_trivia_late_join_refused(bank, settings):
    g = Trivia(bank, settings, rng=random.Random(2), clock=lambda: 0.0)
    await g.handle(A, {"t": "join"})
    await g.handle(A, {"t": "start"})
    assert (await g.handle(B, {"t": "join"})).error


def test_slots_payouts():
    assert payout(["🍒"] * 3, 10) == 100 and payout(["💎"] * 3, 10) == 300
    assert payout(["🍒", "🍒", "🍋"], 10) == 12 and payout(["🍒", "🍋", "🔔"], 10) == 0


async def test_slots_spin_moves_real_coins(bank, settings):
    g = Slots(bank, settings, rng=random.Random(5))
    up = await g.handle(A, {"t": "spin", "bet": 100})
    assert up.state["balance"] == 500 - 100 + up.state["won"] == bank.b["a"] and up.state["for"] == "addr-a"
    assert all(r in SYMBOLS for r in up.state["reels"]) and g.state()["feed"][0]["name"] == "Ann"


@pytest.mark.parametrize("bet", [0, -5, 1001, "5", None, 2.5, True * 0])
async def test_slots_bad_bets(bank, settings, bet):
    g = Slots(bank, settings)
    assert (await g.handle(A, {"t": "spin", "bet": bet})).error and bank.b["a"] == 500


async def test_slots_cannot_overspend(bank, settings):
    g = Slots(bank, settings)
    assert "enough" in (await g.handle(A, {"t": "spin", "bet": 900})).error and bank.b["a"] == 500


def test_slots_house_edge():
    rng, bank_total = random.Random(0), 0
    for _ in range(100_000):
        bank_total += payout([rng.choice(SYMBOLS) for _ in range(3)], 10) - 10
    assert -2.0 < bank_total / 1_000_000 < -0.02          # a coin sink, but not a robbery


def test_registry_and_unknown_messages(bank, settings):
    assert set(GAMES) == {"tictactoe", "connect4", "trivia", "slots"}
    assert create_game("slots", bank, settings).name == "slots"
    with pytest.raises(KeyError):
        create_game("chess", bank, settings)


async def test_unknown_message_is_refused(bank, settings):
    for name in ("tictactoe", "connect4", "trivia", "slots"):
        assert (await create_game(name, bank, settings).handle(A, {"t": "format-disk"})).error


def test_packager_builds_valid_xdc(tmp_path):
    import zipfile

    for name in ("tictactoe", "connect4", "trivia", "slots"):
        path = packager.build(name, tmp_path)
        names = zipfile.ZipFile(path).namelist()
        assert {"index.html", "manifest.toml", "net.js", "style.css", "icon.png"} <= set(names)
        assert packager.digest(path) == packager.digest(packager.build(name, tmp_path))   # deterministic
    with pytest.raises(FileNotFoundError):
        packager.build("nope", tmp_path)
