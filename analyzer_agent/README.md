# Analyzer Agent — Step 2 (code → cross-file spec)

The **second agent** in the system (alongside the Coding Agent). It takes a codebase
**plus the deterministic Step-1 parser draft** and recovers what static parsing
can't see on its own — **cross-file call chains and data lineage** — emitting facts
that a deterministic gate verifies before they can enter the graph.

This is `MASTER_DESIGN.md §5.1 / §5.1.1` (and `02_analyzer.md`) made runnable. It is
**Step 2 only**; Step 1 (the parser) and the grounding gate live in the sibling
`analyzer/` package and are reused verbatim.

```
repo ─▶ analyzer (Step 1 parser, built) ─▶ draft (entities + quads)
                                              │
        analyzer_agent (this) ─ Strands+Bedrock, navigates repo + draft
                                              │  emit_fact(+file:line)
                                              ▼
              analyzer.verify (grounding gate, built, deterministic)
                  ├─ verified  ─▶ graph facts  (Postgres + Neptune)
                  └─ semantic  ─▶ notes        (pgvector)
```

## Dependency floor (hard constraint)
`strands` + `strands_tools` + Python **stdlib** + our own `analyzer` / `ingestion`.
**No LangChain / LangGraph / agent frameworks. No regex, no hardcoded name-lists**
in this package — structure comes from the parser's AST and the gate.

## The pieces

| File | Role |
|---|---|
| `agent.py` | Strands `Agent` + `BedrockModel` assembly (mirrors `coding_agent/agent.py`); `run(task)` → populated `FactStore` |
| `config.py` | `.env`-driven settings (reuses `ingestion.config.load_config`); model ARN **never defaulted** |
| `canonical.py` | the `Type:qualified-name` id contract — kept in lock-step with ingestion's node scheme |
| `store.py` | `FactStore` — every emit routed through `analyzer.verify` → graph / notes / rejected |
| `prompts.py` | the system prompt (job, grounding rule, id rule) — no codebase specifics |
| `hooks.py` | `RepoConfinementHook` — confine `file_read`/`shell` to the repo (read-only cage) |
| `tools/` | `repo_map` · `parser_facts` · `emit_fact` · `lsp_resolve` (config-gated) + `_strands` shim |

## Tools (smooth, Python-first)
The parser is wired **two ways** (per §5.1.1): its full upfront output is the
backbone the agent reads, *and* it's exposed as a live tool for on-demand re-parse.
- `file_read`, `shell` (grep/glob) — Strands built-ins, repo-confined, read-only.
- `repo_map()` — whole-repo structural map from the parser draft (no tree-sitter).
- `parser_facts(file, only_unresolved)` — the deterministic backbone + the gaps.
- `parse(path)` — **Level 2**: run the parser LIVE on one file (for a file not in the
  draft, or to get clean canonical facts instead of inferring). Parsed against the
  repo root, so its ids match the draft exactly — verified by `test_parse_tool`.
- `emit_fact(subject, predicate, object, file, line, kind, note)` — the only write,
  verified at its `file:line` before it can reach the graph.
- `lsp_resolve(...)` — optional, wired **only** when `ANALYZER_LSP_ENDPOINT` is set;
  otherwise the agent leans on grep + `parser_facts` (graceful degrade).

> **Two levels.** Level 1 = the upfront full parse (the deterministic, diffable
> backbone — non-negotiable). Level 2 = `parse(path)` on demand. The backbone never
> depends on the agent's choices; the live tool only fills gaps and handles files
> the one-shot draft missed (and, later, dispatches to the Java/TS parsers with no
> change to the agent).

## Config (everything parameterized — `.env`)
| Key | Meaning |
|---|---|
| `BEDROCK_MODEL_ARN` | model id / inference-profile ARN — **required, never defaulted** |
| `AWS_REGION` | Bedrock region |
| `ANALYZER_LANGUAGES` | `python` (v1); future `java,angular,react` |
| `ANALYZER_MAX_ITERATIONS` | autonomous-loop cap |
| `ANALYZER_FANOUT` / `ANALYZER_MAX_SUBAGENTS` | sub-agent fan-out on/off + cap |
| `ANALYZER_SCOPE` | `exhaustive` / `changed-only` |
| `ANALYZER_LSP_ENDPOINT` | LSP-over-MCP endpoint (empty → LSP tool off) |
| `PG_*` · `NEPTUNE_*` | stores (shared with ingestion; degrade if unset) |

## Run
```bash
PYTHONPATH=/path/to/2026/implementation \
  python -m analyzer_agent /path/to/app --app-id DEMO --out facts.yaml
```
Requires the Strands runtime + a valid `BEDROCK_MODEL_ARN`. Output is an
ingestion-ready quad YAML of **verified** facts, plus run stats
(graph facts / notes / rejected / precision).

## The canonical-id precondition
The agent's edges only connect if their endpoints match ingestion's node ids.
ingestion writes `f"{app}:{type}:{name}"` for nodes and `f"{app}:{quad.subject}"`
for edges — so subjects/objects **must** be `Type:qualified-name` ids.
`canonical.py` is that contract and `tests/test_canonical.py` locks it to the real
`neptune_writer` f-strings so they can't drift (the 0%-connect bug from the build
session). The Step-1 parser must adopt the same scheme for its own entities — a
shared, one-time fix.

## Tests
```bash
PYTHONPATH=/path/to/2026/implementation python -m pytest analyzer_agent/tests -q
```
18 tests, pure stdlib, no Strands/Bedrock needed — they cover the canonical-id
contract, the store/grounding-gate routing, the repo guard, the config-gated tool
registry, and the injected tools against a draft. The autonomous loop itself needs
the live runtime (same as `coding_agent`).
