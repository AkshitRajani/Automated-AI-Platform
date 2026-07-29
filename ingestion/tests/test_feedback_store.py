"""
Tests for the feedback store.

The pure layer (FeedbackRecord validation) needs no DB driver and always runs. The DB
path is exercised against a fake connection that records SQL — same pattern as the
requirements-writer tests — so lifecycle semantics (insert, open-only reads, status
moves, stale-marking that never deletes) are asserted without a live Postgres.
"""
from __future__ import annotations

import pytest

from ingestion.writers.feedback_store import (ACTIONS, ARTIFACTS, STATUSES,
                                              FeedbackRecord, FeedbackStore)


def _rec(**over):
    base = dict(app_id="DCFO", unit="Method:com.x.LoanController.createLoan",
                artifact="test", action="reject", comment="asserts on hardcoded total",
                reviewer="alice", code_version="v1")
    base.update(over)
    return FeedbackRecord(**base)


# --- pure layer: FeedbackRecord validation -----------------------------------

def test_valid_record_constructs():
    r = _rec()
    assert r.status == "open"
    assert r.action in ACTIONS and r.artifact in ARTIFACTS and r.status in STATUSES


def test_approve_needs_no_comment():
    r = _rec(action="approve", comment="")
    assert r.action == "approve"


@pytest.mark.parametrize("action", ["reject", "comment"])
def test_reject_and_comment_require_words(action):
    with pytest.raises(ValueError):
        _rec(action=action, comment="   ")


def test_bad_enums_refused():
    with pytest.raises(ValueError):
        _rec(artifact="doc")
    with pytest.raises(ValueError):
        _rec(action="dislike")
    with pytest.raises(ValueError):
        _rec(status="pending")


def test_app_and_unit_required():
    with pytest.raises(ValueError):
        _rec(app_id=" ")
    with pytest.raises(ValueError):
        _rec(unit="")


# --- DB path: fake connection --------------------------------------------------

class _FakeCursor:
    def __init__(self, log, rows):
        self.log = log
        self._rows = rows
        self.rowcount = len(rows) if rows else 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self, rows=None):
        self.log: list = []
        self.rows = rows or []
        self.commits = 0
        self.autocommit = None

    def cursor(self):
        return _FakeCursor(self.log, self.rows)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_store_requires_conn_or_config():
    with pytest.raises(ValueError):
        FeedbackStore()


def test_add_inserts_and_commits():
    conn = _FakeConn(rows=[(7,)])
    store = FeedbackStore(conn=conn)
    new_id = store.add(_rec())
    assert new_id == 7
    sql, params = conn.log[0]
    assert "INSERT INTO app_feedback" in sql and "RETURNING id" in sql
    assert params[0] == "DCFO" and params[3] == "reject"
    assert conn.commits == 1


def test_add_stores_empty_strings_as_null():
    conn = _FakeConn(rows=[(1,)])
    FeedbackStore(conn=conn).add(_rec(action="approve", comment="", reviewer="", code_version=""))
    _, params = conn.log[0]
    # target, comment, reviewer, code_version all NULL when empty
    assert params[4] is None and params[5] is None and params[6] is None and params[7] is None


def test_target_validated_and_stored():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        _rec(target="vibe")                       # not in the vocabulary
    conn = _FakeConn(rows=[(1,)])
    FeedbackStore(conn=conn).add(_rec(target="contract"))
    _, params = conn.log[0]
    assert params[4] == "contract"


def test_open_records_filters_open_only_and_narrows():
    row = (3, "DCFO", "Method:m", "spec", "comment", "contract", "clarify output", "bob", "v1", "open")
    conn = _FakeConn(rows=[row])
    got = FeedbackStore(conn=conn).open_records("DCFO", unit="Method:m", artifact="spec")
    sql, params = conn.log[0]
    assert "status = 'open'" in sql and "unit = %s" in sql and "artifact = %s" in sql
    assert "ORDER BY created_at" in sql
    assert params == ("DCFO", "Method:m", "spec")
    assert len(got) == 1 and got[0].id == 3 and got[0].action == "comment"


def test_open_records_rejects_bad_artifact():
    with pytest.raises(ValueError):
        FeedbackStore(conn=_FakeConn()).open_records("DCFO", artifact="doc")


def test_mark_moves_status_and_counts():
    conn = _FakeConn(rows=[(1,), (2,)])       # rowcount = 2 via fake
    n = FeedbackStore(conn=conn).mark([1, 2], "applied")
    sql, params = conn.log[0]
    assert "UPDATE app_feedback SET status = %s" in sql
    assert params == ("applied", [1, 2])
    assert n == 2 and conn.commits == 1


def test_mark_refuses_unknown_status_and_empty_ids():
    store = FeedbackStore(conn=_FakeConn())
    with pytest.raises(ValueError):
        store.mark([1], "done")
    assert store.mark([], "applied") == 0     # no-op, no SQL


def test_mark_stale_is_update_never_delete():
    conn = _FakeConn(rows=[(1,)])
    n = FeedbackStore(conn=conn).mark_stale("DCFO", ["Method:m", ""])
    sql, params = conn.log[0]
    assert "UPDATE app_feedback SET status = 'stale'" in sql
    assert "DELETE" not in sql
    assert params == ("DCFO", ["Method:m"])   # empty unit filtered out
    assert n == 1
