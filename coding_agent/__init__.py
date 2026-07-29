"""
Coding Agent — autonomous Strands + Bedrock agent that writes grounded
regression-test bundles for a code change.

Canonical design: ``2026/solution/final_design/04_coding_agent_agentic.md``.

The agent is autonomous *inside* a deterministic boundary: it reasons and calls
its tools in whatever order it judges best (Strands runs the loop), while the
guarantees — every emitted name is real, an external grader certifies pass/fail,
repair is bounded — are enforced in plain code around it, never trusted to the
prompt alone.

Slice 1 scope (locked 2026-06-16): Python-in / Behave-out, ``app_id``-only KB
scoping, workspace-scoped ``shell`` enabled.

Layering (so the core stays testable without the Strands runtime):
  - ``schemas``  — the external Pydantic contracts (AgentTask in, TestBundle out)
  - ``kb.backend`` — pure data access over the live KB (psycopg2 / boto3); no Strands
  - ``tools.*``  — thin ``@tool`` wrappers that adapt the backend to Strands
  - ``agent``    — assembles the Strands Agent (model + prompt + tools)
  - ``boundary`` — the deterministic boundary (grounding gate + bounded repair)
"""

__all__ = ["schemas"]
