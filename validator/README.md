# Step-file Validator

Deterministic static checks for generated **Behave** step files. It reads each
file's structure and reports concrete defects — the kind that make a generated
test crash, collide, or pass while checking nothing.

- **Pure standard library** (`ast` + `importlib.metadata`). **No external
  dependencies, no `pip install`** — a single self-contained package you can run
  as-is.
- **Deterministic** — same files in, same findings out. No LLM, no scoring, no
  weights. Every finding is a fact read off the code's structure.
- **No regex, no hardcoded library lists** — names are resolved through real
  lexical scope; library availability is resolved against the real environment.

---

## Run it

```bash
python -m validator path/to/step_files          # a folder or a single .py file
python -m validator path/to/steps --json         # machine-readable (agent loop / CI)
python -m validator path/to/steps --check-libraries   # also verify imports exist (run in target env)
```

Exit code is `0` when there are no ERROR findings, `1` otherwise (CI-friendly).

Try it on the bundled examples (faithful reproductions of the standup findings):

```bash
python -m validator validator/examples/bad_steps    # 8 errors + 2 warnings
python -m validator validator/examples/good_steps    # clean
```

---

## What it checks

| # | Rule | Catches | Severity |
|---|---|---|---|
| 1 | `duplicate-step-definition` | two steps with the same `@given/@when/@then` pattern — behave keeps the last, the rest are dead code | ERROR |
| 2 | `undefined-name` | a name used but never imported or defined (e.g. `re`, `BytesIO`) → `NameError` | ERROR |
| 3 | `unavailable-library` | an imported library not available in the target environment (opt-in, no allowlist) | ERROR |
| 4 | `missing-cross-file-import` | a function defined in another step file but used here without importing it | ERROR |
| 5 | `no-op-step` | a `then` step whose body is empty or only `pass` — it asserts nothing | ERROR |
| 6 | `unconditional-raise` / `dead-code` | a step that always raises before asserting; statements after a `return`/`raise` | ERROR / WARNING |
| 7 | `over-mocking` | the system under test replaced by a `patch(...)` / `MagicMock` — asserting on a stand-in, not the real call path | WARNING |

These map directly to the two reported issues — **duplicate definitions → rule 1**
and **missing libraries → rules 2, 3, 4** — and cover the rest of the reported
defects for free.

### How each rule works (no regex, no hardcoding)

- **Undefined names (2, 4):** build the set of names the file was *given*
  (imports, definitions, arguments, builtins, the names behave injects) and the
  set it *uses*; anything used-but-not-given is a defect. Resolved through real
  lexical scope (a name defined in one function is not visible in another).
- **Unavailable library (3):** a library is available if it is in the standard
  library, an installed distribution, **or** a first-party module in the project.
  Anything else is missing. This reads the *actual* installed inventory, so it
  must run **inside the target environment** — which is also where
  import-name vs package-name mismatches (`sklearn` ships in `scikit-learn`)
  resolve correctly. It is therefore opt-in (`--check-libraries`).
- **Duplicate steps (1):** replicates behave's own registry — a step is keyed by
  `(step_type, pattern)`. Two functions sharing a key collide. Keyed on the
  **pattern**, never the function name (behave step functions are routinely all
  named `step_impl`).
- **No-op / raise / dead code / over-mock (5, 6, 7):** structural questions about
  a step's body — is there an assertion, is the first statement a `raise`, is a
  stand-in being substituted for the real call.

---

## Output

Human-readable by default; `--json` emits the structured form the coding agent
reads in its repair loop:

```json
{
  "ok": false,
  "files_checked": 1,
  "error_count": 2,
  "findings": [
    {
      "rule": "undefined-name", "severity": "ERROR",
      "file": ".../s3_steps.py", "line": 11, "symbol": "re",
      "message": "uses 're', which is never imported or defined (NameError at runtime)",
      "suggestion": "import or define 're' before using it"
    }
  ]
}
```

---

## Where this fits

One engine, two front doors:

- **This CLI** — the reference handover; run it standalone against any folder of
  step files.
- **A coding-agent tool** — the same `validate()` function becomes a tool the
  generation agent calls after writing a test; each finding is fed back as a
  precise repair instruction (`gate, line, fix`). In AWS Strands that wrapper is
  a few lines around `validate()` — the engine here is unchanged:

  ```python
  from strands import tool
  from validator import validate

  @tool
  def validate_step_files(path: str) -> dict:
      """Statically validate generated Behave step files; returns findings."""
      return validate(path).to_dict()
  ```

This validator is the **static layer of the eval's gate cascade** — the checks
that need no execution (does it parse, is every name real, does it assert
something, are steps unique). The execution gates (does it hit the real call
path, does it catch a planted bug) run later in the sandbox.

---

## Library layout

```
validator/
├── __main__.py      # CLI
├── runner.py        # orchestrator: run every check -> one Report
├── loader.py        # discover + parse step files (a non-parsing file is itself a finding)
├── scope.py         # classes 2 & 4 — undefined names via lexical scope
├── checks.py        # classes 1, 5, 6, 7 — behave-specific structural checks
├── environment.py   # class 3 — library availability (opt-in, target-env)
├── models.py        # Finding / Severity / Report
└── examples/
    ├── bad_steps/   # faithful reproductions of the standup findings
    └── good_steps/  # a clean file that passes every check
```
