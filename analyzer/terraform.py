"""
Terraform pass — the wiring that lives in the DEPLOY repo (Step 1, no LLM).

Some estates write their connections not in a serverless manifest but in
Terraform: lambdas are declared as ``aws_lambda_function`` resources (or as
entries in a ``.tfvars`` value map consumed by a shared module — the provider's
own argument names, ``function_name``/``handler``, mark the shape), and state
machines are ``aws_sfn_state_machine`` resources whose ``definition`` is either
an inline ``jsonencode({...})``, a heredoc/JSON string, or a
``templatefile("x.asl.json", { blank = value })`` call — whose var map states,
word for word, what each ``${blank}`` in the definition file means.

Reading is DETERMINISTIC: a hand-rolled lexer + recursive-descent reader for
the HCL subset that can state facts literally — blocks, attributes, literal
values, object/list values, function calls, dotted references. It follows
HCL's own published grammar for that subset; no regex over prose, no name
rules, no app-specific knowledge. Anything outside the subset (arithmetic,
conditionals, for-expressions, remote state) is left exactly as found: an
unresolved ``${...}`` blank that the name checkpoint asks a human about.
We copy, never conclude — the same trust ladder as the wiring pass.

Produced (consumed by wiring.extract_wiring):
  entities/quads   LambdaFunction:<name> --HANDLED_BY--> Function:<module.func>
  bindings         token -> literal (tfvars scalars, variable defaults, locals,
                   lambda environment blocks)
  definitions      <asl relpath> -> machine name   (templatefile targets)
  varmaps          <asl relpath> -> {blank: value} (templatefile var maps)
  inline machines  (relpath, name, doc)            (jsonencode / string bodies)
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

from .models import Entity, Quad, Source

# --- values -----------------------------------------------------------------------
# Literals are plain Python values. Structured non-literals are tagged tuples:
#   ("ref", [part, ...])      a dotted/indexed reference, parts flattened
#   ("call", name, [args])    a function call
#   ("unparsed", None)        anything outside the subset — honestly unknown


def _is_literal(v) -> bool:
    return isinstance(v, (str, int, float, bool)) and not (
        isinstance(v, str) and "${" in v)


# --- lexer -------------------------------------------------------------------------
_PUNCT = set("{}[]()=,.:")
_KEYWORDS = {"true": True, "false": False, "null": None}


def _lex(text: str) -> List[Tuple[str, object]]:
    toks: List[Tuple[str, object]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            toks.append(("NL", "\n"))
            i += 1
            continue
        if c == "#" or text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if text.startswith("<<", i):                       # heredoc: <<TAG / <<-TAG
            j = i + 2
            if j < n and text[j] == "-":
                j += 1
            k = j
            while k < n and (text[k].isalnum() or text[k] == "_"):
                k += 1
            tag = text[j:k]
            line_end = text.find("\n", k)
            if tag and line_end >= 0:
                pos = line_end + 1
                body_start = pos
                while pos <= n:
                    nl = text.find("\n", pos)
                    line = text[pos:(nl if nl >= 0 else n)]
                    if line.strip() == tag or nl < 0:
                        toks.append(("STR", text[body_start:pos]))
                        i = (nl + 1) if nl >= 0 else n
                        break
                    pos = nl + 1
                continue
        if c == '"':
            j, out = i + 1, []
            while j < n:
                ch = text[j]
                if ch == "\\" and j + 1 < n:
                    esc = text[j + 1]
                    out.append({"n": "\n", "t": "\t", '"': '"',
                                "\\": "\\"}.get(esc, "\\" + esc))
                    j += 2
                    continue
                if ch == '"' or ch == "\n":
                    break            # HCL strings never span lines: an unterminated
                out.append(ch)       # quote ends at the newline, so ONE typo can
                j += 1               # never swallow the rest of the file
            toks.append(("STR", "".join(out)))
            i = j + (1 if j < n and text[j] == '"' else 0)
            continue
        if c.isdigit() or (c == "-" and i + 1 < n and text[i + 1].isdigit()):
            j = i + 1
            while j < n and (text[j].isdigit() or text[j] == "."):
                j += 1
            raw = text[i:j]
            toks.append(("NUM", float(raw) if "." in raw else int(raw)))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "_-"):
                j += 1
            toks.append(("IDENT", text[i:j]))
            i = j
            continue
        if c in _PUNCT:
            toks.append(("P", c))
            i += 1
            continue
        toks.append(("OP", c))                             # operator soup we don't model
        i += 1
    toks.append(("EOF", ""))
    return toks


# --- reader ------------------------------------------------------------------------
class _Reader:
    def __init__(self, toks: List[Tuple[str, object]]):
        self.toks = toks
        self.i = 0

    def _skip_nl(self):
        while self.toks[self.i][0] == "NL":
            self.i += 1

    def peek(self, skip_nl=True) -> Tuple[str, object]:
        if skip_nl:
            j = self.i
            while self.toks[j][0] == "NL":
                j += 1
            return self.toks[j]
        return self.toks[self.i]

    def next(self, skip_nl=True) -> Tuple[str, object]:
        if skip_nl:
            self._skip_nl()
        t = self.toks[self.i]
        if t[0] != "EOF":
            self.i += 1
        return t

    # skip to a value terminator at the current nesting depth — error recovery
    # for expressions outside the subset. The VALUE is lost (unparsed), the
    # FILE keeps reading.
    def skip_value(self):
        depth = 0
        while True:
            kind, val = self.toks[self.i]
            if kind == "EOF":
                return
            if kind == "P" and val in "{[(":
                depth += 1
            elif kind == "P" and val in "}])":
                if depth == 0:
                    return
                depth -= 1
            elif depth == 0 and (kind == "NL" or (kind == "P" and val == ",")):
                return
            self.i += 1

    def value(self):
        kind, val = self.peek()
        if kind == "STR":
            self.next()
            return self._maybe_expr_tail(val)
        if kind == "NUM":
            self.next()
            return self._maybe_expr_tail(val)
        if kind == "P" and val == "{":
            return self._object()
        if kind == "P" and val == "[":
            return self._list()
        if kind == "IDENT":
            if val in _KEYWORDS:
                self.next()
                return self._maybe_expr_tail(_KEYWORDS[val])
            return self._ref_or_call()
        self.skip_value()
        return ("unparsed", None)

    def _maybe_expr_tail(self, parsed):
        """A literal followed on the same line by an operator is part of a larger
        expression we don't model — drop to unparsed rather than half-read it."""
        kind, val = self.peek(skip_nl=False)
        if kind == "OP" or (kind == "P" and val == "."):
            self.skip_value()
            return ("unparsed", None)
        return parsed

    def _object(self) -> dict:
        self.next()                                        # consume {
        out: dict = {}
        while True:
            kind, val = self.peek()
            if kind == "EOF" or (kind == "P" and val == "}"):
                self.next()
                return out
            if kind == "P" and val == ",":
                self.next()
                continue
            if kind not in ("IDENT", "STR"):
                self.skip_value()
                if self.peek(skip_nl=False)[0] == "NL":
                    self.next(skip_nl=False)
                continue
            key = str(self.next()[1])
            kind, val = self.peek()
            if kind == "P" and val in ("=", ":"):
                self.next()
                out[key] = self.value()
            else:                                          # bare key — not our subset
                out[key] = ("unparsed", None)

    def _list(self) -> list:
        self.next()                                        # consume [
        out: list = []
        while True:
            kind, val = self.peek()
            if kind == "EOF" or (kind == "P" and val == "]"):
                self.next()
                return out
            if kind == "P" and val == ",":
                self.next()
                continue
            out.append(self.value())

    def _ref_or_call(self):
        name = str(self.next()[1])
        kind, val = self.peek(skip_nl=False)
        if kind == "P" and val == "(":                     # call
            self.next()
            args = []
            while True:
                kind, val = self.peek()
                if kind == "EOF" or (kind == "P" and val == ")"):
                    self.next()
                    return ("call", name, args)
                if kind == "P" and val == ",":
                    self.next()
                    continue
                args.append(self.value())
        parts = [name]                                     # dotted / indexed reference
        while True:
            kind, val = self.peek(skip_nl=False)
            if kind == "P" and val == ".":
                self.next(skip_nl=False)
                kind, val = self.peek(skip_nl=False)
                if kind != "IDENT":
                    self.skip_value()
                    return ("unparsed", None)
                parts.append(str(self.next(skip_nl=False)[1]))
                continue
            if kind == "P" and val == "[":
                self.next(skip_nl=False)
                kind, val = self.peek()
                if kind not in ("STR", "NUM"):
                    self.skip_value()
                    return ("unparsed", None)
                parts.append(str(self.next()[1]))
                kind, val = self.peek()
                if kind == "P" and val == "]":
                    self.next()
                continue
            if kind == "OP":
                self.skip_value()
                return ("unparsed", None)
            return ("ref", parts)

    def body(self, top=False) -> Tuple[dict, list]:
        """(attributes, blocks) until the matching '}' (or EOF at top level).
        A block is (type, [labels], attrs, blocks)."""
        attrs: dict = {}
        blocks: list = []
        while True:
            kind, val = self.peek()
            if kind == "EOF":
                return attrs, blocks
            if kind == "P" and val == "}":
                if not top:
                    self.next()
                    return attrs, blocks
                self.next()                                # stray brace — keep reading
                continue
            if kind not in ("IDENT", "STR"):
                self.next()                                # recovery: drop the token
                continue
            name = str(self.next()[1])
            kind, val = self.peek()
            if kind == "P" and val == "=":
                self.next()
                attrs[name] = self.value()
                continue
            labels = []
            while self.peek()[0] == "STR":
                labels.append(str(self.next()[1]))
            kind, val = self.peek()
            if kind == "P" and val == "{":
                self.next()
                b_attrs, b_blocks = self.body()
                blocks.append((name, labels, b_attrs, b_blocks))
            # else: something outside the subset — the name token is dropped


def parse_hcl(text: str) -> Tuple[dict, list]:
    """(top-level attributes, top-level blocks). tfvars files are attributes
    only; .tf files are mostly blocks."""
    return _Reader(_lex(text)).body(top=True)


# --- resolution --------------------------------------------------------------------
class _Index:
    """Everything the repo states, indexed for word-for-word lookup."""

    def __init__(self):
        self.resources: Dict[Tuple[str, str], dict] = {}   # (type, label) -> attrs
        self.variables: Dict[str, object] = {}             # name -> default literal
        self.locals: Dict[str, object] = {}
        self.tfvars: Dict[str, object] = {}                # includes nested maps

    def add_tf(self, blocks: list):
        for btype, labels, attrs, sub_blocks in blocks:
            if btype == "resource" and len(labels) == 2:
                self.resources[(labels[0], labels[1])] = attrs
            elif btype == "variable" and len(labels) == 1:
                if _is_literal(attrs.get("default")):
                    self.variables[labels[0]] = attrs["default"]
            elif btype == "locals":
                for k, v in attrs.items():
                    if _is_literal(v):
                        self.locals[k] = v

    def add_tfvars(self, attrs: dict):
        self.tfvars.update(attrs)

    def resolve(self, value) -> Optional[str]:
        """A value -> its literal string, or None when the repo doesn't state it."""
        if _is_literal(value):
            return str(value)
        if isinstance(value, tuple) and value[0] == "ref":
            parts = value[1]
            if parts[0] == "var" and len(parts) >= 2:
                # var.name, or a pure data walk into a tfvars value map:
                # var.some-map["entry"].field — every hop is a literal key into
                # data the repo states word-for-word; any missing hop -> None.
                cand = self.tfvars.get(parts[1], self.variables.get(parts[1]))
                for key in parts[2:]:
                    if not isinstance(cand, dict):
                        return None
                    cand = cand.get(key)
                return str(cand) if _is_literal(cand) else None
            if len(parts) == 2 and parts[0] == "local":
                cand = self.locals.get(parts[1])
                return str(cand) if _is_literal(cand) else None
            if len(parts) == 3:
                rtype, label, attr = parts
                body = self.resources.get((rtype, label))
                if body is None:
                    return None
                # AWS's own identity arguments: a lambda IS its function_name,
                # a state machine IS its name — the provider's documented schema.
                if rtype == "aws_lambda_function" and attr in (
                        "arn", "id", "function_name", "qualified_arn", "invoke_arn"):
                    cand = body.get("function_name")
                    return str(cand) if _is_literal(cand) else None
                if rtype == "aws_sfn_state_machine" and attr in ("arn", "id", "name"):
                    cand = body.get("name")
                    return str(cand) if _is_literal(cand) else None
                cand = body.get(attr)
                return str(cand) if _is_literal(cand) else None
        return None

    def resolve_deep(self, value):
        """Resolve refs inside objects/lists; an unresolvable ref becomes its own
        ``${...}`` blank so it stays VISIBLE downstream instead of vanishing."""
        if isinstance(value, tuple):
            got = self.resolve(value)
            if got is not None:
                return got
            if value[0] == "ref":
                return "${" + ".".join(value[1]) + "}"
            return "${unparsed}"
        if isinstance(value, dict):
            return {k: self.resolve_deep(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve_deep(v) for v in value]
        return value


def _substitute_string(s: str, index: _Index) -> str:
    """Replace each ``${expr}`` span whose expr is a resolvable reference; leave
    every other span exactly as found (a visible blank)."""
    out, i = [], 0
    while True:
        j = s.find("${", i)
        if j < 0:
            out.append(s[i:])
            return "".join(out)
        k = s.find("}", j + 2)
        if k < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:j])
        inner = s[j + 2:k]
        value = _Reader(_lex(inner)).value()
        got = index.resolve(value) if isinstance(value, tuple) else (
            str(value) if _is_literal(value) else None)
        out.append(got if got is not None else s[j:k + 1])
        i = k + 1


def substitute_tokens(node, mapping: Dict[str, str]):
    """Fill known blanks in a parsed document: every ``${token}`` whose token is
    in the mapping is replaced word-for-word; unknown tokens stay visible."""
    if isinstance(node, str):
        for k, v in mapping.items():
            node = node.replace("${%s}" % k, v)
        return node
    if isinstance(node, dict):
        return {k: substitute_tokens(v, mapping) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute_tokens(v, mapping) for v in node]
    return node


# --- harvest -----------------------------------------------------------------------
def _clean_template_path(path: str) -> str:
    """'${path.module}/import.asl.json' -> 'import.asl.json' (Terraform's own
    self-reference prefix; everything after it is the repo-relative file)."""
    if path.startswith("${") and "}" in path:
        path = path[path.index("}") + 1:]
    return path.lstrip("/").lstrip("./")


def _harvest_env(entry: dict, bindings: Dict[str, str]):
    for env_key in ("environment_vars", "environment", "variables"):
        env = entry.get(env_key)
        if isinstance(env, dict):
            inner = env.get("variables")
            if isinstance(inner, dict):                    # provider nests env under
                env = inner                                # environment { variables = {} }
            for k, v in env.items():
                if _is_literal(v):
                    bindings[str(k)] = str(v)


def _lambda_shape(entry) -> bool:
    """The AWS provider's own lambda argument names mark a lambda declaration,
    wherever it appears (resource block or a module's .tfvars value map)."""
    return isinstance(entry, dict) and (
        _is_literal(entry.get("function_name")) or _is_literal(entry.get("handler")))


def _read_text(path: str) -> str:
    """Read a config file whatever a Windows editor did to it: sniff the BOM
    (UTF-8-sig / UTF-16 LE / UTF-16 BE) and decode accordingly; plain bytes
    fall back to UTF-8. A wrongly-decoded file previously lexed to garbage and
    SILENTLY yielded nothing — the exact failure that hid a whole lambda-list."""
    raw = open(path, "rb").read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    return raw.decode("utf-8", errors="replace")


def extract_terraform(app_dir: str, keep=None, env_file=None):
    """Scan .tf/.tfvars (same discovery rules as every pass). Returns
    (entities, quads, bindings, definitions, varmaps, inline_machines, notes,
    handler_hints, env_info).
    ``notes`` is the observability channel: which files were read, which were
    skipped and why, and what was found — so a silent miss can never happen
    again (the zero-lambda incident: nothing reported that nothing was read).

    ``env_file`` (A15): which of several COMPETING .tfvars files grounds this
    map. Competition is detected by the files themselves — two .tfvars files
    declaring the same top-level key with different values describe different
    environments; merging them silently would put devl values in a test map.
    With no selection, every competing file is EXCLUDED (nothing mixed) and
    ``env_info['candidates']`` carries the question for the checkpoint."""
    from .extract import discover
    from .wiring import _handler_to_function_id, arn_name, is_state_machine
    import yaml as _yaml

    entities: List[Entity] = []
    quads: List[Quad] = []
    bindings: Dict[str, str] = {}
    definitions: Dict[str, str] = {}                       # asl relpath -> machine name
    varmaps: Dict[str, Dict[str, str]] = {}                # asl relpath -> {blank: value}
    inline: List[Tuple[str, str, dict]] = []               # (rel, machine, doc)
    notes: List[str] = []

    index = _Index()
    parsed: List[Tuple[str, dict, list]] = []              # (rel, attrs, blocks)
    map_sources: List[Tuple[str, dict]] = []               # dict-valued attrs from ANY home
    for path in discover(app_dir, exts=(".tf", ".tfvars")):
        if keep is not None and os.path.realpath(path) not in keep:
            continue
        rel = os.path.relpath(path, app_dir)
        try:
            text = _read_text(path)
            attrs, blocks = parse_hcl(text)
        except Exception as exc:                           # never crash — but never
            notes.append(f"terraform: could not read {rel} "
                         f"({exc.__class__.__name__}: {exc}) — file skipped")
            continue                                       # be silent about it either
        if not attrs and not blocks and len(text.strip()) > 40:
            notes.append(f"terraform: {rel} parsed to nothing despite having "
                         f"content — check its encoding/syntax")
        parsed.append((rel, attrs, blocks))
        if not path.endswith(".tfvars"):
            index.add_tf(blocks)
            index.add_tfvars({k: v for k, v in attrs.items() if _is_literal(v)})
            # lambda declarations live wherever the layout put them — collect
            # every dict-valued attribute container for the shape scan below:
            for btype, labels, b_attrs, _sub in blocks:
                if btype in ("locals", "module"):
                    map_sources.append((rel, b_attrs))
                elif btype == "variable" and isinstance(b_attrs.get("default"), dict):
                    map_sources.append((rel, {"default": b_attrs["default"]}))

    # --- environment selection (A15) -------------------------------------------
    # Two .tfvars files declaring the SAME top-level key with DIFFERENT values
    # describe different environments of one estate. Reading both would silently
    # mix environments' values into one map, so: the competing group is either
    # decided (env_file) or excluded whole, and the question goes to a human.
    tfvars_files = [(rel, attrs) for rel, attrs, _b in parsed
                    if rel.endswith(".tfvars")]
    competing: set = set()
    for i, (rel_a, a) in enumerate(tfvars_files):
        for rel_b, b in tfvars_files[i + 1:]:
            if any(k in b and b[k] != v for k, v in a.items()):
                competing.add(rel_a)
                competing.add(rel_b)
    env_info = {"candidates": sorted(competing), "chosen": None}
    excluded: set = set()
    if competing:
        chosen = [c for c in sorted(competing)
                  if env_file and (c == env_file or os.path.basename(c) == env_file
                                   or c.endswith(os.sep + env_file)
                                   or c.replace(os.sep, "/").endswith("/" + env_file))]
        if len(chosen) == 1:
            env_info["chosen"] = chosen[0]
            excluded = competing - {chosen[0]}
            notes.append(
                f"terraform: environment file {chosen[0]} grounds this map — "
                f"{len(excluded)} other environment file(s) present, NOT used: "
                + ", ".join(sorted(excluded)))
        else:
            excluded = set(competing)
            notes.append(
                f"terraform: {len(competing)} files declare the same settings "
                f"with different values (" + ", ".join(sorted(competing)) +
                ") — no environment chosen, so NONE of them was used; answer "
                "'environment_file' in the worksheet (or pass --env-file)")
    for rel, attrs in tfvars_files:
        if rel not in excluded:
            index.add_tfvars(attrs)

    seen_lambdas: set = set()
    handler_hints: Dict[str, List[str]] = {}               # lam id -> path-shaped
                                                           # literals from its entry
                                                           # (s3_key etc.) — the
                                                           # entry's own statement of
                                                           # where its code lives

    def emit_lambda(name: str, entry: dict, rel: str):
        lam = f"LambdaFunction:{arn_name(name)}"
        _harvest_env(entry, bindings)                      # EVERY home's env values
        for v in entry.values():                           # top-level fields only —
            if _is_literal(v) and isinstance(v, str) and "/" in v:
                handler_hints.setdefault(lam, [])          # env values are runtime
                if v not in handler_hints[lam]:            # settings, not deploy
                    handler_hints[lam].append(v)           # metadata
        if lam in seen_lambdas:                            # count (B1: the dedup used
            return                                         # to skip the second home's
        seen_lambdas.add(lam)                              # settings entirely)
        entities.append(Entity(id=lam, type="LambdaFunction", name=name,
                               language="wiring", source=Source(rel, None, None)))
        handler = entry.get("handler")
        if _is_literal(handler):
            fn_id = _handler_to_function_id(str(handler))
            if fn_id:
                quads.append(Quad(lam, "HANDLED_BY", fn_id, True, 1.0, rel, None,
                                  language="wiring"))

    def scan_maps_for_lambdas(rel: str, attrs: dict):
        """The shape scan, wherever the map lives: a dict entry carrying the AWS
        provider's own lambda argument names IS a lambda declaration — in a
        .tfvars value map, a locals block, a variable default, or a module call."""
        for _k, v in attrs.items():
            if isinstance(v, dict):
                for entry_name, entry in v.items():
                    if _lambda_shape(entry):
                        fname = entry.get("function_name")
                        name = str(fname) if _is_literal(fname) else str(entry_name)
                        emit_lambda(name, entry, rel)

    # --- pass 2: harvest with the full index in hand -------------------------------
    for k, v in index.variables.items():
        bindings.setdefault(str(k), str(v))
    for k, v in index.locals.items():
        bindings.setdefault(str(k), str(v))

    for rel, attrs in map_sources:                         # locals / variable / module
        scan_maps_for_lambdas(rel, attrs)

    for rel, attrs, blocks in parsed:
        if rel.endswith(".tfvars"):
            if rel in excluded:                            # a different environment
                continue                                   # (or an undecided one)
            for k, v in attrs.items():
                if _is_literal(v):
                    bindings[str(k)] = str(v)
            scan_maps_for_lambdas(rel, attrs)
            continue

        for btype, labels, b_attrs, _sub in blocks:
            if btype != "resource" or len(labels) != 2:
                continue
            rtype, label = labels
            if rtype == "aws_lambda_function":
                fname = b_attrs.get("function_name")
                name = str(fname) if _is_literal(fname) else label
                emit_lambda(name, b_attrs, rel)
                continue
            if rtype != "aws_sfn_state_machine":
                continue
            m_name = b_attrs.get("name")
            machine = str(m_name) if _is_literal(m_name) else label
            definition = b_attrs.get("definition")
            if isinstance(definition, tuple) and definition[0] == "call":
                _c, fn, args = definition
                # templatefile(path, {vars}) and file(path) share Terraform's own
                # path semantics — both bind the definition FILE to the machine's
                # deployed name; templatefile additionally states the var map.
                if fn in ("templatefile", "file") and args and isinstance(args[0], str) \
                        and "${" not in _clean_template_path(args[0]):
                    target = _clean_template_path(args[0])
                    target = os.path.normpath(
                        os.path.join(os.path.dirname(rel), target))
                    definitions[target] = machine
                    vmap: Dict[str, str] = {}
                    if fn == "templatefile" and len(args) > 1 and isinstance(args[1], dict):
                        for token, val in args[1].items():
                            got = index.resolve(val)
                            if got is not None:
                                vmap[str(token)] = got
                    varmaps[target] = vmap
                elif fn == "jsonencode" and args and isinstance(args[0], dict):
                    doc = index.resolve_deep(args[0])
                    if is_state_machine(doc):
                        inline.append((rel, machine, doc))
            elif isinstance(definition, str):              # heredoc / plain JSON string
                body = _substitute_string(definition, index)
                doc = None
                try:
                    doc = json.loads(body)
                except Exception:
                    try:
                        doc = _yaml.safe_load(body)
                    except Exception:
                        doc = None
                if isinstance(doc, dict) and is_state_machine(doc):
                    inline.append((rel, machine, doc))

    if parsed:
        notes.append(f"terraform: {len(parsed)} file(s) read — "
                     f"{len(seen_lambdas)} lambda declaration(s), "
                     f"{len(definitions) + len(inline)} machine definition(s), "
                     f"{len(bindings)} binding(s) harvested")
    return entities, quads, bindings, definitions, varmaps, inline, notes, \
        handler_hints, env_info
