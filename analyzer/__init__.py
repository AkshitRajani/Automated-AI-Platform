"""
Analyzer — code → spec (Component 0, the onboarding front door).

v1 = Step 1 only: a **deterministic Python parser** (pure `ast`, no LLM) that
turns a codebase into the **entities + quads** the ingestion `quad_parser`
consumes. Source of truth for the KB; exhaustive, reproducible, free.

    from analyzer import analyze, to_yaml
    qf = analyze("/path/to/app", app_id="DEMO")
    open("quad.yaml", "w").write(to_yaml(qf))

Step 2 (LLM enrichment → pgvector) and the Java/TS parsers come later; the output
contract (entities + quads) is identical across languages.
"""
from __future__ import annotations

from .emit import to_dict, to_yaml, write
from .extract import analyze
from .load import load_quadfile
from .models import Entity, Note, Quad, QuadFile, Source

__all__ = ["analyze", "to_dict", "to_yaml", "write", "load_quadfile",
           "Entity", "Note", "Quad", "QuadFile", "Source"]
