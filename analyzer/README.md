# Analyzer — code → spec (the onboarding front door)

Turns a codebase into the **entities + quads** the ingestion `quad_parser`
consumes — the missing first step that produces the spec the rest of the pipeline
needs. This is **v1: Step 1 only — a deterministic Python parser, no LLM.**

The design (MASTER_DESIGN §5.1) is one analyzer, two internal steps:
1. **Parser (this)** — static analysis → the canonical structural facts → Postgres + Neptune.
2. **LLM enrichment (later)** — meaning/summaries → pgvector. Not in v1.

The split was settled by experiment (`2026/experiments/analyzer_ab/`): the parser
is the **source of truth** because it is exhaustive, free, and — load-bearing —
**reproducible** (an LLM-built graph churned 99% on unchanged code).

---

## What it extracts (pure `ast`, every file, all node types)

**Entities** (nodes): `Module`, `Class`, `Function`, `Method` — each with `file:line`.

**Quads** (edges), keyed by the predicate ingestion routes on:

| Predicate | From | → |
|---|---|---|
| `EXPOSES_ENDPOINT` | FastAPI `@app.get(...)` / Flask `@app.route(...)` | app_endpoints |
| `READS_FROM_S3` · `WRITES_TO_S3` | boto3 `get_object` / `put_object` / … | app_s3_paths |
| `INVOKES_LAMBDA` · `INVOKES_STEP_FUNCTION` | `client.invoke(...)` / `start_execution(...)` | app_service_invocations |
| `READS_ENV_VAR` | `os.environ[...]` / `os.getenv(...)` (incl. module-level) | app_parameters |
| `QUERIES_DATABASE` · `WRITES_DATABASE` | SQL in `.execute("...")` | app_tables |
| `CALLS` | app-internal function calls (resolved to entity ids) | Neptune edge |
| `DEFINES` | module/class → its members | Neptune edge |

**Honest by construction:** a string literal becomes a `resolved=True` fact; a
variable (`Bucket=bucket`, `FunctionName=self.lambda_name`) becomes a symbolic
object with `resolved=False` — left for the ingestion **bindings resolver**
(§5.3) to fill in. The analyzer never guesses a value.

---

## Run it

```bash
# a Python codebase → a quad YAML for ingestion
python -m analyzer /path/to/app --app-id DEMO --out quad.yaml --stats
```

```python
from analyzer import analyze, to_yaml
qf = analyze("/path/to/app", app_id="DEMO")
open("quad.yaml", "w").write(to_yaml(qf))
```

Validated on the sandbox app: **132 entities, 279 quads, 0 quarantined** through
the real `quad_parser`, deterministic, 0.1s, $0.

---

## Properties

- **Deterministic** — same code in → byte-identical quad file out (Neptune diffing depends on this).
- **Comprehensive** — every file, every `def`/`class`, env reads at module *and* function level (the 491→580 completeness lesson baked in).
- **Contract-clean** — output feeds the existing ingestion with **zero quarantine** (a test asserts it).
- **Pure stdlib `ast`** — no LLM, no external deps beyond PyYAML (already an ingestion dep).

---

## Layout

```
analyzer/
├── __main__.py   # CLI
├── extract.py    # the ast parser: code → entities + quads
├── emit.py       # entities + quads → quad YAML (ingestion-compatible)
├── models.py     # Entity / Quad / QuadFile
├── tests/        # 8 tests incl. the ingestion-contract test
└── README.md
```

**Next:** the Java/TS parsers (same entities+quads contract, different front end),
then Step 2 (LLM enrichment → pgvector) and the `kb_raw_code` agent tool.
