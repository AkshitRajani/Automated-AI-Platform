"""
Neptune lineage walk — the backend behind the ``kb_graph`` tool.

This walks the dependency/lineage graph from a node ("which table does
``late_fee_handler`` read?", "who calls this endpoint?") — the intentional
traversal that lets the agent disambiguate and recover when a flat lookup is
empty.

Reality for slice 1: Neptune is **optional**. When it is not configured (no
endpoint in ``.env``) the client degrades to an actionable empty result rather
than failing — the agent then leans on ``kb_query`` facts instead.

Testability: the hop orchestration (expand frontier, dedup, bound by ``limit``)
is pure Python and unit-tested with a fake executor. The Gremlin string building
is a separate pure function, also tested. Only the live boto3 call is untested
here (no live Neptune in this environment).

Node-id / edge scheme is bound to ``ingestion/graph/neptune_writer.py``:
nodes carry a ``name`` property and an ``app_id`` property; edge label = the
quad predicate (e.g. ``QUERIES_DATABASE``, ``INVOKES_LAMBDA``).
"""
from __future__ import annotations

from typing import List, Literal, Optional, Protocol

from pydantic import BaseModel

Direction = Literal["out", "in", "both"]

# Edge labels the ingestion writer actually emits (bound to PREDICATE_ROUTES +
# structural edges). Used for validation/help text, not to restrict the agent.
KNOWN_RELATIONS = [
    "CONTAINS", "DEFINES", "EXPOSES_ENDPOINT", "CALLS_HTTP_API", "INVOKES_LAMBDA",
    "INVOKES_STEP_FUNCTION", "PUBLISHES_TO_SNS", "WRITES_DATABASE", "QUERIES_DATABASE",
    "READS_DYNAMODB_TABLE", "WRITES_DYNAMODB_TABLE", "READS_FROM_S3", "WRITES_TO_S3",
    "READS_CONFIG_FROM_S3", "HAS_JPA_RELATIONSHIP", "READS_SSM_PARAMETER", "READS_ENV_VAR",
]


class Edge(BaseModel):
    src: str
    relation: str
    dst: str
    dst_kind: str


class GraphResult(BaseModel):
    start: str
    edges: List[Edge] = []
    note: Optional[str] = None


# --- Gremlin/Neptune query builder — kept for reference/rollback, no longer
# wired up by GraphClient.from_env() below (replaced by build_cypher/Neo4j).
# def build_gremlin(node: str, relations: List[str], direction: Direction,
#                   app_id: str, limit: int) -> str:
#     """Build a single-hop Gremlin query that returns projected edges.
#
#     Matched-by ``name`` + ``app_id`` (the writer stores both as vertex
#     properties). All values are passed as literals here for the query *string*;
#     the boto client sends them as the query body (Neptune has no SQL-style
#     injection surface, and ``app_id``/``name`` are internal canonical tokens).
#     """
#     step = {"out": "outE", "in": "inE", "both": "bothE"}[direction]
#     vstep = {"out": "inV", "in": "outV", "both": "otherV"}[direction]
#     rel_args = ",".join(f"'{r}'" for r in relations) if relations else ""
#     return (
#         f"g.V().has('app_id','{app_id}').has('name','{node}')"
#         f".{step}({rel_args}).as('e').{vstep}().as('v')"
#         f".select('e','v').by(label).by(valueMap('name'))"
#         f".limit({limit})"
#     )


def build_cypher(node: str, relations: List[str], direction: Direction,
                 app_id: str, limit: int) -> str:
    """Build a single-hop Cypher query that returns projected edges — the
    Neo4j equivalent of the Gremlin builder above. Matched by ``name`` +
    ``app_id`` (Neo4jWriter stores both as node properties, same scheme).
    ``app_id``/``node`` are internal canonical tokens (never user-supplied
    text), same trust boundary as the Gremlin version — still passed as
    parameters here rather than string-interpolated, for defense in depth.
    """
    pattern = {
        "out": "(s)-[e]->(v)",
        "in": "(s)<-[e]-(v)",
        "both": "(s)-[e]-(v)",
    }[direction]
    rel_filter = ""
    if relations:
        rel_filter = ":" + "|".join(relations)
        pattern = pattern.replace("[e]", f"[e{rel_filter}]")
    return (
        f"MATCH {pattern.replace('(s)', '(s {app_id: $app_id, name: $node})')} "
        f"RETURN type(e) AS e, v.name AS name LIMIT {int(limit)}"
    )


class GremlinExecutor(Protocol):
    """Anything that can run one hop and return normalized edge dicts:
    ``[{'src','relation','dst','dst_kind'}, ...]``."""
    def one_hop(self, node: str, relations: List[str], direction: Direction,
                app_id: str, limit: int) -> List[dict]: ...


# --- Neptune executor — kept for reference/rollback, no longer instantiated
# by GraphClient.from_env() below (replaced by _Neo4jExecutor).
# class _NeptuneExecutor:
#     """Live executor over Neptune via boto3 ``neptunedata`` (Gremlin)."""
#
#     def __init__(self, settings: dict):
#         self._settings = settings
#
#     def one_hop(self, node, relations, direction, app_id, limit) -> List[dict]:
#         import boto3  # lazy — only when Neptune is actually configured
#         gremlin = build_gremlin(node, relations, direction, app_id, limit)
#         client = boto3.client(
#             "neptunedata",
#             endpoint_url=f"https://{self._settings['endpoint']}:{self._settings['port']}",
#             region_name=self._settings.get("region", "us-east-1"),
#         )
#         raw = client.execute_gremlin_query(gremlinQuery=gremlin)
#         return _parse_neptune_result(node, direction, raw)
#
#
# def _parse_neptune_result(node: str, direction: Direction, raw: dict) -> List[dict]:
#     """Normalize Neptune's ``execute_gremlin_query`` payload to edge dicts.
#     Defensive: shape varies, so unknown payloads yield no edges rather than raise."""
#     out: List[dict] = []
#     data = (raw or {}).get("result", {}).get("data", [])
#     for item in data:
#         try:
#             relation = item.get("e")
#             v = item.get("v", {})
#             name = v.get("name")
#             dst = name[0] if isinstance(name, list) else name
#             if relation and dst:
#                 out.append({"src": node, "relation": str(relation),
#                             "dst": str(dst), "dst_kind": ""})
#         except Exception:
#             continue
#     return out


class _Neo4jExecutor:
    """Live executor over Neo4j via the official ``neo4j`` driver (Cypher).
    Replaces ``_NeptuneExecutor`` — same one-hop interface, no AWS involved."""

    def __init__(self, settings: dict):
        self._settings = settings
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase  # lazy — only when Neo4j is actually configured
            self._driver = GraphDatabase.driver(
                self._settings["uri"],
                auth=(self._settings.get("user", "neo4j"), self._settings.get("password", "")),
            )
        return self._driver

    def one_hop(self, node, relations, direction, app_id, limit) -> List[dict]:
        cypher = build_cypher(node, relations, direction, app_id, limit)
        driver = self._get_driver()
        with driver.session() as session:
            raw = session.run(cypher, app_id=app_id, node=node).data()
        return _parse_neo4j_result(node, raw)


def _parse_neo4j_result(node: str, raw: List[dict]) -> List[dict]:
    """Normalize Neo4j's ``session.run(...).data()`` rows to edge dicts.
    Defensive: shape varies, so unknown rows yield no edges rather than raise."""
    out: List[dict] = []
    for row in raw or []:
        try:
            relation = row.get("e")
            dst = row.get("name")
            if relation and dst:
                out.append({"src": node, "relation": str(relation),
                            "dst": str(dst), "dst_kind": ""})
        except Exception:
            continue
    return out


class GraphClient:
    """Walks the lineage graph. Pure orchestration over an injected executor."""

    def __init__(self, executor: Optional[GremlinExecutor], available: bool):
        self._executor = executor
        self.available = available

    @classmethod
    def from_env(cls) -> "GraphClient":
        # Neptune wiring — kept for reference/rollback, no longer active:
        # from coding_agent.config import neptune_settings
        # s = neptune_settings()
        # if not s.get("endpoint"):
        #     return cls(executor=None, available=False)
        # return cls(executor=_NeptuneExecutor(s), available=True)
        from coding_agent.config import neo4j_settings
        s = neo4j_settings()
        if not s.get("uri"):
            return cls(executor=None, available=False)
        return cls(executor=_Neo4jExecutor(s), available=True)

    def walk(self, start: str, relations: Optional[List[str]] = None, hops: int = 1,
             direction: Direction = "out", app_id: str = "", limit: int = 25) -> GraphResult:
        relations = relations or []
        if not app_id:
            return GraphResult(start=start, edges=[],
                               note="app_id is required to scope the graph walk; none provided.")
        if not self.available or self._executor is None:
            return GraphResult(
                start=start, edges=[],
                note="Neptune is not configured (optional for slice 1). "
                     "Use kb_query facts to ground names instead.",
            )

        hops = max(1, hops)
        frontier = [start]
        visited: set[str] = set()
        edges: List[Edge] = []
        seen_edges: set[tuple] = set()

        for _ in range(hops):
            next_frontier: List[str] = []
            for node in frontier:
                if node in visited:
                    continue
                visited.add(node)
                for row in self._executor.one_hop(node, relations, direction, app_id, limit):
                    e = Edge(src=row.get("src", node), relation=row["relation"],
                             dst=row["dst"], dst_kind=row.get("dst_kind", ""))
                    key = (e.src, e.relation, e.dst)
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    edges.append(e)
                    next_frontier.append(e.dst)
                    if len(edges) >= limit:
                        return GraphResult(start=start, edges=edges)
            frontier = next_frontier

        note = None if edges else (
            f"no edges from '{start}' in {app_id} for the given relations/direction."
        )
        return GraphResult(start=start, edges=edges, note=note)
