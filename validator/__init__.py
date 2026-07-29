"""
Step-file validator — deterministic static checks for generated Behave step
files. Pure standard library (`ast` + `importlib.metadata`); no external
dependencies; no LLM in the judgment.

    from validator import validate
    report = validate("path/to/steps")
    report.ok            # True when there are no ERROR findings
    report.to_dict()     # JSON-ready (this is what the agent loop reads)
"""
from .models import Finding, Report, Severity
from .runner import validate

__all__ = ["validate", "Finding", "Report", "Severity"]
