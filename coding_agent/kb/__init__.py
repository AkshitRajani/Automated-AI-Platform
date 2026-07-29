"""
Knowledge-Base data access — pure backend, no Strands dependency.

  - ``facts``  — Postgres fact lookups (backs the ``kb_query`` tool)
  - ``graph``  — Neptune lineage walk (backs the ``kb_graph`` tool)

Both bind to the *real* ingestion schema. Connection values come only from the
shared ``.env`` via ``coding_agent.config`` — never hardcoded — so the agent
moves between environments by swapping ``.env`` alone.
"""
