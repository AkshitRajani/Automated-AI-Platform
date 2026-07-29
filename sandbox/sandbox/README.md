# Sandbox

A local, spec-driven sandbox that boots a complete AWS-style integration
surface (LocalStack + Microcks + Postgres + Glue Docker) on your laptop
from a single `spec.yaml`. Designed for running BDD regression bundles
(`.feature` + `behave` step files) against a faithful-shape mock of the
target environment.

This is **wiring**, not business logic. Every Lambda is a stub that
returns shape-correct synthetic data. A test that passes here is proof
that the bundle's AWS calls, names, schemas, contracts, and DDL line up
— the same bundle should then be runnable against the real environment
unchanged.

---

## Prerequisites

| Tool           | Version  | Notes                                    |
| -------------- | -------- | ---------------------------------------- |
| Docker Desktop | ≥ 4.30   | with Compose v2 (`docker compose ...`)   |
| Python         | 3.11     | for the constructor + backend            |
| Node.js        | ≥ 20     | for the optional web UI                  |
| RAM            | ≥ 8 GB   | LocalStack + Microcks + Postgres + Glue  |

Docker images pulled on first boot (~3 GB total):
`localstack/localstack-pro`, `quay.io/microcks/microcks-uber`,
`postgres:16`, `amazon/aws-glue-libs:5.0`.

> **LocalStack Pro** requires `LOCALSTACK_AUTH_TOKEN` in your environment.
> Without it, Lambda + Step Functions + Glue features won't start. A
> Community edition works for S3 / DynamoDB only.

---

## Quick start (CLI)

```bash
# 1. From repo root: generate the docker-compose file + seeder for the profile
python -m core.constructor up core/profiles/default --emit-only

# 2. Boot the stack
cd core/profiles/default
docker compose up -d

# 3. Seed AWS resources (Lambdas, S3 buckets, DDB tables, Step Functions)
./seeder.sh

# 4. Verify
aws --endpoint-url=http://localhost:4566 lambda list-functions \
  --query 'Functions[].FunctionName' --no-cli-pager
```

You should see ~28 Lambdas listed. Cold-start latency for the first
invoke is ~1 s; subsequent invokes ~20 ms.

To tear down:

```bash
docker compose down -v
```

---

## Quick start (Web UI)

The web app gives you a visual map of the stack, a Monaco editor for
`spec.yaml`, and an Upload tab that runs `.feature` + `_steps.py` bundles
against the booted stack via `behave`.

```bash
# Backend (FastAPI) — port 8765
cd web_app/backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.main:app --port 8765

# Frontend (Vite) — port 5173
cd web_app/ui
npm install
npm run dev
```

Open <http://localhost:5173>. The Map view auto-loads the active profile.
Use **Upload** to drop a `.feature` + `_steps.py` pair and watch `behave`
run live.

---

## Smoke test

A **smoke test** here means: upload a real test bundle and let `behave`
hit the live stack via `boto3`. There is no source-code pattern matching
— it is `boto3` → LocalStack → Microcks → Postgres for real.

- **PASS** → wiring works. The Lambda name resolved, the contract matched,
  the SQL ran. Same bundle should pass against the real environment.
- **FAIL** → infrastructure refused the call. Typical: `ResourceNotFoundException`
  (Lambda not in `spec.yaml`), `ValidationException` (event shape wrong),
  or `400` from Microcks (request didn't match the OpenAPI contract).

A trivial way to confirm wiring is up:

```bash
aws --endpoint-url=http://localhost:4566 lambda invoke \
  --function-name gu2-unitTest \
  --payload '{"hello":"world"}' /tmp/out.json --no-cli-pager
cat /tmp/out.json
```

---

## Infra & flow

### What boots

A `docker compose up -d` produces five services, all on a single bridge
network `<project>_sandbox-net`:

| Service     | Image                            | Role                                             |
| ----------- | -------------------------------- | ------------------------------------------------ |
| localstack  | localstack/localstack-pro        | Lambda, S3, DynamoDB, Step Functions, IAM, KMS   |
| microcks    | quay.io/microcks/microcks-uber   | OpenAPI mock for the DBM + CAL HTTP APIs         |
| postgres    | postgres:16                      | Warehouse tables (real DDL, seeded from samples) |
| glue        | amazon/aws-glue-libs:5.0         | PySpark jobs invoked via LocalStack passthrough  |
| seeder      | python:3.11-slim (run-once)      | Provisions LocalStack resources at first boot    |

### How wiring is generated

```
core/profiles/default/spec.yaml          (single source of truth)
        │
        ▼
python -m core.constructor up profiles/default --emit-only
        │
        ├─→ core/profiles/default/docker-compose.yml     (service graph + ports + env)
        ├─→ core/profiles/default/seeder.sh              (AWS resource provisioning script)
        └─→ core/profiles/default/sandbox.manifest.json  (build manifest, consumed by the UI)
```

The constructor never invents wiring — every container, env var, port,
volume, and Lambda registration comes from a field in `spec.yaml`.
Regenerating with the same `spec.yaml` produces a byte-identical
compose file (deterministic — see `core/constructor/sandbox_id.py`).

### Runtime flow — anatomy of a test invocation

```
┌───────────────────────────────────────────────────────────────┐
│  behave (test process, host)                                  │
│   step → boto3.client('lambda').invoke(FunctionName=…)        │
└─────────────────────────┬─────────────────────────────────────┘
                          │  HTTP POST :4566
                          ▼
┌───────────────────────────────────────────────────────────────┐
│  LocalStack edge :4566                                        │
│   ├ resolves function name from registry (seeded at boot)     │
│   ├ spawns Lambda runtime container on sandbox-net            │
│   └ forwards event payload to handler                         │
└─────────────────────────┬─────────────────────────────────────┘
                          ▼
┌───────────────────────────────────────────────────────────────┐
│  Lambda container  (core/scripts/smart_stub_handler.py)       │
│   ├ reads fidelity.json   → L1 / L2 / L3 tier                 │
│   ├ validates event against input_example.json   (L3 only)    │
│   ├ may call:                                                 │
│   │    http://microcks:8080/rest/…   (DBM / CAL contracts)    │
│   │    http://localstack:4566        (S3, DDB, Step Functions)│
│   │    postgres://postgres:5432      (table reads / writes)   │
│   └ returns shape from output_example.json                    │
└─────────────────────────┬─────────────────────────────────────┘
                          ▼
              behave assertion reads back from
              Postgres / DDB / S3 and verifies.
              PASS → end-to-end wiring is correct.
```

### Where the contracts live

- **`spec.yaml`** declares logical names: `lambdas[].name`, `s3[].bucket`,
  `ddb[].table`, `postgres.databases[].tables[]`, `microcks.services[]`.
- **`attachments/lambdas/*.zip`** are the deployed handlers — every one
  is a thin wrapper around `smart_stub_handler.py` plus per-lambda
  `fidelity.json` + `input_example.json` + `output_example.json`.
- **`attachments/contracts/{dbm,cal}.openapi.yaml`** is what Microcks
  imports at boot. Test calls to those services hit Microcks, which
  matches against the OpenAPI examples and returns the canned response.
- **`attachments/postgres/ddl/*.sql`** is what `seeder.sh` runs against
  Postgres on first boot to create the warehouse schema.

### Docker network — the one knob that matters

Lambda containers spawned by LocalStack must attach to the same network
as the long-running Microcks / Postgres / Glue containers, otherwise
calls from inside a Lambda to `http://microcks:8080` fail with DNS
error. The constructor sets:

```yaml
environment:
  LAMBDA_DOCKER_NETWORK: ${COMPOSE_PROJECT_NAME:-default}_sandbox-net
```

so LocalStack passes the correct network when spawning Lambda runtimes.
If you run with a custom Compose project name
(`docker compose -p myproj up`), export `COMPOSE_PROJECT_NAME=myproj`
before regenerating the compose file.

### Logs & introspection

| To see                       | Run                                                                |
| ---------------------------- | ------------------------------------------------------------------ |
| Lambda invocation logs       | `docker logs -f <project>-localstack-1 \| grep <lambda-name>`      |
| Lambda container start/exit  | `docker ps -a --filter "name=<project>-localstack-1-lambda-"`      |
| Microcks request log         | UI at <http://localhost:8080> → "Daily invocations" / "Tests"      |
| Postgres queries             | `docker exec -it <project>-postgres-1 psql -U sandbox sandbox`     |
| Step Function executions     | `aws --endpoint-url=http://localhost:4566 stepfunctions list-executions --state-machine-arn …` |

---

## Stub fidelity tiers

Every Lambda declares a fidelity tier in its `fidelity.json`:

| Tier | Behavior                                                            |
| ---- | ------------------------------------------------------------------- |
| L3   | Validates inner event shape strictly; returns observed output shape |
| L2   | Returns correct top-level response shape with synthetic values      |
| L1   | Echo: accepts any input, returns `{}`                               |

Step Functions support `SF-L2` (named resolves, synthetic success) and
`SF-L1` (not deployed).

Upgrading a stub from L1 → L2 → L3 only requires populating
`profiles/default/lambdas/<name>/{input_example.json, output_example.json}`
and bumping `fidelity` in `fidelity.json`. The smart-stub handler
(`core/scripts/smart_stub_handler.py`) reads these at cold start.

---

## Port map

| Service                      | Port  | URL                       |
| ---------------------------- | ----- | ------------------------- |
| LocalStack edge              | 4566  | `http://localhost:4566`   |
| Microcks UI + REST           | 8080  | `http://localhost:8080`   |
| Microcks gRPC                | 9090  |                           |
| Postgres                     | 5432  | `postgres://sandbox:sandbox@localhost:5432/sandbox` |
| Glue Docker                  | 18080 |                           |
| Web backend (FastAPI)        | 8765  | `http://localhost:8765`   |
| Web UI (Vite dev)            | 5173  | `http://localhost:5173`   |

---

## Layout

```
sandbox/
├── README.md
├── core/
│   ├── constructor/        spec.yaml → docker-compose + seeder
│   ├── scripts/            stub builders, smart-stub handler, helpers
│   ├── profiles/
│   │   └── default/        one tenant profile: spec.yaml + lambdas/ + attachments/
│   └── test_framework/     behave step utilities (boto3 helpers)
└── web_app/
    ├── backend/            FastAPI bridge (topology, runs, uploads, SSE)
    └── ui/                 React + Vite + React Flow + Monaco
```

### `core/profiles/default/`

- `spec.yaml` — single source of truth for the profile (tenant, AWS
  resources, contracts, business rules, tickets)
- `sandbox.manifest.json` — generated; what the constructor produced
- `docker-compose.yml` — generated; one container per service
- `seeder.sh` — generated; provisions LocalStack resources
- `lambdas/<name>/` — per-Lambda `fidelity.json`, `handler.py`,
  `input_example.json`, `output_example.json`
- `attachments/` — DDL, IAM policies, OpenAPI contracts, sample payloads
  (the inputs the constructor reads, kept verbatim from the source environment)

---

## What's intentionally not here

- **Real business logic.** Every Lambda is a stub; the sandbox proves
  wiring, not correctness of the underlying transforms.
- **Real KMS/VPC fidelity.** The sandbox uses LocalStack's default
  in-memory crypto; tests that depend on real KMS or VPC routing should
  be tagged `@requires_aws` and run against the real environment.
- **Authoritative Step Function ASL bodies.** Where the source environment
  has Step Function workflows whose ASL has not been observed, the profile
  carries a placeholder workflow that produces a synthetic success outcome.
  Replace under `attachments/iam/` / spec when real ASL is available.

---

## Troubleshooting

- **`docker compose up` hangs on Lambda cold start** — the Lambda Docker
  network name in `docker-compose.yml` (`<project>_sandbox-net`) must
  match what LocalStack spawns Lambda containers into. The constructor
  writes this correctly for project name `default`. If you `docker compose
  -p <name>` with a custom project name, regenerate with
  `python -m core.constructor up core/profiles/default --emit-only` after
  setting the project name.
- **Microcks 502** — first boot pulls images; wait ~60 s and retry.
- **Postgres connection refused** — `pg_isready` against
  `postgres://sandbox:sandbox@localhost:5432/sandbox`; if it fails, check
  `docker compose logs postgres` for a port-already-in-use error.
- **Glue container exits immediately** — Glue 5.0 needs ≥ 4 GB of
  memory allocated to Docker Desktop.

---

## License

Provided to the tenant for evaluation. No warranty.
