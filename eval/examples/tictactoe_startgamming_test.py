from unittest.mock import patch


def run(sut):
    # Scenario 1: valid move immediately. count=1 -> symbol_2's turn.
    board1 = [[" ", " ", " "], [" ", " ", " "], [" ", " ", " "]]
    with patch("builtins.input", side_effect=["0", "0"]):
        result1 = sut.startGamming(board1, "X", "O", 1)
    assert result1[0][0] == "O"

    # Scenario 2: out-of-range retry, then valid. count=2 -> symbol_1's turn.
    board2 = [[" ", " ", " "], [" ", " ", " "], [" ", " ", " "]]
    with patch("builtins.input", side_effect=["5", "5", "1", "1"]):
        result2 = sut.startGamming(board2, "X", "O", 2)
    assert result2[1][1] == "X"

    # Scenario 3: filled-cell retry, then empty. count=1 -> symbol_2's turn.
    board3 = [["X", " ", " "], [" ", " ", " "], [" ", " ", " "]]
    with patch("builtins.input", side_effect=["0", "0", "2", "2"]):
        result3 = sut.startGamming(board3, "X", "O", 1)
    assert result3[2][2] == "O"
    assert result3[0][0] == "X"
