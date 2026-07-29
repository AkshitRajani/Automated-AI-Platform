# BDD Behaviour Scoring

## In short (for stakeholders)

We do **not** score by how many scenarios GenAI wrote, or by whether the
Given / When / Then wording looks similar.

**Truth sources (must be trusted):**
1. **Golden behavioural tests** — human-approved tests that encode *what the
   system actually does* (the behaviour contract).
2. **Feature MD / requirement docs** — per-feature specs of *what each feature
   must cover* (stories, shalls, acceptance behaviour).

**What the scorer does:** profile both truth sources and the GenAI suite as
*behaviours* (stage, intent, actions — not surface phrasing). A GenAI scenario
counts as a **match only if that behaviour aligns** with golden and/or the MD
feature contract.

| We reward | We do not reward |
|-----------|------------------|
| Covering the same real behaviours as golden + MD | More scenarios for their own sake |
| Behaviour signatures that match the truth set | Copying Given/When/Then wording |
| Efficient coverage of golden behaviours | Padding / duplicate fluff |

---

Standalone module that scores **generated Gherkin BDD** against **manual
(golden) behavioural tests** and optional **feature MD / requirement docs**.

It answers: *Do the GenAI tests exercise the same behaviours as the trusted
truth sources — not merely similar scenario text?*

Golden tests are ground truth for behaviour. Feature MD describes what each
feature should cover. Generated scenarios are matched on **behaviour profiles**,
then rolled into a golden-first overall score (manual recall and match quality
dominate; scenario count alone does not).

---

## How it works

```mermaid
flowchart LR
  subgraph inputs [Inputs]
    M[Manual .feature]
    G[Generated .feature]
    R[Requirements .md / .json]
  end

  subgraph profile [Behaviour profiling]
    MP[Profile manual scenarios]
    GP[Profile generated scenarios]
    RP[Extract + profile requirement items]
  end

  subgraph match [Matching]
    MG[Generated ↔ Manual]
    GR[Generated ↔ Requirements]
    TRI[Triangulation]
  end

  OUT[score_report.html / .json]

  M --> MP
  G --> GP
  R --> RP
  MP --> MG
  GP --> MG
  GP --> GR
  RP --> GR
  MG --> TRI
  GR --> TRI
  TRI --> OUT
```

### Pipeline

1. **Parse** — Load golden `.feature` files, GenAI `.feature` files, and feature
   MD / requirement docs (`.md` / `.json`, including docs mixed into the golden zip).
2. **Profile behaviour** — Assign each scenario / requirement item a behaviour
   signature (not a text fingerprint of the Gherkin lines):
   - `workflow_stage` (e.g. validate, load, monitor)
   - `intent` (positive / negative / neutral)
   - `actions` (business verbs that describe what is exercised)
3. **Match on behaviour** — A GenAI scenario is a match **only if** its behaviour
   signature aligns with a golden scenario and/or an MD feature behaviour item
   (configurable threshold; default `0.5`). Wording similarity alone is not enough.
4. **Score (golden-first)** — Weighted toward covering trusted golden behaviours
   and MD ACs; suite size / padding does not inflate the score.
5. **Report** — HTML + JSON: matches, behaviour gaps, and integrity notes.

### Requirement extraction (Bedrock agent mode)

Large requirement markdown files are not sent whole to the model. Instead:

- **Tier A (primary):** User Stories (G/W/T ACs) and Consolidated shall bullets
- **Tier B (secondary):** Function Spec, Gap Analysis — skipped by default in agent mode
- **Metadata:** Traceability, I/O tables, System Overview — parsed but not sent to Bedrock

Optimisations (all code defaults, no env vars needed):

- One Bedrock item per user story (all ACs combined)
- Duplicate shall bullets dropped when they repeat story content
- Adaptive batching (~25 items or 12 KB text per call)
- Parallel label batches + disk cache for repeat runs

First Bedrock run: ~2–3 minutes. Cached re-runs: seconds.

---

## What you need

| Item | Required | Notes |
|------|----------|-------|
| Python 3.12+ | Yes | 3.12 and 3.13 both work; Bedrock agent uses `strands-agents` |
| Manual `.feature` folder or zip | Yes | Golden reference tests |
| Generated `.feature` folder or zip | Yes | Tests to score |
| Requirement docs | No | `.md` / `.json` from requirement agent — **or** mixed into the manual zip/folder next to `.feature` files |
| AWS Bedrock credentials | No* | *Recommended; `auto` mode falls back to regex |

---

## Setup

### 1. Install dependencies

```powershell
cd path\to\scoring
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` lists only what scoring uses: `strands-agents`, `boto3`, `pydantic`.
It does **not** include `strands-agents-tools` or `psycopg2-binary` (Coding Agent needs those; scoring does not).

If `strands-agents` fails to install (common on locked-down corporate networks), use **regex-only** deps instead:

```powershell
pip install -r requirements-core.txt
```

Then set `SCORING_PROFILING_MODE=regex` in `.env` (no Bedrock needed).

### 2. Create config

```powershell
copy scoring\scoring\.env.example scoring\scoring\.env
```

Edit `scoring/scoring/.env` (inside the Python package folder).

### 3. Minimum `.env` (folder mode)

```env
SCORING_ROOT=C:\path\to\scoring

SCORING_GOLDEN=C:\path\to\manual_features
SCORING_GENERATED=C:\path\to\generated_features
SCORING_REQUIREMENTS=C:\path\to\requirements

SCORING_OUTPUT_DIR=C:\path\to\output
SCORING_THRESHOLD=0.5
SCORING_PROFILING_MODE=auto
```

For **zip mode**, use `SCORING_GOLDEN_ZIP`, `SCORING_GENERATED_ZIP`, and optionally `SCORING_REQUIREMENTS_ZIP` instead of folder paths.

### 4. Bedrock (optional)

Add to `.env` for Claude Opus profiling:

```env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
BEDROCK_MODEL_ARN=us.anthropic.claude-opus-4-8
```

Do not commit `.env` — it contains secrets.

---

## Running

From the **outer** `scoring/` folder (where `run.py` lives):

```powershell
# Score from .env folder paths
py run.py run

# One-off threshold override
py run.py run --threshold 0.5

# Score from zips (default CLI when no subcommand)
py run.py

# Web UI — upload two zips in the browser
py run.py serve --open

# PowerShell wrapper
.\run.ps1 run
```

### Profiling modes

| Mode | Behaviour |
|------|-----------|
| `auto` | Bedrock agent when AWS is configured; otherwise regex |
| `agent` | Always Bedrock (fails without AWS) |
| `regex` | Fast local regex profiling, no API calls |

Strict matching (exact stage, exact intent, shared action) is enabled automatically in agent mode.

---

## Output

Written to `SCORING_OUTPUT_DIR`:

| File | Description |
|------|-------------|
| `score_report.html` | Visual report — open in browser |
| `score_report.json` | Full structured results |

Key headline metrics (golden-first overall):

- **Manual coverage (recall)** — % of golden/manual scenarios covered (primary)
- **Coverage efficiency** — manuals covered per generated scenario (rewards lean suites)
- **Suite precision** — % of generated scenarios aligned with a manual test (secondary; padding hurts)
- **Requirement AC recall** — % of requirement ACs covered (supporting, when requirements present)
- **Triangulation** — generated scenarios aligned with *both* manual and requirements (supporting)
- **Overall score** — weighted blend emphasising golden coverage over generator mimicry

How to read overall: a smaller suite that covers more of the golden tests should beat a larger padded suite that only looks similar on a per-generated-scenario basis.
---

## Project layout

```
scoring/
├── run.py              # Launcher (sets PYTHONPATH, loads .env)
├── run.ps1             # PowerShell wrapper
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── scoring/            # Python package
    ├── .env            # Your config (git-ignored)
    ├── .env.example    # Template
    ├── __main__.py     # CLI entry point
    ├── score.py        # Scoring orchestrator
    ├── behavior.py     # Regex behaviour extraction
    ├── behavior_match.py
    ├── parse.py        # Gherkin parser
    ├── requirements/   # Requirement doc parsing + profiling
    ├── agent/          # Bedrock profiling agent + cache
    ├── .profile_cache/ # Cached Bedrock profiles (auto-created)
    └── tests/          # pytest suite
```

---

## Tests

```powershell
cd path\to\scoring
py -m pytest scoring/tests -q
```

---

## Corporate laptop setup

Company machines often block PyPI or packages like `strands-agents`. Two paths:

### Option A — Regex mode (recommended on locked-down laptops)

No `strands-agents`, no AWS, no outbound Bedrock calls. Scoring still runs end-to-end.

```powershell
cd path\to\scoring
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-core.txt
```

In `scoring/scoring/.env`:

```env
SCORING_PROFILING_MODE=regex
```

Then run as usual: `py run.py run`

### Option B — Full Bedrock agent (needs IT approval)

Ask IT to allow **PyPI** access (or your internal mirror) for:

- `strands-agents`
- `boto3`
- `pydantic`

If your company uses a **proxy**, configure pip once:

```powershell
pip config set global.proxy http://user:pass@proxy.company.com:8080
```

If PyPI is blocked entirely, download wheels on an allowed machine and copy them over:

```powershell
pip download -r requirements.txt -d wheels
# copy wheels/ to laptop, then:
pip install --no-index --find-links wheels -r requirements.txt
```

Bedrock also needs AWS credentials and outbound HTTPS to AWS — confirm with IT/security.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Could not find a version … strands-agents` | Upgrade pip (`python -m pip install --upgrade pip`), confirm Python 3.12+ (`python --version`), check PyPI/network access. Or use `pip install -r requirements-core.txt` + `SCORING_PROFILING_MODE=regex` |
| `No module named strands` | Activate venv and `pip install -r requirements.txt`, or use regex mode (see above) |
| Bedrock `AccessDeniedException` | Try `AWS_REGION=us-east-1`; confirm model access for your account |
| Run too slow first time | Expected — Bedrock profiles all inputs; second run uses cache |
| Low score at threshold 0.9 | Lower threshold (`0.5` is typical) or check generated test quality |
| Want regex-only / offline | Set `SCORING_PROFILING_MODE=regex` |

Changing `SCORING_THRESHOLD` only re-runs matching — it does not call Bedrock again.
