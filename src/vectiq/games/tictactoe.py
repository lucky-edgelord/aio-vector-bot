from __future__ import annotations

from .seats import TwoPlayerGame

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


class TicTacToe(TwoPlayerGame):
    name = "tictactoe"
    title = "Tic-Tac-Toe"

    def __init__(self, bank, settings):
        super().__init__(bank, settings)
        self.board = [""] * 9
        self.line: tuple | None = None

    def reset_board(self):
        self.board, self.line = [""] * 9, None

    def apply_move(self, mark, msg):
        i = msg.get("i")
        if not isinstance(i, int) or not 0 <= i < 9:
            return "Pick a square from 0 to 8."
        if self.board[i]:
            return "That square is taken."
        self.board[i] = mark
        for line in LINES:
            if all(self.board[k] == mark for k in line):
                self.winner, self.line, self.over = mark, line, True
                return None
        if all(self.board):
            self.winner, self.over = "draw", True
        return None

    def state(self):
        return {"t": "state", "game": self.name, "board": self.board, "turn": self.turn, "winner": self.winner,
                "line": list(self.line) if self.line else None, "seats": self.seats_state()}
