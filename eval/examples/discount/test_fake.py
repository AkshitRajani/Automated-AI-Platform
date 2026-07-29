"""The fake-pass — the dangerous test that fooled the 2025 system. It *calls* the
real SUT (so it passes gate 3) and its assertion *looks* real (so it passes gate
4), but it asserts on a value it recomputed itself, never on the SUT's output. So
when gate 6 sabotages the SUT's return value, this test does not notice — it
catches 0 mutants and is rejected at gate 6."""


def run(sut):
    total = 100
    expected = round(total * 0.9, 2)
    sut.apply_discount(total, True)          # calls real code, but ignores the result
    assert expected == round(total * 0.9, 2)  # asserts on a local recompute, not the SUT
