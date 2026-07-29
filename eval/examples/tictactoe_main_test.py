import io
import contextlib
from unittest.mock import patch


def run(sut):
    # intro enter, sym symbol choice "X", sym enter,
    # then 6 moves (O,X,O,X,O,X) where X wins the top row, then report enter.
    inputs = ["", "X", "",
              "1", "0", "0", "0", "1", "1", "0", "1", "2", "0", "0", "2",
              ""]
    buf = io.StringIO()
    with patch("builtins.input", side_effect=inputs):
        with contextlib.redirect_stdout(buf):
            sut.main()
    output = buf.getvalue()
    assert "Welcome to Pam's Tic Tac Toe game" in output
    assert "Player X, you won!" in output
    assert "Winner : Player X." in output
