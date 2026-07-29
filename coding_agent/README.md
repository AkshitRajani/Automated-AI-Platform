# Coding Agent

Autonomous **Strands + Bedrock** agent that writes a **grounded** regression-test
bundle for a code change. Canonical design:
[`2026/solution/final_design/04_coding_agent_agentic.md`](../../solution/final_design/04_coding_agent_agentic.md).

The agent is autonomous *inside* a deterministic boundary: it reasons and calls
its tools in whatever order it judges best (Strands runs the loop), while the
guarantees — every emitted name is real, an external grader certifies pass/fail,
repair is bounded — are enforced in plain code around it, never trusted to the
prompt.

**Slice 1 (locked 2026-06-16):** Python-in / **Behave**-out · `app_id`-only KB
scoping · workspace-scoped `shell` on.

## Layout

| Module | Role | Needs Strands? |
|---|---|---|
| `schemas.py` | `AgentTask` in / `TestBundle` out (flat Pydantic contracts) | no |
| `config.py` | reuses `ingestion.config` — all conn values from `.env` | no |
| `kb/facts.py` | `kb_query` backend — Postgres fact lookups (injected conn) | no |
| `kb/graph.py` | `kb_graph` backend — Neptune lineage (degrades if absent) | no |
| `tools/` | thin `@tool` wrappers over the backends + validator | no* |
| `prompts.py` | the agent system prompt (5 hard rules) | no |
| `agent.py` | assembles `Agent(model, prompt, tools, hooks)` | **yes** (in `build_agent`) |
| `hooks.py` | workspace-confinement BeforeToolCall hook | yes |
| `boundary.py` | grounding gate + lint gate + bounded repair | gate is pure; repair needs Strands |
| `__main__.py` | CLI: `python -m coding_agent task.json` | yes (at run) |

\* Tool modules import via a shim that falls back to an identity decorator when
Strands is absent, so the backends stay unit-testable. `build_agent` imports
Strands directly, so there is no way to silently run the real agent without it.

## Design principles (held throughout)

- **Never hardcode connections.** Every Postgres/Neptune/Bedrock value comes from
  the shared `.env` via `config.py`. Swap environments by swapping `.env` alone.
- **Anthropic standards.** Six high-leverage coarse tools; actionable empties
  ("not found … do not invent"); human-readable names + provenance, not raw ids;
  `response_format`/`limit` for token control; no tool reaches the grader.
- **Autonomous.** The agent decides tool order and recovers from tool errors
  itself; determinism lives only at the boundary.

## Run

```bash
cp ../.env.example ../.env   # fill in PG_*, NEPTUNE_* (optional), BEDROCK_MODEL_ARN
pip install -r requirements.txt
PYTHONPATH=/path/to/2026/implementation python -m coding_agent example_task.json
```

## Test

```bash
PYTHONPATH=/path/to/2026/implementation python -m pytest coding_agent/tests -q
```

Tests cover the backends, tools, workspace guard, and grounding gate with no
live DB / Neptune / Strands. The live agent loop needs a Strands-installed
environment with valid Bedrock + KB settings.

## What's backed vs. stubbed (slice 1)

| Capability | Status |
|---|---|
| `kb_query` facts (14 Postgres tables) | ✅ real |
| `kb_query` vector | ⚠️ stub (no pgvector table yet) |
| `kb_query` columns / UI selectors | ❌ gap (no such table) — returns a flagged empty |
| `kb_graph` (Neptune) | ✅ real when configured; degrades to actionable empty otherwise |
| `lint_tests` (Behave/Python) | ✅ real (wraps the built validator) |
| External Eval (real-invocation / coverage / mutation) | separate component; slots into `boundary.py`, never a tool |
| 4-axis scope / provenance | ⚠️ `app_id` only (ETSAPS-4264, the client-owned) |
