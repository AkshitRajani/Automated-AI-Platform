import io
import contextlib
from unittest.mock import patch


def run(sut):
    board = [[" ", " ", " "], [" ", " ", " "], [" ", " ", " "]]
    # O plays (1,0),(1,1),(2,0); X plays (0,0),(0,1),(0,2) -> X wins top row.
    inputs = ["1", "0", "0", "0", "1", "1", "0", "1", "2", "0", "0", "2", ""]
    buf = io.StringIO()
    with patch("builtins.input", side_effect=inputs):
        with contextlib.redirect_stdout(buf):
            sut.isFull(board, "X", "O")
    output = buf.getvalue()
    assert board[0] == ["X", "X", "X"]
    assert "Player X, you won!" in output
    assert "Winner : Player X." in output
