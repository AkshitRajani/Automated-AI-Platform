"""Tests for zip-based standalone scoring."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scoring.standalone import run_from_zips
from scoring.zip_input import ZipInputError, extract_feature_zip


def _zip_features(folder: Path, dest_zip: Path) -> None:
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in folder.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(folder))


FEATURE = (
    "Feature: Login\n"
    "  Scenario: User signs in with valid credentials\n"
    "    When the user submits valid credentials\n"
    "    Then the user is logged in\n"
)


def test_extract_feature_zip(tmp_path):
    feat_dir = tmp_path / "features"
    feat_dir.mkdir()
    (feat_dir / "login.feature").write_text(FEATURE, encoding="utf-8")
    archive = tmp_path / "manual.zip"
    _zip_features(feat_dir, archive)
    out = tmp_path / "out"
    root = extract_feature_zip(archive, out)
    assert list(root.rglob("*.feature"))


def test_extract_rejects_empty_zip(tmp_path):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "no features")
    with pytest.raises(ZipInputError, match="No .feature"):
        extract_feature_zip(archive, tmp_path / "out")


def test_run_from_zips_writes_json_and_html(tmp_path):
    golden_dir = tmp_path / "golden" / "features"
    gen_dir = tmp_path / "gen" / "features"
    golden_dir.mkdir(parents=True)
    gen_dir.mkdir(parents=True)
    (golden_dir / "login.feature").write_text(FEATURE, encoding="utf-8")
    (gen_dir / "login.feature").write_text(FEATURE, encoding="utf-8")

    golden_zip = tmp_path / "golden.zip"
    gen_zip = tmp_path / "generated.zip"
    _zip_features(golden_dir, golden_zip)
    _zip_features(gen_dir, gen_zip)

    out = tmp_path / "reports"
    result = run_from_zips(golden_zip, gen_zip, output_dir=out)

    assert result.json_path.is_file()
    assert result.html_path.is_file()
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert "simplified" in payload
    assert "detailed" in payload
    assert result.report.matched_behaviors == 1
    assert "score" in result.html_path.read_text(encoding="utf-8").lower()


def test_run_from_zips_reads_md_inside_golden_zip(tmp_path):
    """Manual zip may mix .feature + .md; md becomes requirements input."""
    golden_dir = tmp_path / "golden"
    gen_dir = tmp_path / "gen"
    golden_dir.mkdir()
    gen_dir.mkdir()
    (golden_dir / "login.feature").write_text(FEATURE, encoding="utf-8")
    (gen_dir / "login.feature").write_text(FEATURE, encoding="utf-8")
    (golden_dir / "unit_spec.md").write_text(
        "## User Stories\n\n"
        "### US-1 Login\n\n"
        "1. Given a user When they sign in Then they are logged in\n",
        encoding="utf-8",
    )

    golden_zip = tmp_path / "golden.zip"
    gen_zip = tmp_path / "generated.zip"
    _zip_features(golden_dir, golden_zip)
    _zip_features(gen_dir, gen_zip)

    result = run_from_zips(golden_zip, gen_zip, output_dir=tmp_path / "reports")
    assert result.requirements_dir is not None
    assert result.report.has_requirements
    assert result.report.input_integrity is not None
    assert result.report.input_integrity["requirement_files"] >= 1


def test_folder_score_reads_md_beside_manual_features(tmp_path, monkeypatch):
    from scoring.score import score

    monkeypatch.setenv("SCORING_PROFILING_MODE", "regex")
    golden = tmp_path / "manual"
    gen = tmp_path / "generated"
    golden.mkdir()
    gen.mkdir()
    (golden / "login.feature").write_text(FEATURE, encoding="utf-8")
    (gen / "login.feature").write_text(FEATURE, encoding="utf-8")
    (golden / "spec.md").write_text(
        "## Consolidated Requirements\n\n"
        "- The system shall authenticate valid users\n",
        encoding="utf-8",
    )
    report = score(str(golden), str(gen), threshold=0.5)
    assert report.has_requirements
