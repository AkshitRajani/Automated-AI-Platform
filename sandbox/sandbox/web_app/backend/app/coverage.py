"""Coverage view for the UI's Spec panel.

If profiles/<P>/COVERAGE.md exists, parse the three-color summary table out of it
(Section, REAL, STUB, GAP, Verdict). Otherwise derive a structural checklist
from spec.yaml so the UI always has something to show.
"""
from __future__ import annotations
import re

from .settings import profile_dir
from .topology import read_spec


def build_coverage(profile: str) -> dict:
    pdir = profile_dir(profile)
    md = pdir / "COVERAGE.md"
    if md.exists():
        rows = _parse_table(md.read_text())
        if rows:
            return {"profile": profile, "source": "COVERAGE.md", "rows": rows}
    return {"profile": profile, "source": "derived", "rows": _derive_from_spec(profile)}


def _parse_table(text: str) -> list[dict]:
    """Pull rows out of the three-color summary markdown table."""
    lines = text.splitlines()
    rows: list[dict] = []
    in_table = False
    for line in lines:
        if line.strip().startswith("| Section"):
            in_table = True
            continue
        if in_table:
            if not line.strip().startswith("|"):
                if rows:
                    break
                continue
            if re.match(r"^\|\s*-+", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 5:
                continue
            section, real, stub, gap, verdict = cells[:5]
            if section.lower().startswith("section"):
                continue
            rows.append({
                "section": section,
                "real": real,
                "stub": stub,
                "gap": gap,
                "verdict": verdict,
            })
    return rows


def _derive_from_spec(profile: str) -> list[dict]:
    spec = read_spec(profile)
    counts = [
        ("lambdas", len(spec.get("lambdas", []) or [])),
        ("step_functions", len(spec.get("step_functions", []) or [])),
        ("dynamodb", len(spec.get("dynamodb", []) or [])),
        ("s3_buckets", len(spec.get("s3_buckets", []) or [])),
        ("glue_jobs", len(spec.get("glue_jobs", []) or [])),
        ("behavioral_contracts", len(spec.get("behavioral_contracts", []) or [])),
        ("data_flows", len(spec.get("data_flows", []) or [])),
        ("control_flows", len(spec.get("control_flows", []) or [])),
        ("business_rules", len(spec.get("business_rules", []) or [])),
        ("tickets", len(spec.get("tickets", []) or [])),
    ]
    return [
        {"section": k, "real": str(n), "stub": "", "gap": "", "verdict": "present" if n else "missing"}
        for k, n in counts
    ]
