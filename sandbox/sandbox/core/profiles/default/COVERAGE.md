# tenant spec.yaml — Coverage Report

**Authored:** 2026-04-30
**Spec file:** `profiles/default/spec.yaml`
**Schema:** `<schema>/spec.schema.json`

## Three-color summary

| Section | REAL | STUB | TAGGED-GAP / UNKNOWN | Verdict |
|---|---:|---:|---:|---|
| tenant | 2/4 | 0/4 | 2/4 | partial — contacts unknown |
| lambdas (20) | 20/20 names | 20/20 runtime+handler+timeout | 20/20 env_vars, 0/20 IAM | shippable shapes; bodies need handler.zip |
| step_functions | 2/2 names + integrations | 0/2 | 2/2 ASL bodies | tag `@requires_aws` for L3 |
| dynamodb | 1/1 name | 1/1 schema | 1/1 sample rows | one table, schema guessed |
| s3_buckets | 2/2 names + prefix | 1/2 sample objects | 1/2 | strong |
| column_dictionary | input 107 cols (MB42.csv) + output 28 cols (parquet) | global_aliases small | columns_csv_sha256 computed at constructor | strong |
| glue_jobs | 1/1 mb4.yml + params | 0 | example_run_args | strong |
| iam_roles | 0/3 bodies | 3/3 names + trust | 3/3 attached_policies | weak — needs P2 ask |
| network | 5/5 dns_aliases | vpc/subnet prose | 0 | strong |
| data_flows | 5 edges synthesized | 0 | full topology | one main flow proven |
| control_flows | 1 workflow synthesized | 0 | second workflow | one of two |
| column_lineage | 3 transforms shown | rest synthesizable | full set at constructor time | proof-of-shape only |
| behavioral_contracts | 2/2 names + state machines | 2/2 OpenAPI bodies | 2/2 real OpenAPI | tag `@requires-dbm-real`, `@requires-cal-real` |
| parameters | 5/5 tokens REAL | 0 | source for some unconfirmed | strong |
| business_rules | 5/5 names + prose | 5/5 draft SQL | 5/5 authoritative SQL | tag `@requires-rule-sql` |
| tickets | 5 IDs REAL | 5/5 ticket_yaml bodies (synthesized from .doc) | ground_truth bundles | partial |

**Overall:** every top-level section has at least one REAL entry. Every TAGGED-GAP has either a tag, a placeholder, or a fallback that lets the constructor proceed.

## What this means in plain English

**We can run the constructor today.** Every field the constructor *needs* to stand up Docker Compose has a value:

- 20 Lambda code paths exist (need handler.zip packaging step)
- mb4.yml drives the Glue job
- 107-column dictionary populates the schema service
- 5 parameter tokens are catalogued
- 2 stateful Microcks dispatchers can be written from the state_machine + response_per_state in `behavioral_contracts`
- DDL synthesizable from parquet schemas
- Postgres seeds: copy `all_loans.parquet` + 14 chunks

**What we cannot test at L3 yet (tag and route to L4):**

| Capability | Tag | Reason |
|---|---|---|
| Step Function orchestration | `@requires_aws` | No ASL JSON; LocalStack Step Functions still useful but choreography unverified |
| Real DBM behavior beyond seed | `@requires-dbm-real` | OpenAPI is a stub from one sample |
| Real CAL behavior beyond seed | `@requires-cal-real` | OpenAPI is a stub; async timing simplified |
| Authoritative rule SQL | `@requires-rule-sql` | Draft SQL only; mb4.yml shows fragments but not the full canonical form |
| IAM policy evaluation | `@requires_aws` | No policy bodies; Access Analyzer at L2 checks emitted IAM only |
| Distributed Map error semantics | `@requires_aws` | LocalStack divergence (known V1 finding) |
| Glue bookmarks | `@requires_aws` | LocalStack does not implement |

## Field-by-field source map

### tenant
| Field | Status | Source / placeholder |
|---|---|---|
| name | REAL | "tenant" |
| snapshot_date | REAL | 2026-04-30 |
| primary_contact | UNKNOWN | "Moin" placeholder; email is `.PLACEHOLDER` |
| technical_owner | UNKNOWN | "Baseer" placeholder; email is `.PLACEHOLDER` |

**Gap closer:** ask_f delivers contact list, or pull from email threads.

### lambdas (20 entries)
| Field group | Status | Source |
|---|---|---|
| lambda_name | REAL | `<source>/` |
| family / role | REAL | extracted from naming pattern `hlx-aap_sandbox-{family}-{role}-lambda` |
| runtime | STUB (python3.11) | inferred from bdd-test-agent venv |
| handler | STUB (`handler.lambda_handler`) | AWS default |
| timeout / memory | STUB | sensible defaults; tune from real telemetry later |
| env_vars | TAGGED-GAP for 18; STUB for KLC pair | DBM_BASE_URL/CAL_BASE_URL extrapolated from V1 construction_guide |
| iam_policy_ref | TAGGED-GAP | no per-Lambda policies in artifacts |
| invocation_pattern | STUB | guessed from role name (cleanup → async, rest → sync) |
| upstream_dependencies | STUB (partial) | extracted from naming + mb4.yml/payload references |
| example_event_payload | TAGGED-GAP | none in artifacts |
| source_archive | REAL src present | needs constructor zip step |

**Gap closer:** ask_f returns one `handler_py.yaml` per Lambda OR the deployment template tenant uses (CDK/SAM/CFN).

### step_functions
| Name | ASL | Lambda integrations | Status |
|---|---|---|---|
| aap_sandbox-generic-Step-workflow | TAGGED-GAP | 4 inferred | name from tenant/architecture.md |
| aap_sandbox-generic-api-submission-workflow | TAGGED-GAP | 3 inferred | name from tenant/architecture.md |

**Gap closer:** ask_f delivers the two ASL JSONs.

### dynamodb (1 table)
| Field | Status | Notes |
|---|---|---|
| table_name | REAL | `aap_sandbox-dynamo-api-submission-status-table` |
| hash_key | STUB (`scenario_id`) | from `${scenario_id}` token in mb4.yml |
| sort_key | STUB (null) | unconfirmed |
| attribute_definitions | STUB | one entry |
| sample_rows_path | TAGGED-GAP | none |

**Gap closer:** ask_f delivers schema + 50 sample rows.

### s3_buckets (2)
| Bucket | Real? | Sample objects |
|---|---|---|
| etl_workflow-devl-fcdl-pp80-staging | REAL pattern | SYNTHESIZED from 2025/.../data/inputs/ |
| tenant-project-files | REAL | for L4 hand-off path |

### column_dictionary
| Sub-field | Status | Notes |
|---|---|---|
| tables[0]: LN_INTRM_TM_SERS_DATA_PREP_SPST | REAL | 107 cols, input table; MB42.csv is the dict; matches `all_loans.parquet` schema |
| tables[1]: LN_TM_SERS_MBS4PLUS | SYNTHESIZED | 28 cols, output table; columns extracted from parquet schema |
| framework_reserved | REAL | from spec.template.json + design |
| casing_exceptions | REAL | confirmed against parquet schema (last 3 fields literally lower_snake in the file) |
| global_aliases | STUB | only 3 entries; expand as Coding Agent learns |

**Phase 0 simplification:** MB42.csv is used as-is. The constructor reads `Field Name` and `Data Type` columns directly into `db.schemas` (the only fields L2 lint #4 and the Coding Agent's `lookup_schema` tool actually read). The schema's richer fields (`null_semantics`, `pii_class`, `aliases`, etc.) are not exercised in Phase 0; we revisit if Stage 3 entity resolution starts needing them.

### glue_jobs (1)
| Field | Status |
|---|---|
| job_name | REAL |
| pipeline_yaml_path | REAL (mb4.yml, 295 lines) |
| input_dataset_path | REAL pattern |
| output_dataset_path | REAL pattern |
| required_parameters | REAL (5 tokens extracted) |

### parameters (5 tokens)
All REAL. `${jumpoff_full_date}` and `${Loan Past Due Threshold (repurch_num_months)}` confirmed via grep against mb4.yml.

### behavioral_contracts (2)
DBM and CAL state machines REAL (from V1 construction_guide.md §7), but the actual OpenAPIs that Microcks needs are STUB (handwritten from sample.txt and payload.txt). When the tenant ships P0.2 and P0.3, swap the OpenAPI files; state machine stays.

### business_rules (5)
Names REAL. Prose REAL (from findings/05). Draft SQL TAGGED-GAP. Authoritative SQL is P0.4 ask_f item.

### tickets (5)
IDs REAL. `.doc` files exist for FNCOFFTF-31855, -31879. Ticket YAMLs SYNTHESIZED at constructor time by parsing the .doc files (or by the Normalizer pipeline).

## Attachment manifest — what physically needs to land in `attachments/`

```
profiles/default/
├── spec.yaml                                       ✓ written
├── COVERAGE.md                                     ✓ this file
└── attachments/
    ├── lambdas/
    │   ├── hlx-aap_sandbox-backbone-metadata-api-input/
    │   │   └── handler.zip                         ✓ from 2025/sample/.../{name}/
    │   ├── hlx-aap_sandbox-common-code/
    │   │   └── handler.zip                         (× 20 lambdas — copy + zip)
    │   └── ... (18 more)
    ├── pipelines/
    │   └── mb4.yml                                 ✓ from 2025/.../block_box/mb4.yml
    ├── parquets/
    │   ├── all_loans.parquet                       ✓ from 2025/.../data/inputs/
    │   ├── chunk_1.parquet … chunk_14.parquet      ✓
    │   └── LN_TM_SERS_MBS4PLUS.parquet             ✓ from 2025/.../block_box/ (REFERENCE output)
    ├── column_dictionary/
    │   ├── MB42.csv                                 ✓ from 2025/ (input table dict, 107 rows, used as-is)
    │   └── LN_TM_SERS_MBS4PLUS.columns.csv          GENERATE from parquet schema (output, 28 cols)
    ├── postgres/
    │   └── ddl/
    │       ├── LN_INTRM_TM_SERS_DATA_PREP_SPST.sql  ✓ generated by scripts/parquet_to_ddl.py (107 cols)
    │       └── LN_TM_SERS_MBS4PLUS.sql              ✓ generated by scripts/parquet_to_ddl.py (28 cols)
    ├── contracts/
    │   ├── dbm.openapi.yaml                        STUB: write from reference/sample.txt
    │   ├── dbm.dispatcher.js                       STUB: kv-TTL pattern from V1
    │   ├── cal.openapi.yaml                        STUB: write from reference/payload.txt
    │   └── cal.dispatcher.js                       STUB: 2s RUNNING→SUCCEEDED flip
    ├── microcks/
    │   ├── dbm.state.json                          STUB: derived from sample.txt
    │   └── cal.state.json                          STUB: 2 scenarios (Shock + No-Shock)
    ├── rules/
    │   └── draft/
    │       ├── CHANGE_SOURCE_2616.draft.sql        DRAFT: agent-generated; signoff_status='inferred'
    │       ├── CHANGE_SOURCE_3519.draft.sql        DRAFT (extractable from mb4.yml directly)
    │       ├── CHANGE_SOURCE_2908.draft.sql        DRAFT
    │       ├── CHANGE_SOURCE_3067.draft.sql        DRAFT
    │       └── CHANGE_SOURCE_3515.draft.sql        DRAFT
    ├── tickets/
    │   ├── FNCOFFTF-31855.yaml                     SYNTHESIZE from .doc via Normalizer
    │   ├── FNCOFFTF-31879.yaml                     SYNTHESIZE
    │   ├── FNCOFFTF-1284.yaml                      cited only; minimal stub
    │   ├── FNCOFFTF-23379.yaml                     cited only
    │   └── FNCOFFTF-16658.yaml                     from handler_py.yaml
    ├── ground_truth/
    │   └── FNCOFFTF-31855/                         BUILD: HITL-signed expected outputs
    │       ├── expected_output.parquet
    │       └── manifest.yaml
    ├── s3_objects/
    │   └── etl_workflow-staging.tar.gz                   PACK: tar of input parquets + 14 chunks
    └── iam/                                        TAGGED-GAP — placeholders only
        ├── lambda-execution-role.PLACEHOLDER.json
        ├── step-execution-role.PLACEHOLDER.json
        └── glue-execution-role.PLACEHOLDER.json
```

✓ = REAL file copy
GENERATE = run script against existing artifact
SYNTHESIZE = derive from REAL (deterministic transform)
STUB = handwritten from a sample
DRAFT = agent-generated, low-confidence
PLACEHOLDER = empty file pending tenant

## Bottom line

**The constructor can `up` this profile today.** Tag-routed scenarios will skip the L3 paths that require artifacts we don't have, and the zero-call gate still enforces real invocations on everything else.

Every TAGGED-GAP has a one-to-one mapping to an `ask_f` line item. When tenant returns the package, each delivered artifact replaces a stub or placeholder — the spec doesn't restructure, it sharpens.
