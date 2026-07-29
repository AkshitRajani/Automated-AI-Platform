"""
Workflow-YAML parser — the etl_workflow ETL dialect (Step 1, no LLM).

Empirically there is exactly ONE workflow format in the corpus (etl_workflow `actions[]`,
6 action types), so this is one extractor, not a registry. Detection is by SHAPE
(an `actions` list whose items carry an `action` key) — never by filename — which
correctly excludes the look-alike `{document, content, function_name}` code-storage
files.

Robust to slight format drift: resources are also picked up by the **`${…}`/`s3://`
convention** (100% stable across the corpus), so a renamed field still yields its
resource; and an unknown action type is FLAGGED, never silently dropped.

Emits the same entities + quads as the Python parser → straight into ingestion.
"""
from __future__ import annotations

import re
from typing import Iterator, List, Set, Tuple

from .models import Entity, Quad, Source

import sqlglot
from sqlglot import exp

KNOWN_ACTIONS = {"EXTRACT", "LOAD", "MERGE", "PURGE", "EXECUTE", "TRANSFORM"}
PRODUCERS = {"EXTRACT", "MERGE", "TRANSFORM"}   # actions that yield a downstream dataframe
# the ${...}/s3:// resource convention (a genuine string convention, kept as the drift net)
_RES = re.compile(r"s3://[^\s'\"]+|\$\{[\w.]+\.(?:glue_table_name|glue_database_name|s3_bucket|s3_prefix)\}")


def is_workflow(doc) -> bool:
    """SHAPE test: an actions list with at least one item carrying an `action` key."""
    return (isinstance(doc, dict) and isinstance(doc.get("actions"), list)
            and any(isinstance(s, dict) and "action" in s for s in doc["actions"]))


def _symbolic(s) -> bool:
    return "${" in str(s)


def _backbone(val) -> str | None:
    """`dataBackbone: name=X:scenario=Y` → X. Plain string split, no regex."""
    if not isinstance(val, str) or "name=" not in val:
        return None
    return val.split("name=", 1)[1].split(":")[0].strip() or None


def _sql_refs(sql: str) -> list:
    """Table/dataframe names referenced in a SQL string, via sqlglot's AST (not
    regex). Templated `${...}` SQL won't parse → handled by dataBackbone instead."""
    try:
        tree = sqlglot.parse_one(sql, error_level="ignore")
    except Exception:
        return []
    return [t.name for t in tree.find_all(exp.Table)] if tree is not None else []


def _strings(node) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def extract_workflow(doc: dict, relpath: str) -> Tuple[List[Entity], List[Quad], Set[str]]:
    entities: List[Entity] = []
    quads: List[Quad] = []
    unknown: Set[str] = set()

    # canonical ids: Type:name (matches the code parser + Neptune node keying)
    wf = f"WorkflowFile:{relpath}"
    entities.append(Entity(id=wf, type="WorkflowFile", name=relpath,
                           language="yaml-workflow", source=Source(relpath, 1, None)))
    _RES_TYPE = {"QUERIES_DATABASE": "Table", "WRITES_DATABASE": "Table",
                 "WRITES_TO_S3": "S3Object", "READS_FROM_S3": "S3Object", "CALLS": "Symbol"}

    # Single ordered pass — `current[df]` = the step that *currently* produces a
    # dataframe, so lineage links to the most-recent prior producer (a later
    # LOAD/PURGE on the same name can't clobber it).
    current = {}
    for i, s in enumerate(doc.get("actions", [])):
        if not isinstance(s, dict) or "action" not in s:
            continue
        action = str(s["action"])
        name = s.get("name") or f"{action.lower()}_{i}"
        step_qual = f"{relpath}::{name}"
        sid = f"Step:{step_qual}"
        entities.append(Entity(id=sid, type="Step", name=step_qual,
                               language="yaml-workflow", source=Source(relpath, None, None)))
        quads.append(Quad(wf, "DEFINES", sid, True, 1.0, relpath, None,
                          language="yaml-workflow"))
        if action not in KNOWN_ACTIONS:
            unknown.add(action)

        def add(pred, obj, resolved=True, conf=1.0):
            t = _RES_TYPE.get(pred)
            o = f"{t}:{obj}" if t else str(obj)         # typed resource URN
            quads.append(Quad(sid, pred, o, resolved, conf, relpath, None,
                              language="yaml-workflow"))

        emitted_feeds = set()                           # per-step: one FEEDS per source

        def feeds(producer_or_name, resolved=True, conf=1.0):
            p = str(producer_or_name)
            if ":" not in p:                            # a bare dataframe name (cross-file)
                p = f"Dataframe:{p}"
            if p in emitted_feeds:                      # srcDataframe + sql naming the same
                return                                  # source must not double the edge
            emitted_feeds.add(p)
            quads.append(Quad(p, "FEEDS", sid, resolved, conf, relpath, None,
                              language="yaml-workflow"))

        bb = _backbone(s.get("dataBackbone"))

        # --- READS (before we register this step as a producer) ---------------
        if action in ("EXTRACT", "MERGE") and bb:
            add("QUERIES_DATABASE", bb, not _symbolic(bb))
        sql = s.get("sql")
        if isinstance(sql, str):
            for ref in set(_sql_refs(sql)):                      # sqlglot AST (dataframe lineage)
                if ref in current and current[ref] != sid:       # known dataframe → real lineage
                    feeds(current[ref])
                else:                                            # upstream df (other step/file)
                    feeds(ref, resolved=False, conf=0.5)
        if action == "TRANSFORM":
            src = s.get("srcDataframe")
            if isinstance(src, str):
                feeds(current[src]) if (src in current and current[src] != sid) else feeds(src, False, 0.5)
        # Non-producing consumers (LOAD / PURGE / EXECUTE) that name the dataframe
        # they consume get their lineage link too — previously lineage stopped one
        # step short of the write, so no chain ever reached the loaded table.
        if action not in PRODUCERS:
            src = s.get("srcDataframe") or s.get("dataframe")
            if isinstance(src, str):
                feeds(current[src]) if (src in current and current[src] != sid) else feeds(src, False, 0.5)

        # --- WRITES -----------------------------------------------------------
        if action == "LOAD":
            if bb:
                add("WRITES_DATABASE", bb, not _symbolic(bb))
            elif s.get("table"):
                add("WRITES_DATABASE", s["table"], not _symbolic(s["table"]), 0.9)
            s3 = s.get("dataFileLocation")
            if not s3 and s.get("dataS3Bucket"):
                s3 = f"s3://{s['dataS3Bucket']}/{s.get('dataS3Prefix', '')}"
            if s3:
                add("WRITES_TO_S3", s3, not _symbolic(s3), 1.0 if not _symbolic(s3) else 0.5)
        if action == "EXECUTE" and s.get("customFunction"):
            add("CALLS", s["customFunction"])

        # --- drift safety net: unknown action → resources via the convention ---
        if action not in KNOWN_ACTIONS:
            seen = set()
            for text in _strings(s):
                for r in _RES.findall(text):
                    if r in seen:
                        continue
                    seen.add(r)
                    add("WRITES_TO_S3" if r.startswith("s3://") else "QUERIES_DATABASE", r, False, 0.4)

        # --- register this step as the producer of its output dataframe -------
        if action in PRODUCERS:
            df = s.get("dataframe") or s.get("trgDataframe")
            if isinstance(df, str):
                current[df] = sid

    return entities, quads, unknown
