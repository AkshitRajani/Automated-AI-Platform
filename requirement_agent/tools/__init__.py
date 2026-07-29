"""
The domain tools the requirement agent calls, as thin Strands ``@tool`` wrappers:

Grounding (read the analyzer output — the onboarding-time analogue of the coding
agent's ``kb_inventory`` / ``kb_query``, since there is no live KB yet):
  - ``list_units``        — enumerate the app's units (uncapped)
  - ``read_facts``        — what one unit touches (its quads), uncapped

Navigation (the RAW source, read-only, confined to the source root):
  - ``read_source`` / ``search_source`` / ``list_source``

Emission (write the document incrementally — any size, no model-response limit):
  - ``start_unit`` / ``write_section`` / ``finish_unit`` / ``skip_type``

There are no general file/shell built-ins: documents are written only through the emit
tools (deterministic, workspace-scoped), and the source is read-only. State for the
analyzer facts, the source pointer, and the emit accumulator is injected once per run
(``set_facts`` / ``set_source`` / ``reset_emit``).
"""
from requirement_agent.tools.analyzer_facts import list_units, read_facts, set_facts
from requirement_agent.tools.emit import (build_requirement_set, finish_unit, reset_emit,
                                          skip_type, start_unit, write_section)
from requirement_agent.tools.read_source import (
    list_source, read_source, search_source, set_source,
)

__all__ = [
    "list_units", "read_facts", "set_facts",
    "read_source", "search_source", "list_source", "set_source",
    "start_unit", "write_section", "finish_unit", "skip_type",
    "reset_emit", "build_requirement_set",
]
