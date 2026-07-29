"""
Wiring parser — the arrows that live OUTSIDE code (Step 1, no LLM).

Serverless applications are connected by configuration, not calls: a deployment
manifest maps function NAMES to handler CODE, and a state-machine definition
(Amazon States Language) chains those functions in order. Without these files the
graph is islands — code invokes `StateMachine:X` and the trail goes cold, because
nothing says what X runs. This pass reads the wiring and emits the missing arrows.

Detection is by SHAPE, never by filename (same discipline as workflow.py):
  - deployment manifest — a mapping with a `functions` table whose entries carry a
    `handler` (the serverless-framework shape; SAM/CDK synth output matches too).
    An optional `stateMachines` table (name -> {definition: <path>}) binds ASL
    definition files to their deployed machine names.
  - state machine definition — a mapping with `StartAt` + `States`: the two keys
    the ASL specification itself requires. JSON and YAML both accepted.

Identity uses AWS's own published ARN format (arn:partition:service:region:acct:
type:name): any ARN collapses to its trailing resource NAME, so the code call
site, the manifest entry, and the definition all land on ONE node id. That is a
documented AWS grammar, not an app convention.

Emitted (same Entity/Quad model as every pass):
  LambdaFunction:<name>  --HANDLED_BY-->     Function:<module.func>      (manifest)
  StateMachine:<name>    --FEEDS-->          State:<machine>::<StartAt>  (entry)
  State:<m>::<s>         --INVOKES_LAMBDA--> LambdaFunction:<name>       (Task states)
  State:<m>::<s>         --FEEDS-->          State:<m>::<next>           (Next/Choice/Default)

A definition file with no manifest binding still parses — its machine id falls
back to the file stem and every quad is marked unresolved, honestly.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import yaml

from .models import Entity, Quad, Source


# --- AWS's published ARN grammar -------------------------------------------------
def arn_name(value: str) -> str:
    """arn:partition:service:region:account:resourceType:resource -> resource.
    Non-ARN strings pass through untouched, so plain names are already canonical."""
    if not isinstance(value, str) or not value.startswith("arn:"):
        return value
    parts = value.split(":")
    return parts[-1] if len(parts) >= 6 and parts[-1] else value


# --- shape tests -------------------------------------------------------------------
def is_manifest(doc) -> bool:
    fns = isinstance(doc, dict) and doc.get("functions")
    return bool(isinstance(fns, dict) and
                any(isinstance(v, dict) and "handler" in v for v in fns.values()))


def is_state_machine(doc) -> bool:
    return (isinstance(doc, dict) and isinstance(doc.get("StartAt"), str)
            and isinstance(doc.get("States"), dict))


# --- manifest ------------------------------------------------------------------------
def _handler_to_function_id(handler: str) -> Optional[str]:
    """'lambdas/ingest_handler.handler' -> 'Function:lambdas.ingest_handler.handler'
    (module path by the serverless handler grammar: everything before the last dot
    is the module, after it the callable)."""
    if not isinstance(handler, str) or "." not in handler:
        return None
    module, func = handler.rsplit(".", 1)
    module = module.replace("/", ".").replace("\\", ".")
    if module.endswith(".py"):
        module = module[:-3]
    return f"Function:{module}.{func}"


# The serverless framework's own event grammar: each entry in a function's
# ``events:`` list is a single-key mapping naming the trigger kind. The value may
# be a scalar or a mapping (both documented forms). We translate each kind to a
# typed source node; unknown kinds are kept, honestly unresolved, never dropped.
def _event_source(kind: str, value) -> Tuple[str, bool]:
    def field(*keys):
        if isinstance(value, dict):
            for k in keys:
                if isinstance(value.get(k), (str, int)):
                    return str(value[k])
        return value if isinstance(value, str) else None

    if kind == "s3":
        bucket = field("bucket")
        return (f"S3Bucket:{bucket}", True) if bucket else ("S3Bucket:<unknown>", False)
    if kind == "schedule":
        rate = field("rate", "cron")
        return (f"Schedule:{rate}", True) if rate else ("Schedule:<unknown>", False)
    if kind == "sqs":
        arn = field("arn")
        return (f"Queue:{arn_name(arn)}", True) if arn else ("Queue:<unknown>", False)
    if kind == "sns":
        topic = field("arn", "topicName")
        return (f"Topic:{arn_name(topic)}", True) if topic else ("Topic:<unknown>", False)
    if kind in ("http", "httpApi"):
        method = (field("method") or "GET").upper()
        path = field("path")
        return (f"APIEndpoint:{method} {path}", True) if path \
            else ("APIEndpoint:<unknown>", False)
    return (f"EventSource:{kind}", False)      # a kind we haven't met — flagged, kept


def harvest_environment(doc: dict) -> Dict[str, str]:
    """Repo-declared answers: literal values from `environment:` blocks (global
    `provider.environment` + per-function). ONLY word-for-word literals are taken —
    a value containing `${...}` is itself unresolved and is never harvested. This
    is the auto rung of the trust ladder (doc 10): we copy, never conclude."""
    out: Dict[str, str] = {}

    def take(block):
        if not isinstance(block, dict):
            return
        for key, value in block.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)) \
                    and "${" not in str(value):
                out[key] = str(value)

    take((doc.get("provider") or {}).get("environment") if isinstance(doc.get("provider"), dict) else None)
    for spec in (doc.get("functions") or {}).values():
        if isinstance(spec, dict):
            take(spec.get("environment"))
    return out


def extract_manifest(doc: dict, relpath: str) -> Tuple[List[Entity], List[Quad], Dict[str, str]]:
    """Entities+quads for the name->handler map and each function's declared
    triggers, plus {definition-path: machine-name} bindings for the ASL pass."""
    entities: List[Entity] = []
    quads: List[Quad] = []
    for name, spec in (doc.get("functions") or {}).items():
        if not isinstance(spec, dict):
            continue
        fn_id = _handler_to_function_id(spec.get("handler", ""))
        lam = f"LambdaFunction:{arn_name(str(name))}"
        entities.append(Entity(id=lam, type="LambdaFunction", name=str(name),
                               language="wiring", source=Source(relpath, None, None)))
        if fn_id:
            quads.append(Quad(lam, "HANDLED_BY", fn_id, True, 1.0, relpath, None,
                              language="wiring"))
        for event in spec.get("events") or []:
            if not isinstance(event, dict) or len(event) != 1:
                continue
            kind, value = next(iter(event.items()))
            source, resolved = _event_source(str(kind), value)
            kind_prefix = source.split(":", 1)[0]
            entities.append(Entity(id=source, type=kind_prefix, name=source,
                                   language="wiring", source=Source(relpath, None, None)))
            quads.append(Quad(lam, "RECEIVES_EVENT", source, resolved,
                              1.0 if resolved else 0.5, relpath, None, language="wiring"))

    definitions: Dict[str, str] = {}
    machines = doc.get("stateMachines")
    if isinstance(machines, dict):
        for m_name, m_spec in machines.items():
            if isinstance(m_spec, dict) and isinstance(m_spec.get("definition"), str):
                definitions[os.path.normpath(m_spec["definition"])] = str(m_name)
    return entities, quads, definitions


# --- state machine (ASL) ----------------------------------------------------------------
def _task_lambda(state: dict) -> Optional[str]:
    """The lambda a Task state runs, per the two ASL spec forms: a direct function
    ARN in Resource, or the optimized `states:::lambda:invoke` integration with
    Parameters.FunctionName."""
    res = state.get("Resource")
    if not isinstance(res, str):
        return None
    if res.endswith(":lambda:invoke"):
        params = state.get("Parameters") or {}
        fn = params.get("FunctionName")
        return arn_name(fn) if isinstance(fn, str) else None
    if ":function:" in res:
        return arn_name(res)
    # A bare name (no ARN scheme at all) is what resolution produces — arn_name
    # collapses every lambda reference to its trailing name, so a colon-free
    # Resource IS the collapsed form. Every other integration keeps its colons.
    # A still-blank ``${token}`` is returned AS the token (B3): the fact stays
    # visible and the token becomes a checkpoint question — dropping it made an
    # unresolved reference silently vanish instead of being asked about.
    if res and ":" not in res:
        return res
    return None


def _walk_states(states: dict, machine: str, relpath: str,
                 entities: List[Entity], quads: List[Quad], resolved: bool):
    """One pass over a States map; recurses into Parallel branches and Map iterators
    (the ASL spec's own nesting points)."""
    conf = 1.0 if resolved else 0.5
    for s_name, state in states.items():
        if not isinstance(state, dict):
            continue
        sid = f"State:{machine}::{s_name}"
        entities.append(Entity(id=sid, type="State", name=f"{machine}::{s_name}",
                               language="wiring", source=Source(relpath, None, None)))
        lam = _task_lambda(state)
        if lam:
            # A target still holding a ${blank} is NOT resolved, whatever the
            # machine's own resolution says — the flag is per-object truth
            # (study S3: skipped blanks read as full-confidence facts).
            known = resolved and "${" not in lam
            quads.append(Quad(sid, "INVOKES_LAMBDA", f"LambdaFunction:{lam}",
                              known, conf if known else 0.5, relpath, None,
                              language="wiring"))
        nexts = []
        if isinstance(state.get("Next"), str):
            nexts.append(state["Next"])
        for choice in state.get("Choices") or []:
            if isinstance(choice, dict) and isinstance(choice.get("Next"), str):
                nexts.append(choice["Next"])
        if isinstance(state.get("Default"), str):
            nexts.append(state["Default"])
        for catcher in state.get("Catch") or []:               # error-handler jumps —
            if isinstance(catcher, dict) and isinstance(catcher.get("Next"), str):
                nexts.append(catcher["Next"])                  # a Catch target is a
        for nxt in nexts:                                      # successor like any Next
            quads.append(Quad(sid, "FEEDS", f"State:{machine}::{nxt}",
                              resolved, conf, relpath, None, language="wiring"))
        # A Parallel/Map container FEEDS each branch's StartAt — the spec's own
        # semantics (the container starts its branches); without this edge every
        # branch head looks unreached and roots a fake journey.
        for branch in state.get("Branches") or []:            # Parallel
            if isinstance(branch, dict) and isinstance(branch.get("States"), dict):
                if isinstance(branch.get("StartAt"), str):
                    quads.append(Quad(sid, "FEEDS",
                                      f"State:{machine}::{branch['StartAt']}",
                                      resolved, conf, relpath, None, language="wiring"))
                _walk_states(branch["States"], machine, relpath, entities, quads, resolved)
        for key in ("Iterator", "ItemProcessor"):              # Map (both spec names)
            sub = state.get(key)
            if isinstance(sub, dict) and isinstance(sub.get("States"), dict):
                if isinstance(sub.get("StartAt"), str):
                    quads.append(Quad(sid, "FEEDS",
                                      f"State:{machine}::{sub['StartAt']}",
                                      resolved, conf, relpath, None, language="wiring"))
                _walk_states(sub["States"], machine, relpath, entities, quads, resolved)


def extract_state_machine(doc: dict, relpath: str,
                          machine_name: Optional[str]) -> Tuple[List[Entity], List[Quad]]:
    resolved = machine_name is not None
    machine = machine_name or os.path.splitext(os.path.basename(relpath))[0]
    entities: List[Entity] = [Entity(id=f"StateMachine:{machine}", type="StateMachine",
                                     name=machine, language="wiring",
                                     source=Source(relpath, 1, None))]
    quads: List[Quad] = [Quad(f"StateMachine:{machine}", "FEEDS",
                              f"State:{machine}::{doc['StartAt']}",
                              resolved, 1.0 if resolved else 0.5, relpath, None,
                              language="wiring")]
    _walk_states(doc["States"], machine, relpath, entities, quads, resolved)
    return entities, quads


# --- the pass ---------------------------------------------------------------------------
def extract_wiring(app_dir: str, keep=None, env_file=None) -> tuple:
    """Scan yaml/yml/json for manifests and state machines (shape-detected), in two
    phases so manifest bindings can name the machines. ``keep`` mirrors extract.py's
    single-file re-parse filter."""
    from .extract import discover
    entities: List[Entity] = []
    quads: List[Quad] = []

    docs: List[Tuple[str, dict]] = []
    for path in discover(app_dir, exts=(".yml", ".yaml", ".json")):
        if keep is not None and os.path.realpath(path) not in keep:
            continue
        rel = os.path.relpath(path, app_dir)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                doc = yaml.safe_load(fh)          # YAML is a JSON superset — one loader
        except Exception:
            continue
        if isinstance(doc, dict):
            docs.append((rel, doc))

    definitions: Dict[str, str] = {}
    bindings: Dict[str, str] = {}
    for rel, doc in docs:                          # phase 1 — manifests
        if is_manifest(doc):
            ents, qds, defs = extract_manifest(doc, rel)
            entities.extend(ents)
            quads.extend(qds)
            definitions.update(defs)
            bindings.update(harvest_environment(doc))

    # --- terraform: the wiring that lives in the deploy repo --------------------
    from . import terraform as tf_mod
    tf_ents, tf_quads, tf_bindings, tf_defs, tf_varmaps, tf_inline, tf_notes, \
        tf_hints, tf_env = tf_mod.extract_terraform(app_dir, keep, env_file)
    entities.extend(tf_ents)
    quads.extend(tf_quads)
    bindings.update(tf_bindings)
    definitions.update(tf_defs)

    seen_docs = set()
    for rel, doc in docs:                          # phase 2 — state machines
        if is_state_machine(doc):
            norm = os.path.normpath(rel)
            seen_docs.add(norm)
            name = definitions.get(norm)
            vmap = tf_varmaps.get(norm)
            if vmap:                               # fill the blanks the repo states,
                doc = tf_mod.substitute_tokens(doc, vmap)   # word-for-word
            ents, qds = extract_state_machine(doc, rel, name)
            entities.extend(ents)
            quads.extend(qds)

    # phase 2b — definition TARGETS the doc walk missed (B2): a templatefile
    # target is an explicit word-for-word path; the machine it defines must be
    # read whatever extension the file carries (.tpl, .asl, anything). The file's
    # CONTENT decides — it parses as a state machine or it is noted, never
    # silently counted-but-not-read.
    for norm, name in definitions.items():
        if norm in seen_docs:
            continue
        full = os.path.join(app_dir, norm)
        if not os.path.isfile(full):
            tf_notes.append(f"terraform: machine definition file {norm} "
                            f"(for {name}) is not in the upload — machine not read")
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                doc = yaml.safe_load(fh)
        except Exception:
            doc = None
        if not is_state_machine(doc):
            tf_notes.append(f"terraform: {norm} (definition of {name}) does not "
                            f"parse as a state machine — machine not read")
            continue
        vmap = tf_varmaps.get(norm)
        if vmap:
            doc = tf_mod.substitute_tokens(doc, vmap)
        ents, qds = extract_state_machine(doc, norm, name)
        entities.extend(ents)
        quads.extend(qds)

    for rel, machine, doc in tf_inline:            # machines defined inline in .tf
        ents, qds = extract_state_machine(doc, rel, machine)
        entities.extend(ents)
        quads.extend(qds)
    return entities, quads, bindings, tf_notes, tf_hints, tf_env
