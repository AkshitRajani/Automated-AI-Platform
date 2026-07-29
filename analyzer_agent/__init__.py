"""
Analyzer Agent — Step 2 of the analyzer (Component 0).

An autonomous **Strands + Bedrock** agent that takes a codebase **plus the
deterministic Step-1 parser draft** and recovers what static parsing cannot see
on its own: **cross-file call chains and data lineage**. Every fact it emits
carries ``file:line`` and is re-verified by the deterministic grounding gate
(``analyzer.verify``) before it can enter the graph.

Design: ``2026/solution/final_design/02_analyzer.md`` (+ MASTER_DESIGN §5.1/§5.1.1).

Dependency floor — nothing beyond this:
  * ``strands`` + ``strands_tools``   (the agent runtime + built-in tools)
  * Python **stdlib**
  * our own ``analyzer`` (parser + grounding gate) and ``ingestion`` (config + KB)

No LangChain / LangGraph / agent frameworks. No regex, no hardcoded name-lists in
this package — structure comes from the parser's AST and the grounding gate.

Public surface::

    from analyzer_agent import AnalyzerTask, run
    result = run(AnalyzerTask(repo_dir="/path/to/app", app_id="DEMO"))
    print(result.stats)        # verified / notes / rejected / precision
"""
from __future__ import annotations

from .agent import AnalyzerTask, build_agent, run
from .store import EmittedFact, FactStore

__all__ = ["AnalyzerTask", "run", "build_agent", "FactStore", "EmittedFact"]
