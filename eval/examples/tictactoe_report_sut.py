def report(count, winner, symbol_1, symbol_2):
    print("\n")
    input("Press enter to see the game summary. ")
    if (winner == False) and (count % 2 == 1):
        print("Winner : Player " + symbol_1 + ".")
    elif (winner == False) and (count % 2 == 0):
        print("Winner : Player " + symbol_2 + ".")
    else:
        print("There is a tie. ")
