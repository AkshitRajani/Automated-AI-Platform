"""Config / .env loading."""
from __future__ import annotations

import os
from pathlib import Path

from scoring.config import ScoringConfig, apply_python_path, load_env_file


def test_scoring_root_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SCORING_ROOT", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    root = tmp_path / "scoring_root"
    root.mkdir()
    env = tmp_path / ".env"
    env.write_text(f"SCORING_ROOT={root}\n", encoding="utf-8")
    load_env_file(env)
    cfg = ScoringConfig.load(env)
    assert Path(cfg.scoring_root) == root.resolve()


def test_pythonpath_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SCORING_ROOT", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    root = tmp_path / "via_pythonpath"
    root.mkdir()
    env = tmp_path / ".env"
    env.write_text(f"PYTHONPATH={root}\n", encoding="utf-8")
    load_env_file(env)
    cfg = ScoringConfig.load(env)
    assert Path(cfg.scoring_root) == root.resolve()


def test_apply_python_path_inserts_root(monkeypatch, tmp_path):
    monkeypatch.delenv("SCORING_ROOT", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    root = tmp_path / "scoring"
    root.mkdir()
    env = tmp_path / ".env"
    env.write_text(f"SCORING_ROOT={root}\n", encoding="utf-8")
    load_env_file(env)
    applied = apply_python_path()
    assert applied == root.resolve()
    assert str(root.resolve()) in __import__("sys").path


def test_load_env_file_sets_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("SCORING_GOLDEN_ZIP", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "SCORING_GOLDEN_ZIP=C:\\manual.zip\n"
        "SCORING_GENERATED_ZIP=C:\\generated.zip\n"
        "SCORING_OUTPUT_DIR=C:\\out\n"
        "SCORING_THRESHOLD=0.55\n"
        "SCORING_OPEN=true\n",
        encoding="utf-8",
    )
    load_env_file(env)
    cfg = ScoringConfig.load(env)
    assert cfg.golden_zip.endswith("manual.zip")
    assert cfg.generated_zip.endswith("generated.zip")
    assert cfg.output_dir.endswith("out")
    assert cfg.threshold == 0.55
    assert cfg.open_report is True


def test_existing_env_not_overwritten_by_file(monkeypatch, tmp_path):
    monkeypatch.setenv("SCORING_GOLDEN_ZIP", "from_shell.zip")
    env = tmp_path / ".env"
    env.write_text("SCORING_GOLDEN_ZIP=from_file.zip\n", encoding="utf-8")
    load_env_file(env)
    cfg = ScoringConfig.load(env)
    assert cfg.golden_zip == "from_shell.zip"
