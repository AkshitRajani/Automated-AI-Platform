"""
The domain tools the agent calls, as thin Strands ``@tool`` wrappers over the
pure backends:

  - ``kb_query``      — resolve a real identifier (Postgres facts)
  - ``kb_graph``      — walk the Neptune lineage graph
  - ``lint_tests``    — static linter over generated step files (wraps the validator)
  - ``read_source`` / ``search_source`` / ``list_source`` — read the onboarded app's
    RAW source on demand (the kb_raw_code escape hatch); read-only, degrades to a
    note when no codebase pointer was given.

The file/shell tools are Strands built-ins, wired (workspace-scoped) in
``coding_agent.agent``, not here.
"""
from coding_agent.tools.kb_query import kb_query, set_client
from coding_agent.tools.kb_inventory import kb_inventory
from coding_agent.tools.kb_requirements import kb_requirements
from coding_agent.tools.kb_examples import kb_examples
from coding_agent.tools.kb_graph import kb_graph, set_graph_client
from coding_agent.tools.lint_tests import lint_tests
from coding_agent.tools.read_source import (
    list_source, read_source, search_source, set_source,
)

__all__ = ["kb_query", "kb_inventory", "kb_requirements", "kb_examples", "kb_graph",
           "lint_tests", "read_source", "search_source", "list_source",
           "set_client", "set_graph_client", "set_source"]
