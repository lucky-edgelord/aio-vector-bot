"""The contract between a game's rules and the WebXDC session that carries it.

A game is plain Python with no network in it: feed it messages from players, get back the state to
broadcast. That keeps every rule unit-testable. The session host (``cogs/games.py``) does the I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Player:
    """A verified participant. ``addr`` is what their client calls itself (used only to highlight "you")."""

    npub: str
    name: str = ""
    addr: str = ""

    @property
    def label(self) -> str:
        return self.name or (self.npub[:10] + "…")


@dataclass
class Outcome:
    """A finished result for one player, paid and recorded by the host."""

    player: Player
    won: bool = False
    drawn: bool = False
    score: int = 0
    coins: int = 0
    note: str = ""


class Bank(Protocol):
    """What a game may ask of the economy."""

    async def balance(self, npub: str) -> int: ...

    async def adjust(self, npub: str, amount: int, reason: str) -> int: ...


@dataclass
class Update:
    """What the host does after a message: broadcast ``state`` (always the whole state), record outcomes."""

    state: dict | None = None
    outcomes: list[Outcome] = field(default_factory=list)
    error: str | None = None
    to_sender_only: bool = False


class Game:
    """Base class. One instance per shared app message."""

    name = "game"
    title = "Game"

    def __init__(self, bank: Bank, settings: dict[str, Any]):
        self.bank = bank
        self.settings = settings

    # -- required ---------------------------------------------------------------------
    def state(self) -> dict:
        raise NotImplementedError

    async def handle(self, who: Player, msg: dict) -> Update:
        raise NotImplementedError

    # -- optional ---------------------------------------------------------------------
    async def tick(self, now: float) -> Update | None:
        """Called about once a second by the host; return an Update when time-based state changed."""
        return None

    async def left(self, who: Player) -> Update | None:
        return None

    @property
    def finished(self) -> bool:
        return False
