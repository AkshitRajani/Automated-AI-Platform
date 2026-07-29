"""
Feedback store — human-in-the-loop records in Postgres (app_feedback).

The HITL contract between components (see final_design/08_feedback_loop.md): any surface
(UI, API, a test script) records review actions here; the agents read the OPEN records for
a unit when regenerating; the pipeline marks records applied once the regenerated artifact
addresses them. The store is deliberately dumb — no interpretation, no scoring, just the
records and their lifecycle: open -> applied -> closed, or open -> stale on re-onboard.

Design notes (match the rest of ingestion):
  - **Pure layer first**: ``FeedbackRecord`` validates itself with no DB driver in sight,
    so the rules (a reject must say why; approve needs no words) are unit-testable alone.
  - **Connection injected or built from config**, same as the other writers:
    ``FeedbackStore(conn=fake)`` for tests, ``FeedbackStore(config=...)`` for real psycopg2.
  - **Lifecycle is explicit**: records never mutate their content — only ``status`` moves.
    Stale-marking on re-onboard is a bulk status change, never a delete; the audit trail
    survives.
  - **Nothing invented**: ``code_version`` is stored as given (NULL when unknown), and
    ``reviewer`` is whatever the surface supplied — the store never fabricates either.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

ARTIFACTS = ("spec", "test")
ACTIONS = ("approve", "reject", "comment")
STATUSES = ("open", "applied", "closed", "stale")
# What KIND of thing the feedback concerns (per-gap G29): typed so a correction becomes
# the right kind of reusable knowledge. Optional — untyped feedback is still valid.
TARGETS = ("behavior-scope", "payload", "contract", "data-condition", "assertion",
           "expected-result", "environment", "naming", "structure")


@dataclass
class FeedbackRecord:
    """One review action on one unit's artifact — exactly the columns ``app_feedback`` holds.

    Validates on construction: a reject or comment with no words gives the regenerating
    agent nothing to apply, so it is refused here, not discovered downstream.
    """
    app_id: str
    unit: str
    artifact: str                    # 'spec' | 'test'
    action: str                      # 'approve' | 'reject' | 'comment'
    comment: str = ""
    reviewer: str = ""
    code_version: str = ""
    target: str = ""                 # optional; one of TARGETS when set
    status: str = "open"
    id: Optional[int] = None

    def __post_init__(self):
        if not (self.app_id or "").strip():
            raise ValueError("feedback record needs an app_id")
        if not (self.unit or "").strip():
            raise ValueError("feedback record needs a unit id")
        if self.artifact not in ARTIFACTS:
            raise ValueError(f"artifact must be one of {ARTIFACTS}, got {self.artifact!r}")
        if self.action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}, got {self.action!r}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")
        if self.target and self.target not in TARGETS:
            raise ValueError(f"target must be one of {TARGETS} (or empty), got {self.target!r}")
        if self.action in ("reject", "comment") and not (self.comment or "").strip():
            raise ValueError(f"a {self.action!r} must carry a comment — the agent needs words to apply")


_COLUMNS = ("id", "app_id", "unit", "artifact", "action", "target", "comment",
            "reviewer", "code_version", "status")


def _record_from_row(row: Sequence) -> FeedbackRecord:
    """Build a record from a SELECT row in ``_COLUMNS`` order (id first)."""
    return FeedbackRecord(
        id=row[0], app_id=row[1], unit=row[2], artifact=row[3], action=row[4],
        target=row[5] or "", comment=row[6] or "", reviewer=row[7] or "",
        code_version=row[8] or "", status=row[9],
    )


class FeedbackStore:
    """Reads and writes ``app_feedback`` (records in, lifecycle updates out)."""

    def __init__(self, config: Optional[dict] = None, conn=None):
        if conn is not None:
            self.conn = conn                # injected (tests / a shared connection)
        elif config is not None:
            import psycopg2
            self.conn = psycopg2.connect(
                host=config["host"], port=config["port"], database=config["database"],
                user=config["user"], password=config["password"],
            )
        else:
            raise ValueError("FeedbackStore needs either a config or a conn")
        try:
            self.conn.autocommit = False
        except Exception:                   # some fakes don't expose autocommit
            pass

    def add(self, record: FeedbackRecord) -> Optional[int]:
        """Insert one record; returns its id (None on fakes that return no row)."""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_feedback (
                    app_id, unit, artifact, action, target, comment, reviewer,
                    code_version, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (record.app_id, record.unit, record.artifact, record.action,
                  record.target or None, record.comment or None, record.reviewer or None,
                  record.code_version or None, record.status))
            row = cur.fetchone()
        self.conn.commit()
        new_id = row[0] if row else None
        logger.info(f"  Feedback: {record.action} on {record.artifact} {record.unit} "
                    f"({record.app_id}) recorded as id={new_id}")
        return new_id

    def open_records(self, app_id: str, unit: Optional[str] = None,
                     artifact: Optional[str] = None) -> List[FeedbackRecord]:
        """Every OPEN record for an app — optionally narrowed to one unit / one artifact.
        Oldest first, so agents apply feedback in the order it was given."""
        if not app_id:
            raise ValueError("app_id is required")
        sql = f"SELECT {', '.join(_COLUMNS)} FROM app_feedback WHERE app_id = %s AND status = 'open'"
        params: list = [app_id]
        if unit is not None:
            sql += " AND unit = %s"
            params.append(unit)
        if artifact is not None:
            if artifact not in ARTIFACTS:
                raise ValueError(f"artifact must be one of {ARTIFACTS}, got {artifact!r}")
            sql += " AND artifact = %s"
            params.append(artifact)
        sql += " ORDER BY created_at, id"
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
        return [_record_from_row(r) for r in rows]

    def mark(self, ids: Sequence[int], status: str) -> int:
        """Move records to a new lifecycle status. Returns how many rows changed."""
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE app_feedback SET status = %s, updated_at = NOW()
                WHERE id = ANY(%s)
            """, (status, ids))
            changed = getattr(cur, "rowcount", 0) or 0
        self.conn.commit()
        return changed

    def mark_stale(self, app_id: str, units: Sequence[str]) -> int:
        """Re-onboard hook: OPEN feedback on changed units becomes 'stale' (needs re-review).
        A bulk status move, never a delete — the audit trail survives."""
        if not app_id:
            raise ValueError("app_id is required")
        units = [u for u in units if u]
        if not units:
            return 0
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE app_feedback SET status = 'stale', updated_at = NOW()
                WHERE app_id = %s AND status = 'open' AND unit = ANY(%s)
            """, (app_id, units))
            changed = getattr(cur, "rowcount", 0) or 0
        self.conn.commit()
        if changed:
            logger.info(f"  Feedback: {changed} open record(s) marked stale for {app_id}")
        return changed

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
