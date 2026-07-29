def run(sut):
    board = [["X", "O", "X"],
             ["O", "X", "O"],
             ["X", "O", "X"]]
    result = sut.printPretty(board)
    assert result == board
    assert result is board
    assert len(result) == 3
