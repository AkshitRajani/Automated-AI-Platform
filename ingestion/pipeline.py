"""
Main pipeline orchestrator.
Processes all quad files in a given folder, one by one.
Each file is independent — one failure doesn't stop the others.
"""
import logging
import os
from pathlib import Path
from typing import Any

from ingestion.parsers.quad_parser import parse_quad_file, Quad
from ingestion.parsers.resolver import Resolver
from ingestion.writers.postgres_writer import PostgresWriter
from ingestion.writers.embedding_writer import EmbeddingWriter
from ingestion.graph.neptune_writer import NeptuneWriter  # kept for reference/rollback, no longer instantiated below
from ingestion.graph.neo4j_writer import Neo4jWriter
from ingestion.components.inferrer import infer_components
from ingestion.config import load_config

logger = logging.getLogger(__name__)


def run_pipeline(source: str) -> dict[str, Any]:
    config = load_config()

    # Ensure schema exists
    _ensure_schema(config["postgres"])

    quad_files = _discover_quad_files(source)

    logger.info(f"Discovered {len(quad_files)} quad file(s) in {source}")

    # Load parameter bindings (if any exist)
    bindings_dir = os.environ.get("PARAM_BINDINGS_SOURCE", "")
    resolver = Resolver(bindings_dir)
    if resolver.has_bindings:
        logger.info(f"Parameter resolver: {resolver.binding_count} bindings loaded")
    else:
        logger.info("Parameter resolver: no bindings — tokens will stay as ${...}")

    report = {
        "files_processed": 0,
        "succeeded": 0,
        "failed": 0,
        "failed_files": [],
        "apps": [],
        "bindings_loaded": resolver.binding_count,
    }

    pg_writer = PostgresWriter(config["postgres"])
    # neptune_writer = NeptuneWriter(config["neptune"])  # replaced by Neo4j below
    neptune_writer = Neo4jWriter(config["neo4j"])
    # Embedding writer is optional: only if a Bedrock embedding model is configured.
    embed_writer = None
    if config.get("bedrock", {}).get("embedding_model") or config.get("bedrock", {}).get("model_arn"):
        try:
            embed_writer = EmbeddingWriter(config["postgres"], config["bedrock"])
        except Exception as exc:
            logger.warning(f"Embedding writer unavailable — notes won't be embedded: {exc}")

    for quad_file_path in quad_files:
        report["files_processed"] += 1
        fallback_id = _derive_app_id(quad_file_path)

        try:
            logger.info(f"Processing: {quad_file_path} (fallback app_id: {fallback_id})")
            app_id = _process_one_app(quad_file_path, fallback_id, pg_writer, neptune_writer, resolver, embed_writer)
            report["succeeded"] += 1
            report["apps"].append({"app_id": app_id, "status": "ok"})

        except Exception as e:
            logger.error(f"FAILED: {quad_file_path} — {e}", exc_info=True)
            report["failed"] += 1
            report["failed_files"].append(str(quad_file_path))
            report["apps"].append({"app_id": fallback_id, "status": "failed", "error": str(e)})

    return report


def ingest_requirements(app_id: str, requirements_dir: str,
                        code_version: str | None = None) -> dict[str, Any]:
    """Ingest one app's requirement-agent output into ``app_requirements``.

    A parallel onboarding artifact, deliberately decoupled from quad ingestion: it does
    not discover or parse quad files. Run it after the app's quads are loaded (so the fact
    tables the requirement names point at already exist). Idempotent per app.
    """
    from ingestion.writers.requirements_writer import (RequirementsWriter,
                                                       load_requirement_docs)
    config = load_config()
    _ensure_schema(config["postgres"])

    rows = load_requirement_docs(requirements_dir)
    writer = RequirementsWriter(config["postgres"])
    try:
        written = writer.write_requirements(app_id, rows, code_version=code_version)
    finally:
        writer.close()

    logger.info(f"Requirements ingested for {app_id}: {written} unit(s) from {requirements_dir}")
    return {"app_id": app_id, "units_written": written, "docs_found": len(rows),
            "requirements_dir": requirements_dir}


def _process_one_app(quad_file_path: str, app_id: str, pg: PostgresWriter, neptune: "NeptuneWriter | Neo4jWriter", resolver: Resolver, embed: "EmbeddingWriter | None" = None) -> str:
    """Process a single quad file end-to-end. Returns the app_id actually used."""

    # Step 1: Parse the quad file
    parsed = parse_quad_file(quad_file_path)

    # The analyzer stamps the app_id the operator chose into the file's own
    # metadata. Trust that over the filename guess, so renaming or re-saving a
    # quad file under a different name can never fork a duplicate app in the KB.
    stamped = (parsed.metadata or {}).get("app_id")
    if stamped and stamped != app_id:
        logger.info(f"  app_id from quad metadata: '{stamped}' (filename implied '{app_id}')")
        app_id = stamped

    logger.info(
        f"  Parsed: {parsed.entity_count} entities, "
        f"{parsed.quad_count} quads, "
        f"{parsed.quarantine_count} quarantined"
    )

    # Step 2: Resolve parameters in quads — the quad file's own repo-declared
    # bindings (analyzer harvest) merged under the worksheet (worksheet wins).
    if parsed.bindings:
        resolver = resolver.merged(parsed.bindings)
        logger.info(f"  Bindings: +{len(parsed.bindings)} repo-declared from the quad file")
    resolved_count = 0
    if resolver.has_bindings:
        for quad in parsed.quads:
            new_object, is_resolved = resolver.resolve(quad.object)
            if new_object != quad.object:
                quad.object = new_object
                if quad.context:
                    quad.context.resolved = is_resolved
                resolved_count += 1

        # Also resolve in summary lists
        for key in parsed.summary:
            if isinstance(parsed.summary[key], list):
                new_list = []
                for item in parsed.summary[key]:
                    if isinstance(item, str):
                        resolved_item, _ = resolver.resolve(item)
                        new_list.append(resolved_item)
                    else:
                        new_list.append(item)
                parsed.summary[key] = new_list

        logger.info(f"  Resolved: {resolved_count} quad objects updated with real names")

    # Step 3: Infer components from entity file paths
    components = infer_components(app_id, parsed.entities)
    logger.info(f"  Components inferred: {len(components)}")

    # Step 4: CLEAN RE-LOAD — erase this app's prior analyzer-derived facts +
    # graph before writing the fresh batch, so removed facts don't linger and
    # quads don't double (issues D3/D4/D5). Postgres wipe stays in the open
    # transaction and is flushed by write_application's commit, so it is atomic
    # with the parent-row upsert and a failed load is self-healing on retry.
    # First-ever load: every delete is a harmless no-op.
    pg.delete_app(app_id)
    neptune.delete_app(app_id)  # `neptune` now holds a Neo4jWriter instance (see run_pipeline) — same interface

    # The application row FIRST — param_bindings carries a foreign key to it, so
    # this order is load-bearing (issue D1: the old order failed every first-ever
    # ingest that carried bindings, and retry could never recover).
    pg.write_application(app_id, parsed.metadata)
    if resolver.has_bindings:
        pg.write_param_bindings(app_id, resolver.bindings)

    # Step 5: Write to Postgres (flat facts + quad archive)
    pg.write_components(app_id, components)
    pg.write_entities(app_id, parsed.entities, components)
    pg.write_summary_facts(app_id, parsed.summary)
    pg.write_quads(app_id, parsed.quads)
    logger.info(f"  Postgres: done")

    # Step 6: Write to the graph store (nodes + edges) — Neo4j now, was Neptune
    # (NeptuneWriter kept intact in neptune_writer.py for reference/rollback)
    neptune.write_nodes(app_id, parsed.entities, parsed.summary, components)
    neptune.write_edges(app_id, parsed.quads, components)
    logger.info(f"  Neo4j: done")

    # Step 7: Embed behavioural notes -> pgvector (optional, graceful)
    if embed is not None and parsed.notes:
        try:
            n = embed.write_notes(app_id, parsed.notes)
            logger.info(f"  pgvector: embedded {n}/{len(parsed.notes)} notes")
        except Exception as exc:
            logger.warning(f"  pgvector embedding failed (facts/graph intact): {exc}")

    return app_id


def _discover_quad_files(source: str) -> list[str]:
    """Find all .yaml files in the source folder."""
    if source.startswith("s3://"):
        return _discover_s3(source)
    else:
        folder = Path(source)
        if not folder.exists():
            raise FileNotFoundError(f"Source folder not found: {source}")
        return sorted(str(f) for f in folder.glob("*.yaml"))


def _discover_s3(uri: str) -> list[str]:
    """List .yaml files in an S3 prefix."""
    import boto3
    parts = uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""

    s3 = boto3.client("s3")
    response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)

    files = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        if key.endswith(".yaml") or key.endswith(".yml"):
            files.append(f"s3://{bucket}/{key}")
    return sorted(files)


def _derive_app_id(quad_file_path: str) -> str:
    """
    Fallback only — the real app_id is read from the quad file's metadata (see
    _process_one_app). Derives an id from the quad file name when metadata lacks one.
    'myapp_quad_store.yaml' → 'myapp'
    'app_b_quad_store.yaml' → 'app_b'
    """
    name = Path(quad_file_path).stem
    for suffix in ("_quad_store", "_quad", "_quads"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def _ensure_schema(pg_config: dict):
    """Create tables if they don't exist. Reads schema.sql from the package directory."""
    import psycopg2
    schema_path = Path(__file__).parent / "schema.sql"
    if not schema_path.exists():
        logger.warning("schema.sql not found — skipping schema setup")
        return

    conn = psycopg2.connect(
        host=pg_config["host"],
        port=pg_config["port"],
        database=pg_config["database"],
        user=pg_config["user"],
        password=pg_config["password"],
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text())
    conn.close()
    logger.info("Schema: verified")
