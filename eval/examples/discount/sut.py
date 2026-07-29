"""A tiny code-under-test: the kind of backend logic a regression test targets.
Has a branch and arithmetic, so output sabotage (gate 6) has something to catch."""


def apply_discount(total, is_member):
    if is_member:
        return round(total * 0.9, 2)
    return total


def is_eligible(total):
    return total >= 100
