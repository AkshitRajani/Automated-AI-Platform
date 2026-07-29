"""
Automated AI Platform — Requirement Agent.

The second onboarding producer (MASTER_DESIGN §5.2). Given an application's code
plus the analyzer's output, it writes ONE requirement doc per testable unit — the
behavior + interface contract that makes a generated test blackbox instead of
whitebox. Built exactly like the coding agent: an autonomous Strands+Bedrock loop
inside a deterministic boundary (grounding gate + coverage gate + bounded repair).

It does NOT read the live KB — at onboarding the KB does not exist yet — it grounds
against the analyzer's facts (a quad file) and the raw source.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
