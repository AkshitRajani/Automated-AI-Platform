import io
import contextlib
from unittest.mock import patch


def run(sut):
    buf1 = io.StringIO()
    with patch("builtins.input", return_value=""):
        with contextlib.redirect_stdout(buf1):
            sut.report(3, False, "X", "O")
    assert "Winner : Player X." in buf1.getvalue()

    buf2 = io.StringIO()
    with patch("builtins.input", return_value=""):
        with contextlib.redirect_stdout(buf2):
            sut.report(4, False, "X", "O")
    assert "Winner : Player O." in buf2.getvalue()

    buf3 = io.StringIO()
    with patch("builtins.input", return_value=""):
        with contextlib.redirect_stdout(buf3):
            sut.report(9, True, "X", "O")
    assert "There is a tie." in buf3.getvalue()
