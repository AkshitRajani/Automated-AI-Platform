def run(sut):
    empty_board = [[" ", " ", " "],
                   [" ", " ", " "],
                   [" ", " ", " "]]
    assert sut.isWinner(empty_board, "X", "O", 1) is True

    x_wins_top_row = [["X", "X", "X"],
                       [" ", " ", " "],
                       [" ", " ", " "]]
    assert sut.isWinner(x_wins_top_row, "X", "O", 1) is False
