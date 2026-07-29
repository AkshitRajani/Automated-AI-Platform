# Running the whole Automated AI Platform

Automated AI Platform is a **pipeline of modules**, not one server. After clone + install:

```powershell
cd <path-to-automated_ai_platform>
powershell -ExecutionPolicy Bypass -File .\setup_platform.ps1   # once
powershell -ExecutionPolicy Bypass -File .\start_local.ps1      # once / when Docker stopped
. .\setup_env.ps1                                               # every new terminal
```

## Local Docker endpoints (started by `start_local.ps1`)

| Service | URL / DSN |
|---------|-----------|
| Knowledge Base Postgres (+pgvector) | `localhost:5432` / `knowledge_base` / `postgres`/`postgres` |
| Sandbox Postgres | `localhost:5433` / `aap_sandbox` |
| LocalStack | http://localhost:4566 |
| Microcks | http://localhost:8080 |
| Sandbox API | http://127.0.0.1:8765/docs |
| Sandbox UI | http://localhost:5173/ |
| Scoring UI | `cd scoring; ..\.venv\Scripts\python.exe run.py serve --open` |

Neptune cloud is optional locally — graph CSVs are written to `.platform_runs\neptune\`.

## Useful commands

```powershell
# Analyze YOUR app → quads (replace path + app-id)
& $env:AAP_PYTHON -m analyzer C:\path\to\your\app --app-id MYAPP --out .\.platform_runs\quads\MYAPP.yaml --stats

# Or platform fixture (smoke only)
& $env:AAP_PYTHON -m analyzer .\analyzer\tests\fixtures\sample_app --app-id DEMO --out .\.platform_runs\quads\DEMO.yaml --stats

# Ingest quads into local KB
& $env:AAP_PYTHON -m ingestion

# Eval / score / validator (offline-capable)
& $env:AAP_PYTHON -m eval --sut .\eval\examples\discount\sut.py --test .\eval\examples\discount\test_good.py --changed .\eval\examples\discount\sut.py:6
& $env:AAP_PYTHON -m core score --app-id DCFO --generated .\scoring\demo_suites\v2\feature --golden .\scoring\demo_suites\golden\feature

# Sandbox web (if not already running)
cd sandbox\sandbox\web_app\backend
..\..\..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
# other terminal:
cd sandbox\sandbox\web_app\ui
npm run dev
```

## Full AI generate still needs

- Bedrock credentials in agent `.env` files (`BEDROCK_MODEL_ARN`, `AWS_REGION`) + AWS creds via boto3
- Your application path for `python -m core onboard ...`
- Real ticket + diff for `python -m core generate ...`
- Optional: real Neptune endpoint if you need live graph queries (local CSV capture works without it)
