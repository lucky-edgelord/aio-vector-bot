"""Shared logic for two-player turn games."""

from __future__ import annotations

from .base import Game, Outcome, Player, Update


class TwoPlayerGame(Game):
    marks = ("X", "O")

    def __init__(self, bank, settings):
        super().__init__(bank, settings)
        self.seats: dict[str, Player | None] = {m: None for m in self.marks}
        self.turn = self.marks[0]
        self.winner: str | None = None     # a mark, or "draw"
        self.over = False

    @property
    def finished(self) -> bool:
        return self.over

    def mark_of(self, who: Player) -> str | None:
        return next((m for m, p in self.seats.items() if p and p.npub == who.npub), None)

    def seats_state(self) -> dict:
        return {m: ({"name": p.label, "addr": p.addr} if p else None) for m, p in self.seats.items()}

    def reset_board(self) -> None:
        raise NotImplementedError

    def apply_move(self, mark: str, msg: dict) -> str | None:
        """Play the move; return an error string, or None. Must set self.winner/self.over when it ends."""
        raise NotImplementedError

    async def handle(self, who: Player, msg: dict) -> Update:
        kind = msg.get("t")
        if kind == "hello":
            return Update(state=self.state(), to_sender_only=False)
        if kind == "join":
            if self.mark_of(who):
                return Update(state=self.state())
            free = next((m for m in self.marks if self.seats[m] is None), None)
            if free is None:
                return Update(error="Both seats are taken. You are watching.")
            self.seats[free] = who
            return Update(state=self.state())
        if kind == "rematch":
            if self.mark_of(who) and self.over:
                self.reset_board()
                self.turn, self.winner, self.over = self.marks[0], None, False
                return Update(state=self.state())
            return Update(error="Nothing to rematch yet.")
        if kind == "move":
            mark = self.mark_of(who)
            if mark is None:
                return Update(error="Take a seat first.")
            if self.over:
                return Update(error="The game is over. Ask for a rematch.")
            if any(p is None for p in self.seats.values()):
                return Update(error="Waiting for an opponent.")
            if mark != self.turn:
                return Update(error="Not your turn.")
            if (err := self.apply_move(mark, msg)):
                return Update(error=err)
            outcomes: list[Outcome] = []
            if self.over:
                outcomes = self.outcomes()
            else:
                self.turn = self.marks[1] if mark == self.marks[0] else self.marks[0]
            return Update(state=self.state(), outcomes=outcomes)
        return Update(error="Unknown message.")

    def outcomes(self) -> list[Outcome]:
        win, draw = self.settings["winner_coins"], self.settings["draw_coins"]
        out = []
        for mark, player in self.seats.items():
            if player is None:
                continue
            if self.winner == "draw":
                out.append(Outcome(player, drawn=True, coins=draw, note="draw"))
            else:
                won = mark == self.winner
                out.append(Outcome(player, won=won, coins=win if won else 0, note="won" if won else "lost"))
        return out

    async def left(self, who: Player) -> Update | None:
        return None
