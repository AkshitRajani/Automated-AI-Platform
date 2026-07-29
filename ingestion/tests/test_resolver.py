"""
Resolver hardening tests — the bindings loader must never glob the working
directory, never half-load a non-bindings file, and never pass non-string
values through to the Postgres writer.
"""
import os

import yaml

from ingestion.parsers.resolver import Resolver


def test_empty_source_means_no_bindings(tmp_path, monkeypatch):
    """Unset/empty bindings source -> no bindings — even with YAMLs in the cwd."""
    (tmp_path / "stray.yaml").write_text(yaml.safe_dump({"A": "1"}))
    monkeypatch.chdir(tmp_path)
    r = Resolver("")
    assert not r.has_bindings


def test_quad_shaped_file_is_rejected_whole(tmp_path):
    """A quad file dropped in the bindings folder must be skipped, not eaten as
    five 'bindings' with dict values (the crash the checkpoint caught)."""
    quadish = {"metadata": {"app_id": "x"}, "summary": {"n": 1},
               "entities": [{"id": "a"}], "quads": [{"s": 1}], "notes": []}
    (tmp_path / "quads.yaml").write_text(yaml.safe_dump(quadish))
    r = Resolver(str(tmp_path))
    assert not r.has_bindings


def test_valid_bindings_load_and_resolve(tmp_path):
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(
        {"log_path": "s3://real-bucket/logs", "Loan Past Due Threshold": 24}))
    r = Resolver(str(tmp_path))
    assert r.binding_count == 2
    resolved, ok = r.resolve("${log_path}/today")
    assert ok and resolved == "s3://real-bucket/logs/today"
    resolved, ok = r.resolve("${Loan Past Due Threshold}")
    assert ok and resolved == "24"          # scalars coerced to str


def test_mixed_file_loads_scalars_skips_nested(tmp_path):
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(
        {"GOOD": "value", "BAD": {"nested": "map"}, "ALSO_BAD": ["list"]}))
    r = Resolver(str(tmp_path))
    assert r.bindings == {"GOOD": "value"}
    assert all(isinstance(v, str) for v in r.bindings.values())


def test_endpoint_uniqueness_includes_http_method():
    """Schema regression: GET/PUT/DELETE on one path are three endpoints. The
    unique key must cover the method (the old key silently dropped verbs)."""
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
    with open(schema_path) as fh:
        schema = fh.read()
    assert "UNIQUE (app_id, kind, path_template)" not in schema
    assert "uq_endpoints_app_kind_method_path" in schema
    assert "COALESCE(http_method, '')" in schema


def test_merged_worksheet_beats_repo_file():
    """doc 10: quad-file bindings merge UNDER the worksheet — a human beats a file."""
    from ingestion.parsers.resolver import Resolver
    sheet = Resolver("")
    sheet.bindings = {"K": "human-said-this"}
    merged = sheet.merged({"K": "repo-said-this", "ONLY_REPO": "repo-value"})
    assert merged.resolve("${K}") == ("human-said-this", True)
    assert merged.resolve("${ONLY_REPO}") == ("repo-value", True)
    assert sheet.bindings == {"K": "human-said-this"}   # original untouched
