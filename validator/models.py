"""
Validator data model — Finding, Severity, Report.

A Finding is the single unit of output. It is deliberately small and JSON-serializable:
the same structure is (a) printed for a human reviewer and (b) handed back to the coding
agent verbatim so it can repair the exact line that failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List


class Severity(str, Enum):
    ERROR = "ERROR"      # the test will break or assert nothing — never deliverable
    WARNING = "WARNING"  # a smell that needs justification or review


@dataclass(frozen=True)
class Finding:
    rule: str                 # stable rule id, e.g. "duplicate-step-definition"
    severity: Severity
    file: str
    line: int
    message: str              # what is wrong, in plain English
    suggestion: str = ""      # how to fix it (read by the agent in the repair loop)
    symbol: str = ""          # the offending name / pattern, when there is one

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    files_checked: int = 0

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def ok(self) -> bool:
        """A file set passes the static gate only if there are zero ERRORs."""
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "files_checked": self.files_checked,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "findings": [f.to_dict() for f in self.findings],
        }
