"""
The analyzer agent's domain tools + the run-context injectors.

Smooth, sharp set (Python-first):
  * ``repo_map``      — whole-repo structural map (from the parser draft)
  * ``parser_facts``  — the deterministic backbone + the unresolved gaps to close
  * ``parse``         — run the parser LIVE on one file (Level 2, on-demand)
  * ``emit_fact``     — the only write; routed through the grounding gate
  * ``lsp_resolve``   — optional, config-gated accurate cross-file resolution

Navigation (``file_read``, ``shell`` for grep/glob) comes from ``strands_tools`` and
is added in ``agent.build_agent``.
"""
from __future__ import annotations

from .context import set_draft, set_root, set_store
from .emit_fact import emit_fact
from .lsp import lsp_available, lsp_resolve
from .parse_file import parse
from .parser_facts import parser_facts
from .repo_map import repo_map

__all__ = ["repo_map", "parser_facts", "parse", "emit_fact", "lsp_resolve",
           "lsp_available", "set_store", "set_draft", "set_root"]
