"""
Standalone scoring entry — manual, generated, and optional requirements in; reports out.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .html_report import write_html
from .models import ScoreReport
from .score import score
from .zip_input import FeatureZipPair, ZipInputError, extract_feature_zip


@dataclass
class StandaloneResult:
    report: ScoreReport
    json_path: Path
    html_path: Path
    golden_dir: Path
    generated_dir: Path
    requirements_dir: Optional[Path] = None


def run_from_zips(
    golden_zip: str | Path,
    generated_zip: str | Path,
    *,
    requirements_zip: str | Path | None = None,
    output_dir: str | Path = ".",
    threshold: float = 0.45,
    json_name: str = "score_report.json",
    html_name: str = "score_report.html",
    title: str = "BDD Behaviour Score Report",
) -> StandaloneResult:
    """Unzip archives, score, and write JSON + HTML to ``output_dir``."""
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / json_name
    html_path = out / html_name

    pair = FeatureZipPair(
        golden_zip, generated_zip, requirements_zip=requirements_zip,
    )
    with pair:
        golden_dir = pair.golden_dir
        generated_dir = pair.generated_dir
        req_dir = pair.requirements_dir
        report = score(
            golden=str(golden_dir),
            generated=str(generated_dir),
            threshold=threshold,
            requirements=str(req_dir) if req_dir else None,
        )

    payload = report.to_dict()
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    write_html(report, str(html_path), title=title)

    return StandaloneResult(
        report=report,
        json_path=json_path,
        html_path=html_path,
        golden_dir=Path(golden_dir),
        generated_dir=Path(generated_dir),
        requirements_dir=Path(req_dir) if req_dir else None,
    )


def open_html_report(html_path: str | Path) -> None:
    import webbrowser
    webbrowser.open(Path(html_path).resolve().as_uri())


def prompt_for_zip_pair() -> Tuple[Path, Path]:
    print("=" * 60)
    print("BDD SCORING — standalone mode")
    print("=" * 60)
    print()
    print("Provide two zip files:")
    print("  1. Manual (golden) feature folder")
    print("  2. Generated feature folder")
    golden = _prompt_zip_validated("Manual feature folder", kind="feature")
    generated = _prompt_zip_validated("Generated feature folder", kind="feature")
    return golden, generated


def _prompt_zip_validated(label: str, *, kind: str = "feature") -> Path:
    print()
    print(f"  {label}")
    print("  Zip your folder, then enter the full path to the .zip file.")
    while True:
        raw = input(f"  Path to {label} zip: ").strip().strip('"').strip("'")
        if not raw:
            print("  Please enter a path.")
            continue
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            print(f"  File not found: {path}")
            continue
        if not zipfile.is_zipfile(path):
            print(f"  Not a zip file: {path}")
            continue
        tmp = Path(tempfile.mkdtemp())
        try:
            if kind == "requirements":
                from .zip_input import extract_requirements_zip
                extract_requirements_zip(path, tmp / "check")
            else:
                extract_feature_zip(path, tmp / "check")
        except ZipInputError as exc:
            print(f"  {exc}")
            continue
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return path
