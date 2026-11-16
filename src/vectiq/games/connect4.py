from __future__ import annotations

from .seats import TwoPlayerGame

ROWS, COLS = 6, 7


def find_four(board: list[list[str]], mark: str):
    for r in range(ROWS):
        for c in range(COLS):
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                cells = [(r + dr * k, c + dc * k) for k in range(4)]
                if all(0 <= rr < ROWS and 0 <= cc < COLS and board[rr][cc] == mark for rr, cc in cells):
                    return cells
    return None


class Connect4(TwoPlayerGame):
    name = "connect4"
    title = "Connect Four"
    marks = ("R", "Y")

    def __init__(self, bank, settings):
        super().__init__(bank, settings)
        self.board = [[""] * COLS for _ in range(ROWS)]   # row 0 is the top
        self.line = None

    def reset_board(self):
        self.board, self.line = [[""] * COLS for _ in range(ROWS)], None

    def apply_move(self, mark, msg):
        col = msg.get("col")
        if not isinstance(col, int) or not 0 <= col < COLS:
            return "Pick a column from 0 to 6."
        for r in range(ROWS - 1, -1, -1):
            if not self.board[r][col]:
                self.board[r][col] = mark
                if (line := find_four(self.board, mark)):
                    self.winner, self.line, self.over = mark, line, True
                elif all(self.board[0]):
                    self.winner, self.over = "draw", True
                return None
        return "That column is full."

    def state(self):
        return {"t": "state", "game": self.name, "board": self.board, "turn": self.turn, "winner": self.winner,
                "line": [list(c) for c in self.line] if self.line else None, "seats": self.seats_state()}
