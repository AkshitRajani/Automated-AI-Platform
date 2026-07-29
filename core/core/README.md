# Core — the wired end-to-end workflow

The orchestration spine that connects the built components into the two flows of
`MASTER_DESIGN.md §3`. **This is the part that ships to the client.** It is
dependency-pure (`strands` + stdlib + our components only) — no Flask, no MLflow,
no web concerns. It only *emits* a structured event stream; sinks are attached from
outside.

```
ONBOARDING   codebase ─▶ analyzer(parser) ─▶ analyzer_agent ─▶ ingestion ─▶ KB
PER-CHANGE   ticket+diff ─▶ coding_agent ─▶ eval(gate cascade) ─▶ deliver
OPTIONAL     generated features ─▶ scoring ─▶ score_report.json + .html
```

## Use
```python
from core import Pipeline
pipe = Pipeline()                                   # reads .env
pipe.trace.add_listener(my_sink)                    # observe everything (optional)

pipe.onboard("s3://bucket/app.zip", app_id="DEMO")  # dir | .zip | s3://
pipe.generate(ticket_text="...", diff="...", app_id="DEMO",
              workspace_dir="./ws", framework="behave")
pipe.score(app_id="DCFO", generated_dir="./ws/features", golden_dir="./feature")
```
CLI: `python -m core onboard <src> --app-id DEMO` · `python -m core generate ...` · `python -m core score ...`

## The pieces
| File | Role |
|---|---|
| `pipeline.py` | `Pipeline` facade — owns config + trace, exposes `onboard` / `generate` / `score` |
| `onboarding.py` | parser → analyzer_agent → merge → ingestion, each a trace span |
| `generate.py` | coding_agent + eval (injected as the external judge into the boundary) |
| `score.py` | behaviour-based BDD benchmark → JSON + HTML reports (wraps `scoring`) |
| `execenv.py` | config-selected eval execution env: `InProcessEnv` / `SandboxEnv` |
| `source.py` | resolve a source to a local dir: directory / `.zip` / `s3://` |
| `config.py` | `CoreConfig` from `.env` (reuses ingestion's loader) |
| `trace.py` | the observability backbone — nested spans, pluggable listeners, zero deps |

## How the wiring respects the design
- **Eval is outside the agent.** `generate` injects the gate cascade into
  `coding_agent.boundary.run_with_boundary(external_eval=...)` — the slot the
  boundary reserved. The agent is graded from outside and never reaches the eval as
  a tool; failed-gate reasons feed the existing repair loop in the same shape.
- **A/B parity is one config line.** `CORE_EVAL_ENV=inprocess|sandbox` swaps the
  execution env; the cascade is identical. `sandbox` unavailable → falls back to
  in-process (a run is never blocked on Docker).
- **Everything configurable.** Onboarding source, AWS creds/region, store
  endpoints, repair cap, stability/mutation counts — all from `.env`.
- **Honest degradation.** No Bedrock → the analyzer agent is skipped (parser-only
  onboarding, logged). No Postgres → the merged quad YAML is still written for
  inspection, ingestion reported as skipped. Nothing is faked.

## Config (`.env`, added on top of the shared ingestion/agent keys)
| Key | Meaning | Default |
|---|---|---|
| `CORE_EVAL_ENV` | `inprocess` / `sandbox` | `inprocess` |
| `CORE_SANDBOX_DIR` | sandbox checkout (when `sandbox`) | — |
| `CORE_QUAD_DIR` | where merged quad YAMLs are staged | temp dir |
| `CORE_MAX_REPAIRS` | agent repair attempts | `2` |
| `CORE_STABILITY_RUNS` / `CORE_MUTATION_MAX` | gate 7 / gate 6 counts | `3` / `8` |
| `CORE_GOLDEN_BDD_ROOT` | per-app golden BDD root | `golden_bdd` |
| `CORE_SCORE_OUTPUT_DIR` | score report output dir | cwd |
| `SCORING_THRESHOLD` | behaviour match threshold | `0.45` |
| `BEDROCK_MODEL_ARN`, `AWS_REGION`, `PG_*`, `NEPTUNE_*` | inherited (shared `.env`) | — |

## Observability
The core emits `core.trace` events (nested spans for every stage, log/metric
entries). The CLI attaches a stdout sink; the **web backend** (separate package)
attaches the MLflow sink + the live UI feed. The core itself never imports any of
that — which is why it stays clean for the client.

## Tests
```bash
PYTHONPATH=/path/to/2026/implementation python -m pytest core/tests -q
```
12 tests, no Bedrock/AWS needed: trace nesting, source resolution, parser-only
onboarding (graceful degrade), the diff parser (gate-5 lines), and the exec-env
selector. The live loops (agent, ingestion load) need the runtime + stores.
