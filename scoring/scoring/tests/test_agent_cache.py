"""Tests for profile cache fingerprinting."""
from pathlib import Path

from scoring.agent.cache import fingerprint_paths, load_cached_profiles, save_cached_profiles


def test_fingerprint_stable_for_same_content(tmp_path: Path):
    feature = tmp_path / "demo.feature"
    feature.write_text("Feature: X\n  Scenario: Y\n", encoding="utf-8")
    fp1 = fingerprint_paths([feature])
    fp2 = fingerprint_paths([feature])
    assert fp1 == fp2


def test_fingerprint_changes_when_content_changes(tmp_path: Path):
    feature = tmp_path / "demo.feature"
    feature.write_text("Feature: X\n", encoding="utf-8")
    fp1 = fingerprint_paths([feature])
    feature.write_text("Feature: X\n  Scenario: Z\n", encoding="utf-8")
    fp2 = fingerprint_paths([feature])
    assert fp1 != fp2


def test_cache_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SCORING_PROFILE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SCORING_PROMPT_VERSION", "1")
    profiles = {"a.feature::S": {"scenario_id": "a.feature::S", "workflow_stage": "load", "intent": "positive", "actions": ["import"]}}
    save_cached_profiles("manual", "abc123", profiles)
    loaded = load_cached_profiles("manual", "abc123")
    assert loaded == profiles
    assert load_cached_profiles("manual", "wrong") is None
