"""
Neo4j writer — replaces NeptuneWriter's role, direct graph writes via Cypher.

Neo4j Community Edition runs locally (free, no AWS account, no S3 staging
bucket, no bulk-load trigger) — writes go straight over the Bolt protocol as
``MERGE`` statements. Mirrors ``NeptuneWriter``'s public interface
(``delete_app`` / ``write_nodes`` / ``write_edges``) so callers (``ingestion/
pipeline.py``) can swap one for the other with minimal changes. See
``neptune_writer.py`` for the original AWS-based implementation, kept intact
for reference / rollback.
"""
from __future__ import annotations

import logging
from typing import Optional

from ingestion.parsers.quad_parser import Entity, Quad
from ingestion.components.inferrer import Component, assign_component

logger = logging.getLogger(__name__)


class Neo4jWriter:
    def __init__(self, config: dict):
        self.uri = config.get("uri", "")
        self.user = config.get("user", "neo4j")
        self.password = config.get("password", "")
        self._driver = None
        if self.uri:
            try:
                from neo4j import GraphDatabase
                self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            except Exception as exc:
                logger.warning(f"Neo4j not configured — driver could not connect ({exc}); "
                              f"writes will be skipped, same degrade-gracefully behavior as "
                              f"NeptuneWriter without an endpoint.")
                self._driver = None

    def delete_app(self, app_id: str) -> None:
        """Drop every node tagged with this app_id before a fresh load — the
        graph half of the per-app clean re-onboard (mirrors
        NeptuneWriter.delete_app's semantics, but Neo4j has no separate
        cluster-drop step — one Cypher statement does it)."""
        if self._driver is None:
            return
        try:
            with self._driver.session() as session:
                session.run("MATCH (n {app_id: $app_id}) DETACH DELETE n", app_id=app_id)
        except Exception as exc:
            logger.warning(f"  Neo4j per-app drop failed for '{app_id}' ({exc}); the load "
                           f"will still add/update, but stale edges from deleted code may remain.")

    def write_nodes(self, app_id: str, entities: list, summary: dict, components: list) -> None:
        if self._driver is None:
            logger.warning(f"Neo4j not configured — nodes for {app_id} were not written.")
            return
        with self._driver.session() as session:
            session.run(
                "MERGE (a:Application {id: $id}) "
                "SET a.app_id = $app_id, a.display_name = $name",
                id=app_id, app_id=app_id, name=app_id,
            )
            for comp in components:
                session.run(
                    "MERGE (c:Component {id: $id}) "
                    "SET c.app_id = $app_id, c.name = $name, c.path_prefix = $path_prefix, "
                    "c.entity_count = $entity_count "
                    "WITH c "
                    "MATCH (a:Application {id: $app_id}) "
                    "MERGE (a)-[:CONTAINS]->(c)",
                    id=comp.component_id, app_id=app_id, name=comp.name,
                    path_prefix=comp.path_prefix, entity_count=comp.entity_count,
                )
            for entity in entities:
                node_id = f"{app_id}:{entity.type}:{entity.name}"
                component_id = assign_component(entity, components)
                # entity.type is one of a fixed internal vocabulary (Module/Class/
                # Function/Method), never user-supplied text — safe to use as a label.
                session.run(
                    f"MERGE (e:{entity.type} {{id: $id}}) "
                    "SET e.app_id = $app_id, e.name = $name, e.language = $language, "
                    "e.file_path = $file_path, e.component_id = $component_id "
                    "WITH e "
                    "MATCH (c:Component {id: $component_id}) "
                    "MERGE (c)-[:DEFINES]->(e)",
                    id=node_id, app_id=app_id, name=entity.name,
                    language=entity.language or "",
                    file_path=entity.source.file_path if entity.source else "",
                    component_id=component_id,
                )
            for endpoint in summary.get("endpoints_exposed", []):
                node_id = f"{app_id}:Endpoint:{endpoint}"
                session.run(
                    "MERGE (n:Endpoint {id: $id}) SET n.app_id = $app_id, n.name = $name, n.kind = 'exposed'",
                    id=node_id, app_id=app_id, name=endpoint,
                )
            for table in summary.get("tables_read", []) + summary.get("tables_written", []):
                node_id = f"{app_id}:Table:{table}"
                session.run(
                    "MERGE (n:Table {id: $id}) SET n.app_id = $app_id, n.name = $name",
                    id=node_id, app_id=app_id, name=table,
                )
            for table in summary.get("dynamodb_read", []) + summary.get("dynamodb_written", []):
                node_id = f"{app_id}:DynamoDBTable:{table}"
                session.run(
                    "MERGE (n:DynamoDBTable {id: $id}) SET n.app_id = $app_id, n.name = $name",
                    id=node_id, app_id=app_id, name=table,
                )
            for path in summary.get("s3_read", []) + summary.get("s3_written", []):
                node_id = f"{app_id}:S3Path:{path}"
                session.run(
                    "MERGE (n:S3Path {id: $id}) SET n.app_id = $app_id, n.name = $name",
                    id=node_id, app_id=app_id, name=path,
                )

    def write_edges(self, app_id: str, quads: list, components: list) -> None:
        if self._driver is None:
            logger.warning(f"Neo4j not configured — edges for {app_id} were not written.")
            return
        with self._driver.session() as session:
            for quad in quads:
                source_id = f"{app_id}:{quad.subject}"
                target_id = f"{app_id}:{quad.object}"
                s_type, s_name = _split_typed(quad.subject)
                t_type, t_name = _split_typed(quad.object)
                props = {"app_id": app_id}
                if quad.context:
                    if quad.context.confidence is not None:
                        props["confidence"] = str(quad.context.confidence)
                    if quad.context.resolved is not None:
                        props["resolved"] = str(quad.context.resolved).lower()
                    if quad.context.extraction_method:
                        props["extraction_method"] = quad.context.extraction_method
                # quad.predicate/s_type/t_type are from the fixed internal
                # vocabulary (PREDICATE_ROUTES, entity/resource kinds), never
                # user-supplied text — safe as Cypher labels/rel types (Cypher
                # requires these static in the query text, can't be parameterized).
                # Using the type here (not discarding it, as the first version of
                # this method did) matches NeptuneWriter's original completeness —
                # auto-created stub nodes now get a real label, not an empty one.
                session.run(
                    f"MERGE (s:{s_type} {{id: $source_id}}) ON CREATE SET s.app_id = $app_id, s.name = $s_name "
                    f"MERGE (t:{t_type} {{id: $target_id}}) ON CREATE SET t.app_id = $app_id, t.name = $t_name "
                    f"MERGE (s)-[r:{quad.predicate}]->(t) "
                    "SET r += $props",
                    source_id=source_id, target_id=target_id, app_id=app_id,
                    s_name=s_name, t_name=t_name, props=props,
                )
        logger.info(f"  Neo4j: wrote {len(quads)} edge(s) for {app_id}")

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()


def _split_typed(raw: str) -> tuple:
    """Split 'DatabaseTable:name' into ('DatabaseTable', 'name')."""
    if ":" in raw:
        idx = raw.index(":")
        return raw[:idx], raw[idx + 1:]
    return "Unknown", raw
