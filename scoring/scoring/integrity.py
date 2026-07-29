"""
Input integrity audit — verify no silent data loss across the three scoring inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from .models import Scenario
from .parse import load_features
from .requirements.extract import extract_items_from_doc
from .requirements.parse import load_requirements


@dataclass
class InputIntegrityReport:
    manual_files: int = 0
    manual_scenarios: int = 0
    manual_steps: int = 0
    manual_outline_scenarios: int = 0
    generated_files: int = 0
    generated_scenarios: int = 0
    generated_steps: int = 0
    generated_outline_scenarios: int = 0
    requirement_files: int = 0
    requirement_bytes: int = 0
    requirement_sections: int = 0
    requirement_items_extracted: int = 0
    requirement_md_files: int = 0
    profiling_mode: str = "regex"
    strict_matching: bool = False
    requirement_strategy: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "manual_files": self.manual_files,
            "manual_scenarios": self.manual_scenarios,
            "manual_steps": self.manual_steps,
            "manual_outline_scenarios": self.manual_outline_scenarios,
            "generated_files": self.generated_files,
            "generated_scenarios": self.generated_scenarios,
            "generated_steps": self.generated_steps,
            "generated_outline_scenarios": self.generated_outline_scenarios,
            "requirement_files": self.requirement_files,
            "requirement_bytes": self.requirement_bytes,
            "requirement_sections": self.requirement_sections,
            "requirement_items_extracted": self.requirement_items_extracted,
            "requirement_md_files": self.requirement_md_files,
            "profiling_mode": self.profiling_mode,
            "strict_matching": self.strict_matching,
            "requirement_strategy": self.requirement_strategy,
            "notes": self.notes,
        }


def _count_feature_files(root: Path) -> int:
    if root.is_file():
        return 1 if root.suffix.lower() == ".feature" else 0
    return len(list(root.rglob("*.feature")))


def _audit_bdd(
    scenarios: List[Scenario],
    *,
    files: int,
) -> dict:
    return {
        "files": files,
        "scenarios": len(scenarios),
        "steps": sum(len(s.steps) for s in scenarios),
        "outline_scenarios": sum(1 for s in scenarios if s.is_outline),
    }


def build_integrity_report(
    *,
    manual: Union[str, List[Scenario], None] = None,
    generated: Union[str, List[Scenario], None] = None,
    requirements: Union[str, List[str], None] = None,
    req_profiles_count: int = 0,
    profiling_mode: str = "regex",
    strict_matching: bool = False,
    requirement_strategy: str = "",
) -> InputIntegrityReport:
    report = InputIntegrityReport(
        profiling_mode=profiling_mode,
        strict_matching=strict_matching,
        requirement_strategy=requirement_strategy,
    )

    if manual is not None:
        if isinstance(manual, list):
            manual_scenarios = manual
            manual_files = len({s.feature_file for s in manual_scenarios})
        else:
            root = Path(manual)
            manual_scenarios = load_features(root)
            manual_files = _count_feature_files(root)
        stats = _audit_bdd(manual_scenarios, files=manual_files)
        report.manual_files = stats["files"]
        report.manual_scenarios = stats["scenarios"]
        report.manual_steps = stats["steps"]
        report.manual_outline_scenarios = stats["outline_scenarios"]

    if generated is not None:
        if isinstance(generated, list):
            gen_scenarios = generated
            gen_files = len({s.feature_file for s in gen_scenarios})
        else:
            root = Path(generated)
            gen_scenarios = load_features(root)
            gen_files = _count_feature_files(root)
        stats = _audit_bdd(gen_scenarios, files=gen_files)
        report.generated_files = stats["files"]
        report.generated_scenarios = stats["scenarios"]
        report.generated_steps = stats["steps"]
        report.generated_outline_scenarios = stats["outline_scenarios"]

    if requirements is not None:
        docs = load_requirements(requirements)
        report.requirement_files = len(docs)
        report.requirement_md_files = sum(
            1 for d in docs if str(d.get("_source_file", "")).lower().endswith(".md")
        )
        report.requirement_bytes = sum(int(d.get("_byte_count") or 0) for d in docs)
        report.requirement_sections = sum(len(d.get("sections") or {}) for d in docs)
        extracted = sum(len(extract_items_from_doc(d)) for d in docs)
        if profiling_mode == "agent":
            from .requirements.extract import extract_items_for_agent
            agent_items = sum(len(extract_items_for_agent(d)) for d in docs)
            report.requirement_items_extracted = agent_items
            if agent_items != extracted:
                report.notes.append(
                    f"Agent Bedrock labelling uses {agent_items} compact item(s); "
                    f"full tier extract yields {extracted}."
                )
        else:
            report.requirement_items_extracted = extracted
        if req_profiles_count and req_profiles_count != report.requirement_items_extracted:
            report.notes.append(
                f"Profiled {req_profiles_count} requirement item(s) from "
                f"{report.requirement_items_extracted} extracted."
            )
        for doc in docs:
            raw = doc.get("raw_text")
            if raw is not None:
                joined = "\n".join(str(v) for v in (doc.get("sections") or {}).values())
                if raw.strip() and joined.strip() and raw.strip() not in joined:
                    report.notes.append(
                        f"{doc.get('_source_file')}: raw_text preserved alongside sections."
                    )

    return report
