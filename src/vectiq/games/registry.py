from __future__ import annotations

from typing import Any

from .base import Bank, Game
from .connect4 import Connect4
from .slots import Slots
from .tictactoe import TicTacToe
from .trivia import Trivia

GAMES: dict[str, type[Game]] = {g.name: g for g in (TicTacToe, Connect4, Trivia, Slots)}


def create_game(name: str, bank: Bank, settings: dict[str, Any]) -> Game:
    return GAMES[name](bank, settings)
