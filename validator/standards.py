"""
Team standards — per-application quality rules as CONFIG, checked mechanically.

The long-term half of the feedback loop (final_design/08_feedback_loop.md §4): when the
same reviewer feedback recurs ("tag every scenario", "name must carry the ticket id"),
a person promotes it into the app's standards config, and from then on the machine
enforces it — the reviewer never repeats themselves.

Nothing team-specific lives in this code. The checker implements a small, generic rule
vocabulary; every value (which tags, which substrings, which limits) comes from the
per-app config the caller supplies. An unknown config key fails loudly — a typo must
never silently disable a rule.

Rule vocabulary (v1 — deliberately small, all mechanically checkable):
  required_tags               every scenario carries ALL of these tags (feature-level
                              tags count for its scenarios, per Gherkin inheritance)
  forbidden_tags              no scenario (or feature) carries ANY of these
  scenario_name_must_include  every scenario name contains AT LEAST ONE listed substring
  max_scenarios_per_feature   a feature file holds at most this many scenarios
  require_feature_description a feature has prose between "Feature:" and its scenarios
  severity                    "ERROR" (default) or "WARNING" for all standards findings

The .feature scan is line-structural (tag lines, Feature:/Scenario: keywords) — the
Gherkin container format, not prose interpretation. English keywords only (the project's
generation targets); a non-matching file simply yields no scenarios, and zero feature
files under a configured root is reported, never silently passed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

from .models import Finding, Severity

_LIST_KEYS = ("required_tags", "forbidden_tags", "scenario_name_must_include")
_KNOWN_KEYS = _LIST_KEYS + ("max_scenarios_per_feature", "require_feature_description",
                            "severity")

_RULE_PREFIX = "team-standard"


def load_standards(config: dict) -> dict:
    """Validate a standards config. Returns the normalized dict; raises ValueError on
    an unknown key or a wrong type — fail loud, a typo must not disable a rule."""
    if not isinstance(config, dict):
        raise ValueError(f"standards config must be an object, got {type(config).__name__}")
    unknown = sorted(set(config) - set(_KNOWN_KEYS))
    if unknown:
        raise ValueError(f"unknown standards key(s): {', '.join(unknown)} "
                         f"(known: {', '.join(_KNOWN_KEYS)})")
    out: dict = {}
    for key in _LIST_KEYS:
        if key in config:
            val = config[key]
            if not isinstance(val, list) or not all(isinstance(v, str) and v.strip() for v in val):
                raise ValueError(f"'{key}' must be a list of non-empty strings")
            out[key] = [v.strip() for v in val]
    if "max_scenarios_per_feature" in config:
        val = config["max_scenarios_per_feature"]
        if not isinstance(val, int) or isinstance(val, bool) or val < 1:
            raise ValueError("'max_scenarios_per_feature' must be a positive integer")
        out["max_scenarios_per_feature"] = val
    if "require_feature_description" in config:
        val = config["require_feature_description"]
        if not isinstance(val, bool):
            raise ValueError("'require_feature_description' must be true or false")
        out["require_feature_description"] = val
    sev = config.get("severity", "ERROR")
    if sev not in ("ERROR", "WARNING"):
        raise ValueError("'severity' must be 'ERROR' or 'WARNING'")
    out["severity"] = sev
    return out


# --- the structural .feature scan --------------------------------------------

@dataclass
class _Scenario:
    name: str
    line: int
    tags: List[str] = field(default_factory=list)   # own tags + inherited feature tags


@dataclass
class _Feature:
    path: str
    line: int = 0
    tags: List[str] = field(default_factory=list)
    has_description: bool = False
    scenarios: List[_Scenario] = field(default_factory=list)


def _scan_feature(path: str) -> _Feature:
    """Line-structural Gherkin scan: tag lines, Feature:, Scenario:/Scenario Outline:.
    Deterministic; no prose interpretation."""
    feat = _Feature(path=path)
    pending_tags: List[str] = []
    seen_feature = False
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("@"):
                pending_tags.extend(t for t in line.split() if t.startswith("@"))
                continue
            if line.startswith("Feature:"):
                seen_feature = True
                feat.line = lineno
                feat.tags = pending_tags
                pending_tags = []
                continue
            if line.startswith(("Scenario:", "Scenario Outline:")):
                name = line.split(":", 1)[1].strip()
                feat.scenarios.append(_Scenario(
                    name=name, line=lineno, tags=pending_tags + feat.tags))
                pending_tags = []
                continue
            # any other content line between Feature: and the first Scenario is prose
            if seen_feature and not feat.scenarios:
                if not line.startswith(("Background:", "Given", "When", "Then",
                                        "And", "But", "|", "Examples:")):
                    feat.has_description = True
    return feat


def _feature_files(root: str) -> List[str]:
    if os.path.isfile(root):
        return [root] if root.endswith(".feature") else []
    found: List[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.endswith(".feature"):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


# --- the checks ----------------------------------------------------------------

def check_standards(root: str, standards: dict) -> List[Finding]:
    """Run the configured team standards over every .feature under ``root``.
    ``standards`` must already be normalized by ``load_standards``."""
    sev = Severity(standards.get("severity", "ERROR"))
    rules_active = [k for k in standards if k != "severity"]
    if not rules_active:
        return []

    files = _feature_files(root)
    if not files:
        # A configured-but-uncheckable run is said out loud, never silently green.
        return [Finding(
            rule=f"{_RULE_PREFIX}-nothing-to-check", severity=Severity.WARNING,
            file=root, line=0,
            message="team standards are configured but no .feature files were found here",
            suggestion="check the lint path — the standards were NOT applied to anything",
        )]

    findings: List[Finding] = []
    for path in files:
        feat = _scan_feature(path)

        if standards.get("require_feature_description") and not feat.has_description:
            findings.append(Finding(
                rule=f"{_RULE_PREFIX}-feature-description", severity=sev,
                file=path, line=feat.line or 1,
                message="feature has no description prose under 'Feature:'",
                suggestion="add a short description of what this feature covers",
            ))

        limit = standards.get("max_scenarios_per_feature")
        if limit is not None and len(feat.scenarios) > limit:
            findings.append(Finding(
                rule=f"{_RULE_PREFIX}-max-scenarios", severity=sev,
                file=path, line=feat.line or 1,
                message=(f"{len(feat.scenarios)} scenarios in one feature "
                         f"(team limit: {limit})"),
                suggestion="split the feature by behaviour",
            ))

        forbidden = set(standards.get("forbidden_tags", []))
        for tag in sorted(forbidden.intersection(feat.tags)):
            findings.append(Finding(
                rule=f"{_RULE_PREFIX}-forbidden-tag", severity=sev,
                file=path, line=feat.line or 1,
                message=f"feature carries forbidden tag {tag}",
                suggestion=f"remove {tag}", symbol=tag,
            ))

        for sc in feat.scenarios:
            missing = [t for t in standards.get("required_tags", []) if t not in sc.tags]
            if missing:
                findings.append(Finding(
                    rule=f"{_RULE_PREFIX}-required-tag", severity=sev,
                    file=path, line=sc.line,
                    message=(f"scenario '{sc.name}' is missing required tag(s): "
                             f"{', '.join(missing)}"),
                    suggestion="add the tag(s) above the scenario (or on the feature)",
                    symbol=missing[0],
                ))
            for tag in sorted(forbidden.intersection(sc.tags)):
                if tag in feat.tags:
                    continue                      # already reported at feature level
                findings.append(Finding(
                    rule=f"{_RULE_PREFIX}-forbidden-tag", severity=sev,
                    file=path, line=sc.line,
                    message=f"scenario '{sc.name}' carries forbidden tag {tag}",
                    suggestion=f"remove {tag}", symbol=tag,
                ))
            must_include = standards.get("scenario_name_must_include", [])
            if must_include and not any(s in sc.name for s in must_include):
                findings.append(Finding(
                    rule=f"{_RULE_PREFIX}-scenario-name", severity=sev,
                    file=path, line=sc.line,
                    message=(f"scenario name '{sc.name}' contains none of the required "
                             f"marker(s): {', '.join(must_include)}"),
                    suggestion="include the team's marker in the scenario name",
                ))
    return findings
