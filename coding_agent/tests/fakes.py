"""
A minimal fake DB-API connection for testing KBClient without a live Postgres.

It routes each query to canned rows by the table name found in the SQL, and
records every (sql, params) pair so tests can assert the SQL is parameterized
(no input value ever interpolated into the query text).
"""
from __future__ import annotations

from typing import Dict, List, Tuple


class FakeCursor:
    def __init__(self, rows_by_table: Dict[str, List[tuple]], log: list):
        self._rows_by_table = rows_by_table
        self._log = log
        self._result: List[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: Tuple = ()):  # noqa: D401
        self._log.append((sql, params))
        # Find which fact table this query hits, and whether it's exact or LIKE.
        is_like = "ILIKE" in sql
        self._result = []
        for table, rows in self._rows_by_table.items():
            if f"FROM {table} " in sql:
                # rows is a dict: {"exact": [...], "like": [...]}
                self._result = rows["like"] if is_like else rows["exact"]
                break

    def fetchall(self):
        return list(self._result)


class FakeConn:
    def __init__(self, rows_by_table: Dict[str, dict]):
        self._rows_by_table = rows_by_table
        self.log: list = []

    def cursor(self):
        return FakeCursor(self._rows_by_table, self.log)

    def close(self):
        pass
