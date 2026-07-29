$env:PYTHONIOENCODING="utf-8"
$base = "C:\infosoft\automated_ai_platform-main\eval\examples"

Write-Host "`n=== outOfBoard ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_outofboard_sut.py" --test "$base\tictactoe_outofboard_test.py" --changed "$base\tictactoe_outofboard_sut.py:2"

Write-Host "`n=== illegal ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_illegal_sut.py" --test "$base\tictactoe_illegal_test.py" --changed "$base\tictactoe_illegal_sut.py:2"

Write-Host "`n=== intro ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_intro_sut.py" --test "$base\tictactoe_intro_test.py" --changed "$base\tictactoe_intro_sut.py:2"

Write-Host "`n=== sym ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_sym_sut.py" --test "$base\tictactoe_sym_test.py" --changed "$base\tictactoe_sym_sut.py:11"

Write-Host "`n=== report ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_report_sut.py" --test "$base\tictactoe_report_test.py" --changed "$base\tictactoe_report_sut.py:5"

Write-Host "`n=== startGamming ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_startgamming_sut.py" --test "$base\tictactoe_startgamming_test.py" --changed "$base\tictactoe_startgamming_sut.py:39"

Write-Host "`n=== isFull ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_isfull_sut.py" --test "$base\tictactoe_isfull_test.py" --changed "$base\tictactoe_isfull_sut.py:109,114"

Write-Host "`n=== main ===" -ForegroundColor Cyan
& $env:AAP_PYTHON -m eval --sut "$base\tictactoe_main_sut.py" --test "$base\tictactoe_main_test.py" --changed "$base\tictactoe_main_sut.py:153"
