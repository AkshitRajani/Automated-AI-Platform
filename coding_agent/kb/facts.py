"""
Postgres fact lookups — the backend behind the ``kb_query`` tool.

This resolves a real identifier (endpoint / table / helper / parameter / S3 path
/ service invocation) from the live KB before the agent writes it into a test.
It is **pure data access**: no Strands, no LLM. It binds to the exact tables the
ingestion writer populates (see ``ingestion/writers/postgres_writer.py``).

Design notes that match reality, not the idealized doc:
  - The connection is **injected** (``KBClient(conn)``) so the logic is testable
    without a live DB; ``KBClient.from_env()`` builds the real psycopg2
    connection from the shared ``.env`` (nothing hardcoded).
  - All SQL is **parameterized** (``%s``) — query text never interpolates input.
  - The **vector path is stubbed** (no pgvector table exists yet) → facts-only.
  - ``column`` / UI-selector kinds return empty with a ``note`` flagging the gap
    (no columns table / selector table in the schema yet).
  - Empties are **actionable**: the note tells the agent to tag-and-stop, never
    invent — the anti-hallucination contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel

Kind = Literal[
    "endpoint", "table", "helper", "function", "parameter",
    "s3_path", "service_invocation", "any",
]


# --- result models (also re-exposed by the kb_query tool) -------------------

class Candidate(BaseModel):
    canonical_name: str          # real name, e.g. "POST /fees/late" or "execute_lambda"
    kind: str                    # endpoint|table|helper|parameter|s3_path|service_invocation
    detail: Optional[str] = None # http_method / kind / param_type / entity_type, when known
    provenance: str              # "app_endpoints@APP"  (table @ app_id)
    resolved: bool               # False if it's an unresolved ${...} token
    confidence: float


class GroundResult(BaseModel):
    query: str
    candidates: List[Candidate] = []
    note: Optional[str] = None   # actionable guidance when there is no exact hit


class EntityGroup(BaseModel):
    entity_type: str             # whatever type the parser recorded (WorkflowFile, …)
    count: int
    names: List[str]             # capped per type


class KBInventory(BaseModel):
    """The application's testable surface, read from the KB — for whole-app discovery."""
    app_id: str
    groups: List[EntityGroup] = []   # entities grouped by their real entity_type
    endpoints: List[str] = []        # "GET /path"
    note: Optional[str] = None


class RequirementContract(BaseModel):
    """One unit's requirement doc, read from ``app_requirements`` — what the unit is
    SUPPOSED to do, so the agent can test behaviour, not just shape/location.

    ``provenance`` / ``requirement_backed`` decide how a behaviour is treated:
      - requirement_backed=True  → a real requirement backs it; assert it as the ORACLE.
      - requirement_backed=False → code-derived; use it to choose scenarios (incl. negative
        paths) but assert only grounded shape/location and tag @needs-requirement.
    ``note`` restates that rule inline so the agent sees it on every fetch."""
    app_id: str
    unit: str
    found: bool
    unit_type: Optional[str] = None
    title: Optional[str] = None
    provenance: Optional[str] = None
    requirement_backed: bool = False
    confidence: Optional[float] = None
    grounding: Optional[str] = None
    grounded_identifiers: List[str] = []
    sections: Dict[str, str] = {}     # section name -> markdown body (the whole doc)
    # Per-section provenance: sections a reviewer corrected are 'human-confirmed' —
    # those specific sections ARE oracle-worthy even when requirement_backed is false.
    section_provenance: Dict[str, str] = {}
    note: Optional[str] = None


class ApprovedExample(BaseModel):
    """One reviewer-APPROVED artifact from the KB — style/shape guidance, not facts."""
    subject: str                      # the unit the approved artifact belongs to
    text: str                         # the approved artifact (e.g. a .feature file)


class ExamplesResult(BaseModel):
    """Approved examples for a unit — the long-term feedback channel: what a human
    already signed off on, retrieved as reference, never stuffed wholesale into context."""
    app_id: str
    unit: str
    found: bool
    examples: List[ApprovedExample] = []
    note: Optional[str] = None


def _as_list(value) -> List[str]:
    """jsonb comes back already-parsed from psycopg2, but tolerate a JSON string too."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [value]
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def _as_dict(value) -> Dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _provenance_note(requirement_backed: bool, human_sections=()) -> str:
    if requirement_backed:
        base = ("Backed by a real requirement — assert the described behaviour as the "
                "oracle (expected values), grounding every name via kb_query.")
    else:
        base = ("Code-derived (no backing requirement). Use it to choose which scenarios to "
                "write — including the negative / failure paths — but assert only the grounded "
                "shape and location (real table / S3 path / status), and tag the behavioural "
                "assertion @needs-requirement. Do not treat a code-derived behaviour as proven.")
    human = sorted(human_sections)
    if human:
        base += (" EXCEPTION — these sections were corrected/confirmed by a human reviewer "
                 "and MAY be asserted as the oracle: " + ", ".join(human) + ".")
    return base


# --- schema binding ---------------------------------------------------------

@dataclass(frozen=True)
class _Source:
    """How one ``kind`` maps onto a real fact table."""
    table: str
    name_col: str
    detail_cols: tuple[str, ...] = ()
    has_resolved: bool = False
    has_confidence: bool = False


# Bound to ingestion/writers/postgres_writer.py — these tables/columns are real.
FACT_SOURCES: dict[str, _Source] = {
    "endpoint":           _Source("app_endpoints", "path_template", ("http_method",), True, True),
    "table":              _Source("app_tables", "table_token", ("kind",), True, True),
    "helper":             _Source("app_functions", "symbol", ("entity_type", "language", "file_path"), False, False),
    "function":           _Source("app_functions", "symbol", ("entity_type", "language", "file_path"), False, False),
    "parameter":          _Source("app_parameters", "token", ("param_type",), False, False),
    "s3_path":            _Source("app_s3_paths", "path", ("kind",), True, True),
    "service_invocation": _Source("app_service_invocations", "target_arn", ("predicate",), True, True),
}

# "any" searches the distinct tables once (helper/function share app_functions).
_ANY_KINDS = ["endpoint", "table", "helper", "parameter", "s3_path", "service_invocation"]

# Kinds the schema cannot back yet — surface the gap, do not pretend.
_UNSUPPORTED = {
    "column": "no column-level table exists in the KB yet",
    "selector": "no UI-selector table exists in the KB yet",
}


class KBClient:
    """Resolves identifiers over the Postgres fact store."""

    def __init__(self, conn):
        # conn is any DB-API 2.0 connection (real psycopg2, or a fake in tests).
        self._conn = conn

    @classmethod
    def from_env(cls) -> "KBClient":
        import psycopg2  # imported lazily so tests need no driver
        from coding_agent.config import postgres_dsn_kwargs
        return cls(psycopg2.connect(**postgres_dsn_kwargs()))

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def chain_members(self, app_id: str) -> dict:
        """chain id -> the member/entry ids of that Journey or BehaviorGroup, from
        the analyzer's own HAS_MEMBER / STARTS_AT facts. Deterministic membership
        for journey-aware coverage: a brick tested through its chain is covered by
        the chain's entry, not owed its own test."""
        out: dict = {}
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT subject_id, object_id FROM quad_archive "
                "WHERE app_id = %s AND predicate IN ('HAS_MEMBER', 'STARTS_AT')",
                (app_id,),
            )
            for chain, member in cur.fetchall():
                out.setdefault(str(chain), set()).add(str(member))
        return out

    # -- whole-app discovery (the kb_inventory tool) ------------------------

    def inventory(self, app_id: str, per_type_cap: int = 100) -> KBInventory:
        """The app's full entity surface, grouped by entity_type, plus its endpoints.

        Reports whatever the parser recorded — it does not assume a fixed set of
        types, so it stays correct as the parser's vocabulary grows. The caller (the
        agent) decides which groups are testable functional units."""
        if not app_id:
            return KBInventory(app_id="", note="app_id is required.")

        groups: dict[str, List[str]] = {}
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT entity_type, symbol FROM app_functions "
                "WHERE app_id = %s ORDER BY entity_type, symbol",
                (app_id,),
            )
            for etype, symbol in cur.fetchall():
                groups.setdefault(str(etype), []).append(str(symbol))

        endpoints: List[str] = []
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT http_method, path_template FROM app_endpoints "
                "WHERE app_id = %s ORDER BY path_template",
                (app_id,),
            )
            endpoints = [f"{(m or 'ANY')} {p}" for m, p in cur.fetchall()]

        group_models = [
            EntityGroup(entity_type=t, count=len(names), names=names[:per_type_cap])
            for t, names in sorted(groups.items())
        ]
        note = None
        if not group_models and not endpoints:
            note = (f"No entities found for app_id '{app_id}'. Confirm the app is "
                    f"onboarded into the KB.")
        return KBInventory(app_id=app_id, groups=group_models,
                           endpoints=endpoints, note=note)

    # -- requirement lookup (the kb_requirements tool) ----------------------

    def requirements(self, app_id: str, unit: str) -> RequirementContract:
        """The requirement doc for one unit — what it is supposed to do.

        Exact lookup by ``(app_id, unit)`` (the agent already knows the unit id from
        kb_inventory), so no similarity search is needed. Returns ``found=False`` with
        actionable guidance when no doc exists — the agent then tests from facts and tags
        @needs-requirement rather than inventing behaviour."""
        if not app_id or not unit:
            return RequirementContract(
                app_id=app_id, unit=unit, found=False,
                note="app_id and unit are both required to fetch a requirement.",
            )
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT unit_type, title, provenance, requirement_backed, confidence, "
                "grounding, grounded_identifiers, sections, section_provenance "
                "FROM app_requirements WHERE app_id = %s AND unit = %s LIMIT 1",
                (app_id, unit),
            )
            rows = cur.fetchall()
        if not rows:
            return RequirementContract(
                app_id=app_id, unit=unit, found=False,
                note=("No requirement doc for this unit. Test from KB facts (kb_query / "
                      "kb_graph) and tag the behavioural assertions @needs-requirement; "
                      "do not invent behaviour."),
            )
        (unit_type, title, provenance, requirement_backed, confidence,
         grounding, grounded_identifiers, sections, section_provenance) = rows[0]
        backed = bool(requirement_backed)
        sec_prov = _as_dict(section_provenance)
        human = [s for s, p in sec_prov.items() if p == "human-confirmed"]
        return RequirementContract(
            app_id=app_id, unit=unit, found=True,
            unit_type=unit_type, title=title, provenance=provenance,
            requirement_backed=backed,
            confidence=float(confidence) if confidence is not None else None,
            grounding=grounding,
            grounded_identifiers=_as_list(grounded_identifiers),
            sections=_as_dict(sections),
            section_provenance=sec_prov,
            note=_provenance_note(backed, human),
        )

    def approved_examples(self, app_id: str, unit: str, limit: int = 2) -> ExamplesResult:
        """Reviewer-approved artifacts for reference — the long-term feedback channel.

        Deterministic retrieval, capped at ``limit``: an example for THIS unit first
        (exact subject match), then the app's most recent approved examples. Vector
        similarity is a later upgrade — stated, not simulated. Empty is honest: no
        approvals yet means no examples, never a fabricated one."""
        if not app_id or not unit:
            return ExamplesResult(
                app_id=app_id, unit=unit, found=False,
                note="app_id and unit are both required to fetch approved examples.",
            )
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT subject, text FROM app_embeddings "
                "WHERE app_id = %s AND kind = 'approved_example' "
                "ORDER BY (subject = %s) DESC, created_at DESC, id DESC LIMIT %s",
                (app_id, unit, int(limit)),
            )
            rows = cur.fetchall() or []
        if not rows:
            return ExamplesResult(
                app_id=app_id, unit=unit, found=False,
                note=("No reviewer-approved examples for this app yet. Write the tests "
                      "from the requirement doc and KB facts as usual."),
            )
        return ExamplesResult(
            app_id=app_id, unit=unit, found=True,
            examples=[ApprovedExample(subject=s or "", text=t or "") for s, t in rows],
            note=("Reviewer-approved artifacts — match their style and conventions. They "
                  "are REFERENCE, not facts: every name in YOUR test still needs kb_query "
                  "grounding for THIS unit."),
        )

    # -- the one public entry the tool calls --------------------------------

    def resolve(
        self,
        query: str,
        kind: str = "any",
        app_id: str = "",
        limit: int = 5,
        response_format: str = "concise",
    ) -> GroundResult:
        if not app_id:
            return GroundResult(
                query=query, candidates=[],
                note="app_id is required for grounded results; none was provided.",
            )
        if kind in _UNSUPPORTED:
            return GroundResult(
                query=query, candidates=[],
                note=f"kind='{kind}' is not yet in the KB ({_UNSUPPORTED[kind]}). "
                     f"Tag @needs-helper-source / @needs-data and stop; do not invent it.",
            )

        kinds = [kind] if kind in FACT_SOURCES else _ANY_KINDS

        exact: List[Candidate] = []
        fuzzy: List[Candidate] = []
        for k in kinds:
            src = FACT_SOURCES[k]
            exact += self._select(src, k, app_id, query, like=False,
                                  limit=limit, detailed=(response_format == "detailed"))
            fuzzy += self._select(src, k, app_id, query, like=True,
                                  limit=limit, detailed=(response_format == "detailed"))

        if exact:
            return GroundResult(query=query, candidates=exact[:limit])

        # S3 bucket names: the KB stores full object paths (``bucket/key``), so a bare
        # bucket name never matches a path exactly — but the bucket IS a real resource the
        # app uses (the KB proves it by storing objects under it). Resolve it as an exact,
        # grounded name so the grounding gate accepts it (a bucket is a legitimate thing to
        # name in a test). Not a fuzzy guess — it is backed by real stored objects.
        if "/" not in query and not query.startswith("s3://") and kind in ("s3_path", "any"):
            if self._bucket_has_objects(app_id, query):
                return GroundResult(query=query, candidates=[Candidate(
                    canonical_name=query, kind="s3_path", detail="bucket",
                    provenance=f"app_s3_paths@{app_id} (bucket)",
                    resolved=True, confidence=1.0)])

        if fuzzy:
            return GroundResult(
                query=query, candidates=fuzzy[:limit],
                note="no exact match; closest by name below — verify before use.",
            )
        return GroundResult(
            query=query, candidates=[],
            note=f"'{query}' not found in {app_id}. It is not a real name — "
                 f"tag (@needs-helper-source / @needs-data) and stop; do not invent it.",
        )

    # -- internals ----------------------------------------------------------

    def _bucket_has_objects(self, app_id: str, bucket: str) -> bool:
        """True if the KB stores any S3 object under this bucket — i.e. the bucket is a
        real resource, just recorded as full ``bucket/key`` paths rather than a standalone
        name. Handles both the bare (``bucket/…``) and ``s3://bucket/…`` stored forms."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM app_s3_paths WHERE app_id = %s "
                "AND (path LIKE %s OR path LIKE %s) LIMIT 1",
                (app_id, f"{bucket}/%", f"s3://{bucket}/%"),
            )
            return cur.fetchone() is not None

    def _select(self, src: _Source, kind: str, app_id: str, query: str,
                like: bool, limit: int, detailed: bool) -> List[Candidate]:
        cols = [src.name_col, *src.detail_cols]
        if src.has_resolved:
            cols.append("resolved")
        if src.has_confidence:
            cols.append("confidence")

        if like:
            where = f"app_id = %s AND {src.name_col} ILIKE %s"
            params = (app_id, f"%{query}%")
        else:
            where = f"app_id = %s AND {src.name_col} = %s"
            params = (app_id, query)

        sql = f'SELECT {", ".join(cols)} FROM {src.table} WHERE {where} LIMIT %s'
        with self._conn.cursor() as cur:
            cur.execute(sql, (*params, limit))
            rows = cur.fetchall()

        return [self._row_to_candidate(src, kind, app_id, cols, row, like, detailed)
                for row in rows]

    @staticmethod
    def _row_to_candidate(src: _Source, kind: str, app_id: str, cols: List[str],
                          row: tuple, fuzzy: bool, detailed: bool) -> Candidate:
        by_col = dict(zip(cols, row))
        name = str(by_col[src.name_col])

        detail = None
        if detailed or src.detail_cols:
            parts = [str(by_col[c]) for c in src.detail_cols if by_col.get(c) is not None]
            detail = " · ".join(parts) if parts else None

        resolved = bool(by_col["resolved"]) if src.has_resolved else True
        if src.has_confidence and by_col.get("confidence") is not None:
            confidence = float(by_col["confidence"])
        else:
            confidence = 1.0 if not fuzzy else 0.5

        return Candidate(
            canonical_name=name,
            kind=kind,
            detail=detail if detailed else (detail if src.detail_cols else None),
            provenance=f"{src.table}@{app_id}",
            resolved=resolved,
            confidence=confidence,
        )
