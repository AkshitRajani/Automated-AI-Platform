"""
The Python parser (Step 1 of the analyzer) — pure stdlib `ast`, no LLM.

Deterministic: same code in → identical entities + quads out. Comprehensive by
design (every file, every def/class, all node types) — the 491→580 lesson from
the analyzer A/B is baked in: we count every function-like unit, not a naive
subset.

What it extracts:
  entities — Module / Class / Function / Method, each with file:line.
  quads    — the typed relationships, keyed by the predicate ingestion
             routes on:
               EXPOSES_ENDPOINT     FastAPI/Flask route decorators
               READS_FROM_S3 / WRITES_TO_S3        boto3 S3 ops
               INVOKES_LAMBDA / INVOKES_STEP_FUNCTION
               READS_ENV_VAR        os.environ / os.getenv
               QUERIES_DATABASE / WRITES_DATABASE  SQL in .execute(...)
               CALLS                app-internal function calls (graph edge)
               DEFINES              module/class → its members (graph edge)

Literals become resolved facts; variables become symbolic objects with
resolved=False (the ingestion bindings resolver, §5.3, fills those in later).
"""
from __future__ import annotations

import ast
import os
import re
from typing import Dict, Iterator, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp

from .models import Entity, Quad, QuadFile, Source

HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}   # closed HTTP standard


def _load_s3_ops() -> Dict[str, str]:
    """Every S3 operation → its HTTP verb, from botocore's own data model (no
    hardcoded method-name lists; read-vs-write derived from the verb)."""
    try:
        from botocore.session import Session
        from botocore import xform_name
        model = Session().get_component("data_loader").load_service_model("s3", "service-2")
        return {xform_name(op): (spec.get("http", {}) or {}).get("method", "GET")
                for op, spec in model.get("operations", {}).items()}
    except Exception:
        return {}


_S3_OPS = _load_s3_ops()


def _load_aws_ops(service: str) -> Dict[str, set]:
    """operation snake-name → the operation's own input-member names, straight
    from botocore's published service model (same source as `_load_s3_ops`).
    Detection is by SHAPE: a call matches only when it uses the operation's name
    AND one of that operation's documented parameters — so a generic method name
    on some unrelated object (`queue.publish(...)`) never matches."""
    try:
        from botocore.session import Session
        from botocore import xform_name
        model = Session().get_component("data_loader").load_service_model(service, "service-2")
        shapes = model.get("shapes", {})
        out: Dict[str, set] = {}
        for op, spec in model.get("operations", {}).items():
            shape = (spec.get("input") or {}).get("shape")
            members = (shapes.get(shape, {}) or {}).get("members", {}) or {}
            out[xform_name(op)] = set(members)
        return out
    except Exception:
        return {}


# The AWS interactions the map records beyond S3/invoke — each entry is
# (service, operation, parameter-that-names-the-resource, predicate, urn kind).
# The operation names and parameters are AWS's OWN published API, validated
# against the botocore model at load time; nothing app-specific appears here.
_AWS_RESOURCE_OPS = [
    ("secretsmanager", "get_secret_value", "SecretId", "READS_SECRET", "Secret"),
    ("ssm", "get_parameter", "Name", "READS_SSM_PARAMETER", "Parameter"),
    ("ssm", "get_parameters", "Names", "READS_SSM_PARAMETER", "Parameter"),
    ("ssm", "get_parameters_by_path", "Path", "READS_SSM_PARAMETER", "Parameter"),
    ("sns", "publish", "TopicArn", "PUBLISHES_TO_SNS", "Topic"),
]


def _aws_ops_index() -> Dict[str, list]:
    """snake-op-name → [(param, predicate, kind, all-model-members)], only for
    operations the live botocore model actually documents."""
    models: Dict[str, Dict[str, set]] = {}
    out: Dict[str, list] = {}
    for service, op, param, predicate, kind in _AWS_RESOURCE_OPS:
        if service not in models:
            models[service] = _load_aws_ops(service)
        members = models[service].get(op)
        if members and param in members:
            out.setdefault(op, []).append((param, predicate, kind, members))
    return out


_AWS_OPS = _aws_ops_index()


def _sql_facts(sql: str) -> List[Tuple[str, bool]]:
    """(table, is_write) for each table in a SQL string — via sqlglot's AST, not
    regex. Handles JOINs/CTEs/subqueries; unparseable SQL yields nothing."""
    try:
        tree = sqlglot.parse_one(sql, error_level="ignore")
    except Exception:
        return []
    if tree is None:
        return []
    write = isinstance(tree, (exp.Insert, exp.Update, exp.Delete, exp.Merge))
    out, seen = [], set()
    for t in tree.find_all(exp.Table):
        name = t.name
        if name and name not in seen:
            seen.add(name)
            out.append((name, write))
    return out


def _strict_sql_facts(text: str) -> List[Tuple[str, bool]]:
    """Like `_sql_facts`, but for text NOT known to be SQL (config values): the
    parse itself is the test. Counts only when the parser produces a real
    STATEMENT (select/insert/update/delete/merge — the closed DML set) that
    touches at least one table; prose, paths, and identifiers parse to
    expressions or table-less trees and are rejected. No pattern matching —
    sqlglot's grammar decides."""
    if not isinstance(text, str):
        return []
    try:
        tree = sqlglot.parse_one(text, error_level="ignore")
    except Exception:
        return []
    if not isinstance(tree, (exp.Select, exp.Union, exp.Insert, exp.Update,
                             exp.Delete, exp.Merge)):
        return []
    return _sql_facts(text)


# --- file discovery ---------------------------------------------------------
def discover(root: str, exts=(".py",)) -> List[str]:
    if os.path.isfile(root):
        return [root] if root.endswith(exts) else []
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {"__pycache__", ".venv", "venv", "node_modules", ".git"}
                       and not d.startswith(".")]
        for name in filenames:
            if name.endswith(exts):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


# --- literal vs symbolic ----------------------------------------------------
def _const(node) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _value(node) -> Tuple[str, bool]:
    """(text, resolved): a string literal is resolved; anything else is symbolic."""
    v = _const(node)
    if isinstance(v, str):
        return v, True
    try:
        return ast.unparse(node), False
    except Exception:
        return "<expr>", False


def _callable_name(func) -> Optional[str]:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _kwargs(call) -> Dict[str, ast.AST]:
    return {k.arg: k.value for k in call.keywords if k.arg}


# --- canonical identity (the SCIP principle: id = Type:qualified-name) -------
# Identity is derived from program STRUCTURE (module + class/func ancestry), not
# from a file path. A call site resolves to the SAME id as the definition, so
# edge endpoints equal node ids and the graph connects. Move-stable: no line
# numbers, no path-as-identity.
def _module(relpath: str) -> str:
    p = relpath[:-3] if relpath.endswith(".py") else relpath
    p = p.replace(os.sep, ".").replace("/", ".")
    return p[:-len(".__init__")] if p.endswith(".__init__") else p


def canon(kind: str, qualname: str) -> str:
    """The canonical id: e.g. Function:web.app.main.health, Method:mod.Cls.do."""
    return f"{kind}:{qualname}"


# Typed resource URNs — a resource's canonical id is its real address.
def res(kind: str, value: str) -> str:
    return f"{kind}:{value}"


# --- def/class collection (qualified-name scope tracking) -------------------
def _collect_defs(tree, module: str) -> List[Tuple[str, str, str, ast.AST, str]]:
    """Every Class/Function/Method as (canonical_id, kind, qualname, node, container_id)."""
    found: List[Tuple[str, str, str, ast.AST, str]] = []
    module_id = canon("Module", module)

    def rec(node, prefix: str, container_id: str, in_class: bool):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qual = f"{module}.{prefix}.{child.name}" if prefix else f"{module}.{child.name}"
                cid = canon("Class", qual)
                found.append((cid, "Class", qual, child, container_id))
                rec(child, f"{prefix}.{child.name}" if prefix else child.name, cid, in_class=True)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{module}.{prefix}.{child.name}" if prefix else f"{module}.{child.name}"
                kind = "Method" if in_class else "Function"
                cid = canon(kind, qual)
                found.append((cid, kind, qual, child, container_id))
                rec(child, f"{prefix}.{child.name}" if prefix else child.name, cid, in_class=False)
            else:
                rec(child, prefix, container_id, in_class)

    rec(tree, "", module_id, in_class=False)
    return found


def _body_nodes(func_node) -> Iterator[ast.AST]:
    """Descendants of a function, NOT entering nested def/class bodies (those are
    their own entities, so their calls belong to them)."""
    for child in ast.iter_child_nodes(func_node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield child
        yield from _body_nodes(child)


# --- per-function detectors -------------------------------------------------
def _endpoints(func_node) -> Iterator[Tuple[str, str, bool]]:
    """(verb, path, resolved) from FastAPI `@app.get(...)` / Flask `@app.route(...)`."""
    for dec in getattr(func_node, "decorator_list", []):
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args):
            continue
        attr = dec.func.attr
        if attr in HTTP_VERBS:
            path, resolved = _value(dec.args[0])
            yield attr.upper(), path, resolved
        elif attr == "route":
            path, resolved = _value(dec.args[0])
            methods = ["GET"]
            kw = _kwargs(dec)
            if "methods" in kw and isinstance(kw["methods"], (ast.List, ast.Tuple)):
                lits = [_const(e) for e in kw["methods"].elts]
                methods = [m for m in lits if isinstance(m, str)] or ["GET"]
            for m in methods:
                yield m.upper(), path, resolved


def _env_assignments(func_node) -> Dict[str, str]:
    """variable -> env KEY, for direct same-function indirection
    (``v = os.environ["K"]`` / ``v = os.getenv("K")``). Lets the blank be emitted
    as ``${K}`` — the same token the manifest's environment block declares — so a
    code blank and its repo-stated answer meet on one string (doc 10)."""
    out: Dict[str, str] = {}
    for node in _body_nodes(func_node):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        v = node.value
        key = None
        if (isinstance(v, ast.Subscript) and isinstance(v.value, ast.Attribute)
                and v.value.attr == "environ"):
            key = _const(v.slice)
        elif (isinstance(v, ast.Call) and _callable_name(v.func) == "getenv" and v.args):
            key = _const(v.args[0])
        if isinstance(key, str):
            out[node.targets[0].id] = key
    return out


def _env_key_of(node) -> Optional[str]:
    """The env KEY a node reads INLINE — the three stdlib forms, by AST shape:
    ``os.environ["K"]`` / ``os.getenv("K"[, d])`` / ``os.environ.get("K"[, d])``.
    None for anything else. (A10: the inline form previously fell through as raw
    source text and the harvested binding could never meet it.)"""
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and node.value.attr == "environ"):
        key = _const(node.slice)
        return key if isinstance(key, str) else None
    if isinstance(node, ast.Call):
        name = _callable_name(node.func)
        if name == "getenv" and node.args:
            key = _const(node.args[0])
            return key if isinstance(key, str) else None
        if (name == "get" and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ" and node.args):
            key = _const(node.args[0])
            return key if isinstance(key, str) else None
    return None


def _resource_quads(subject: str, relpath: str, func_node,
                    symbols: Dict[str, Set[str]]) -> Iterator[Quad]:
    env_of = _env_assignments(func_node)

    def tokenized(text: str, resolved: bool):
        """An unresolved bare variable that came straight from an env var becomes
        its ${KEY} token; anything else passes through untouched."""
        if not resolved and text in env_of:
            return "${" + env_of[text] + "}", False
        return text, resolved

    def toknode(node) -> Tuple[str, bool]:
        """A value node → (text, resolved), recognising every setting-read style:
        a literal stays itself; an inline env read (any of the three stdlib
        shapes) becomes its ``${KEY}`` token; a bare variable assigned from an
        env read earlier in the function becomes the same token; an f-string
        whose every piece is one of those becomes one tokenized string. All
        four spellings of the same fact land on the SAME ``${KEY}`` string the
        terraform/manifest harvest declares — so the resolver can meet them."""
        key = _env_key_of(node)
        if key is not None:
            return "${" + key + "}", False
        if isinstance(node, ast.JoinedStr):
            parts, ok = [], True
            for piece in node.values:
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    parts.append(piece.value)
                    continue
                if isinstance(piece, ast.FormattedValue):
                    inner_key = _env_key_of(piece.value)
                    if inner_key is None and isinstance(piece.value, ast.Name):
                        inner_key = env_of.get(piece.value.id)
                    if inner_key is not None:
                        parts.append("${" + inner_key + "}")
                        continue
                ok = False
                break
            if ok:
                text = "".join(parts)
                return text, "${" not in text
        return tokenized(*_value(node))

    def raw(*parts):
        """True when any part is RAW unresolved text (no ${token} to answer) —
        such a fact can never be upgraded to resolved by the name resolver."""
        return any((not r) and "${" not in t for t, r in parts)

    for node in _body_nodes(func_node):
        # os.environ["X"]
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"):
            key = _const(node.slice)
            if isinstance(key, str):
                yield Quad(subject, "READS_ENV_VAR", key, True, 1.0, relpath, node.lineno)
            continue
        if not isinstance(node, ast.Call):
            continue
        name = _callable_name(node.func)
        kw = _kwargs(node)
        line = node.lineno

        # Outbound web call (A8) — detected by the URL ITSELF, not by any library
        # name: `http://`/`https://` is the web's own closed scheme grammar, so a
        # call whose url= kwarg or first argument starts with it IS a web call,
        # whatever client made it. AWS-SDK-shaped calls are excluded — those are
        # modeled by their own branches below, and their URL-valued parameters
        # (queue URLs, presigned posts) are addresses of AWS resources, not
        # outbound API calls.
        if name not in _S3_OPS and name not in _AWS_OPS:
            url_node = kw.get("url") or (node.args[0] if node.args else None)
            if url_node is not None:
                url, u_res = toknode(url_node)
                if url.lower().startswith(("http://", "https://")):
                    verb = name.upper() if name in HTTP_VERBS else None
                    target = f"{verb} {url}" if verb else url
                    yield Quad(subject, "CALLS_HTTP_API", res("APIEndpoint", target),
                               u_res, 1.0 if u_res else 0.5, relpath, line,
                               symbolic=raw((url, u_res)))

        if name in _S3_OPS:                                  # any real S3 op (botocore model)
            bucket, br = toknode(kw["Bucket"]) if "Bucket" in kw else ("<bucket>", False)
            key, kr = toknode(kw["Key"]) if "Key" in kw else ("", True)
            obj = f"{bucket}/{key}" if key else bucket
            pred = "READS_FROM_S3" if _S3_OPS[name] in ("GET", "HEAD") else "WRITES_TO_S3"
            yield Quad(subject, pred, res("S3Object", obj), br and kr,
                       1.0 if (br and kr) else 0.5, relpath, line,
                       symbolic=raw((bucket, br), (key, kr)))
        elif name in _AWS_OPS:                               # secrets/params/SNS (botocore model, A9)
            for param, pred, kind, members in _AWS_OPS[name]:
                if param not in kw or not (set(kw) & members):
                    continue
                value_node = kw[param]
                # names ONLY, never values: the fact records WHICH secret/
                # parameter/topic is touched — its contents are never read.
                nodes = (value_node.elts if isinstance(value_node, (ast.List, ast.Tuple))
                         else [value_node])
                for vn in nodes:
                    obj, r = toknode(vn)
                    if r:
                        from .wiring import arn_name
                        obj = arn_name(obj)
                    yield Quad(subject, pred, res(kind, obj), r,
                               1.0 if r else 0.5, relpath, line,
                               symbolic=raw((obj, r)))
                break
        elif name == "invoke" and "FunctionName" in kw:
            obj, r = toknode(kw["FunctionName"])
            if r:
                from .wiring import arn_name
                obj = arn_name(obj)      # ARN -> resource name (AWS's published grammar)
            yield Quad(subject, "INVOKES_LAMBDA", res("LambdaFunction", obj), r,
                       1.0 if r else 0.5, relpath, line, symbolic=raw((obj, r)))
        elif name == "start_execution" and "stateMachineArn" in kw:
            obj, r = toknode(kw["stateMachineArn"])
            if r:
                from .wiring import arn_name
                obj = arn_name(obj)      # so the call site and the definition share one node
            yield Quad(subject, "INVOKES_STEP_FUNCTION", res("StateMachine", obj), r,
                       1.0 if r else 0.5, relpath, line, symbolic=raw((obj, r)))
        elif name == "getenv" and node.args:
            key, r = _value(node.args[0])
            if r:
                yield Quad(subject, "READS_ENV_VAR", res("Parameter", key), True, 1.0, relpath, line)
        elif (name == "get" and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Attribute)
              and node.func.value.attr == "environ" and node.args):
            key, r = _value(node.args[0])
            if r:
                yield Quad(subject, "READS_ENV_VAR", res("Parameter", key), True, 1.0, relpath, line)
        elif name == "execute" and node.args:
            sql = _const(node.args[0])
            if isinstance(sql, str):
                for table, write in _sql_facts(sql):         # sqlglot AST, not regex
                    pred = "WRITES_DATABASE" if write else "QUERIES_DATABASE"
                    yield Quad(subject, pred, res("Table", table.strip('"')), True, 0.9, relpath, line)
        elif name and name in symbols:
            targets = symbols[name]
            if len(targets) == 1:                          # resolved → the callee's canonical id
                yield Quad(subject, "CALLS", next(iter(targets)), True, 1.0, relpath, line)
            else:                                           # ambiguous → unresolved Symbol urn
                yield Quad(subject, "CALLS", res("Symbol", name), False, 0.5, relpath, line)


# --- top-level analyze ------------------------------------------------------
RESERVED_SHEET_KEYS = {"environment_file", "confirm_lambda_names"}
RESERVED_SHEET_PREFIXES = ("lambda_name.",)


def _reserved(key: str) -> bool:
    return key in RESERVED_SHEET_KEYS or key.startswith(RESERVED_SHEET_PREFIXES)


def analyze(app_dir: str, app_id: str, only=None, names_dir=None,
            env_file=None) -> QuadFile:
    """Parse a codebase into entities + quads.

    ``only`` (optional): restrict to these file(s) — abs or repo-relative paths —
    while still computing every qualified name relative to ``app_dir``, so a
    single-file re-parse yields the *same* canonical ids as the full draft. Used by
    the analyzer agent's ``parse`` tool for cheap on-demand re-parsing. Default
    (None) parses the whole tree, unchanged.

    ``names_dir`` (optional): the worksheet directory. Human answers in
    ``<app_id>_worksheet.yaml`` are applied AFTER the repo's own bindings (a human
    beats a repo file — doc 10); tokens in ``<app_id>_decisions.yaml`` count as
    decided. The journey pass runs ONLY when every ``${token}`` in the graph is
    answered or decided — an unresolved graph gets NO journeys, ever (they would
    be fragments of our blindness, not routes of the app). Pending tokens are
    reported in ``qf.pending_names``."""
    sheet_answers: Dict[str, str] = {}
    sheet_decisions: Dict[str, dict] = {}
    if names_dir:
        import yaml as _yaml

        def _sheet(name):
            p = os.path.join(names_dir, f"{app_id.lower()}_{name}.yaml")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    try:
                        data = _yaml.safe_load(fh)
                    except _yaml.YAMLError as exc:      # operator error, not a crash
                        raise ValueError(
                            f"{p} is not valid YAML — fix the file and re-run "
                            f"({exc})") from exc
                    return data if isinstance(data, dict) else {}
            return {}
        sheet_answers = {str(k): str(v).strip() for k, v in _sheet("worksheet").items()
                         if v is not None and str(v).strip()}
        sheet_decisions = {str(k): (v if isinstance(v, dict) else {"decision": str(v)})
                           for k, v in _sheet("decisions").items()}
    # an explicit parameter (CLI flag / API field) beats the worksheet entry
    env_file = env_file or sheet_answers.get("environment_file")

    # Single-file app_dir: os.path.relpath(file, file) degenerates to "." (extract.py
    # bug found analyzing eval/examples/discount/sut.py directly — every entity's
    # qualified name collapsed to "..funcname"). Use the parent directory as the
    # relpath base so a single file yields its own basename instead.
    rel_base = os.path.dirname(app_dir) if os.path.isfile(app_dir) else app_dir

    keep = None
    files = discover(app_dir)
    if only:
        keep = {os.path.realpath(p if os.path.isabs(p) else os.path.join(app_dir, p))
                for p in only}
        files = [f for f in files if os.path.realpath(f) in keep]
    parsed: List[Tuple[str, ast.AST]] = []
    qf = QuadFile(app_id=app_id)
    # WHAT THIS RUN READ — counted while reading, stamped into the quad's
    # metadata, and shown by the verification report. After the week a missing
    # terraform layer hid behind ordinary-looking output: absence is now
    # STATED, never implied.
    manifest = {"python_files_found": len(files), "python_files_parsed": 0,
                "python_files_unparseable": 0, "workflow_files_parsed": 0,
                "terraform_files_found": 0, "java_files_found": 0,
                "config_files_with_sql": 0, "zip_files_not_opened": 0}

    # Pass 1 — entities + symbol table (bare name → canonical ids, for call resolution).
    symbols: Dict[str, Set[str]] = {}
    defs_by_file: Dict[str, list] = {}
    for path in files:
        rel = os.path.relpath(path, rel_base)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                tree = ast.parse(fh.read(), filename=path)
        except SyntaxError:
            manifest["python_files_unparseable"] += 1
            continue
        manifest["python_files_parsed"] += 1
        module = _module(rel)
        parsed.append((rel, tree))
        qf.entities.append(Entity(id=canon("Module", module), type="Module", name=module,
                                  source=Source(rel, 1, None)))
        defs = _collect_defs(tree, module)
        defs_by_file[rel] = (tree, defs, module)
        for cid, kind, qual, node, container in defs:
            qf.entities.append(Entity(
                id=cid, type=kind, name=qual,
                source=Source(rel, getattr(node, "lineno", None),
                              getattr(node, "end_lineno", None))))
            if kind in ("Function", "Method"):
                symbols.setdefault(qual.split(".")[-1], set()).add(cid)   # bare name → canonical id

    # Pass 2 — quads (structure + resources + calls).
    for rel, (tree, defs, module) in defs_by_file.items():
        # module-level resource usage (config/env read at import time) → the Module entity
        qf.quads.extend(_resource_quads(canon("Module", module), rel, tree, symbols))
        for cid, kind, qual, node, container in defs:
            # DEFINES edge (module/class → member)
            qf.quads.append(Quad(container, "DEFINES", cid, True, 1.0, rel,
                                 getattr(node, "lineno", None)))
            if kind in ("Function", "Method"):
                for verb, path, resolved in _endpoints(node):
                    qf.quads.append(Quad(cid, "EXPOSES_ENDPOINT", res("APIEndpoint", f"{verb} {path}"),
                                         resolved, 1.0 if resolved else 0.5, rel, node.lineno))
                qf.quads.extend(_resource_quads(cid, rel, node, symbols))

    # --- workflow YAML files (etl_workflow dialect) ------------------------------
    import yaml
    from . import workflow as wfmod
    qf.flagged_unknown_actions = set()
    for path in discover(app_dir, exts=(".yml", ".yaml")):
        if keep is not None and os.path.realpath(path) not in keep:
            continue
        rel = os.path.relpath(path, rel_base)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                doc = yaml.safe_load(fh)
        except Exception:
            continue                       # malformed YAML → skip (don't crash the run)
        if not wfmod.is_workflow(doc):
            continue                       # not a workflow (config / wrapped-code / openapi)
        ents, quads, unknown = wfmod.extract_workflow(doc, rel)
        manifest["workflow_files_parsed"] += 1
        qf.entities.extend(ents)
        qf.quads.extend(quads)
        qf.flagged_unknown_actions |= unknown

    # --- SQL kept in config files (A11) --------------------------------------
    # Some estates store their queries in JSON/YAML config ("run query #7
    # from the notebook") and in .sql files; in-code SQL alone misses them. A
    # config string is SQL only if it PARSES as a real statement touching a
    # table (`_strict_sql_facts` — the grammar is the test). Facts attach to a
    # ConfigFile entity; when a function's code carries the query's own KEY as
    # a literal, the same facts attach to that function too (the join is two
    # word-for-word strings meeting).
    def _config_strings(node, key=None):
        """(last-mapping-key, string) pairs from a parsed JSON/YAML document."""
        if isinstance(node, str):
            yield key, node
        elif isinstance(node, dict):
            for k, v in node.items():
                yield from _config_strings(v, str(k))
        elif isinstance(node, list):
            for v in node:
                yield from _config_strings(v, key)

    literal_index: Dict[str, Set[str]] = {}        # constant string -> function ids
    for rel, (tree, defs, module) in defs_by_file.items():
        for cid, kind, qual, node, container in defs:
            if kind not in ("Function", "Method"):
                continue
            for sub in _body_nodes(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    literal_index.setdefault(sub.value, set()).add(cid)

    for path in discover(app_dir, exts=(".json", ".yml", ".yaml", ".sql")):
        if keep is not None and os.path.realpath(path) not in keep:
            continue
        rel = os.path.relpath(path, rel_base)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except Exception:
            continue
        if path.endswith(".sql"):
            pairs = [(os.path.basename(rel), raw)]
        else:
            import yaml as _yaml_cfg
            try:
                doc = _yaml_cfg.safe_load(raw)
            except Exception:
                continue
            pairs = list(_config_strings(doc))
        cfg_id = None
        emitted: Set[tuple] = set()
        for cfg_key, text in pairs:
            tables = _strict_sql_facts(text)
            if not tables:
                continue
            if cfg_id is None:
                manifest["config_files_with_sql"] += 1
                cfg_id = res("ConfigFile", rel.replace(os.sep, "/"))
                qf.entities.append(Entity(id=cfg_id, type="ConfigFile",
                                          name=rel.replace(os.sep, "/"),
                                          language="config",
                                          source=Source(rel, 1, None)))
            joined_fns = sorted(literal_index.get(cfg_key or "", ()))
            for table, write in tables:
                pred = "WRITES_DATABASE" if write else "QUERIES_DATABASE"
                tbl = res("Table", table.strip('"'))
                if (cfg_id, pred, tbl) not in emitted:
                    emitted.add((cfg_id, pred, tbl))
                    qf.quads.append(Quad(cfg_id, pred, tbl, True, 0.9, rel, None,
                                         language="config"))
                # the key-literal join: code that names this query runs it —
                # ONLY keys whose value actually parsed as SQL take part
                for fn_id in joined_fns:
                    if (fn_id, pred, tbl) not in emitted:
                        emitted.add((fn_id, pred, tbl))
                        qf.quads.append(Quad(fn_id, pred, tbl, True, 0.9, rel,
                                             None, language="config"))
            for fn_id in joined_fns:
                if (fn_id, "READS_FILE", cfg_id) not in emitted:
                    emitted.add((fn_id, "READS_FILE", cfg_id))
                    qf.quads.append(Quad(fn_id, "READS_FILE", cfg_id,
                                         True, 0.9, rel, None, language="config"))

    # --- wiring files: deployment manifests + state machine definitions ------
    from . import wiring as wiring_mod
    w_ents, w_quads, w_bindings, w_notes, w_hints, w_env = \
        wiring_mod.extract_wiring(app_dir, keep, env_file)
    qf.env_candidates = list(w_env.get("candidates") or [])
    qf.environment_file = w_env.get("chosen")
    qf.entities.extend(w_ents)
    qf.quads.extend(w_quads)
    qf.bindings.update(w_bindings)      # repo-declared answers travel with the facts
    qf.analyzer_notes.extend(w_notes)   # what was read/skipped — never silent again

    # --- deployed-name confirmation (A7) -----------------------------------
    # Terraform states lambda names as the DEPLOY REPO spells them — and some
    # estates spell only half the name there (the deploy machinery completes it
    # invisibly). The analyzer cannot know which; a human can, in one look. So:
    # every terraform-declared name is listed for confirmation; corrections come
    # back as ``lambda_name.<declared>: <deployed>`` worksheet entries; nothing
    # flows downstream until ``confirm_lambda_names: yes``. Confirmed answers
    # merge and are never asked again. Manifest-declared names (the serverless
    # framework's own semantics: the entry name IS the deployed name) are not
    # questioned.
    tf_lams = [e for e in qf.entities
               if e.type == "LambdaFunction" and e.source
               and e.source.file_path.endswith((".tf", ".tfvars"))]
    qf.lambda_names_declared = sorted({e.name for e in tf_lams})
    confirm_raw = str(sheet_answers.get("confirm_lambda_names", "")).strip().lower()
    qf.lambda_names_confirmed = confirm_raw in ("yes", "y", "true")
    corrections = {k[len("lambda_name."):]: v
                   for k, v in sheet_answers.items()
                   if k.startswith("lambda_name.") and v}
    declared_names = {e.name for e in tf_lams}
    for stale in sorted(set(corrections) - declared_names):
        qf.sheet_warnings.append(
            f"worksheet corrects lambda_name.{stale} but the terraform declares "
            f"no lambda by that name — stale or misspelled; ignored")
    applied: Dict[str, str] = {}
    if corrections:
        id_map: Dict[str, str] = {}
        for e in tf_lams:
            if e.name in corrections and corrections[e.name] != e.name:
                new_name = corrections[e.name]
                id_map[e.id] = f"LambdaFunction:{new_name}"
                applied[e.name] = new_name
                e.id, e.name = f"LambdaFunction:{new_name}", new_name
        if id_map:
            for q in qf.quads:
                if q.subject in id_map:
                    q.subject = id_map[q.subject]
                if q.object in id_map:
                    q.object = id_map[q.object]
            w_hints = {id_map.get(k, k): v for k, v in w_hints.items()}
    qf.lambda_name_corrections = applied

    # --- Java sources (JavaParser helper — see java_helper/) ----------------
    java_files = discover(app_dir, exts=(".java",))
    if java_files:
        from . import java_extract
        j_ents, j_quads, j_notes = java_extract.extract_java(app_dir)
        if keep is not None:                  # `only` re-parse: same ids, filtered files
            keep_rel = {os.path.relpath(p, app_dir) for p in keep}
            j_ents = [e for e in j_ents if e.source and e.source.file_path in keep_rel]
            j_quads = [q for q in j_quads if q.file_path in keep_rel]
            j_notes = [n for n in j_notes if n.file_path in keep_rel]
        qf.entities.extend(j_ents)
        qf.quads.extend(j_quads)
        qf.notes.extend(j_notes)

    manifest["terraform_files_found"] = len(discover(app_dir, exts=(".tf", ".tfvars")))
    manifest["java_files_found"] = len(java_files)
    zips = discover(app_dir, exts=(".zip",))
    manifest["zip_files_not_opened"] = len(zips)
    if zips:
        names = ", ".join(sorted(os.path.basename(z) for z in zips)[:5])
        qf.analyzer_notes.append(
            f"upload contains {len(zips)} zip file(s) the analyzer does NOT "
            f"open ({names}) — if wiring or code lives inside, extract them "
            f"into the folder and re-run")
    qf.parse_manifest = manifest

    # --- bucket joins: object-level S3 facts meet bucket-level triggers --------
    # Code writes OBJECTS (S3Object:<bucket>/<key>); a trigger registers on the
    # BUCKET (S3Bucket:<bucket>). The join is derivable from our own URN grammar —
    # the bucket is the segment before the first '/' — emitted only for buckets a
    # trigger actually declared, so no noise nodes appear.
    trigger_buckets = {e.id for e in qf.entities if e.id.startswith("S3Bucket:")}
    if trigger_buckets:
        seen_joins = set()
        for q in list(qf.quads):
            obj = q.object
            if not obj.startswith("S3Object:"):
                continue
            bucket = "S3Bucket:" + obj[len("S3Object:"):].split("/", 1)[0]
            if bucket in trigger_buckets and (obj, bucket) not in seen_joins:
                seen_joins.add((obj, bucket))
                qf.quads.append(Quad(obj, "IN_BUCKET", bucket, True, 1.0,
                                     q.file_path, None))

    # --- handler joins: the lambda -> code translation (A13) -------------------
    # Deployment handlers name code relative to the BUNDLE root
    # ('data_pull.handler'), while our code ids are repo-relative
    # ('Function:lambdas.data_pull.handler').
    #   rung 1 — a UNIQUE suffix match is the same word-for-word fact modulo the
    #            unknown zip prefix.
    #   rung 2 — when several folders match (identical per-folder handlers), the
    #            lambda entry's own path-shaped fields (s3_key …) state where its
    #            code lives; a candidate whose DISTINCTIVE path parts appear in a
    #            hint wins — but only when exactly ONE does.
    #   rung 3 — still unknown: the edge is REMOVED and the question is recorded
    #            in `handler_unlinked` (lambda, handler, candidates). An edge to
    #            a node that doesn't exist looks wired and connects nothing — a
    #            visible gap beats an invisible lie.
    fn_ids = [e.id for e in qf.entities if e.id.startswith("Function:")]
    known = set(fn_ids)
    drop: List[Quad] = []
    for q in qf.quads:
        if q.predicate != "HANDLED_BY" or q.object in known \
                or not q.object.startswith("Function:"):
            continue
        qual = q.object[len("Function:"):]
        matches = [f for f in fn_ids if f.endswith("." + qual)]
        if len(matches) == 1:
            q.object = matches[0]
            continue
        if len(matches) > 1:
            shared = set.intersection(*[set(m[len("Function:"):].split("."))
                                        for m in matches])
            hints = w_hints.get(q.subject, [])
            hinted = [m for m in matches
                      if any(part not in shared and any(part in h for h in hints)
                             for part in m[len("Function:"):].split("."))]
            if len(hinted) == 1:
                q.object = hinted[0]
                q.confidence = 0.9         # two of THEIR OWN strings met — the
                continue                   # entry's path + the folder's name
        drop.append(q)
        qf.handler_unlinked.append({
            "lambda": q.subject,
            "handler": qual,
            "candidates": sorted(m for m in matches)})
    if drop:
        dropped = set(id(q) for q in drop)
        qf.quads = [q for q in qf.quads if id(q) not in dropped]
        qf.analyzer_notes.append(
            f"handler: {len(drop)} lambda(s) could not be linked to their code "
            f"(ambiguous or absent handler target) — listed under "
            f"handler_unlinked, NOT linked by guesswork")

    # --- name resolution BEFORE journeys ---------------------------------------
    # Fill every ${token} the repo (bindings) or a human (worksheet) has answered,
    # word-for-word, THEN decide whether the graph is complete enough to walk.
    # PROVENANCE: a fact completed by a HUMAN answer is stamped
    # extraction_method="human" — it must never masquerade as a repo-derived
    # fact again (validation study, S1/S5: garbage answers were laundered into
    # confidence-1.0 "ast" facts attributed to files that don't contain them).
    # The answers, the skip/runtime decisions, and any operator-error warnings
    # all travel with the quad (see emit.py metadata) so the audit trail can
    # never be separated from the data it explains.
    _token = re.compile(r"\$\{([^}]+)\}")
    repo_answers = {str(k): str(v) for k, v in qf.bindings.items()}
    # sheets were read ONCE at the top; reserved keys (environment_file,
    # confirm_lambda_names, lambda_name.*) steer the run and are never token
    # answers.
    human_answers = {k: v for k, v in sheet_answers.items() if not _reserved(k)}
    decisions = {k: v for k, v in sheet_decisions.items() if not _reserved(k)}

    all_tokens = {t for q in qf.quads for t in _token.findall(q.object)}
    answers = {**repo_answers, **human_answers}    # a human beats a repo file
    for q in qf.quads:
        if "${" in q.object:
            new = q.object
            used_human = False
            for t in _token.findall(q.object):
                if t in answers:
                    new = new.replace("${%s}" % t, answers[t])
                    used_human = used_human or t in human_answers
            if new != q.object:
                q.object = new
                if used_human:
                    q.extraction_method = "human"  # a person supplied this name
                if "${" not in new and not q.symbolic:
                    # every blank met a word-for-word answer AND nothing raw
                    # remains — only then is the fact fully resolved
                    q.resolved = True
                    q.confidence = 1.0
    qf.pending_names = sorted({t for q in qf.quads
                               for t in _token.findall(q.object)
                               if t not in decisions})
    # Reserved questions ride the same checkpoint, in front of the tokens:
    #   confirm_lambda_names — the declared names await a human's yes/corrections
    #   environment_file     — FIRST always: its answer changes everything below
    if qf.lambda_names_declared and not qf.lambda_names_confirmed:
        qf.pending_names.insert(0, "confirm_lambda_names")
    if qf.env_candidates and not qf.environment_file:
        qf.pending_names.insert(0, "environment_file")
    qf.human_answers = {k: v for k, v in sorted(human_answers.items())
                        if k in all_tokens}
    qf.decisions = {k: v for k, v in sorted(decisions.items()) if k in all_tokens}
    for k in sorted(set(human_answers) - all_tokens):     # stale/misspelled entries
        qf.sheet_warnings.append(
            f"worksheet answers '{k}' but no ${{{k}}} exists in this app — "
            f"stale or misspelled token; ignored")
    for k in sorted(set(human_answers) & set(decisions) & all_tokens):
        qf.sheet_warnings.append(
            f"'{k}' has both a worksheet value and a "
            f"'{decisions[k].get('decision', '?')}' decision — the value wins; "
            f"remove one of the two entries to resolve the contradiction")

    # --- journeys: walk the finished flow graph, record what it proves --------
    # ONLY on a decided graph. An undecided graph gets no journeys at all: the
    # halt is structural, not advisory — nothing downstream can consume journeys
    # that were never computed (the checkpoint cannot be driven past).
    if not qf.pending_names:
        from . import journeys as journeys_mod
        j_ents, j_quads, unwired = journeys_mod.extract_journeys(qf)
        qf.entities.extend(j_ents)
        qf.quads.extend(j_quads)
        qf.unwired = unwired

    # Deterministic ordering.
    qf.entities.sort(key=lambda e: (e.source.file_path if e.source else "", e.id))
    qf.quads.sort(key=lambda q: (q.file_path, q.line or 0, q.predicate, q.object, q.subject))
    return qf
