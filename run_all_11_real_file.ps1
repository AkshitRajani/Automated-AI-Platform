$env:PYTHONIOENCODING="utf-8"
$real = "C:\python-code\PY_tic-tac-toy\Pam Qian_Tic Tac Toe_2016.py"
$tests = "C:\infosoft\automated_ai_platform-main\eval\examples"

Write-Host "`n=== 1/11 main ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_main_test.py" --changed "${real}:10"

Write-Host "`n=== 2/11 intro ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_intro_test.py" --changed "${real}:18"

Write-Host "`n=== 3/11 create_grid ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_creategrid_test.py" --changed "${real}:35"

Write-Host "`n=== 4/11 sym ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_sym_test.py" --changed "${real}:50"

Write-Host "`n=== 5/11 startGamming ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_startgamming_test.py" --changed "${real}:92"

Write-Host "`n=== 6/11 isFull ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_isfull_test.py" --changed "${real}:110,116"

Write-Host "`n=== 7/11 outOfBoard ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_outofboard_test.py" --changed "${real}:122"

Write-Host "`n=== 8/11 printPretty ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_printpretty_test.py" --changed "${real}:134"

Write-Host "`n=== 9/11 isWinner ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_test.py" --changed "${real}:143"

Write-Host "`n=== 10/11 illegal ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_illegal_test.py" --changed "${real}:183"

Write-Host "`n=== 11/11 report ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$real" --test "$tests\tictactoe_report_test.py" --changed "${real}:190"
