import io
import contextlib
from unittest.mock import patch


def run(sut):
    buf = io.StringIO()
    with patch("builtins.input", return_value=""):
        with contextlib.redirect_stdout(buf):
            sut.intro()
    output = buf.getvalue()
    assert "Welcome to Pam's Tic Tac Toe game" in output
    assert "Rules:" in output
