"""
The grounding gate — verify each agent-emitted fact against the real source at its
claimed file:line. This is what makes the analyzer agent safe: no fact enters the
graph unless it is re-checked here. Pure, deterministic, no LLM.

A fact is a dict: {subject, predicate, object, file, line}. verify_fact returns
(ok, reason): ok=True kept, ok=False rejected (hallucinated / wrong location),
ok=None not checkable (no file).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

_TYPES = {"Function", "Method", "Class", "Module", "Symbol", "Table", "S3Object",
          "Parameter", "APIEndpoint", "LambdaFunction", "StateMachine", "Step",
          "Dataframe", "WorkflowFile"}


def _window(root: str, file: str, line: Optional[int], before: int = 3, after: int = 3) -> Optional[str]:
    path = os.path.join(root, file)
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return None
    lo = max(0, (line or 1) - 1 - before)
    hi = min(len(lines), (line or 1) + after)
    return "\n".join(lines[lo:hi])


def verify_fact(root: str, q: dict) -> Tuple[Optional[bool], str]:
    pred = q.get("predicate")
    obj = str(q.get("object", ""))
    file = q.get("file") or (q.get("context", {}) or {}).get("file_path")
    line = q.get("line") or (q.get("context", {}) or {}).get("line_start")
    if not file:
        return None, "no file:line on fact"
    win = _window(root, file, line)
    if win is None:
        return False, f"file not found: {file}"
    obj = obj.split(" (")[0].strip()        # drop explanatory prose: "table (ORM note)" → "table"
    # strip the canonical type prefix (Function:/Table:/Symbol:/Parameter:/…) → the value
    if ":" in obj and obj.split(":", 1)[0] in _TYPES:
        obj = obj.split(":", 1)[1]

    if pred == "EXPOSES_ENDPOINT":
        path = obj.split(" ", 1)[-1]
        if path in win:
            return True, "endpoint path present"
        # Flask blueprint: full path = url_prefix + route, not literal at the line —
        # credit if the route suffix is present alongside a route decorator.
        segs = [s for s in path.split("/") if len(s) > 2 and "<" not in s and "{" not in s]
        last = segs[-1] if segs else path
        return (last in win and ("route" in win.lower() or "@" in win)), "endpoint (blueprint suffix)"
    if pred == "CALLS":
        callee = obj.split("::")[-1].split(".")[-1]
        return (callee in win), "callee name present"
    if pred in ("QUERIES_DATABASE", "WRITES_DATABASE"):
        tok = obj.split(".")[-1].strip("${}")
        orm = (any(s in win for s in ("session", ".query(", ".add(", ".filter", "execute", "__tablename__"))
               or any(k in win.upper() for k in ("INSERT", "SELECT", "UPDATE", "DELETE FROM")))
        return (tok in win or orm), "table/sql/ORM present"
    if pred in ("READS_FROM_S3", "WRITES_TO_S3"):
        return any(s in win for s in ("get_object", "put_object", "upload", "download", "s3", "S3", "boto3")), "s3 op present"
    if pred == "READS_ENV_VAR":
        return (obj in win and ("environ" in win or "getenv" in win)), "env read present"
    if pred == "INVOKES_LAMBDA":
        return ("invoke" in win or obj.split(".")[-1] in win), "lambda invoke present"
    if pred == "FEEDS":
        s = str(q.get("subject", "")).split("::")[-1]
        o = obj.split("::")[-1]
        return (s in win or o in win), "lineage endpoint present"
    if pred == "DEFINES":
        o = obj.split("::")[-1].split(".")[-1]
        return (o in win), "definition present"
    # unknown predicate → require the object token to appear (no free passes)
    tok = obj.split("::")[-1].split(".")[-1].split(" ")[-1].strip("${}/")
    return ((tok in win) if tok else None), "generic token present"


def grade(root: str, quads: list) -> dict:
    kept = rejected = uncheckable = 0
    bad = []
    for q in quads:
        ok, why = verify_fact(root, q)
        if ok is None:
            uncheckable += 1
        elif ok:
            kept += 1
        else:
            rejected += 1
            if len(bad) < 10:
                bad.append({"predicate": q.get("predicate"), "object": q.get("object"),
                            "file": q.get("file"), "reason": why})
    checked = kept + rejected
    precision = round(100 * kept / checked, 1) if checked else 0.0
    return {"total": len(quads), "checked": checked, "kept": kept, "rejected": rejected,
            "uncheckable": uncheckable, "precision": precision, "rejected_samples": bad}
