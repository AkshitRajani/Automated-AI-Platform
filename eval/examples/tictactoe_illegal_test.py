import io
import contextlib


def run(sut):
    board = [[" ", " ", " "], [" ", " ", " "], [" ", " ", " "]]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sut.illegal(board, "X", "O", 0, 0)
    output = buf.getvalue()
    assert "already filled" in output
