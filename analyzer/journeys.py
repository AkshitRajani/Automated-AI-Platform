"""
Journey pass — derive the app's journeys from its own flow graph (Step 1, no LLM).

A journey is a walk through the application: from the place the outside world
presses a button, through code, wiring, and storage handoffs, to the last
observable side effect. The analyzer already emits every arrow (calls, wiring,
lineage, resource reads/writes); this pass WALKS them and records what it finds
as first-class facts, so downstream consumers (ingestion, the spec agent, human
review) receive journeys as data instead of re-deriving them.

Everything here is a graph property — no type lists, no name rules:

  entry      a node with flow-arrows OUT and none IN (a source). Endpoints,
             schedule heads, and workflow heads all fall out of this without
             being named.
  chain      breadth-first walk of the flow graph from an entry.
  journey    a chain that shows real orchestration structure: it passes through
             ordered steps/states, or hands data from a writer to a reader, or
             simply runs deep. Everything else is a small behavior.
  grouping   small behaviors are bundled by the container of their first code
             brick (the class/module that owns them) — one spec per family, so
             ten tiny read-endpoints never become ten documents.

Emitted:
  Journey:<entry>        type=Journey        STARTS_AT <entry>, HAS_MEMBER <node>…
  BehaviorGroup:<owner>  type=BehaviorGroup  HAS_MEMBER <entry-of-small-chain>…

HAS_MEMBER quads carry the hop distance from the entry in ``line`` (documented
here; there is no other per-quad slot for ordering). Membership is evidence —
the arrows themselves stay the source of truth for exact paths.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple

from .models import Entity, Quad, QuadFile, Source

# Flow direction per predicate — the ONE vocabulary shared with the walkability
# checker. Structure/config predicates carry no data flow and are excluded.
FORWARD = {"CALLS", "INVOKES_LAMBDA", "INVOKES_STEP_FUNCTION", "PUBLISHES_TO_SNS",
           "WRITES_TO_S3", "WRITES_DATABASE", "WRITES_DYNAMODB_TABLE", "WRITES_FILE",
           "RETURNS_RESPONSE", "FEEDS", "CALLS_HTTP_API", "IMPLEMENTED_BY", "HANDLED_BY",
           "IN_BUCKET"}     # object-level S3 fact -> its trigger-registered bucket
REVERSED_ = {"READS_FROM_S3", "QUERIES_DATABASE", "READS_DYNAMODB_TABLE", "READS_FILE",
             "READS_CONFIG_FROM_S3", "EXPOSES_ENDPOINT", "RECEIVES_EVENT"}
EXCLUDED = {"DEFINES", "HAS_JPA_RELATIONSHIP", "READS_ENV_VAR", "READS_SSM_PARAMETER",
            "READS_SECRET", "IMPLEMENTS", "RAISES_ERROR", "STARTS_AT", "HAS_MEMBER"}

WRITE_PREDS = {"WRITES_TO_S3", "WRITES_DATABASE", "WRITES_DYNAMODB_TABLE", "WRITES_FILE"}
READ_PREDS = {"READS_FROM_S3", "QUERIES_DATABASE", "READS_DYNAMODB_TABLE", "READS_FILE",
              "READS_CONFIG_FROM_S3"}
# Predicates whose OBJECT is an outside-world entry marker (a "button"): the
# predicate's own meaning says the world initiates here.
ENTRY_PREDS = {"EXPOSES_ENDPOINT", "RECEIVES_EVENT"}

# a chain is a JOURNEY when it shows orchestration structure (see classify())
_DEPTH_THRESHOLD = 4


def _flow_graph(quads: List[Quad]) -> Tuple[Dict[str, Set[str]], Dict[str, int]]:
    """(adjacency, strict in-degree) over flow edges.

    The adjacency is the full walkable flow (data-read reversals included — a
    chain flows THROUGH storage). The in-degree is STRICT: data-read reversals
    (store -> reader) don't count, because being fed by a passive store must not
    stop a node from rooting a journey — only being triggered by something that
    acts (a call, an invoke, a button) does."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    indeg: Dict[str, int] = defaultdict(int)
    for q in quads:
        if q.predicate in EXCLUDED:
            continue
        if q.predicate in FORWARD:
            a, b = q.subject, q.object
        elif q.predicate in REVERSED_:
            a, b = q.object, q.subject
        else:
            continue
        if b not in adj[a]:
            adj[a].add(b)
            if q.predicate not in READ_PREDS:
                indeg[b] += 1
        indeg.setdefault(a, indeg.get(a, 0))
    return adj, indeg


def _bfs(adj: Dict[str, Set[str]], start: str) -> Dict[str, int]:
    """node -> hop distance from start (start excluded)."""
    depth = {start: 0}
    dq = deque([start])
    while dq:
        n = dq.popleft()
        for m in sorted(adj.get(n, ())):
            if m not in depth:
                depth[m] = depth[n] + 1
                dq.append(m)
    depth.pop(start)
    return depth


def classify(members: Dict[str, int], quads: List[Quad]) -> str:
    """'journey' when the chain shows orchestration structure — ordered steps or
    states in the walk, a write->read handoff inside the chain, or real depth.
    Otherwise 'behavior' (a small request/response or single-step unit). A chain
    of one node is never a journey, whatever kind that node is."""
    if len(members) < 2:
        return "behavior"
    kinds = {m.split(":", 1)[0] for m in members}
    if kinds & {"State", "StateMachine"}:
        return "journey"
    in_chain = set(members)
    # an ordered sequence INSIDE the chain (workflow lineage), not merely a
    # step-typed node — one step writing somewhere is a behavior, not a journey
    if any(q.predicate == "FEEDS" and q.subject in in_chain and q.object in in_chain
           for q in quads):
        return "journey"
    if max(members.values()) >= _DEPTH_THRESHOLD:
        return "journey"
    writers = {q.object for q in quads if q.predicate in WRITE_PREDS and q.subject in in_chain}
    readers = {q.object for q in quads if q.predicate in READ_PREDS and q.subject in in_chain}
    if writers & readers:
        return "journey"
    return "behavior"


def _owner(entry: str, members: Dict[str, int], entities: Dict[str, Entity]) -> str:
    """The family a small behavior belongs to: the container of its first code
    brick — everything before the last segment of the qualified name. For an
    entry that IS a code brick, its own container."""
    first_brick = None
    if entry in entities and ":" in entry:
        first_brick = entry
    else:
        for m, _d in sorted(members.items(), key=lambda kv: (kv[1], kv[0])):
            if m in entities:
                first_brick = m
                break
    if first_brick is None:
        return entry
    _kind, qual = first_brick.split(":", 1)
    return qual.rsplit(".", 1)[0] if "." in qual else qual


# Entity types that ARE declared front doors: the wiring/workflow passes emit
# these only from an actual orchestration definition (a state-machine file, a
# workflow file) — the definition itself is the world's declared trigger.
_DOOR_TYPES = {"StateMachine", "WorkflowFile"}


def extract_journeys(qf: QuadFile) -> Tuple[List[Entity], List[Quad], List[str]]:
    """Returns (entities, quads, unwired). ``unwired`` is the front-door rule's
    honesty valve: an orphan whose walk LOOKS like a journey (states, ordered
    steps, depth) but that no real front door reaches is a wiring gap we haven't
    closed — reported by name, never promoted to a Journey. A missing arrow must
    surface as a visible gap, not be laundered into a fake top-level unit (the
    456 lesson: journey count must measure the app, not our blindness)."""
    adj, indeg = _flow_graph(qf.quads)
    entities_by_id = {e.id: e for e in qf.entities}
    # A journey root ACTS (subject of a flow fact) or is a BUTTON (target of an
    # exposure/event fact). A passive store is walked THROUGH, never a root.
    acting = {q.subject for q in qf.quads if q.predicate in FORWARD}
    buttons = {q.object for q in qf.quads if q.predicate in ENTRY_PREDS}
    doors = buttons | {e.id for e in qf.entities if e.type in _DOOR_TYPES}
    sources = sorted(n for n, edges in adj.items()
                     if edges and indeg.get(n, 0) == 0
                     and (n in acting or n in buttons))

    # SUBSUMPTION: a chain whose members all lie inside another chain is not its
    # own journey — it is a stretch of the bigger one. This is what keeps passive
    # inputs (a table only ever read, a config object) from spawning duplicate
    # "journeys": their walk is a sub-walk of the intake that reaches them. The
    # entry itself is not required to appear in the bigger chain (nothing flows
    # INTO a read-only table, yet its whole walk is downstream of the intake).
    # Equal chains keep exactly one root, chosen by id order — deterministic.
    walks = {entry: _bfs(adj, entry) for entry in sources}
    def _covered(entry, members) -> bool:
        mine = set(members)
        for other, o_members in walks.items():
            if other == entry:
                continue
            # a DOOR is never subsumed by a non-door walk: an orphan fragment
            # that happens to reach everything a real trigger reaches must not
            # displace the trigger as the unit's identity
            if entry in doors and other not in doors:
                continue
            full_other = set(o_members) | {other}
            if mine <= full_other:
                if set(o_members) == mine and not (set(members) | {entry}) <= full_other:
                    # same walk, different roots: keep the smaller id
                    if entry < other:
                        continue
                return True
        return False
    subsumed = {entry for entry, members in walks.items() if _covered(entry, members)}

    out_entities: List[Entity] = []
    out_quads: List[Quad] = []
    groups: Dict[str, List[str]] = defaultdict(list)
    unwired: List[str] = []

    for entry in sources:
        if entry in subsumed:
            continue
        members = walks[entry]
        if not members:
            continue
        kind = classify(members, qf.quads)
        if kind == "behavior":
            groups[_owner(entry, members, entities_by_id)].append(entry)
            continue
        # FRONT-DOOR RULE — only a real trigger may root a JOURNEY. A journey-
        # shaped walk rooted anywhere else is a fragment of a bigger route whose
        # incoming arrow we failed to read: report it, never promote it.
        if entry not in doors:
            unwired.append(entry)
            continue
        jid = f"Journey:{entry}"
        # name == id: the name IS the join key. Everything downstream (KB inventory,
        # spec lookup, coverage) matches on this string — a pretty summary here broke
        # the whole chain once (issue C1). The path itself lives in the edges.
        out_entities.append(Entity(
            id=jid, type="Journey", name=jid,
            language="journey", source=Source("", None, None)))
        out_quads.append(Quad(jid, "STARTS_AT", entry, True, 1.0, "", None,
                              language="journey"))
        for m, d in sorted(members.items(), key=lambda kv: (kv[1], kv[0])):
            # Membership of a still-blank node is evidence of a HOLE, not a
            # fact — carry the doubt (study S4: the journey pass was re-stamping
            # symbolic members at full confidence).
            sym = "${" in m
            out_quads.append(Quad(jid, "HAS_MEMBER", m, not sym,
                                  0.5 if sym else 1.0, "", d, language="journey"))

    for owner, entries in sorted(groups.items()):
        gid = f"BehaviorGroup:{owner}"
        out_entities.append(Entity(
            id=gid, type="BehaviorGroup", name=gid,
            language="journey", source=Source("", None, None)))
        for entry in sorted(entries):
            out_quads.append(Quad(gid, "HAS_MEMBER", entry, True, 1.0, "", 0,
                                  language="journey"))
            for m, d in sorted(_bfs(adj, entry).items(), key=lambda kv: (kv[1], kv[0])):
                sym = "${" in m
                out_quads.append(Quad(gid, "HAS_MEMBER", m, not sym,
                                      0.5 if sym else 1.0, "", d, language="journey"))
    return out_entities, out_quads, sorted(unwired)
