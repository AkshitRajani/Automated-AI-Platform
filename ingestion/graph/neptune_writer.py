"""
Neptune writer — generates CSV files and triggers bulk load.

Neptune's bulk loader reads from S3:
  - nodes.csv: ~id, ~label, properties...
  - edges.csv: ~id, ~from, ~to, ~label, properties...

This writer generates those CSVs, uploads to S3, and calls the loader API.
"""
import csv
import hashlib
import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

import boto3

from ingestion.parsers.quad_parser import Entity, Quad
from ingestion.components.inferrer import Component, assign_component

logger = logging.getLogger(__name__)


class NeptuneWriter:
    def __init__(self, config: dict):
        self.endpoint = config.get("endpoint", "")
        self.port = config.get("port", 8182)
        self.s3_bucket = config.get("s3_bucket", "")
        self.iam_role_arn = config.get("iam_role_arn", "")
        self.region = config.get("region", "us-east-1")
        self.local_dir = config.get("local_dir", "")

        self._nodes: list[dict] = []
        self._edges: list[dict] = []
        self._seen_node_ids: set[str] = set()

    def delete_app(self, app_id: str) -> None:
        """Remove this app's prior graph before writing the fresh one — the
        graph half of the per-app clean re-onboard.

        Local capture (no cluster): the per-app CSV directory is rewritten fresh
        on every load, so we just clear the old files — the re-load is already
        clean by overwrite. Configured cluster: the bulk loader only adds and
        updates by ~id, so nodes/edges for deleted code linger forever; we drop
        every node carrying this app_id first (its edges drop with it). The drop
        is best-effort — a failure warns but never aborts the load (worst case is
        the pre-existing lingering-ghost behaviour, never worse)."""
        if not self.s3_bucket or not self.endpoint:
            if self.local_dir:
                out = Path(self.local_dir) / app_id
                for name in ("nodes.csv", "edges.csv"):
                    f = out / name
                    if f.exists():
                        f.unlink()
            return
        try:
            self._drop_app_from_cluster(app_id)
        except Exception as exc:
            logger.warning(
                f"  Neptune per-app drop failed for '{app_id}' ({exc}); the load "
                f"will still add/update, but stale edges from deleted code may remain.")

    def _drop_app_from_cluster(self, app_id: str) -> None:
        """Gremlin drop of every vertex tagged with this app_id (edges cascade)."""
        import json
        import ssl
        import urllib.request

        scheme = "https" if self.port == 8182 else "http"
        url = f"{scheme}://{self.endpoint}:{self.port}/gremlin"
        gremlin = f"g.V().has('app_id', '{app_id}').drop()"
        body = json.dumps({"gremlin": gremlin}).encode("utf-8")
        ssl_ctx = None
        if self.endpoint in ("127.0.0.1", "localhost"):
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30, context=ssl_ctx)
        logger.info(f"  Neptune: dropped prior graph for '{app_id}' before reload")

    def write_nodes(self, app_id: str, entities: list[Entity], summary: dict, components: list[Component]):
        """Generate node records from entities, summary items, and components."""

        # Application node
        self._add_node(app_id, "Application", app_id, {"display_name": app_id})

        # Component nodes
        for comp in components:
            self._add_node(comp.component_id, "Component", comp.name, {
                "app_id": app_id,
                "path_prefix": comp.path_prefix,
                "entity_count": str(comp.entity_count),
            })
            # Application → CONTAINS → Component
            self._add_edge(app_id, comp.component_id, "CONTAINS", app_id)

        # Entity nodes
        for entity in entities:
            node_id = f"{app_id}:{entity.type}:{entity.name}"
            component_id = assign_component(entity, components)
            self._add_node(node_id, entity.type, entity.name, {
                "app_id": app_id,
                "component_id": component_id,
                "language": entity.language or "",
                "file_path": entity.source.file_path if entity.source else "",
            })
            # Component → DEFINES → Entity
            self._add_edge(component_id, node_id, "DEFINES", app_id)

        # Resource nodes from summary (endpoints, tables, S3 paths)
        for endpoint in summary.get("endpoints_exposed", []):
            node_id = f"{app_id}:Endpoint:{endpoint}"
            self._add_node(node_id, "Endpoint", endpoint, {"app_id": app_id, "kind": "exposed"})

        for table in summary.get("tables_read", []) + summary.get("tables_written", []):
            node_id = f"{app_id}:Table:{table}"
            self._add_node(node_id, "Table", table, {
                "app_id": app_id,
                "resolved": str("${" not in table),
            })

        for table in summary.get("dynamodb_read", []) + summary.get("dynamodb_written", []):
            node_id = f"{app_id}:DynamoDBTable:{table}"
            self._add_node(node_id, "DynamoDBTable", table, {"app_id": app_id})

        for path in summary.get("s3_read", []) + summary.get("s3_written", []):
            node_id = f"{app_id}:S3Path:{path}"
            self._add_node(node_id, "S3Path", path, {"app_id": app_id})

    def write_edges(self, app_id: str, quads: list[Quad], components: list[Component]):
        """Generate edge records from quads. Edge label = quad predicate."""

        for quad in quads:
            source_id = f"{app_id}:{quad.subject}"
            target_id = f"{app_id}:{quad.object}"

            # Ensure both nodes exist (create if not seen yet)
            if source_id not in self._seen_node_ids:
                s_type, s_name = _split_typed(quad.subject)
                self._add_node(source_id, s_type, s_name, {"app_id": app_id})

            if target_id not in self._seen_node_ids:
                t_type, t_name = _split_typed(quad.object)
                self._add_node(target_id, t_type, t_name, {"app_id": app_id})

            # Edge properties from context
            props = {"app_id": app_id}
            if quad.context:
                if quad.context.confidence is not None:
                    props["confidence"] = str(quad.context.confidence)
                if quad.context.resolved is not None:
                    props["resolved"] = str(quad.context.resolved).lower()
                if quad.context.extraction_method:
                    props["extraction_method"] = quad.context.extraction_method

            self._add_edge(source_id, target_id, quad.predicate, app_id, props)

        # Flush to S3 and trigger bulk load
        self._flush(app_id)

    def _add_node(self, node_id: str, label: str, name: str, properties: Optional[dict] = None):
        """Add a node if not already seen."""
        if node_id in self._seen_node_ids:
            return
        self._seen_node_ids.add(node_id)
        node = {"~id": node_id, "~label": label, "name:String": name}
        if properties:
            for k, v in properties.items():
                node[f"{k}:String"] = str(v) if v else ""
        self._nodes.append(node)

    def _add_edge(self, from_id: str, to_id: str, label: str, app_id: str, properties: Optional[dict] = None):
        """Add an edge."""
        edge_id = _deterministic_edge_id(from_id, to_id, label)
        edge = {"~id": edge_id, "~from": from_id, "~to": to_id, "~label": label}
        if properties:
            for k, v in properties.items():
                edge[f"{k}:String"] = str(v) if v else ""
        self._edges.append(edge)

    def _flush(self, app_id: str):
        """Write CSVs to S3 and trigger Neptune bulk load.

        With no cluster configured, ``local_dir`` (NEPTUNE_LOCAL_DIR) captures the
        same CSVs to disk — same per-app overwrite semantics as the S3 keys — so
        tests can assert on graph output offline. Without it, the skip is LOUD:
        it names exactly what was discarded."""
        if not self.s3_bucket or not self.endpoint:
            if self.local_dir:
                out = Path(self.local_dir) / app_id
                out.mkdir(parents=True, exist_ok=True)
                for name, rows in (("nodes.csv", self._nodes), ("edges.csv", self._edges)):
                    data = _to_csv(rows)
                    (out / name).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
                logger.warning(
                    f"Neptune not configured — captured {len(self._nodes)} nodes / "
                    f"{len(self._edges)} edges to {out} (NOT loaded into any graph).")
            else:
                logger.warning(
                    f"Neptune not configured — DISCARDING {len(self._nodes)} nodes / "
                    f"{len(self._edges)} edges for {app_id}. Nothing was persisted; "
                    f"set NEPTUNE_ENDPOINT+NEPTUNE_S3_BUCKET or NEPTUNE_LOCAL_DIR.")
            self._nodes.clear()
            self._edges.clear()
            self._seen_node_ids.clear()
            return

        s3 = boto3.client("s3", region_name=self.region)
        prefix = f"neptune-load/{app_id}"

        # Upload nodes CSV
        nodes_csv = _to_csv(self._nodes)
        s3.put_object(Bucket=self.s3_bucket, Key=f"{prefix}/nodes.csv", Body=nodes_csv)
        logger.info(f"  Uploaded {len(self._nodes)} nodes to s3://{self.s3_bucket}/{prefix}/nodes.csv")

        # Upload edges CSV
        edges_csv = _to_csv(self._edges)
        s3.put_object(Bucket=self.s3_bucket, Key=f"{prefix}/edges.csv", Body=edges_csv)
        logger.info(f"  Uploaded {len(self._edges)} edges to s3://{self.s3_bucket}/{prefix}/edges.csv")

        # Trigger Neptune bulk loader
        self._trigger_bulk_load(f"s3://{self.s3_bucket}/{prefix}/")

        # Clear state for next app
        self._nodes.clear()
        self._edges.clear()
        self._seen_node_ids.clear()

    def _trigger_bulk_load(self, s3_source: str):
        """Call Neptune's bulk loader API."""
        import urllib.request
        import json
        import ssl

        # When reaching Neptune through a localhost SSH tunnel the TLS cert is for the
        # real cluster host, not 127.0.0.1, so skip hostname/cert verification for it.
        ssl_ctx = None
        if self.endpoint in ("127.0.0.1", "localhost"):
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        url = f"https://{self.endpoint}:{self.port}/loader"
        payload = json.dumps({
            "source": s3_source,
            "format": "csv",
            "iamRoleArn": self.iam_role_arn,
            "region": self.region,
            "failOnError": "FALSE",
            "parallelism": "OVERSUBSCRIBE",
            "queueRequest": "TRUE",
        }).encode()

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, context=ssl_ctx) as response:
                result = json.loads(response.read())
                logger.info(f"  Neptune bulk load triggered: {result.get('payload', {}).get('loadId', 'unknown')}")
        except Exception as e:
            logger.error(f"  Neptune bulk load failed: {e}")
            raise


def _to_csv(records: list[dict]) -> bytes:
    """Convert a list of dicts to CSV bytes."""
    if not records:
        return b""

    all_keys = []
    for r in records:
        for k in r.keys():
            if k not in all_keys:
                all_keys.append(k)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue().encode("utf-8")


def _split_typed(raw: str) -> tuple[str, str]:
    """Split 'DatabaseTable:name' into ('DatabaseTable', 'name')."""
    if ":" in raw:
        idx = raw.index(":")
        return raw[:idx], raw[idx + 1:]
    return "Unknown", raw


def _deterministic_edge_id(from_id: str, to_id: str, label: str) -> str:
    """Generate a stable edge ID from its components."""
    raw = f"{from_id}|{label}|{to_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
