# Automated AI Platform

Automated AI Platform turns a **real application codebase** into a **Knowledge Base (KB)**, uses an AI agent to write **grounded Behave regression tests** for code changes, and runs a **7-gate quality cascade** before delivering tests. A local **sandbox** (LocalStack + Microcks + Postgres) can run those BDD bundles against mock AWS infrastructure.

> **This repository is the platform only.** It does **not** include a sample application under test. Point the tools at any app you own (Python microservices, etc.) during onboarding.

---

## What it does

| Problem | Solution |
|---------|----------|
| Tests invent fake Lambda names, tables, endpoints | KB built from static analysis + verified AI enrichment |
| AI writes plausible but hollow tests | Grounding gate + 7-gate eval (including mutation testing) |
| No local way to run AWS-style integration tests | Sandbox boots Lambdas, S3, Step Functions, Postgres from `spec.yaml` |
| Onboarding vs per-change are different workflows | `core` orchestrates both end-to-end |

**Two main flows:**

```
ONBOARDING (once per app)     codebase → analyzer → analyzer_agent → ingestion → KB
PER-CHANGE (per ticket)       ticket + diff → coding_agent → eval → delivered test bundle
                              optional: score generated BDD vs golden manual BDD
```

---

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │              core (orchestrator)         │
                         │   onboard() · generate() · score() · trace │
                         └───────────────┬─────────────────────────┘
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         │ ONBOARDING                    │ PER-CHANGE                     │
         ▼                               ▼                               │
  ┌──────────────┐                ┌──────────────┐                        │
  │  analyzer/   │ Step 1: AST    │ coding_agent │ Strands + Bedrock      │
  │  (parser)    │ parser, no LLM │              │ writes Behave tests    │
  └──────┬───────┘                └──────┬───────┘                        │
         │                               │                                │
  ┌──────▼───────┐                ┌──────▼───────┐                        │
  │analyzer_agent│ Step 2: cross- │  boundary    │ grounding + lint       │
  │  (AI enrich) │ file facts     │  + eval      │ + 7-gate cascade       │
  └──────┬───────┘                └──────────────┘                        │
         │                               │                                │
         ▼                               ▼                                │
  ┌──────────────┐                ┌──────────────┐                        │
  │  ingestion   │ Postgres +     │  validator   │ static Behave lint      │
  │              │ Neptune        │              │                         │
  └──────────────┘                └──────────────┘                        │
         │                                                                 │
         ▼                                                                 │
  ┌──────────────┐                ┌──────────────┐                        │
  │  KB stores   │◀───────────────│   sandbox    │ LocalStack BDD runner  │
  │ PG + Neptune │   kb_query     │              │                        │
  └──────────────┘                └──────────────┘                        │
```

Supporting modules: `spec_agent` / `requirement_agent` (docs from analyzer facts), `scoring` (generated vs golden Gherkin), `verification` (KB/quad health checks).

---

## Repository layout

```
automated_ai_platform/
├── analyzer/              # Deterministic AST/Java/TF parser → quad YAML
├── analyzer_agent/        # Strands + Bedrock enrichment of parser facts
├── ingestion/             # Quad YAML → Postgres (+ optional Neptune)
├── coding_agent/          # Ticket + diff → grounded Behave test bundle
├── spec_agent/            # Journey / spec docs from analyzer facts
├── requirement_agent/     # Per-unit requirement docs
├── validator/             # Static Behave step linter
├── eval/                  # 7-gate quality cascade (incl. mutation)
├── scoring/               # Generated vs golden Gherkin scoring (+ UI)
├── core/                  # Orchestrator: onboard / generate / score
├── sandbox/               # LocalStack + Microcks + FastAPI/React UI
├── verification/          # Read-only health checks
├── checkpoints/           # Human checkpoint helpers
├── docs/                  # Architecture / onboarding notes
├── docker-compose.local.yml
├── setup_platform.ps1     # One-time: venv + pip install
├── setup_env.ps1          # Every terminal: PYTHONPATH + activate venv
├── start_local.ps1        # Docker: KB Postgres + sandbox stack
└── sync_aws_env.py        # Copy AWS/Bedrock keys across .env files
```

Runtime artifacts (quads, workspaces, reports) are written under `.platform_runs/` locally and are gitignored.

---

## Prerequisites

| Tool | Version | Required for |
|------|---------|--------------|
| **Python** | 3.12+ recommended (`py -3.12` on Windows) | All modules |
| **Docker Desktop** | ≥ 4.30 | Local KB Postgres + sandbox |
| **Node.js + npm** | 18+ | Sandbox React UI only |
| **AWS credentials** | Bedrock-enabled account | AI agents (`analyzer_agent`, `coding_agent`, `spec_agent`, …) |
| **Git** | any recent | Clone / contribute |

**Not included / you must provide:**

- Your **application under test** (path on disk)
- Real **AWS Bedrock** model access (for AI-assisted flows)
- Optional: **Neptune** cluster (local runs can capture graph CSVs without live Neptune)

---

## Quick setup (Windows)

### 1. Clone and install the platform

```powershell
git clone <your-repo-url> automated_ai_platform
cd automated_ai_platform

# Creates .venv, installs module requirements, copies .env.example → .env
powershell -ExecutionPolicy Bypass -File .\setup_platform.ps1
```

### 2. Configure secrets

Edit the generated env files (never commit real `.env`):

| File | What to set |
|------|-------------|
| `ingestion/.env` | `PG_*` (local defaults below), optional `NEPTUNE_*`, `AWS_REGION`, Bedrock ARNs |
| `spec_agent/.env` | `BEDROCK_MODEL_ARN`, `AWS_REGION` |
| `requirement_agent/.env` | `BEDROCK_MODEL_ARN`, `AWS_REGION` |
| `scoring/scoring/.env` | Scoring paths / threshold; optional Bedrock for agent mode |

Templates live next to each file as `.env.example`.

**Local Postgres defaults** (after `start_local.ps1`):

```
PG_HOST=127.0.0.1
PG_PORT=5432
PG_DATABASE=knowledge_base
PG_USER=postgres
PG_PASSWORD=postgres
```

Optional helper to copy AWS/Bedrock keys from scoring into ingestion + spec_agent:

```powershell
.\.venv\Scripts\python.exe .\sync_aws_env.py
```

AWS credentials themselves use the normal boto3 chain (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`, shared profile, or instance role) — keep them out of committed files.

### 3. Start local infrastructure

Requires Docker Desktop running:

```powershell
powershell -ExecutionPolicy Bypass -File .\start_local.ps1
```

This brings up:

| Service | URL / DSN |
|---------|-----------|
| Knowledge Base Postgres (+ pgvector) | `localhost:5432` / `knowledge_base` / `postgres`/`postgres` |
| Sandbox Postgres | `localhost:5433` |
| LocalStack | http://localhost:4566 |
| Microcks | http://localhost:8080 |
| Sandbox API | http://127.0.0.1:8765/docs |
| Sandbox UI | http://localhost:5173/ |

Neptune cloud is optional locally — graph CSVs go under `.platform_runs\neptune\`.

### 4. Activate the environment (every new terminal)

```powershell
. .\setup_env.ps1
```

This sets `AAP_ROOT`, `PYTHONPATH`, and `AAP_PYTHON` (prefers `.venv`).

---

## Point the platform at your application

Replace `C:\path\to\your\app` and `MYAPP` with your values.

### A. Analyze → quads (no LLM)

```powershell
. .\setup_env.ps1
New-Item -ItemType Directory -Force -Path .\.platform_runs\quads | Out-Null

& $env:AAP_PYTHON -m analyzer C:\path\to\your\app `
  --app-id MYAPP `
  --out .\.platform_runs\quads\MYAPP.yaml `
  --stats
```

Tiny built-in fixture (platform self-check, not a product sample):

```powershell
& $env:AAP_PYTHON -m analyzer .\analyzer\tests\fixtures\sample_app `
  --app-id DEMO `
  --out .\.platform_runs\quads\DEMO.yaml `
  --stats
```

### B. Ingest quads into the KB

Ensure `ingestion/.env` points at local Postgres, then:

```powershell
& $env:AAP_PYTHON -m ingestion
```

Schema is applied by Docker on first boot (`ingestion/schema.sql`). To re-apply:

```powershell
Get-Content .\ingestion\schema.sql -Raw |
  docker exec -i aap_kb_postgres psql -U postgres -d knowledge_base
```

### C. Onboard via orchestrator (analyzer → agent → ingestion)

Needs Bedrock credentials:

```powershell
& $env:AAP_PYTHON -m core onboard C:\path\to\your\app --app-id MYAPP
```

### D. Generate tests for a change

```powershell
& $env:AAP_PYTHON -m core generate `
  --app-id MYAPP `
  --ticket-file .\ticket.txt `
  --diff-file .\change.diff `
  --workspace .\.platform_runs\MYAPP\workspace `
  --framework behave
```

### E. Offline-capable checks (no Bedrock)

```powershell
# 7-gate eval on bundled discount example
& $env:AAP_PYTHON -m eval `
  --sut .\eval\examples\discount\sut.py `
  --test .\eval\examples\discount\test_good.py `
  --changed .\eval\examples\discount\sut.py:6

# Score generated Gherkin vs golden
& $env:AAP_PYTHON -m core score `
  --app-id DCFO `
  --generated .\scoring\demo_suites\v2\feature `
  --golden .\scoring\demo_suites\golden\feature

# Validator / module help
& $env:AAP_PYTHON -m validator --help
& $env:AAP_PYTHON -m scoring --help
```

### F. Sandbox UI (if not already started)

```powershell
# API
cd sandbox\sandbox\web_app\backend
..\..\..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765

# UI (other terminal)
cd sandbox\sandbox\web_app\ui
npm install
npm run dev
```

Scoring UI:

```powershell
cd scoring
..\.venv\Scripts\python.exe run.py serve --open
```

More day-to-day commands: see [RUN_PLATFORM.md](./RUN_PLATFORM.md).

---

## Components (short)

| Module | Role |
|--------|------|
| **analyzer** | Deterministic parser → entities + quads (no LLM) |
| **analyzer_agent** | Cross-file enrichment via Strands + Bedrock; facts verified before KB |
| **ingestion** | Quad YAML → Postgres (+ Neptune CSV/S3 load) |
| **coding_agent** | Ticket + diff → Behave `.feature` + steps; KB-grounded identifiers |
| **validator** | Static Behave lint (stdlib) |
| **eval** | Binary deliver/reject across 7 gates (incl. mutation) |
| **scoring** | Behaviour match of generated vs golden Gherkin |
| **core** | `Pipeline.onboard` / `.generate` / `.score` |
| **sandbox** | Local AWS mock + web console |
| **spec_agent** / **requirement_agent** | Spec / requirement docs from analyzer facts |
| **verification** | Health checks for quads / KB / specs |

### Coding agent hard rules (enforced by gates)

1. Real invocation — never fake in-memory context  
2. Never invent a name — every literal must come from KB  
3. Real data from the ticket  
4. Follow the chosen framework exactly  
5. Parameterize endpoints, buckets, tokens  

### Eval gates

| Gate | Question |
|------|----------|
| 1 Runs | Parses / loads? |
| 2 Grounded | Every name real in KB? |
| 4 Real value | Asserts something concrete? |
| 3 Calls real code | Executed SUT lines? |
| 5 Covers change | Hit changed diff lines? |
| 6 Planted bug | Fails on mutated SUT? |
| 7 Stable | Same verdict on re-run? |

---

## Tech stack

| Layer | Tools |
|-------|-------|
| AI agents | **Strands** + **AWS Bedrock** (Claude) |
| KB stores | **Postgres**, **pgvector**, optional **Neptune** |
| Parsing | stdlib `ast`, **sqlglot**, **botocore**, **PyYAML** |
| Tests out | **Behave** (primary) |
| Local AWS | **Docker Compose**, **LocalStack**, **Microcks** |
| Sandbox UI | **React** + **Vite**; backend **FastAPI** |

**Explicitly excluded:** LangChain, LangGraph, LlamaIndex

---

## Environment variables (cheat sheet)

| Variable | Where | Purpose |
|----------|-------|---------|
| `AAP_ROOT` / `PYTHONPATH` / `AAP_PYTHON` | `setup_env.ps1` | Module imports + preferred interpreter |
| `PG_HOST` `PG_PORT` `PG_DATABASE` `PG_USER` `PG_PASSWORD` | `ingestion/.env` | Knowledge Base Postgres |
| `NEPTUNE_*` | `ingestion/.env` | Optional live graph load |
| `BEDROCK_MODEL_ARN` | agent `.env` files | Required for AI modules |
| `AWS_REGION` | agent / ingestion `.env` | Bedrock + AWS clients |
| `QUAD_FILES_SOURCE` | `ingestion/.env` | Where ingestion reads quad YAML (S3 or local path) |

---

## Development notes

- Prefer `.\setup_platform.ps1` over hand-picking `requirements.txt` files.
- Do not commit `.env`, `.venv/`, `node_modules/`, or `.platform_runs/`.
- Module CLIs: `python -m analyzer|ingestion|coding_agent|spec_agent|requirement_agent|eval|validator|core|scoring|analyzer_agent`.
- Deeper architecture docs live under `docs/onboarding/` and each module’s `README.md`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError` for platform packages | Run `. .\setup_env.ps1` in that shell |
| Postgres connection refused | `.\start_local.ps1` and confirm Docker is running |
| Bedrock / auth errors | Set `BEDROCK_MODEL_ARN` + valid AWS creds; try `sync_aws_env.py` |
| `python -m X` exits oddly | Use `& $env:AAP_PYTHON -m X` after setup |
| Sandbox UI blank | `npm install` then `npm run dev` under `sandbox/sandbox/web_app/ui` |
| Schema missing tables | Re-pipe `ingestion/schema.sql` into `aap_kb_postgres` (see above) |

---

## License / ownership

Open-source friendly platform tooling. Confirm licensing with your team before publishing outside your org.
