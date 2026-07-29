"""
Eval data model — the verdict shape of the gate cascade.

The cascade produces **no score**: its output is one bit (`deliver`) plus the
per-gate trail and, for a delivered test, a raw count of facts (mutants caught,
lines covered) used only for Pareto ordering among survivors — never a grade.

`Finding` and `Severity` are reused **verbatim** from the validator, so a gate
failure feeds the coding agent's bounded-repair loop in exactly the same shape a
static finding does. One repair format, two layers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

# The static layer's finding shape, reused as-is (eval ⊃ validator).
from validator.models import Finding, Severity  # noqa: F401  (re-exported)


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"   # not applicable here (e.g. no changed lines, nothing to mutate)


@dataclass
class GateOutcome:
    number: int                 # the design's gate number (1..7)
    name: str
    status: GateStatus
    detail: str = ""
    findings: List[Finding] = field(default_factory=list)
    data: Dict[str, int] = field(default_factory=dict)   # machine evidence (counts)

    def to_dict(self) -> dict:
        return {
            "gate": self.number,
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "findings": [f.to_dict() for f in self.findings],
            "data": self.data,
        }


@dataclass
class Verdict:
    deliver: bool
    gates: List[GateOutcome] = field(default_factory=list)
    failed_gate: Optional[int] = None
    evidence: Dict[str, int] = field(default_factory=dict)   # counts, for ranking only

    @property
    def repair_findings(self) -> List[Finding]:
        """Every finding from the failed gate — handed back to the agent verbatim."""
        out: List[Finding] = []
        for g in self.gates:
            if g.status is GateStatus.FAIL:
                out += g.findings
        return out

    def to_dict(self) -> dict:
        return {
            "deliver": self.deliver,
            "failed_gate": self.failed_gate,
            "evidence": self.evidence,
            "gates": [g.to_dict() for g in self.gates],
        }
