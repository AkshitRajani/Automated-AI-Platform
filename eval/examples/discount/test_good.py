"""A real test: calls the SUT and asserts on its actual output, both branches.
Passes all seven gates — and catches the planted bugs in gate 6, because a wrong
output breaks a concrete assertion."""


def run(sut):
    assert sut.apply_discount(100, True) == 90.0     # member branch
    assert sut.apply_discount(100, False) == 100     # non-member branch
    assert sut.is_eligible(100) is True
    assert sut.is_eligible(99) is False
