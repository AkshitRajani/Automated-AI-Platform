# Knowledge Base Ingestion Pipeline

Reads quad files (one per application), fills Postgres and Neptune so the AI agent can query them to generate tests.

---

## What It Does

```
Quad files (S3) → Parse → Fill Postgres (facts) + Neptune (graph)
                       → Resolve parameters (if bindings provided)
```

One command. Processes all quad files in the source folder. Each file is independent — one failure doesn't stop the others.

---

## Setup

### 1. Copy the example config

```bash
cp .env.example .env
```

### 2. Fill in your values

```
QUAD_FILES_SOURCE       S3 folder containing quad files
PARAM_BINDINGS_SOURCE   Local folder for parameter binding files (optional)
PG_HOST / PG_PORT       Postgres connection
NEPTUNE_ENDPOINT        Neptune cluster endpoint
NEPTUNE_S3_BUCKET       S3 bucket for Neptune CSV uploads
NEPTUNE_IAM_ROLE        IAM role Neptune uses to read from S3
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Run

```bash
python -m ingestion
```

That's it. Everything is read from `.env`.

---

## What Goes Where

| Source | Postgres | Neptune |
|---|---|---|
| Metadata | `app_applications` (1 row per app) | Application node |
| Components | `app_components` (inferred from file paths) | Component nodes |
| Entities | `app_functions` (all types) | Entity nodes |
| Endpoints | `app_endpoints` | Endpoint nodes |
| Tables | `app_tables` | Table nodes |
| S3 paths | `app_s3_paths` | S3Path nodes |
| Parameters | `app_parameters` | Parameter nodes |
| All quads | `quad_archive` (complete record) | Edges (label = predicate) |
| Service invocations | `app_service_invocations` | Service edges |
| Table relationships | `app_table_relationships` | Relationship edges |
| Bindings | `param_bindings` | — |

---

## Parameter Bindings (Optional)

The analyzer produces parameterized names like `${TABLE.glue_database_name}` instead of real table names. To resolve these, drop a YAML file in the `bindings/` folder:

```yaml
# bindings/app_bindings.yaml
TABLE.glue_database_name: real_database_name
TABLE.glue_table_name: real_table_name
```

Re-run `python -m ingestion` and the pipeline resolves tokens automatically. If no bindings exist, the pipeline still runs — tokens stay as `${...}` and are marked `resolved=false`.

---

## Adding a New Application

1. Drop the quad file in the S3 source folder
2. (Optional) Drop a bindings file in `bindings/`
3. Run `python -m ingestion`

No code changes needed.

---

## Fault Tolerance

| Scenario | What happens |
|---|---|
| Quad file is corrupt YAML | Skipped. Others continue. Error logged. |
| One entity is malformed | Quarantined. Rest of file continues. |
| Unknown entity type | Accepted as-is. Warning logged. |
| Unknown predicate | Stored in `quad_archive`. Warning logged. |
| No bindings file | Tokens stay as `${...}`. Pipeline still runs. |
| Run twice on same data | No duplicates. Idempotent writes. |

---

## Project Structure

```
ingestion/
    __main__.py              Entry point
    pipeline.py              Orchestrator — processes each file independently
    config.py                Reads .env configuration
    schema.sql               Postgres CREATE TABLE statements
    requirements.txt         Python dependencies
    .env.example             Configuration template

    parsers/
        quad_parser.py       YAML parser with per-record fault tolerance
        resolver.py          Parameter binding resolver

    components/
        inferrer.py          Component inference from entity file paths

    writers/
        postgres_writer.py   Batch inserts into Postgres fact tables

    graph/
        neptune_writer.py    CSV generation + Neptune bulk loader

    bindings/                Drop parameter binding YAML files here
```

---

## Tech Stack

| Component | Tool |
|---|---|
| YAML parsing | PyYAML (CSafeLoader) |
| Postgres | psycopg2 |
| Neptune | Bulk loader via S3 CSV |
| AWS access | boto3 (IAM role) |

---

## Neptune Bulk Load

The pipeline cannot call Neptune directly from outside the VPC. It:

1. Generates CSV files (nodes + edges)
2. Uploads them to S3 at `{NEPTUNE_S3_BUCKET}/neptune-load/{app_id}/`
3. Triggers Neptune's bulk loader API

When running from within the same VPC (e.g., on ECS), the trigger works automatically. When running from outside the VPC, the CSV files are uploaded to S3 and the bulk load can be triggered separately.
