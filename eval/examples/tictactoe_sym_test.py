from unittest.mock import patch


def run(sut):
    with patch("builtins.input", side_effect=["X", ""]):
        result = sut.sym()
    assert result == ("X", "O")

    with patch("builtins.input", side_effect=["O", ""]):
        result2 = sut.sym()
    assert result2 == ("O", "X")
