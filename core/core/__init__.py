"""
Core — the wired end-to-end workflow (the part that ships to the client).

This package is the **orchestration spine** that connects the already-built
components into the two flows of `MASTER_DESIGN.md §3`:

    ONBOARDING   codebase ─▶ analyzer(parser) ─▶ analyzer_agent ─▶ ingestion ─▶ KB
    PER-CHANGE   ticket+diff ─▶ coding_agent ─▶ eval(gate cascade) ─▶ deliver

It is **dependency-pure** — `strands` + stdlib + our own components only. No Flask,
no MLflow, no web concerns leak in here: the core only *emits* a structured event
stream (`core.trace`); any observability sink (MLflow, a live UI feed) is attached
by the outer web layer. That separation is deliberate — the core is what production
runs; the web app is a temporary local harness around it.

Everything that varies — the onboarding source (local path / zip / S3), AWS
credentials, store endpoints, which execution env the eval uses — comes from
config / `.env`, never hardcoded.

Public surface::

    from core import Pipeline
    pipe = Pipeline()                       # reads .env
    pipe.onboard("s3://bucket/app.zip", app_id="DEMO")
    pipe.generate(ticket_text="...", diff="...", app_id="DEMO", framework="behave")
"""
from __future__ import annotations

from .pipeline import Pipeline
from .trace import Event, TraceEmitter

__all__ = ["Pipeline", "TraceEmitter", "Event"]
