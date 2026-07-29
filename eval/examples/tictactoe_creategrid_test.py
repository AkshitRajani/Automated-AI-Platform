def run(sut):
    board = sut.create_grid()
    assert board == [[" ", " ", " "],
                      [" ", " ", " "],
                      [" ", " ", " "]]
    assert len(board) == 3
    assert all(len(row) == 3 for row in board)
