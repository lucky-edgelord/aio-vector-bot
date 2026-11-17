from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from pathlib import Path

from .base import Game, Outcome, Player, Update

BANK = json.loads((Path(__file__).parent / "data" / "trivia.json").read_text("utf-8"))
ROUNDS = 8
ANSWER_SECONDS = 15
REVEAL_SECONDS = 4


class Trivia(Game):
    """Lobby, then 8 timed questions. Faster correct answers score more. Coins = correct answers × rate."""

    name = "trivia"
    title = "Trivia"

    def __init__(self, bank, settings, *, rng: random.Random | None = None, clock: Callable[[], float] = time.time):
        super().__init__(bank, settings)
        self.rng, self.clock = rng or random.Random(), clock
        self.players: dict[str, Player] = {}
        self.scores: dict[str, int] = {}
        self.correct: dict[str, int] = {}
        self.phase = "lobby"                      # lobby | question | reveal | done
        self.questions: list[dict] = []
        self.round = 0
        self.deadline = 0.0
        self.answers: dict[str, int] = {}
        self.host: str | None = None

    @property
    def finished(self) -> bool:
        return self.phase == "done"

    @property
    def current(self) -> dict:
        return self.questions[self.round]

    def state(self) -> dict:
        s = {"t": "state", "game": self.name, "phase": self.phase, "round": self.round + 1 if self.questions else 0,
             "rounds": ROUNDS, "deadline": self.deadline,
             "host_addr": self.players[self.host].addr if self.host in self.players else None,
             "players": [{"name": p.label, "addr": p.addr, "npub": n[:8], "score": self.scores.get(n, 0),
                          "correct": self.correct.get(n, 0), "answered": n in self.answers}
                         for n, p in self.players.items()]}
        if self.phase in ("question", "reveal"):
            s["question"] = self.current["q"]
            s["options"] = self.current["options"]
        if self.phase == "reveal":
            s["answer"] = self.current["answer"]
            s["picks"] = {self.players[n].addr or n[:8]: a for n, a in self.answers.items()}
        return s

    async def handle(self, who: Player, msg: dict) -> Update:
        kind = msg.get("t")
        if kind == "hello":
            return Update(state=self.state())
        if kind == "join":
            if self.phase != "lobby":
                return Update(error="The game already started. You are watching.")
            self.players.setdefault(who.npub, who)
            self.scores.setdefault(who.npub, 0)
            self.correct.setdefault(who.npub, 0)
            self.host = self.host or who.npub
            return Update(state=self.state())
        if kind == "start":
            if self.phase != "lobby" or who.npub != self.host:
                return Update(error="Only the host can start, from the lobby.")
            self.questions = self.rng.sample(BANK, ROUNDS)
            self.round = -1
            self._next_question()
            return Update(state=self.state())
        if kind == "answer":
            if self.phase != "question" or who.npub not in self.players:
                return Update(error="You can't answer right now.")
            pick = msg.get("i")
            if who.npub in self.answers:
                return Update(error="Already answered.")
            if not isinstance(pick, int) or isinstance(pick, bool) or not 0 <= pick < len(self.current["options"]):
                return Update(error="Pick one of the options.")
            self.answers[who.npub] = pick
            if pick == self.current["answer"]:
                left = max(self.deadline - self.clock(), 0)
                self.scores[who.npub] += 100 + int(100 * left / ANSWER_SECONDS)
                self.correct[who.npub] += 1
            if len(self.answers) == len(self.players):
                return Update(state=self._reveal())
            return Update(state=self.state())
        return Update(error="Unknown message.")

    def _next_question(self) -> None:
        self.round += 1
        self.phase, self.answers = "question", {}
        self.deadline = self.clock() + ANSWER_SECONDS

    def _reveal(self) -> dict:
        self.phase = "reveal"
        self.deadline = self.clock() + REVEAL_SECONDS
        return self.state()

    async def tick(self, now: float) -> Update | None:
        if self.phase == "question" and now >= self.deadline:
            return Update(state=self._reveal())
        if self.phase == "reveal" and now >= self.deadline:
            if self.round + 1 >= ROUNDS:
                self.phase = "done"
                return Update(state=self.state(), outcomes=self.outcomes())
            self._next_question()
            return Update(state=self.state())
        return None

    def outcomes(self) -> list[Outcome]:
        rate = self.settings["trivia_coins_per_point"]
        best = max(self.scores.values(), default=0)
        return [Outcome(p, won=best > 0 and self.scores[n] == best, score=self.correct[n],
                        coins=self.correct[n] * rate, note=f"{self.correct[n]}/{ROUNDS} correct")
                for n, p in self.players.items()]
