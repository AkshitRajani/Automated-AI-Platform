"""
Postgres writer — batch inserts into fact tables.
All writes are idempotent (ON CONFLICT DO NOTHING).
"""
import logging
from typing import Optional

import psycopg2
from psycopg2.extras import execute_batch

from ingestion.parsers.quad_parser import Entity, Quad, QuadContext
from ingestion.components.inferrer import Component, assign_component

logger = logging.getLogger(__name__)

PREDICATE_ROUTES = {
    "WRITES_DATABASE":       ("app_tables", "written"),
    "QUERIES_DATABASE":      ("app_tables", "read"),
    "READS_DYNAMODB_TABLE":  ("app_tables", "read_dynamodb"),
    "WRITES_DYNAMODB_TABLE": ("app_tables", "written_dynamodb"),
    "WRITES_TO_S3":          ("app_s3_paths", "written"),
    "READS_FROM_S3":         ("app_s3_paths", "read"),
    "READS_CONFIG_FROM_S3":  ("app_s3_paths", "config_read"),
    "EXPOSES_ENDPOINT":      ("app_endpoints", "exposed"),
    "CALLS_HTTP_API":        ("app_endpoints", "called"),
    "INVOKES_LAMBDA":        ("app_service_invocations", None),
    "INVOKES_STEP_FUNCTION": ("app_service_invocations", None),
    "PUBLISHES_TO_SNS":      ("app_service_invocations", None),
    "HAS_JPA_RELATIONSHIP":  ("app_table_relationships", None),
    "READS_SSM_PARAMETER":   ("app_parameters", "ssm"),
    "READS_ENV_VAR":         ("app_parameters", "env_var"),
}


class PostgresWriter:
    def __init__(self, config: dict):
        self.conn = psycopg2.connect(
            host=config["host"],
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
        )
        self.conn.autocommit = False

    # Analyzer-derived fact tables, all app-scoped. Wiped on every re-load so a
    # change upstream (analyzer / ingestion) produces a CLEAN replacement — old
    # facts are never left layered under new ones, and quads never double. The
    # parent row (app_applications) is upserted, not deleted. Human artifacts —
    # app_requirements (specs), app_feedback, and reviewer-approved example
    # embeddings — are NOT touched here: those belong to later stages that own
    # their own replace rules.
    _APP_SCOPED_FACT_TABLES = (
        "quad_archive",
        "app_service_invocations",
        "app_table_relationships",
        "app_parameters",
        "app_s3_paths",
        "app_tables",
        "app_endpoints",
        "app_functions",
        "param_bindings",
        "app_components",
    )

    def delete_app(self, app_id: str) -> dict:
        """Erase this app's analyzer-derived facts before a fresh load — the
        per-app clean re-onboard. Runs inside the open transaction (no commit of
        its own): it is flushed together with ``write_application``'s commit, so
        a wipe is never half-applied, and a re-load after a failed load is
        self-healing. Analyzer-derived note embeddings (kind='note') go too;
        human-approved example embeddings are preserved. First-ever load: every
        DELETE is a harmless no-op (0 rows)."""
        counts: dict[str, int] = {}
        with self.conn.cursor() as cur:
            for table in self._APP_SCOPED_FACT_TABLES:
                cur.execute(f"DELETE FROM {table} WHERE app_id = %s", (app_id,))
                counts[table] = cur.rowcount
            cur.execute(
                "DELETE FROM app_embeddings WHERE app_id = %s AND kind = 'note'",
                (app_id,),
            )
            counts["app_embeddings(note)"] = cur.rowcount
        total = sum(v for v in counts.values() if v and v > 0)
        if total:
            logger.info(f"  Clean re-load: erased {total} prior fact row(s) for '{app_id}'")
        return counts

    def write_application(self, app_id: str, metadata: dict):
        """Insert or update the application record."""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_applications (app_id, source_root, languages_detected, analyzer_version, generated_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (app_id) DO UPDATE SET
                    source_root = EXCLUDED.source_root,
                    languages_detected = EXCLUDED.languages_detected,
                    analyzer_version = EXCLUDED.analyzer_version,
                    generated_at = EXCLUDED.generated_at
            """, (
                app_id,
                metadata.get("source_root", ""),
                metadata.get("languages_detected", []),
                metadata.get("analyzer_version", "unknown"),
                metadata.get("generated_at"),
            ))
        self.conn.commit()

    def write_components(self, app_id: str, components: list[Component]):
        """Insert component records."""
        with self.conn.cursor() as cur:
            for comp in components:
                cur.execute("""
                    INSERT INTO app_components (component_id, app_id, name, path_prefix, languages, entity_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (component_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        path_prefix = EXCLUDED.path_prefix,
                        languages = EXCLUDED.languages,
                        entity_count = EXCLUDED.entity_count
                """, (
                    comp.component_id,
                    comp.app_id,
                    comp.name,
                    comp.path_prefix,
                    comp.languages,
                    comp.entity_count,
                ))
        self.conn.commit()

    def write_entities(self, app_id: str, entities: list[Entity], components: list[Component]):
        """Insert entity records into app_functions."""
        rows = []
        for entity in entities:
            component_id = assign_component(entity, components)
            rows.append((
                app_id,
                entity.type,
                component_id,
                entity.language or "unknown",
                entity.source.file_path if entity.source else "",
                entity.name,
                entity.source.line_start if entity.source else None,
                entity.source.line_end if entity.source else None,
            ))

        with self.conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO app_functions (app_id, entity_type, component_id, language, file_path, symbol, line_start, line_end)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, rows, page_size=500)
        self.conn.commit()

    def write_summary_facts(self, app_id: str, summary: dict):
        """Insert flat facts from the summary section."""
        with self.conn.cursor() as cur:
            # Endpoints
            for endpoint in summary.get("endpoints_exposed", []):
                method, path = _split_endpoint(endpoint)
                cur.execute("""
                    INSERT INTO app_endpoints (app_id, kind, http_method, path_template, resolved)
                    VALUES (%s, 'exposed', %s, %s, true)
                    ON CONFLICT DO NOTHING
                """, (app_id, method, path))

            for endpoint in summary.get("endpoints_called", []):
                cur.execute("""
                    INSERT INTO app_endpoints (app_id, kind, http_method, path_template, full_url, resolved)
                    VALUES (%s, 'called', 'UNKNOWN', %s, %s, true)
                    ON CONFLICT DO NOTHING
                """, (app_id, endpoint, endpoint))

            for endpoint in summary.get("endpoints_called_unresolved", []):
                cur.execute("""
                    INSERT INTO app_endpoints (app_id, kind, http_method, path_template, resolved)
                    VALUES (%s, 'called', 'UNKNOWN', %s, false)
                    ON CONFLICT DO NOTHING
                """, (app_id, endpoint))

            # Tables
            for table in summary.get("tables_read", []):
                cur.execute("""
                    INSERT INTO app_tables (app_id, kind, table_token, resolved)
                    VALUES (%s, 'read', %s, %s)
                    ON CONFLICT DO NOTHING
                """, (app_id, table, "${" not in table))

            for table in summary.get("tables_written", []):
                cur.execute("""
                    INSERT INTO app_tables (app_id, kind, table_token, resolved)
                    VALUES (%s, 'written', %s, %s)
                    ON CONFLICT DO NOTHING
                """, (app_id, table, "${" not in table))

            # DynamoDB tables
            for table in summary.get("dynamodb_read", []):
                cur.execute("""
                    INSERT INTO app_tables (app_id, kind, table_token, resolved)
                    VALUES (%s, 'read_dynamodb', %s, %s)
                    ON CONFLICT DO NOTHING
                """, (app_id, table, "${" not in table))

            for table in summary.get("dynamodb_written", []):
                cur.execute("""
                    INSERT INTO app_tables (app_id, kind, table_token, resolved)
                    VALUES (%s, 'written_dynamodb', %s, %s)
                    ON CONFLICT DO NOTHING
                """, (app_id, table, "${" not in table))

            # S3 paths
            for path in summary.get("s3_read", []):
                cur.execute("""
                    INSERT INTO app_s3_paths (app_id, kind, path, resolved)
                    VALUES (%s, 'read', %s, %s)
                    ON CONFLICT DO NOTHING
                """, (app_id, path, "${" not in path))

            for path in summary.get("s3_written", []):
                cur.execute("""
                    INSERT INTO app_s3_paths (app_id, kind, path, resolved)
                    VALUES (%s, 'written', %s, %s)
                    ON CONFLICT DO NOTHING
                """, (app_id, path, "${" not in path))

            # SSM parameters
            for param in summary.get("ssm_parameters_read", []):
                cur.execute("""
                    INSERT INTO app_parameters (app_id, token, param_type)
                    VALUES (%s, %s, 'ssm')
                    ON CONFLICT DO NOTHING
                """, (app_id, param))

        self.conn.commit()

    def write_quads(self, app_id: str, quads: list[Quad]):
        """
        Write all quads to quad_archive.
        Also route to specialized tables based on predicate.
        """
        archive_rows = []
        for quad in quads:
            subject_type, subject_name = _split_typed_id(quad.subject)
            object_type, object_name = _split_typed_id(quad.object)

            confidence = quad.context.confidence if quad.context else None
            resolved = quad.context.resolved if quad.context else None
            extraction_method = quad.context.extraction_method if quad.context else None
            file_path = quad.context.file_path if quad.context else None
            context_component = quad.context.component if quad.context else None

            route = PREDICATE_ROUTES.get(quad.predicate)
            routed_to = route[0] if route else None

            archive_rows.append((
                app_id,
                quad.subject, subject_type,
                quad.predicate,
                quad.object, object_type,
                confidence, resolved, extraction_method,
                file_path, context_component,
                quad.relationship_type or (quad.context.relationship_type if quad.context else None),
                routed_to,
            ))

        with self.conn.cursor() as cur:
            execute_batch(cur, """
                INSERT INTO quad_archive (
                    app_id, subject_id, subject_type, predicate,
                    object_id, object_type,
                    confidence, resolved, extraction_method,
                    file_path, context_component, relationship_type,
                    routed_to_table
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, archive_rows, page_size=1000)

            # Route to specialized tables
            for quad in quads:
                route = PREDICATE_ROUTES.get(quad.predicate)
                if route:
                    self._route_quad(cur, app_id, quad, route)

        self.conn.commit()

    def _route_quad(self, cur, app_id: str, quad: Quad, route: tuple):
        """Route a quad to its specialized table."""
        table_name, kind = route
        _, object_name = _split_typed_id(quad.object)
        confidence = quad.context.confidence if quad.context else None
        resolved = quad.context.resolved if quad.context else None

        if table_name == "app_tables":
            cur.execute("""
                INSERT INTO app_tables (app_id, kind, table_token, resolved, confidence)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (app_id, kind, object_name, resolved or False, confidence))

        elif table_name == "app_s3_paths":
            cur.execute("""
                INSERT INTO app_s3_paths (app_id, kind, path, resolved, confidence)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (app_id, kind, object_name, resolved or False, confidence))

        elif table_name == "app_endpoints":
            method, path = _split_endpoint(object_name)
            cur.execute("""
                INSERT INTO app_endpoints (app_id, kind, http_method, path_template, resolved, confidence)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (app_id, kind, method, path, resolved or False, confidence))

        elif table_name == "app_service_invocations":
            cur.execute("""
                INSERT INTO app_service_invocations (app_id, source_entity, predicate, target_arn, resolved, confidence)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (app_id, quad.subject, quad.predicate, object_name, resolved or False, confidence))

        elif table_name == "app_table_relationships":
            _, source_table = _split_typed_id(quad.subject)
            rel_type = quad.relationship_type or (quad.context.relationship_type if quad.context else None)
            cur.execute("""
                INSERT INTO app_table_relationships (app_id, source_table, target_table, relationship_type, confidence)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (app_id, source_table, object_name, rel_type or "unknown", confidence))

        elif table_name == "app_parameters":
            cur.execute("""
                INSERT INTO app_parameters (app_id, token, param_type)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (app_id, object_name, kind))

    def write_param_bindings(self, app_id: str, bindings: dict[str, str]):
        """Write parameter bindings to param_bindings table."""
        with self.conn.cursor() as cur:
            for token, value in bindings.items():
                cur.execute("""
                    INSERT INTO param_bindings (app_id, token, environment, resolved_value, source)
                    VALUES (%s, %s, 'devl', %s, 'binding_file')
                    ON CONFLICT (app_id, token, environment) DO UPDATE SET
                        resolved_value = EXCLUDED.resolved_value,
                        source = EXCLUDED.source
                """, (app_id, token, value))
        self.conn.commit()
        logger.info(f"  Param bindings: {len(bindings)} written")

    def close(self):
        self.conn.close()


def _split_endpoint(raw: str) -> tuple[str, str]:
    """Split 'GET /path' into ('GET', '/path'). If no method, returns ('UNKNOWN', raw)."""
    parts = raw.split(" ", 1)
    if len(parts) == 2 and parts[0] in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        return parts[0], parts[1]
    return "UNKNOWN", raw


def _split_typed_id(raw: str) -> tuple[str, str]:
    """Split 'DatabaseTable:APP_ORCN' into ('DatabaseTable', 'APP_ORCN')."""
    if ":" in raw:
        idx = raw.index(":")
        return raw[:idx], raw[idx + 1:]
    return "Unknown", raw
