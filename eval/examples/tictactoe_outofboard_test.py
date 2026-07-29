import io
import contextlib


def run(sut):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sut.outOfBoard(5, 5)
    output = buf.getvalue()
    assert "Out of boarder" in output
