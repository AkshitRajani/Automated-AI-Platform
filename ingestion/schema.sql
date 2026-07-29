-- Ingestion Pipeline Schema
-- Run once to set up the knowledge base tables

-- Applications (one row per quad file)
CREATE TABLE IF NOT EXISTS app_applications (
    app_id              TEXT PRIMARY KEY,
    source_root         TEXT,
    languages_detected  TEXT[],
    analyzer_version    TEXT,
    generated_at        TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Components (inferred from entity file paths)
CREATE TABLE IF NOT EXISTS app_components (
    component_id        TEXT PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    name                TEXT NOT NULL,
    path_prefix         TEXT,
    languages           TEXT[],
    entity_count        INT DEFAULT 0
);

-- Entities (functions, endpoints, workflows, lambda handlers, etc.)
CREATE TABLE IF NOT EXISTS app_functions (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    entity_type         TEXT NOT NULL,
    component_id        TEXT REFERENCES app_components(component_id),
    language            TEXT,
    file_path           TEXT,
    symbol              TEXT NOT NULL,
    line_start          INT,
    line_end            INT,
    UNIQUE (app_id, file_path, symbol)
);

-- Endpoints (exposed and called)
CREATE TABLE IF NOT EXISTS app_endpoints (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    kind                TEXT NOT NULL,
    http_method         TEXT,
    path_template       TEXT NOT NULL,
    full_url            TEXT,
    resolved            BOOLEAN DEFAULT true,
    confidence          REAL
);

-- Uniqueness must include the HTTP method: GET/PUT/DELETE on one path are three
-- distinct endpoints (the old key silently dropped all but the first).
-- COALESCE keeps re-runs idempotent when the method is unknown (NULL).
-- The DROP migrates databases created before this fix; both statements are no-ops
-- on a fresh or already-migrated database.
ALTER TABLE app_endpoints DROP CONSTRAINT IF EXISTS app_endpoints_app_id_kind_path_template_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_endpoints_app_kind_method_path
    ON app_endpoints (app_id, kind, COALESCE(http_method, ''), path_template);

-- Database tables (Glue, DynamoDB, RDS)
CREATE TABLE IF NOT EXISTS app_tables (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    kind                TEXT NOT NULL,
    table_token         TEXT NOT NULL,
    resolved            BOOLEAN DEFAULT true,
    confidence          REAL,
    UNIQUE (app_id, kind, table_token)
);

-- S3 paths
CREATE TABLE IF NOT EXISTS app_s3_paths (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    kind                TEXT NOT NULL,
    path                TEXT NOT NULL,
    resolved            BOOLEAN DEFAULT true,
    confidence          REAL,
    UNIQUE (app_id, kind, path)
);

-- Parameters (unresolved tokens, SSM, env vars)
CREATE TABLE IF NOT EXISTS app_parameters (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    token               TEXT NOT NULL,
    param_type          TEXT DEFAULT 'token',
    UNIQUE (app_id, token)
);

-- Table relationships (from JPA annotations)
CREATE TABLE IF NOT EXISTS app_table_relationships (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    source_table        TEXT NOT NULL,
    target_table        TEXT NOT NULL,
    relationship_type   TEXT,
    confidence          REAL,
    UNIQUE (app_id, source_table, target_table, relationship_type)
);

-- Service invocations (Lambda, Step Function, SNS)
CREATE TABLE IF NOT EXISTS app_service_invocations (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    source_entity       TEXT NOT NULL,
    predicate           TEXT NOT NULL,
    target_arn          TEXT NOT NULL,
    resolved            BOOLEAN DEFAULT false,
    confidence          REAL,
    UNIQUE (app_id, source_entity, predicate, target_arn)
);

-- Quad archive (every single quad stored verbatim)
CREATE TABLE IF NOT EXISTS quad_archive (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    subject_id          TEXT NOT NULL,
    subject_type        TEXT NOT NULL,
    predicate           TEXT NOT NULL,
    object_id           TEXT NOT NULL,
    object_type         TEXT NOT NULL,
    confidence          REAL,
    resolved            BOOLEAN,
    extraction_method   TEXT,
    file_path           TEXT,
    context_component   TEXT,
    relationship_type   TEXT,
    routed_to_table     TEXT
);

-- Parameter bindings (populated when parameter mapping files are provided)
CREATE TABLE IF NOT EXISTS param_bindings (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL REFERENCES app_applications(app_id),
    token               TEXT NOT NULL,
    environment         TEXT DEFAULT 'devl',
    resolved_value      TEXT NOT NULL,
    source              TEXT DEFAULT 'operator',
    UNIQUE (app_id, token, environment)
);

-- pgvector similarity store: behavioural notes (analyzer agent) + summaries.
-- "Find the thing that does X" retrieval for the coding agent's grounding.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS app_embeddings (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              TEXT NOT NULL,
    kind                TEXT NOT NULL DEFAULT 'note',   -- 'note' | 'summary' | 'approved_example'
    subject             TEXT,                           -- canonical id this grounds to
    text                TEXT NOT NULL,
    embedding           vector(1024),                   -- titan-embed-text-v2 (1024-d)
    file_path           TEXT,
    line                INT,
    provenance          TEXT DEFAULT 'agent',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Requirement documents (one row per testable unit, from the requirement agent).
-- The behaviour layer: what each unit is SUPPOSED to do, so the coding agent can test
-- behaviour, not just shape/location. The whole 9-section doc is stored as JSONB; the
-- real names it uses are already in the fact tables (the agent's grounding gate
-- guarantees grounded_identifiers ⊆ analyzer facts), so we do NOT re-load names here.
-- No FK to app_applications (mirrors app_embeddings): requirements can be ingested
-- independently of quad ingestion, in any order.
CREATE TABLE IF NOT EXISTS app_requirements (
    id                   BIGSERIAL PRIMARY KEY,
    app_id               TEXT NOT NULL,
    unit                 TEXT NOT NULL,                          -- canonical unit id (from the analyzer)
    unit_type            TEXT,                                   -- WorkflowFile | LambdaHandler | APIEndpoint | ...
    title                TEXT,
    provenance           TEXT NOT NULL DEFAULT 'code-derived',   -- code-derived | jira:<id> | sttm:<id> | human-confirmed
    requirement_backed   BOOLEAN NOT NULL DEFAULT false,         -- true only when a real requirement backs it
    confidence           REAL,                                   -- NULL for code-derived (never a fake 0.0)
    grounding            TEXT,                                   -- computed grounding descriptor (honest, per-unit)
    grounded_identifiers JSONB NOT NULL DEFAULT '[]'::jsonb,     -- every real name the doc used
    sections             JSONB NOT NULL DEFAULT '{}'::jsonb,     -- section name -> markdown body (the whole doc)
    code_version         TEXT,                                   -- ties the requirement to the code it came from
    source_hash          TEXT,                                   -- content hash of the source doc (provenance/idempotency)
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (app_id, unit)
);

-- Migration (idempotent): per-section provenance for human-confirmed corrections.
-- `sections` stays the whole doc; `section_provenance` marks ONLY the sections a human
-- corrected (section name -> 'human-confirmed'). Absent keys inherit the doc-level
-- provenance column — so a doc with no human input has an empty map, never a fake claim.
ALTER TABLE app_requirements ADD COLUMN IF NOT EXISTS section_provenance JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Feedback records (human-in-the-loop). One row per review action on a unit's artifact.
-- This is the components' HITL contract: any surface (UI, API, a test script) writes rows
-- here; agents read the open records for a unit when regenerating; the pipeline marks them
-- applied. code_version keeps feedback honest across re-onboards — feedback given against
-- old code is flagged 'stale' for re-review, never silently replayed onto new code.
CREATE TABLE IF NOT EXISTS app_feedback (
    id           BIGSERIAL PRIMARY KEY,
    app_id       TEXT NOT NULL,
    unit         TEXT NOT NULL,                    -- canonical unit id (from the analyzer)
    artifact     TEXT NOT NULL,                    -- 'spec' | 'test'
    action       TEXT NOT NULL,                    -- 'approve' | 'reject' | 'comment'
    -- What KIND of thing the feedback concerns, so a correction becomes the right kind of
    -- reusable knowledge (a payload fix ≠ a naming complaint). Optional; vocabulary:
    -- 'behavior-scope'|'payload'|'contract'|'data-condition'|'assertion'|'expected-result'
    -- |'environment'|'naming'|'structure'
    target       TEXT,
    comment      TEXT,                             -- reviewer's words (NULL only for approve)
    reviewer     TEXT,
    code_version TEXT,                             -- code version the feedback was given against
    status       TEXT NOT NULL DEFAULT 'open',     -- 'open' | 'applied' | 'closed' | 'stale'
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_functions_app ON app_functions(app_id);
CREATE INDEX IF NOT EXISTS idx_endpoints_app ON app_endpoints(app_id);
CREATE INDEX IF NOT EXISTS idx_tables_app ON app_tables(app_id);
CREATE INDEX IF NOT EXISTS idx_quads_app ON quad_archive(app_id);
CREATE INDEX IF NOT EXISTS idx_quads_predicate ON quad_archive(predicate);
CREATE INDEX IF NOT EXISTS idx_quads_subject ON quad_archive(subject_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_app ON app_embeddings(app_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_vec ON app_embeddings
    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_requirements_app ON app_requirements(app_id);
CREATE INDEX IF NOT EXISTS idx_requirements_unit ON app_requirements(app_id, unit);
CREATE INDEX IF NOT EXISTS idx_feedback_app_unit ON app_feedback(app_id, unit);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON app_feedback(app_id, status);

-- Migration (idempotent): typed feedback target for DBs created before the column existed.
ALTER TABLE app_feedback ADD COLUMN IF NOT EXISTS target TEXT;
