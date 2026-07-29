"""generate_mutants: distinct output-sabotage variants, each still valid Python."""
import ast

from eval.mutation import generate_mutants

SRC = (
    "def f(x):\n"
    "    if x:\n"
    "        return x * 2\n"
    "    return x\n"
)


def test_produces_distinct_compiling_mutants():
    mutants = generate_mutants(SRC, "f.py", max_n=8)
    assert mutants, "expected at least one mutant"
    sources = {m.source for m in mutants}
    assert len(sources) == len(mutants)          # all distinct
    for m in mutants:
        ast.parse(m.source)                       # every mutant still parses
        assert m.source != SRC                    # and actually changed something


def test_respects_max_n():
    assert len(generate_mutants(SRC, "f.py", max_n=2)) == 2


def test_nothing_to_mutate_is_empty():
    assert generate_mutants("def f(x):\n    print(x)\n", "f.py") == []
