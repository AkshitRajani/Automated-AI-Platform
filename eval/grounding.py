"""
Gate 2 — Grounded. Every identifier the agent emitted is re-checked against the
KB; an unresolved name is rejected as ungrounded. This mirrors the coding agent's
own `boundary.grounding_gate`, but lives in the eval so the cascade owns the full
verdict and the same check can run independently of the agent.

The resolver is **injected** (a `Resolver` Protocol), so the real
`coding_agent.kb.facts.KBClient` satisfies it structurally and tests use a fake —
no DB needed. When no resolver is supplied the gate is SKIP, not PASS: grounding
is unknown, never assumed.
"""
from __future__ import annotations

from typing import Optional, Protocol, Sequence, Tuple

from .models import Finding, GateOutcome, GateStatus, Severity


class Resolver(Protocol):
    def resolve(self, query: str, kind: str = "any", app_id: str = "", limit: int = 10): ...


def check_grounding(identifiers: Sequence[Tuple[str, str]],
                    app_id: str,
                    resolver: Optional[Resolver]) -> GateOutcome:
    if resolver is None:
        return GateOutcome(2, "Grounded", GateStatus.SKIP,
                           "no KB resolver supplied — grounding not checked "
                           "(pass a KBClient, or --names on the CLI)")

    findings = []
    for name, kind in identifiers:
        result = resolver.resolve(name, kind=kind or "any", app_id=app_id, limit=10)
        candidates = getattr(result, "candidates", None) or []
        confirmed = any(
            getattr(c, "canonical_name", None) == name and getattr(c, "resolved", True)
            for c in candidates
        )
        if not confirmed:
            findings.append(Finding(
                rule="ungrounded-identifier", severity=Severity.ERROR,
                file="<bundle>", line=0, symbol=name,
                message=(f"'{name}' ({kind}) was emitted but is not a resolved name "
                         f"in the KB for {app_id} — ungrounded"),
                suggestion=("use a real name from the KB, or tag @needs-helper-source "
                            "and stop; never invent it")))

    if findings:
        return GateOutcome(2, "Grounded", GateStatus.FAIL,
                           f"{len(findings)} ungrounded identifier(s)", findings)
    return GateOutcome(2, "Grounded", GateStatus.PASS,
                       f"{len(identifiers)} identifier(s) confirmed in the KB")
