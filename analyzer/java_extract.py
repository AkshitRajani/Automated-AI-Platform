"""
Java extraction bridge — runs the JavaParser helper (java_helper/) as a
subprocess and converts its JSON into the analyzer's Entity/Quad model.

Division of labor (the guardrails from 06_java_cucumber_karate_extension.md):
  - The JAVA side reads structure: entities, DEFINES/CALLS edges (symbol-solver
    resolved), endpoint annotations (import-resolved FQNs), env vars, raw AWS
    call sites, raw SQL strings at type-anchored JDBC sites.
  - THIS side reuses the exact same authorities the Python path uses:
      * sqlglot (`extract._sql_facts`) turns raw SQL into table facts;
      * botocore's own service model classifies AWS operations read-vs-write
        and validates builder literals against the operation's real input
        shape — never a hardcoded operation or member list.

The bridge is honest about absence: if Java files exist but the helper (or a
JRE) is missing, it raises with build instructions — a whole language is never
silently dropped.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

from .models import Entity, Note, Quad, Source
from .wiring import arn_name

_HELPER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "java_helper")
_TIMEOUT_S = 600


# --- botocore-backed classification (same authority as the Python path) ------
def _service_model(service: str) -> Optional[dict]:
    """Load the botocore model for a Java-SDK service package name. Tries the
    name directly, then falls back to matching AWS's own ``serviceId`` metadata
    (the v2 SDK derives its package names from it, e.g. package ``sfn`` ↔
    serviceId ``SFN`` ↔ botocore file ``stepfunctions``) — an AWS-published
    field, not a hand-maintained alias table."""
    try:
        from botocore.session import Session
        loader = Session().get_component("data_loader")
    except Exception:
        return None
    try:
        return loader.load_service_model(service, "service-2")
    except Exception:
        pass
    want = service.replace("-", "").replace("_", "").lower()
    try:
        for name in loader.list_available_services("service-2"):
            model = loader.load_service_model(name, "service-2")
            sid = (model.get("metadata") or {}).get("serviceId", "")
            if sid.replace(" ", "").replace("-", "").lower() == want:
                return model
    except Exception:
        pass
    return None


def _op_entry(model: dict, java_op: str) -> Optional[Tuple[str, dict]]:
    """Match a Java SDK method name (putObject) to the operation in botocore's
    model (PutObject), case-insensitively — the v2 SDK derives its method names
    from these same operation names."""
    ops = model.get("operations", {})
    lower = java_op.replace("_", "").lower()
    for name, spec in ops.items():
        if name.lower() == lower:
            return name, spec
    return None


def _shape_members(model: dict, op_spec: dict) -> Dict[str, str]:
    """lowercase member name -> canonical member name, from the operation's real
    input shape. Builder methods (.bucket(...)) are these members in lowerCamel."""
    shape_name = (op_spec.get("input") or {}).get("shape")
    if not shape_name:
        return {}
    shape = (model.get("shapes") or {}).get(shape_name) or {}
    return {m.lower(): m for m in (shape.get("members") or {})}


def _member_literals(model: dict, op_spec: dict, literals: Dict[str, str]) -> Dict[str, str]:
    """Builder literals validated against the input shape: only keys that are real
    members of the operation survive, keyed by their canonical member name."""
    members = _shape_members(model, op_spec)
    out = {}
    for key, value in (literals or {}).items():
        canonical = members.get(key.lower())
        if canonical:
            out[canonical] = value
    return out


def _aws_quads(calls: List[dict]) -> Tuple[List[Quad], List[Note]]:
    """Map raw {service, operation, literals} records to the analyzer's predicate
    vocabulary — the same three families the Python path covers (S3 read/write,
    Lambda invoke, Step Function start). Anything else becomes an honest Note."""
    quads: List[Quad] = []
    notes: List[Note] = []
    models: Dict[str, Optional[dict]] = {}

    for call in calls:
        service, op = call["service"], call["operation"]
        subject, rel, line = call["subject"], call["file"], call.get("line")
        if service not in models:
            models[service] = _service_model(service)
        model = models[service]
        entry = _op_entry(model, op) if model else None

        if model and entry and service == "s3":
            op_name, spec = entry
            verb = ((spec.get("http") or {}).get("method") or "GET").upper()
            lits = _member_literals(model, spec, call.get("literals") or {})
            bucket, key = lits.get("Bucket"), lits.get("Key")
            resolved = bucket is not None
            obj = f"{bucket}/{key}" if (bucket and key) else (bucket or "<bucket>")
            pred = "READS_FROM_S3" if verb in ("GET", "HEAD") else "WRITES_TO_S3"
            quads.append(Quad(subject, pred, f"S3Object:{obj}", resolved,
                              1.0 if resolved else 0.5, rel, line, language="java"))
        elif model and entry and service == "lambda" and entry[0].lower() == "invoke":
            lits = _member_literals(model, entry[1], call.get("literals") or {})
            fn = lits.get("FunctionName")
            fn = arn_name(fn) if fn else fn      # ARN -> name: one node per resource
            quads.append(Quad(subject, "INVOKES_LAMBDA",
                              f"LambdaFunction:{fn or '<function>'}", fn is not None,
                              1.0 if fn else 0.5, rel, line, language="java"))
        elif model and entry and service in ("sfn", "stepfunctions") \
                and entry[0].lower() == "startexecution":
            lits = _member_literals(model, entry[1], call.get("literals") or {})
            arn = lits.get("stateMachineArn") or lits.get("StateMachineArn")
            arn = arn_name(arn) if arn else arn
            quads.append(Quad(subject, "INVOKES_STEP_FUNCTION",
                              f"StateMachine:{arn or '<state-machine>'}", arn is not None,
                              1.0 if arn else 0.5, rel, line, language="java"))
        else:
            notes.append(Note(
                text=f"AWS call {service}.{op} at {rel}:{line} — recorded but not "
                     f"mapped to a predicate (outside the S3/Lambda/StepFunction "
                     f"families the parser covers)",
                subject=subject, file_path=rel, line=line, provenance="parser"))
    return quads, notes


def _sql_quads(records: List[dict]) -> List[Quad]:
    from .extract import _sql_facts          # sqlglot — the same semantic filter
    quads: List[Quad] = []
    for record in records:
        for table, write in _sql_facts(record["sql"]):
            pred = "WRITES_DATABASE" if write else "QUERIES_DATABASE"
            resolved = bool(record.get("resolved", True))
            quads.append(Quad(record["subject"], pred, f"Table:{table.strip(chr(34))}",
                              resolved, 0.9 if resolved else 0.5,
                              record["file"], record.get("line"), language="java"))
    return quads


# --- the subprocess bridge ----------------------------------------------------
def helper_classpath(helper_dir: Optional[str] = None) -> Optional[str]:
    base = helper_dir or os.environ.get("ANALYZER_JAVA_HELPER") or _HELPER_DIR
    classes = os.path.join(base, "build", "classes")
    jars = os.path.join(base, "jars")
    if not (os.path.isdir(classes) and os.path.isdir(jars)):
        return None
    return f"{classes}:{os.path.join(jars, '*')}"


def extract_java(app_dir: str, helper_dir: Optional[str] = None,
                 ) -> Tuple[List[Entity], List[Quad], List[Note]]:
    """Run the helper over ``app_dir``; return (entities, quads, notes)."""
    java = shutil.which("java")
    classpath = helper_classpath(helper_dir)
    if java is None or classpath is None:
        raise RuntimeError(
            "Java sources found but the Java helper is unavailable. "
            "Install a JDK (11+) and build the helper once:\n"
            f"    {os.path.join(_HELPER_DIR, 'build.sh')}\n"
            "or point ANALYZER_JAVA_HELPER at a built helper directory. "
            "Java files are never silently skipped."
        )
    proc = subprocess.run(
        [java, "-cp", classpath, "JavaFactExtractor", app_dir],
        capture_output=True, text=True, timeout=_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Java helper failed: {proc.stderr[-500:]}")
    data = json.loads(proc.stdout)

    entities = [
        Entity(id=e["id"], type=e["type"], name=e["name"], language="java",
               source=Source(e["file"], e.get("line_start"), e.get("line_end")))
        for e in data.get("entities", [])
    ]
    quads = [
        Quad(q["subject"], q["predicate"], q["object"], bool(q["resolved"]),
             float(q["confidence"]), q["file"], q.get("line"), language="java")
        for q in data.get("quads", [])
    ]
    aws_quads, notes = _aws_quads(data.get("aws_calls", []))
    quads.extend(aws_quads)
    quads.extend(_sql_quads(data.get("sql_strings", [])))
    quads.extend(_implementation_edges(quads))
    return entities, quads, notes


def _implementation_edges(quads: List[Quad]) -> List[Quad]:
    """Interface-method -> implementing-method edges, derived by joining the
    class-level IMPLEMENTS facts (symbol-resolved from the `implements` clause)
    with the DEFINES structure. Java itself requires the implementing class to
    define the interface's methods, so a method-name match inside a verified
    implements pair is the language's guarantee — not a naming convention.
    Without this edge every journey breaks at the service boundary: the caller
    CALLS the interface method while the behavior hangs off the implementation."""
    defines: Dict[str, set] = {}
    for q in quads:
        if q.predicate == "DEFINES" and q.subject.startswith("Class:") \
                and q.object.startswith("Method:"):
            defines.setdefault(q.subject, set()).add(q.object)

    out: List[Quad] = []
    for q in quads:
        if q.predicate != "IMPLEMENTS" or not q.resolved:
            continue
        impl_prefix = "Method:" + q.subject[len("Class:"):] + "."
        iface_prefix = "Method:" + q.object[len("Class:"):] + "."
        impl_methods = {m[len(impl_prefix):] for m in defines.get(q.subject, ())
                        if m.startswith(impl_prefix)}
        iface_methods = {m[len(iface_prefix):] for m in defines.get(q.object, ())
                         if m.startswith(iface_prefix)}
        for name in sorted(iface_methods & impl_methods):
            out.append(Quad(iface_prefix + name, "IMPLEMENTED_BY", impl_prefix + name,
                            True, 1.0, q.file_path, q.line, language="java"))
    return out
