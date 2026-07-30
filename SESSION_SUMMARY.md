# Session Summary — Automated AI Platform Setup & Verification

**Date:** 2026-07-29
**Test subject:** `Pam Qian_Tic Tac Toe_2016.py` (real, pre-existing Python code, not a bundled fixture)

---

## 1. Environment setup

- Activated project `.venv`, loaded `PYTHONPATH`/`AAP_PYTHON` via `setup_env.ps1`.
- Confirmed Docker infrastructure already running and healthy: `aap_kb_postgres` (Knowledge Base, port 5432), `default-postgres-1` (Sandbox DB, port 5433), `default-localstack-1`, `default-microcks-1`, `default-runner-1`.
- Started the Sandbox API backend (uvicorn) and confirmed it responding to real HTTP requests.

## 2. Analyzer — verified working

- Ran `analyzer` directly against the real, full Tic-Tac-Toe file.
- Correctly extracted **12 entities** (1 Module + 11 Functions) and **23 relationships** (11 `DEFINES`, 12 `CALLS`).
- Cross-checked independently by querying the Postgres knowledge base directly (not just trusting the tool's own output) — confirmed exact `line_start`/`line_end` for every function.

## 3. Ingestion — verified working

- Fixed `ingestion\.env`: pointed `QUAD_FILES_SOURCE` at the local quads folder instead of the placeholder S3 URI; cleared placeholder `NEPTUNE_ENDPOINT`/`NEPTUNE_S3_BUCKET` values and set `NEPTUNE_LOCAL_DIR` so the optional graph-capture step writes locally instead of failing on missing AWS credentials.
- Confirmed successful ingestion into the Knowledge Base Postgres.

## 4. `core onboard` — verified working

- Ran the combined analyzer+ingestion pipeline via `core onboard` against the real file (as a directory, since `core onboard` requires a directory/zip/S3 URI, unlike the raw `analyzer` module which also accepts a single file).

## 5. Eval — verified working, and a real bug found + fixed

- Wrote hand-crafted tests and ran the 7-gate `eval` system against **all 11 functions** individually, all reaching `DELIVER`.
- **Found a real bug in the platform itself**: `eval/mutation.py`'s gate 6 mutated `return` statements in file order across the *whole* SUT file, capped at 8 — so multi-function files exhausted the mutation budget on early, unrelated functions before ever reaching the function actually under test (proven with exact numbers: `isWinner` went from "0/8 caught" to "4/4 caught" purely from the fix, with no test changes).
- **Fixed it**: scoped mutation to only the function(s) containing the `--changed` lines, in `eval/mutation.py`, `eval/gates.py`, `eval/cascade.py`. Verified no regressions (17/17 existing eval tests still pass). Re-confirmed all 11 functions now test correctly **directly against the real, unmodified file** — no more need to isolate functions into separate files.

## 6. Real bug found and fixed in the user's actual code

- `isWinner`'s column-win check had `symbol_2` in both the `if` and `elif` branches (should have been `symbol_1` in the `if`) — meaning a column win for `symbol_1` could never be detected. Fixed directly in `Pam Qian_Tic Tac Toe_2016.py`.

## 7. `requirement_agent` — deterministic core verified

- Ran its bundled test suite (`test_boundary.py`, `test_emit.py`, `test_facts.py`, `test_render.py`) — **18/18 passed**. These cover the grounding/doc-validity/coverage gates, the emit/manifest tools, quad-file loading, and the markdown renderer — all explicitly Bedrock-free.
- The actual AI spec-writing step (via Strands + Bedrock) remains unverified — blocked on AWS credentials.

## 8. Verification report — ran successfully

- Ran `check_quadfile` (part of `verification/verify_all.py`) against TICTACTOE's quad file — mostly `PASS`/`INFO`, with 2 expected `WARN`s (zero journeys detected; one needs-wiring fragment, consistent with `main` having no caller in the graph).

## 9. Component inventory across the whole repo (13 top-level components)

| Category | Components |
|---|---|
| Always AI-free by design | `analyzer`, `eval`, `ingestion`, `checkpoints`, `sandbox`, `validator`, `verification` |
| Hybrid (partial offline mode) | `core` (`onboard` vs `generate`), `requirement_agent` (core vs AI writing), `scoring` (regex vs Bedrock mode) |
| Needs Bedrock, but has Bedrock-free unit tests | `analyzer_agent`, `coding_agent` |
| Needs Bedrock, no offline verification possible | `spec_agent` (older duplicate of `requirement_agent`) |

## 10. Git — repository set up and pushed

- Confirmed existing `.gitignore` already correctly excludes `.venv`, `node_modules`, `.env` secrets, `.platform_runs/`, caches.
- Committed and pushed to `https://github.com/AkshitRajani/Automated-AI-Platform.git` — confirmed `main` branch up to date with `origin/main`.

## 11. Postgres GUI access — set up

- Installed a VS Code database client extension and connected to the Knowledge Base Postgres (`127.0.0.1:5432` / `knowledge_base` / `postgres`/`postgres`) — confirmed working via a live `SELECT` query returning TICTACTOE's function data.

---

## What remains unverified (requires AWS Bedrock)

- AI spec generation (`requirement_agent`'s actual writing step, `spec_agent`)
- AI test generation (`core generate`)
- Bedrock-based behavior profiling in `scoring` (regex mode works without it)

## Known open items

- `scoring`'s test suite, `analyzer_agent`'s test suite, `coding_agent`'s test suite, and `validator`'s bundled examples were provided as commands but not yet confirmed executed in this session.
