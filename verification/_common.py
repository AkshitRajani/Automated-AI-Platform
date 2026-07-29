"""Shared plumbing for the verification scripts. READ-ONLY by design — nothing in
this folder ever writes to the database. Connection comes from the same
environment variables ingestion uses (PG_HOST/PG_PORT/PG_DATABASE/PG_USER/
PG_PASSWORD); no secret is ever printed or written to a report."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

RESULTS: list[dict] = []


def connect():
    import psycopg2
    try:
        return psycopg2.connect(
            host=os.environ.get("PG_HOST", "localhost"),
            port=int(os.environ.get("PG_PORT", "5432")),
            dbname=os.environ.get("PG_DATABASE", "knowledge_base"),
            user=os.environ.get("PG_USER", "postgres"),
            password=os.environ.get("PG_PASSWORD", ""),
        )
    except Exception as exc:
        print(f"[FAIL] cannot connect to Postgres "
              f"(host={os.environ.get('PG_HOST', 'localhost')}, "
              f"db={os.environ.get('PG_DATABASE', 'knowledge_base')}): {exc}")
        print("       set PG_HOST / PG_PORT / PG_DATABASE / PG_USER / PG_PASSWORD "
              "to the same values ingestion uses.")
        sys.exit(3)


def q(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def record(check: str, status: str, summary: str, data=None):
    """status: PASS | WARN | FAIL | INFO. Prints one line, keeps it for the report."""
    print(f"[{status}] {check}: {summary}")
    RESULTS.append({"check": check, "status": status, "summary": summary,
                    "data": data if data is not None else {}})


def write_report(name: str) -> str:
    outdir = os.path.join(os.getcwd(), "verification_report")
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(outdir, f"{name}_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"run": name, "when": stamp, "results": RESULTS}, fh, indent=2)
    # Additive: a plain-English Markdown twin of the same report, same stamp.
    # The JSON above is untouched; this only adds a human-readable file next to it.
    md_path = write_markdown(name, stamp)
    fails = sum(1 for r in RESULTS if r["status"] == "FAIL")
    warns = sum(1 for r in RESULTS if r["status"] == "WARN")
    print(f"\n{'=' * 60}\n{len(RESULTS)} checks — {fails} FAIL, {warns} WARN")
    print(f"report written: {path}")
    print(f"plain-English report: {md_path}")
    print("send those files back when reporting an issue.")
    return path


# --- plain-English Markdown report -------------------------------------------
# Every number below is EXPLAINED, never judged. Each check name maps to a
# sentence saying what it counts; each entity/table type maps to a friendly
# label + meaning. Written once, no model, no new dependencies.

_CHECK_CAPTIONS = {
    "nodes": "Every distinct thing found in the app's map — the flows, workflows, code pieces, storage and configuration names.",
    "linkage (edges by kind)": "The connections between things — how many links of each kind the map holds.",
    "state machines lead somewhere": "Whether each workflow connects onward to the steps it runs, rather than being a dead end.",
    "invoked lambdas lead to code": "Whether each lambda that gets called connects to the code that handles it.",
    "unresolved facts": "Facts whose name is still a ${placeholder} because the real value lives in configuration, not the code.",
    "journey count": "How many separate end-to-end flows the tool traced through the app.",
    "journeys have specs": "How many of those flows already have a written specification document.",
    "longest chain": "The longest single flow the tool could walk, shown step by step.",
    "reach": "On average, how far a flow travels from its starting point.",
    "storage handoffs": "Places where one piece writes data and another reads it — a handoff through storage.",
    "app registered": "Whether the app is known to the knowledge base.",
    "row counts": "How many facts of each kind are stored for this app.",
    "duplicate facts": "Facts stored more than once — a sign an app was loaded twice.",
    "placeholders in KB": "Names still stored as ${placeholder} because their real value was never supplied.",
    "spec docs loaded": "How many specification documents are stored for this app.",
    "spec ↔ inventory join": "Whether each stored document matches a real item in the map.",
    "orphan spec docs (any app)": "Documents stored for an app the map does not know.",
    "file parses": "Whether the analyzer's output file is readable.",
    "entities": "The individual things the analyzer recorded in this file.",
    "facts": "The relationships the analyzer recorded (X calls Y, X writes table Z, …).",
    "journeys walked": "How many end-to-end flows the analyzer traced in this file.",
    "repo-declared answers": "Placeholder values the tool found already written down in the repo's own config.",
    "placeholders": "Names still unresolved — their real value comes from configuration, not the code.",
    "app id": "The name this app is filed under.",
    "blocked or complete": "Whether this run finished, or stopped because some names still need a human's answer (a stopped run carries no journeys, on purpose).",
    "questions for a human": "The exact names nobody could answer from the code, each shown with the place it is used.",
    "human-supplied answers": "Names a person typed in. Every fact built from one is marked as human-supplied, so it can never be mistaken for something the code said.",
    "skip / runtime decisions": "Names a person deliberately left blank (with their reason). The map keeps a visible hole there instead of a guess.",
    "worksheet warnings": "Inconsistencies in the answer sheets — an answer for a name that doesn't exist, or a name both answered and skipped.",
    "needs wiring": "Pieces that look like full flows but that nothing reachable starts — held out for review instead of being counted as journeys.",
    "ready to ingest": "The decision line: READY means the run is complete and this file can be loaded now; WAIT means names still need a human's answer (the file carries no journeys yet) or the file is unhealthy.",
    "compared with previous run": "The same measurements from this file and an earlier one, side by side — what changed between the two runs.",
    "what this run read": "How many files of each kind the analyzer read — a zero here means the files were not in the upload, stated outright instead of hiding behind ordinary-looking output. Zips are never opened; if any are present they are listed so nothing silently rides inside one.",
    "analyzer version": "Which analyzer produced this file — so a result can always be traced to the exact reader that made it.",
    "web calls (outbound APIs)": "Outside services the code calls over the web (payment, data-provider, partner APIs), found by the address in the call itself.",
    "secrets read (names only)": "Which stored credentials the code fetches, by NAME only — the secret's value is never read, never stored, never shown.",
    "parameters read": "Configuration values the code fetches from the parameter store, by name.",
    "notifications published": "Notification topics the code publishes messages to.",
    "database tables": "Every database table the app reads or writes — including queries kept in config files rather than in the code.",
    "bucket names readable": "Whether storage facts show real bucket and file names, or still show placeholders/raw code text whose values were never supplied.",
    "lambda code links": "Whether each declared lambda is connected to the code it runs — flows can only show what a step does if this link exists. Unlinked lambdas are listed as questions, never guessed.",
    "environment": "Which environment's settings ground this map (test, devl, …) — one environment only; the others present are deliberately not mixed in.",
    "lambda names confirmed": "Whether a person has reviewed the lambda names the deploy files declare — some estates write only half the name there, so tests must not trust them unreviewed.",
    "manifest": "The list of what the spec step documented and what it deliberately skipped.",
    "skips carry reasons": "Whether every skipped item recorded why it was skipped.",
    "doc files complete": "Whether every document has all its required sections.",
    "journey coverage vs analyzer": "Whether every flow the analyzer found got a document.",
}

# Friendly label + meaning for typed breakdowns (graph node types / KB tables).
_TYPE_CAPTIONS = {
    # graph node types
    "Journey": ("Journeys", "end-to-end flows through the app"),
    "BehaviorGroup": ("Behavior groups", "families of small request/response behaviors"),
    "StateMachine": ("Workflows (state machines)", "orchestration workflows"),
    "State": ("State-machine states", "the steps inside a state machine"),
    "Step": ("Workflow steps", "steps inside a workflow / pipeline file"),
    "WorkflowFile": ("Workflow files", "ETL / pipeline workflow definitions"),
    "LambdaFunction": ("Lambdas", "serverless functions"),
    "Function": ("Functions", "individual code functions"),
    "Method": ("Methods", "class methods"),
    "Module": ("Modules", "code files / modules"),
    "Class": ("Classes", "code classes"),
    "Symbol": ("Symbols", "named code symbols"),
    "S3Object": ("Storage objects", "files/objects in S3 the code reads or writes"),
    "Table": ("Tables", "database tables the code reads or writes"),
    "Parameter": ("Parameters", "configuration parameters the code reads"),
    "APIEndpoint": ("Endpoints", "API endpoints the app exposes or calls"),
    "Secret": ("Secrets (names)", "stored credentials the code fetches, by name only"),
    "Topic": ("Notification topics", "channels the code publishes messages to"),
    "ConfigFile": ("Config files with SQL", "configuration files holding database queries"),
    "Endpoint": ("Endpoints", "API endpoints the app exposes or calls"),
    # KB row-count table names
    "quad_archive": ("Stored facts", "the archived relationship facts"),
    "app_functions": ("Code entities", "functions, methods and similar"),
    "app_endpoints": ("Endpoints", "API endpoint facts"),
    "app_tables": ("Table facts", "database read/write facts"),
    "app_s3_paths": ("Storage facts", "S3 read/write facts"),
    "app_service_invocations": ("Service calls", "lambda / step-function / SNS calls"),
    "app_parameters": ("Parameter facts", "config/env/SSM reads"),
    "app_requirements": ("Specification docs", "stored documents"),
    "app_components": ("Components", "grouped parts of the app"),
}


def _friendly_run(name: str) -> str:
    return name.replace("check_", "").replace("_", " ").strip().title() or name


def _count_dict(data) -> bool:
    return isinstance(data, dict) and bool(data) and all(isinstance(v, int) for v in data.values())


def _typed_table(data: dict) -> str:
    """A clean table of the meaningful typed counts; the long tail (config/resource
    names) is bucketed into one row so the report stays readable."""
    known = sorted(((k, v) for k, v in data.items() if k in _TYPE_CAPTIONS),
                   key=lambda kv: -kv[1])
    if not known:
        return ""      # nothing to caption cleanly (e.g. relationship kinds) — use the summary
    other = sum(v for k, v in data.items() if k not in _TYPE_CAPTIONS)
    rows = ["| Count | What it is | What it means |", "|---:|---|---|"]
    for k, v in known:
        label, meaning = _TYPE_CAPTIONS[k]
        rows.append(f"| **{v:,}** | {label} | {meaning} |")
    if other:
        rows.append(f"| **~{other:,}** | Other named items | smaller categories plus configuration "
                    f"& resource names not broken out above (buckets, secrets, tables, settings); "
                    f"names that appear once usually get their real value from a `${{…}}` placeholder |")
    return "\n".join(rows)


def write_markdown(name: str, stamp: str) -> str:
    outdir = os.path.join(os.getcwd(), "verification_report")
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{name}_{stamp}.md")
    when = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:11]}:{stamp[11:13]}"
    out = [
        f"# Verification Report — {_friendly_run(name)}",
        "",
        f"*Generated {when} · read-only check · every number is explained, not judged.*",
        "",
        "> This report explains, in plain English, **what the tool found**. It does not decide "
        "what is good or bad — each number comes with what it counts, so your team can read it "
        "without needing us.",
        "",
        "---",
        "",
    ]
    for r in RESULTS:
        heading = str(r["check"])[:1].upper() + str(r["check"])[1:]
        out.append(f"### {heading}")
        out.append("")
        data = r.get("data") or {}
        if isinstance(data, dict) and isinstance(data.get("path"), list):
            out.append(str(r["summary"]))
            out.append("")
            for i, step in enumerate(data["path"]):
                out.append(f"{i + 1}. `{step}`")
        elif _count_dict(data) and len(data) >= 2:
            table = _typed_table(data)
            out.append(table if table else str(r["summary"]))
        else:
            out.append(str(r["summary"]))
        out.append("")
        caption = _CHECK_CAPTIONS.get(str(r["check"]))
        if caption:
            out.append(f"*What this means:* {caption}")
            out.append("")
    out += [
        "---",
        "",
        "*Terms: a **journey** is one end-to-end flow; a **behavior group** is a family of small "
        "behaviors; a **placeholder** (`${…}`) is a name whose real value comes from configuration. "
        "This is a read-only report — no data was changed. The raw numbers are also saved as JSON "
        "next to this file.*",
    ]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return path


def exit_code() -> int:
    return 1 if any(r["status"] == "FAIL" for r in RESULTS) else 0


# --- the flow-graph vocabulary (must mirror the analyzer's journey pass) ------
FORWARD = {"CALLS", "INVOKES_LAMBDA", "INVOKES_STEP_FUNCTION", "PUBLISHES_TO_SNS",
           "WRITES_TO_S3", "WRITES_DATABASE", "WRITES_DYNAMODB_TABLE", "WRITES_FILE",
           "RETURNS_RESPONSE", "FEEDS", "CALLS_HTTP_API", "IMPLEMENTED_BY",
           "HANDLED_BY", "IN_BUCKET"}
REVERSED_ = {"READS_FROM_S3", "QUERIES_DATABASE", "READS_DYNAMODB_TABLE", "READS_FILE",
             "READS_CONFIG_FROM_S3", "EXPOSES_ENDPOINT", "RECEIVES_EVENT"}
EXCLUDED = {"DEFINES", "HAS_JPA_RELATIONSHIP", "READS_ENV_VAR", "READS_SSM_PARAMETER",
            "READS_SECRET", "IMPLEMENTS", "RAISES_ERROR", "STARTS_AT", "HAS_MEMBER"}
