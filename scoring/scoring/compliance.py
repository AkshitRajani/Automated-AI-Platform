"""
Deterministic BDD / Gherkin compliance checks — structure only, from the feature text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from .models import Scenario, Step


@dataclass
class ComplianceFinding:
    feature_file: str
    scenario: str
    rule: str
    severity: str
    message: str

    def to_dict(self) -> dict:
        return {
            "feature_file": self.feature_file,
            "scenario": self.scenario,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class ComplianceReport:
    scenarios_checked: int
    findings: List[ComplianceFinding] = field(default_factory=list)

    @property
    def compliance_pct(self) -> float:
        if self.scenarios_checked == 0:
            return 100.0
        # One point per scenario; deduct for each ERROR finding on that scenario.
        errors_by_scenario = {}
        for f in self.findings:
            if f.severity == "ERROR":
                key = (f.feature_file, f.scenario)
                errors_by_scenario[key] = errors_by_scenario.get(key, 0) + 1
        failing = len(errors_by_scenario)
        passing = self.scenarios_checked - failing
        return max(0.0, passing / self.scenarios_checked * 100.0)

    def to_dict(self) -> dict:
        return {
            "scenarios_checked": self.scenarios_checked,
            "compliance_pct": round(self.compliance_pct, 2),
            "findings": [f.to_dict() for f in self.findings],
        }


def _keyword_order_ok(steps: Sequence[Step]) -> bool:
    order = {"Given": 0, "When": 1, "Then": 2, "And": 3, "But": 3, "Step": 1}
    last = -1
    for step in steps:
        rank = order.get(step.keyword, 1)
        if rank < last and step.keyword != "And" and step.keyword != "But":
            return False
        if step.keyword in ("Given", "When", "Then"):
            last = rank
    return True


def check_scenario(scenario: Scenario) -> List[ComplianceFinding]:
    findings: List[ComplianceFinding] = []
    base = {"feature_file": scenario.feature_file, "scenario": scenario.name}

    if not scenario.name.strip():
        findings.append(ComplianceFinding(
            **base, rule="scenario-name-required", severity="ERROR",
            message="Scenario must have a non-empty name",
        ))

    keywords = [s.keyword for s in scenario.steps]
    if "Given" not in keywords:
        findings.append(ComplianceFinding(
            **base, rule="given-required", severity="ERROR",
            message="Scenario must contain at least one Given step",
        ))
    if "When" not in keywords:
        findings.append(ComplianceFinding(
            **base, rule="when-required", severity="ERROR",
            message="Scenario must contain at least one When step",
        ))
    if "Then" not in keywords:
        findings.append(ComplianceFinding(
            **base, rule="then-required", severity="ERROR",
            message="Scenario must contain at least one Then step",
        ))

    for step in scenario.steps:
        if not step.text.strip():
            findings.append(ComplianceFinding(
                **base, rule="empty-step", severity="ERROR",
                message=f"Step {step.keyword} must not be empty",
            ))

    if scenario.steps and not _keyword_order_ok(scenario.steps):
        findings.append(ComplianceFinding(
            **base, rule="keyword-order", severity="WARNING",
            message="Steps should follow Given → When → Then order",
        ))

    return findings


def check_suite(scenarios: Sequence[Scenario]) -> ComplianceReport:
    findings: List[ComplianceFinding] = []
    for scenario in scenarios:
        findings.extend(check_scenario(scenario))
    return ComplianceReport(scenarios_checked=len(scenarios), findings=findings)
