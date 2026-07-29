"""
Onboarding orchestration — codebase → KB, one call.

    resolve source ─▶ Step 1 parser ─▶ Step 2 analyzer agent ─▶ merge ─▶ ingestion

Each stage is a trace span, so the web layer sees the whole tree live. The agent
stage is **Bedrock-gated**: when no model is configured it is skipped (parser-only
onboarding still produces a valid KB), logged honestly rather than faked.

The merge writes ONE ingestion-ready quad YAML (parser draft + the agent's verified
facts) into the staging dir, then hands that dir to ``ingestion.run_pipeline``,
which loads Postgres + Neptune. Ingestion is also Postgres-gated: with no store
configured the merged quad file is still produced (so you can inspect it), and the
load is reported as skipped.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from analyzer import analyze, to_yaml
from analyzer.models import QuadFile

from .source import resolve_source


@dataclass
class OnboardResult:
    app_id: str
    parser_entities: int
    parser_quads: int
    agent_graph_facts: int
    agent_notes: int
    agent_precision: Optional[float]
    quad_file: str
    ingested: bool
    ingest_report: Optional[dict]


def onboard(src: str, app_id: str, cfg, trace) -> OnboardResult:
    with trace.span("onboard", app_id=app_id, source=src) as sp:
        # 1. source → local dir
        with trace.span("source.resolve", source=src) as s1:
            resolved = resolve_source(src, region=cfg.aws_region, trace=s1)
            s1.set(root=resolved.root)
        try:
            # 2. Step 1 — deterministic parser (the canonical backbone)
            with trace.span("analyzer.parse", root=resolved.root) as s2:
                draft = analyze(resolved.root, app_id=app_id)
                s2.set(entities=len(draft.entities), quads=len(draft.quads))

            # 3. Step 2 — the analyzer agent (cross-file gap-fill), Bedrock-gated
            merged = QuadFile(app_id=app_id, entities=list(draft.entities),
                              quads=list(draft.quads))
            agent_facts = agent_notes = 0
            precision = None
            if cfg.has_bedrock:
                with trace.span("analyzer_agent.run") as s3:
                    try:
                        from analyzer_agent import AnalyzerTask, run as run_agent
                    except ImportError:
                        trace.log("analyzer agent skipped — analyzer_agent package "
                                  "not installed (parser-only onboarding)")
                        s3.set(skipped=True, reason="analyzer_agent_missing")
                    else:
                        try:
                            store = run_agent(AnalyzerTask(repo_dir=resolved.root,
                                                           app_id=app_id, draft=draft))
                            stats = store.stats()
                            agent_facts, agent_notes = stats["graph_facts"], stats["notes"]
                            precision = stats["precision"]
                            merged.quads.extend(store.to_quadfile().quads)
                            merged.notes.extend(store.to_notes())
                            s3.set(**stats)
                        except Exception as exc:
                            # Agent may have emitted facts before crashing (e.g. Windows
                            # console UnicodeEncodeError on callback print). Keep what we can.
                            trace.log(f"analyzer agent ended early: {type(exc).__name__}: {exc}")
                            s3.status = "fail"
                            s3.set(error=f"{type(exc).__name__}: {exc}")
            else:
                trace.log("analyzer agent skipped — BEDROCK_MODEL_ARN not set "
                          "(parser-only onboarding)")

            # 4. write ONE ingestion-ready quad YAML
            quad_dir = cfg.quad_dir or tempfile.mkdtemp(prefix="core_quads_")
            os.makedirs(quad_dir, exist_ok=True)
            quad_file = os.path.join(quad_dir, f"{app_id}.yaml")
            with open(quad_file, "w") as fh:
                fh.write(to_yaml(merged))
            sp.set(quad_file=quad_file)

            # 5. ingestion → Postgres + Neptune (Postgres-gated).
            # A store failure must NOT lose the parse: it's captured in the trace
            # and the quad file is still returned for inspection.
            ingested, report = False, None
            if cfg.has_postgres:
                with trace.span("ingestion.run", quad_dir=quad_dir) as s5:
                    from ingestion.pipeline import run_pipeline
                    try:
                        report = run_pipeline(quad_dir)
                        ingested = True
                        s5.set(**report)
                    except Exception as exc:
                        s5.status = "fail"
                        s5.set(error=f"{type(exc).__name__}: {exc}")
                        trace.log(f"ingestion failed (parse + quad file are intact): {exc}")
            else:
                trace.log("ingestion skipped — Postgres not configured "
                          "(quad file written for inspection)")

            return OnboardResult(
                app_id=app_id,
                parser_entities=len(draft.entities), parser_quads=len(draft.quads),
                agent_graph_facts=agent_facts, agent_notes=agent_notes,
                agent_precision=precision, quad_file=quad_file,
                ingested=ingested, ingest_report=report,
            )
        finally:
            resolved.cleanup()
