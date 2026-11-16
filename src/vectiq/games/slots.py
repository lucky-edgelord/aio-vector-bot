from __future__ import annotations

import random
from collections import deque

from .base import Game, Outcome, Player, Update

SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "🍀", "💎"]


def payout(reels: list[str], bet: int) -> int:
    """Three alike pays 10× (💎 30×), exactly two alike pays 1.2×, otherwise nothing."""
    if reels[0] == reels[1] == reels[2]:
        return bet * (30 if reels[0] == "💎" else 10)
    if len(set(reels)) == 2:
        return bet * 6 // 5
    return 0


class Slots(Game):
    """Bot-authoritative slot machine. Every spin is paid from and into the real SQLite wallet."""

    name = "slots"
    title = "Slots"

    def __init__(self, bank, settings, *, rng: random.Random | None = None):
        super().__init__(bank, settings)
        self.rng = rng or random.SystemRandom()
        self.feed: deque = deque(maxlen=6)

    def state(self) -> dict:
        return {"t": "state", "game": self.name, "feed": list(self.feed), "max_bet": self.settings["slots_max_bet"]}

    async def handle(self, who: Player, msg: dict) -> Update:
        kind = msg.get("t")
        if kind == "hello":
            return Update(state=self.state() | {"balance": await self.bank.balance(who.npub), "for": who.addr})
        if kind != "spin":
            return Update(error="Unknown message.")
        bet = msg.get("bet")
        limit = self.settings["slots_max_bet"]
        if not isinstance(bet, int) or not 1 <= bet <= limit:
            return Update(error=f"Bet between 1 and {limit}.")
        if await self.bank.balance(who.npub) < bet:
            return Update(error="You don't have enough coins.")
        await self.bank.adjust(who.npub, -bet, "slots bet")
        reels = [self.rng.choice(SYMBOLS) for _ in range(3)]
        won = payout(reels, bet)
        if won:
            await self.bank.adjust(who.npub, won, "slots win")
        balance = await self.bank.balance(who.npub)
        self.feed.appendleft({"name": who.label, "reels": reels, "bet": bet, "won": won})
        state = self.state() | {"for": who.addr, "reels": reels, "bet": bet, "won": won, "balance": balance}
        return Update(state=state, outcomes=[Outcome(who, won=won > bet, score=won - bet, note="spin")])
