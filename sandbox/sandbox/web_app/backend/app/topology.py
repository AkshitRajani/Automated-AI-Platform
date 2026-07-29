"""Convert spec.yaml + sandbox.manifest.json into UI-friendly nodes & edges.

A "topology" is a flat list of nodes (Lambdas, Step Fns, S3 buckets, DDB tables,
Glue jobs, Microcks-backed services, Postgres) plus directed edges synthesized
from `data_flows[*].edges` and `lambdas[*].upstream_dependencies`.

The UI never reads the spec directly — it gets this normalized shape.
"""
from __future__ import annotations
from pathlib import Path
import json
import yaml

from .settings import profile_dir

# Confidence levels mirror DATA_FLOW.md §2 — used by the UI to tint nodes.
NODE_KIND_CONFIDENCE = {
    "lambda": "medium",
    "step_function": "medium",
    "s3": "high",
    "dynamodb": "medium",
    "glue_job": "high",
    "microcks": "medium",
    "postgres": "high",
}


def read_spec(profile: str) -> dict:
    spec_path = profile_dir(profile) / "spec.yaml"
    with open(spec_path) as f:
        return yaml.safe_load(f)


_read_spec = read_spec  # back-compat for internal callers


def _read_manifest(profile: str) -> dict:
    manifest_path = profile_dir(profile) / "sandbox.manifest.json"
    with open(manifest_path) as f:
        return json.load(f)


def build_topology(profile: str) -> dict:
    spec = _read_spec(profile)
    manifest = _read_manifest(profile)

    # Index manifest's lambda_roster by name → fidelity tier + source.
    fidelity_index = {
        r["name"]: {
            "tier": r.get("tier", "L1"),
            "source": r.get("source"),
            "tier_kind": r.get("tier_kind", "core"),
            "source_suite": r.get("source_suite"),
        }
        for r in manifest.get("lambda_roster", [])
    }

    nodes: list[dict] = []
    edges: list[dict] = []

    def node(node_id: str, kind: str, label: str, **extra):
        nodes.append({
            "id": node_id,
            "kind": kind,
            "label": label,
            "confidence": NODE_KIND_CONFIDENCE.get(kind, "medium"),
            **extra,
        })

    # Lambdas
    for lam in spec.get("lambdas", []):
        name = lam["lambda_name"]
        fid = fidelity_index.get(name, {})
        node(
            f"lambda:{name}",
            "lambda",
            name,
            family=lam.get("family"),
            role=lam.get("role"),
            runtime=lam.get("runtime"),
            invocation_pattern=lam.get("invocation_pattern"),
            tier_kind=fid.get("tier_kind", lam.get("tier", "core")),
            fidelity_tier=fid.get("tier", "L1"),
            fidelity_source=fid.get("source"),
            source_suite=fid.get("source_suite") or lam.get("source_suite"),
        )

    # Step functions
    for sf in spec.get("step_functions", []):
        node(
            f"stepfn:{sf['state_machine_name']}",
            "step_function",
            sf["state_machine_name"],
            integrations=sf.get("lambda_integrations", []),
        )

    # DynamoDB tables
    for ddb in spec.get("dynamodb", []):
        node(
            f"ddb:{ddb['table_name']}",
            "dynamodb",
            ddb["table_name"],
            hash_key=ddb.get("hash_key"),
        )

    # S3 buckets
    for s3 in spec.get("s3_buckets", []):
        node(
            f"s3:{s3['bucket_name']}",
            "s3",
            s3["bucket_name"],
            purpose=s3.get("purpose"),
        )

    # Glue jobs
    for gj in spec.get("glue_jobs", []):
        node(
            f"glue:{gj['job_name']}",
            "glue_job",
            gj["job_name"],
            input=gj.get("input_dataset_path"),
            output=gj.get("output_dataset_path"),
        )

    # Behavioral contracts → Microcks-backed services
    for c in spec.get("behavioral_contracts", []):
        node(
            f"microcks:{c['name']}",
            "microcks",
            c["name"].upper(),
            interaction_type=c.get("interaction_type"),
            consumer=c.get("consumer"),
        )

    # Postgres (manifest endpoint)
    if "postgres" in manifest.get("endpoints", {}):
        node("pg:aap_sandbox", "postgres", "Aurora-Postgres (aap_sandbox)")

    # Edges from explicit data_flows
    eid = 0
    for flow in spec.get("data_flows", []):
        for e in flow.get("edges", []):
            f, t, via = e["from"], e["to"], e.get("via", "")
            src = _ref_to_node_id(f)
            dst = _ref_to_node_id(t)
            if src and dst:
                eid += 1
                edges.append({
                    "id": f"e{eid}",
                    "source": src,
                    "target": dst,
                    "label": via,
                    "flow": flow["id"],
                })

    # Synthesized edges from lambdas[].upstream_dependencies
    for lam in spec.get("lambdas", []):
        for dep in lam.get("upstream_dependencies", []) or []:
            dst = _dep_to_node_id(dep)
            if dst:
                eid += 1
                edges.append({
                    "id": f"e{eid}",
                    "source": f"lambda:{lam['lambda_name']}",
                    "target": dst,
                    "label": "depends_on",
                    "flow": "deps",
                })

    return {
        "profile": profile,
        "sandbox_id": manifest.get("sandbox_id"),
        "tenant": manifest.get("tenant"),
        "snapshot_date": manifest.get("snapshot_date"),
        "endpoints": manifest.get("endpoints", {}),
        "counts": manifest.get("counts", {}),
        "fidelity_summary": manifest.get("fidelity_summary", {}),
        "nodes": nodes,
        "edges": edges,
    }


def _ref_to_node_id(ref: dict) -> str | None:
    kind = ref.get("kind")
    name = ref.get("name")
    if not name:
        return None
    return {
        "lambda": f"lambda:{name}",
        "dynamodb": f"ddb:{name}",
        "s3": f"s3:{name}",
        "glue_job": f"glue:{name}",
        "step_function": f"stepfn:{name}",
    }.get(kind)


def _dep_to_node_id(dep: str) -> str | None:
    """Parse strings like 'dynamodb:table-name' or 'http:dbm'."""
    if ":" not in dep:
        return None
    kind, name = dep.split(":", 1)
    return {
        "dynamodb": f"ddb:{name}",
        "http": f"microcks:{name}",
        "s3": f"s3:{name}",
    }.get(kind)
