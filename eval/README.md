# Eval — the deterministic gate cascade (Component 3)

The eval answers **one** question about a generated test: *is it good enough to
deliver — yes or no?* It produces **no score, no weights, no labels, no LLM
judge**. A test is delivered only if **every** gate passes; one failure sends it
back for bounded repair, and if repair runs out, it is discarded and a human is
told exactly which gate failed.

This is `MASTER_DESIGN.md §7` made executable. It is the third phase —
**Ingestion → Coding Agent → Eval** — and it *contains* the validator:

```
EVAL  =  validator (static layer)  +  execution layer  +  the orchestrator
         └── already shipped ──┘     └──────── added here ────────┘
```

So the validator is not a separate phase and not a synonym for the eval — it is
the eval's static, no-execution layer. This package wraps it and adds the gates
that must *run* the test.

---

## The seven gates

Run cheapest-first; the cascade stops at the first failure.

| # | Gate | Question | Layer | Backed by |
|---|------|----------|-------|-----------|
| 1 | **Runs** | does it parse / load? | static | `validator` (parse) |
| 2 | **Grounded** | is every name real, per the KB? | static | `grounding.py` + injected resolver |
| 4 | **Checks a real value** | does it assert a concrete value, not a no-op? | static | `validator` (no-op) + vacuous-assert scan |
| 3 | **Calls the real code** | did the test execute any SUT line? | execution | coverage > 0 |
| 5 | **Covers the change** | did it execute the changed lines? | execution | coverage ∩ changed |
| 6 | **Catches a planted bug** | sabotage the output — does the test fail? | execution | `mutation.py` |
| 7 | **Stable** | re-run — same verdict every time? | execution | repeated runs |

> Gates are listed by design number but run in **cost** order (static 1/2/4 →
> one baseline run → execution 3/5/6/7). **Gate 6 is the load-bearing one** — the
> deterministic fake-pass killer (see below).

### Gate 6 in one paragraph

A test is a smoke detector; the way to know it works is to put a little smoke
under it. `mutation.py` takes the SUT and produces a handful of variants, each
with **one return value replaced by a sentinel** (None / 0 / "" / []). The test
runs against each. A real test fails on ≥1 mutant (it noticed) → keep; a fake
test fails on none (it noticed nothing) → reject. Two safety rules: the test must
pass on correct code first (baseline), and catch ≥1 of several mutants. This is
the per-change, label-free use of mutation (Meta TestGen-LLM ships the same
binary filter).

---

## Run it

From `2026/implementation/` (so `validator` and `eval` are both importable):

```bash
python -m eval --sut PATH --test PATH [options]
```

A **test** here is a Python module exposing `def run(sut): ...` that calls the
SUT and asserts on its output. Exit code is `0` when delivered, `1` otherwise.

Try the worked examples — a real test that earns delivery, and a fake-pass that
runs but verifies nothing:

```bash
# DELIVER — all seven gates pass, 8/8 mutants caught
python -m eval --sut eval/examples/discount/sut.py \
               --test eval/examples/discount/test_good.py \
               --changed eval/examples/discount/sut.py:6 --app-id DEMO

# REPAIR/DISCARD — passes gates 1–5, then dies at gate 6 (catches 0 planted bugs)
python -m eval --sut eval/examples/discount/sut.py \
               --test eval/examples/discount/test_fake.py \
               --changed eval/examples/discount/sut.py:6 --app-id DEMO
```

Grounding (gate 2) needs real names; pass a flat allow-list with `--names FILE`
and the identifiers to check with `--ground NAME:KIND` (the real `KBClient` is
the production drop-in). `--json` emits the machine form the repair loop reads.

---

## The execution boundary (A/B parity)

Gates 3/5/6/7 talk to an `ExecutionEnv`, so the cascade is execution-model-
agnostic:

- **`InProcessEnv`** (shipped) — pure stdlib. Runs the test against an importable
  Python SUT and records executed SUT lines via `sys.settrace` (no `coverage`
  dependency). Mutation runs a replacement source compiled under the SUT's own
  filename, so coverage and tracebacks stay truthful. This is the backend-logic
  path.
- **`SandboxEnv` / `ArtsEnv`** (to add) — implement the *same* protocol at the
  integration boundary: LocalStack/behave on our side, ARTS at the client. The
  cascade does not change; only the env swaps. **That swap is the whole of A/B
  stack parity** — the same seven gates, the same mutation operators, on both
  sides. Locally gate 6 sabotages the sandbox's stub output (still catches the
  fake-pass class); at the client the same gate mutates real code.

---

## Where this fits — the integration point

The coding agent's `boundary.py` already reserves the slot (its docstring:
*"the external Eval … is where it would be invoked once built"*). Wiring it in
is a few lines — `evaluate()` replaces / augments the slice-1 lint gate:

```python
from eval import EvalContext, ExecCase, evaluate

ctx = EvalContext.from_bundle(
    bundle, app_id=task.scope.app_id,
    case=ExecCase(sut_path=sut, test_path=test),
    changed_lines=changed, steps_root=task.workspace_dir,
)
verdict = evaluate(ctx, env=sandbox_env, resolver=kb)
if not verdict.deliver:
    reasons = [f.message for f in verdict.repair_findings]   # → bounded repair, same as today
```

`verdict.repair_findings` are `validator.Finding`s — the same shape the agent
already repairs against. One repair format across both layers.

---

## Library layout

```
eval/
├── __main__.py     # CLI front door (mirrors `python -m validator`)
├── cascade.py      # the orchestrator: 7 gates, cheapest-first, short-circuit
├── gates.py        # gates 1, 3, 4, 5, 6, 7
├── grounding.py    # gate 2 — KB resolution (injected resolver)
├── mutation.py     # gate 6 engine — AST output-sabotage operators
├── execution.py    # ExecutionEnv protocol + InProcessEnv (pure stdlib)
├── context.py      # EvalContext (+ from_bundle adapter)
├── models.py       # Verdict / GateOutcome; reuses validator's Finding/Severity
├── examples/discount/   # sut.py + test_good.py (delivers) + test_fake.py (dies @ gate 6)
└── tests/          # 17 tests — engine, gates, validator-reuse, end-to-end
```

**Dependencies:** pure Python standard library, plus the sibling `validator`
package (the static layer). No `pip install`, no `coverage`/`mutmut`/`pytest` at
runtime — a single self-contained handover, the same ethos as the validator.
