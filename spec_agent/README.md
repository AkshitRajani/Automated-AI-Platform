# Requirement Agent

Generates a **requirement document per testable unit** of an application — the same
nine-section, client-style spec your Automated AI Platform viewer produces — by reading the analyzer's
output and (optionally) the raw source. It is an onboarding-time producer: it runs once
per application, **beside the analyzer**, and its output feeds the ingestion pipeline that
builds the knowledge base.

The agent is autonomous (Strands + Amazon Bedrock) but wrapped in a **deterministic
boundary**: every name it writes is re-checked against the analyzer's facts, every
document must be complete, and every unit must be accounted for — or the run does not
deliver.

---

## What it does, in one paragraph

Point it at one application's analyzer output. It discovers every unit, decides which are
functional entry points (handlers, step functions, endpoints, ETL workflows) versus data
assets or internal helpers, and for each functional unit writes a grounded requirement
document — system overview, I/O contract, requirements, function spec, user stories with
Given/When/Then acceptance criteria (including negative paths), traceability, confidence
mapping, and a gap analysis. Because the requirements are derived **from the code**, every
behavior is stamped **`code-derived`** (`requirement_backed: false`) — usable as *context*
for what to test, never as proof of what is correct, until a real requirement (JIRA/STTM)
backs it. There is **no misleading numeric confidence**: provenance is an honest label, and
a computed *grounding* descriptor reports how strongly each document is backed by the facts.

---

## Prerequisites

- **Python 3.10+** (developed on 3.11).
- **Amazon Bedrock access** to a Claude model, with AWS credentials available to `boto3`
  (env vars, shared profile, or an instance/role — the standard AWS chain).
- Python dependencies (see `requirements.txt`):
  ```
  strands-agents
  strands-agents-tools
  boto3
  pydantic>=2
  pyyaml
  ```

> Only the **live run** needs Bedrock. The gates, the facts loader, the schemas, the
> renderer, and the full test suite are pure stdlib + pydantic + pyyaml and run with no
> model and no network.

---

## Install

Place the `spec_agent/` folder inside a directory on your `PYTHONPATH`, then:

```bash
pip install -r spec_agent/requirements.txt
```

Create a `.env` (in the directory you run from, or any parent) with your Bedrock model:

```dotenv
# .env
BEDROCK_MODEL_ARN=us.anthropic.claude-opus-4-8     # a model id or an inference-profile ARN
AWS_REGION=us-east-1
```

The model id is **never defaulted** — if `BEDROCK_MODEL_ARN` is unset the agent fails fast
rather than guessing a model.

---

## Input

### 1. The analyzer output (required)

A single **quad YAML** file — the analyzer's `entities` + `quads` for one application. This
is the same artifact the analyzer already emits. Minimal shape:

```yaml
metadata:
  app_id: APP                       # optional; --app-id overrides
entities:
  - id: "LambdaHandler:my_handler"
    type: LambdaHandler              # LambdaHandler | StepFunctionStateMachine | WorkflowFile | APIEndpoint | Function | Table | S3Object | ...
    name: my_handler
    source: { file_path: handlers/my_handler.py, line_start: 1, line_end: 90 }
quads:
  - subject: "LambdaHandler:my_handler"
    predicate: QUERIES_DATABASE      # QUERIES_DATABASE | WRITES_DATABASE | WRITES_TO_S3 | EXPOSES_ENDPOINT | INVOKES_LAMBDA | RAISES_ERROR | ...
    object: "Table:my_table"
    context: { resolved: true }
```

- **`entities`** — everything the analyzer found (the discovery surface *and* the coverage
  denominator: every entity must end up documented or covered by a skip).
- **`quads`** — what each entity touches; these are the **real names** the agent is allowed
  to use. Anything not present here (or in the raw source) is treated as not real.

### 2. The raw source (optional)

A `.zip` or a folder of the application's code, passed with `--codebase`. When given, the
agent can read the actual code on demand (read-only) to state behavior the quads don't
capture. When omitted, it grounds from the quad facts alone and **says so** in each
document's gap analysis.

---

## Run

From the directory that contains the `spec_agent/` package:

```bash
PYTHONPATH=. python -m spec_agent  <analyzer_output.yaml>  --app-id <APP_ID>  [options]
```

| Argument | Required | Meaning |
|---|---|---|
| `analyzer_output.yaml` | yes | path to the analyzer quad file |
| `--app-id` | yes | the application id / KB scope (e.g. `APP`) |
| `--codebase <path>` | no | the raw source (`.zip` or folder) for `read_source` |
| `--workspace <dir>` | no | output directory (default: a fresh temp dir, printed at start) |

**Example:**

```bash
PYTHONPATH=. python -m spec_agent  ./quads/app.yaml \
  --app-id APP \
  --codebase ./src/app.zip \
  --workspace ./out/app
```

**Exit code:** `0` if delivered (all gates passed), `1` if routed to a human (gates could
not be satisfied within the repair budget). Either way the output and the full log are
written for inspection.

---

## Output

Everything lands under the workspace:

```
<workspace>/
├── requirements/                 # MACHINE-READABLE: one JSON per unit (what ingestion loads)
│   ├── <unit-slug>.json
│   └── ...
├── requirements_md/              # HUMAN-READABLE: the same docs as client-style markdown
│   ├── <unit-slug>.md
│   └── ...
├── requirements_manifest.json    # the index: every unit (documented / skipped) + skipped types
└── agent_log.txt                 # full trace: every tool call + the agent's reasoning
```

> **One requirement document per testable unit** (not one per app). An app with one Lambda
> produces one document; an app with eight ETL workflows produces eight. The `requirements/`
> (JSON) and `requirements_md/` (markdown) folders hold the **same documents in two
> formats** — JSON for the system to ingest, markdown for a person to read.

### The nine sections (every document)

1. **System Overview** — what the unit is and does
2. **Input Specification** — the inputs / sources it consumes (table)
3. **Consolidated Requirements** — "The system shall …"
4. **Output Specification** — the outputs / response it produces (table)
5. **Function Specification** — the entry point + helpers (purpose / params / returns / raises)
6. **User Stories** — `As a …, I want …` + Given/When/Then acceptance criteria (incl. negative paths)
7. **Traceability Matrix** — requirement → functions → story
8. **Confidence Mapping** — provenance/confidence per story
9. **Gap Analysis** — coverage, missing requirements, recommendations, technical debt

### The per-unit JSON (what ingestion consumes)

```jsonc
{
  "unit": "WorkflowFile:.../alf_klc.yml",
  "unit_type": "WorkflowFile",
  "title": "ALF KLC Calculation Workflow",
  "provenance": "code-derived",         // code-derived | jira:<id> | sttm:<id>
  "requirement_backed": false,          // true only when a real requirement backs it
  "confidence": null,                   // NOT asserted for code-derived (never a fake 0.0)
  "grounding": "grounded in 11 analyzer fact(s); no raw source; 11 of 11 names are unresolved deployment tokens (${...})",
  "grounded_identifiers": [          // every real name used — re-checked at the boundary
    "DatabaseTable:${LN_GFEE_CALC_SPST...}",
    "DatabaseTable:${BK_SCORED...}"
  ],
  "sections": {                      // section name -> markdown body
    "System Overview": "...",
    "Input Specification": "| Data Source | Field | ... |",
    "...": "..."
  }
}
```

### The manifest (`requirements_manifest.json`)

```jsonc
{
  "app_id": "APP",
  "provenance": "code-derived",
  "entries": [
    { "unit": "...", "unit_type": "WorkflowFile", "status": "documented",
      "doc_file": "requirements/..._json", "grounded_identifiers": [...],
      "provenance": "code-derived", "requirement_backed": false, "grounding": "grounded in 11 analyzer fact(s); ..." }
  ],
  "skipped_types": [
    { "entity_type": "DatabaseTable", "reason": "data assets, not testable units" },
    { "entity_type": "S3Object",      "reason": "data assets, not testable units" }
  ]
}
```

---

## How it works

```
analyzer quad (+ optional source)
        │
        ▼
  AUTONOMOUS AGENT  (Strands + Bedrock)
   1. list_units            → discover every unit, decide units vs. data/helpers
   2. read_facts(unit)      → ground the real inputs/tables/services/errors
   3. (read_source …)       → read the raw code when facts aren't enough
   4. start_unit / write_section / finish_unit   → build each doc, one section at a time
      skip_type(type, reason)                    → mark a whole non-unit type
        │
        ▼
  DETERMINISTIC BOUNDARY  (plain code, no model)
   • Grounding gate   — every claimed name exists in the analyzer facts (else reject)
   • Doc-validity gate— every documented unit has all nine sections, non-empty
   • Coverage gate    — every analyzer entity is documented or covered by a skip
   • Bounded repair   — on any failure, feed the findings back to the agent (≤2 times),
                        then route to a human
        │
        ▼
  DELIVER  →  per-unit JSON + markdown + manifest + log
```

**Tools the agent has (nine, no general file/shell access):**

| Tool | Purpose |
|---|---|
| `list_units` | enumerate every unit, grouped by type (uncapped) |
| `read_facts(unit)` | what one unit touches — its real names (uncapped) |
| `read_source` / `search_source` / `list_source` | read-only navigation of the raw source |
| `start_unit` / `write_section` / `finish_unit` | build a document incrementally |
| `skip_type` | declare a whole entity type not a testable unit, with a reason |

---

## Design guarantees

- **Any document size.** Documents are written **section by section** (each `write_section`
  appends; a section can be built across many calls), and plain code assembles + validates
  + writes the file. No single model response ever holds a whole document, so document size
  is independent of the model's output-token limit.
- **Nothing invented.** Every name in a document is re-checked against the analyzer facts by
  the grounding gate; ungrounded names are rejected and repaired. If a fact isn't there, the
  document says so in Gap Analysis rather than guessing.
- **Whitebox-safe by construction.** Because the requirements are derived from code, every
  document carries `provenance = code-derived` and `requirement_backed = false`. The
  **interface/contract** (the real I/O names) is always usable for grounding; a **behavior
  rule** is trusted as an oracle only once a real requirement (JIRA/STTM) backs it. This
  prevents "generate a spec from the code, then test the code against that spec" from
  collapsing into a circular test.
- **Honest confidence — never a fake 0.0.** A code-derived behavior has nothing to measure
  numeric alignment against, so `confidence` is reported as **`null` (not asserted)**, not a
  misleading `0.0`. Instead each document gets a **computed `grounding`** descriptor — how
  many analyzer facts back it, whether raw source was available, how many names are
  unresolved `${...}` deployment tokens — which genuinely varies per unit. When JIRA/STTM
  matching backs a behavior, `requirement_backed` flips to `true` and `confidence` becomes a
  real alignment score.
- **Nothing hardcoded.** No application, table, column, or framework names live in the code.
  What to document, and which types are units, is decided at run time from the analyzer
  output.
- **Deterministic verdict.** Delivery is decided by plain, testable gates — not by the model.

---

## Tests

```bash
PYTHONPATH=. python -m pytest spec_agent/tests/ -q
```

The suite is pure (no Bedrock): the facts loader, the three gates, the incremental emit
flow, and the renderer.

---

## File map

| Path | Role |
|---|---|
| `agent.py` | builds the Strands + Bedrock agent (tools, prompt, model config) |
| `prompts.py` | the system prompt |
| `boundary.py` | the three gates + bounded-repair loop; assembles the manifest |
| `schemas.py` | the data contracts + the nine canonical sections |
| `facts.py` | loads the analyzer quad; backs the grounding tools |
| `render.py` | turns a document's JSON into client-style markdown |
| `tools/analyzer_facts.py` | `list_units`, `read_facts` |
| `tools/read_source.py` | `read_source`, `search_source`, `list_source` |
| `tools/emit.py` | `start_unit`, `write_section`, `finish_unit`, `skip_type` |
| `config.py`, `_env.py` | read `BEDROCK_MODEL_ARN` / `AWS_REGION` from `.env` |
| `run_log.py` | writes `agent_log.txt` |
| `__main__.py` | the CLI |
| `tests/` | the pure test suite |

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `BEDROCK_MODEL_ARN is not set` | add it to `.env` (a model id or inference-profile ARN) |
| `NoCredentialsError` / AccessDenied | provide AWS credentials with Bedrock access (env / profile / role) |
| Every unit's gap analysis says "not grounded / read the source" | no `--codebase` was given — the run grounded from quad facts only; pass the source to deepen the docs |
| `ROUTED TO HUMAN` (exit 1) | a gate could not be satisfied within the repair budget — read the "unresolved gate findings" in the run output and `agent_log.txt` |
| Example payload values look generic | example *values* are illustrative; the **names** (tables, endpoints, paths) are grounded — illustrative values are flagged where tokens are unresolved |

---

## Scope notes (current state)

- Requirements are **code-derived** (`requirement_backed: false`, `confidence: null`);
  JIRA/STTM matching — which sets `requirement_backed: true` and a real `confidence` score —
  is a planned fast-follow.
- Output is per-unit JSON + markdown. Wiring these into the ingestion pipeline
  (Postgres / pgvector / Neptune) is the next integration step.
- Example *values* inside payloads are illustrative, not grounded; grounded **names** are
  guaranteed by the boundary.
