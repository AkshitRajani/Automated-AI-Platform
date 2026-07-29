"""
Per-change orchestration — ticket + diff → a delivered (or repaired) test.

    coding_agent (grounding + lint + bounded repair)  ──┐
                                                        ├─▶  delivered bundle
    eval gate cascade (config-selected execution env) ──┘

The eval is injected into the agent's boundary as the external judge (the slot in
``boundary.run_with_boundary``) — so the agent is graded from outside and can never
reach the eval as a tool. The execution env is chosen by config (in-process /
sandbox). Every stage is a trace span.

Requires Bedrock (the agent loop) + the KB (grounding). With neither this raises a
ConfigError rather than faking a result.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .config import ConfigError
from .execenv import make_exec_env


@dataclass
class GenerateResult:
    ticket_id: str
    delivered: bool
    attempts: int
    routed_to_human: bool
    failed_gate: Optional[int]
    reasons: List[str]
    bundle: Optional[object]


def _parse_diff(diff: str) -> Tuple[Optional[str], Dict[str, Set[int]]]:
    """From a unified diff: the primary changed file + the added line numbers per
    file. Pure string parsing — no regex. Used for gate 5 (covers-the-change)."""
    changed: Dict[str, Set[int]] = {}
    current: Optional[str] = None
    new_lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current = None if path == "/dev/null" else path
            changed.setdefault(current, set()) if current else None
        elif line.startswith("@@"):
            # @@ -a,b +c,d @@  → take c (new-file start line)
            try:
                plus = line.split("+", 1)[1]
                head = plus.split(" ", 1)[0]
                new_lineno = int(head.split(",", 1)[0])
            except (IndexError, ValueError):
                new_lineno = 0
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            changed[current].add(new_lineno)
            new_lineno += 1
        elif not line.startswith("-"):
            new_lineno += 1
    primary = max(changed, key=lambda f: len(changed[f])) if changed else None
    return primary, changed


def _apply_unified_diff(workspace_dir: str, diff: str) -> str:
    """Apply a simple unified diff in-process (Windows-safe; no ``patch`` binary)."""
    import re
    notes = []
    # Split into per-file hunks on "--- a/..." lines
    parts = re.split(r'(?m)^--- a/', diff)
    for part in parts:
        part = part.strip("\n")
        if not part:
            continue
        lines = part.splitlines()
        if not lines:
            continue
        # first line is path (after split removed "--- a/")
        rel = lines[0].strip()
        # find +++ and first @@
        body_start = 0
        for i, ln in enumerate(lines):
            if ln.startswith("@@"):
                body_start = i
                break
        else:
            notes.append(f"no hunks for {rel}")
            continue
        path = os.path.join(workspace_dir, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            notes.append(f"missing file {rel}")
            continue
        with open(path, encoding="utf-8") as fh:
            original = fh.read().splitlines(keepends=True)
        # Normalize to list without worrying about trailing newlines in matching
        src_lines = [ln.rstrip("\n") for ln in original]
        out: list[str] = []
        src_i = 0
        i = body_start
        while i < len(lines):
            ln = lines[i]
            if ln.startswith("@@"):
                # @@ -a,b +c,d @@
                try:
                    minus = ln.split("-", 1)[1]
                    start = int(minus.split(",", 1)[0].split()[0])
                    # copy unchanged lines before this hunk (1-based start)
                    target = max(0, start - 1)
                    while src_i < target and src_i < len(src_lines):
                        out.append(src_lines[src_i] + "\n")
                        src_i += 1
                except (IndexError, ValueError):
                    notes.append(f"bad hunk header: {ln}")
                i += 1
                continue
            if ln.startswith("---") or ln.startswith("+++"):
                i += 1
                continue
            if ln.startswith(" "):
                # context — must match
                out.append(ln[1:] + "\n")
                src_i += 1
            elif ln.startswith("-"):
                src_i += 1  # delete
            elif ln.startswith("+"):
                out.append(ln[1:] + "\n")
            elif ln.startswith("\\"):
                pass  # "\ No newline at end of file"
            i += 1
        while src_i < len(src_lines):
            out.append(src_lines[src_i] + "\n")
            src_i += 1
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.writelines(out)
        notes.append(f"patched {rel}")
    return "; ".join(notes) or "no files patched"


def _seed_workspace(workspace_dir: str, source_dir: str, diff: str,
                    changed_files, trace) -> None:
    """Copy app source into the workspace and apply the diff (post-change SUT).

    Copies the full source tree (skipping bulky/irrelevant dirs) so the agent and
    Behave env can import sibling modules. Falls back to changed-files-only if a
    full tree copy is impossible. Applies the unified diff via ``patch`` or a
    pure-Python applicator on Windows.
    """
    import shutil
    import subprocess

    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", ".idea",
            ".pytest_cache", "pic", "model", "data", "ImageStore"}
    copied = 0
    try:
        for dirpath, dirnames, filenames in os.walk(source_dir):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            rel_dir = os.path.relpath(dirpath, source_dir)
            for name in filenames:
                if name.endswith((".pyc", ".png", ".jpg", ".jpeg", ".pth", ".zip")):
                    continue
                src = os.path.join(dirpath, name)
                rel = name if rel_dir == "." else os.path.join(rel_dir, name)
                dst = os.path.join(workspace_dir, rel)
                os.makedirs(os.path.dirname(dst) or workspace_dir, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
    except Exception:
        copied = 0
        for rel in changed_files:
            src = os.path.join(source_dir, rel)
            dst = os.path.join(workspace_dir, rel)
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst) or workspace_dir, exist_ok=True)
                shutil.copy(src, dst)
                copied += 1

    diff_path = os.path.join(workspace_dir, ".change.diff")
    with open(diff_path, "w", encoding="utf-8") as fh:
        fh.write(diff if diff.endswith("\n") else diff + "\n")
    try:
        proc = subprocess.run(["patch", "-p1", "-i", ".change.diff"],
                              cwd=workspace_dir, capture_output=True, text=True)
    except FileNotFoundError as exc:
        note = _apply_unified_diff(workspace_dir, diff)
        trace.log(f"workspace seeded ({copied} files) + in-process patch ({note})",
                  files=list(changed_files), patch_fallback=str(exc))
        return
    if proc.returncode == 0:
        trace.log(f"workspace seeded ({copied} files) + patched (rc=0)",
                  files=list(changed_files), patch_out=(proc.stdout or "")[-200:])
        return
    note = _apply_unified_diff(workspace_dir, diff)
    trace.log(f"workspace seeded ({copied} files) + in-process patch ({note})",
              files=list(changed_files),
              patch_fallback=proc.stderr[-200:] if proc.stderr else str(proc.returncode))


def _fmt_tool_args(inp) -> str:
    """One-line summary of a tool's input — the informative field (path/query/...)
    if there is one, else compact JSON. Keeps the live log readable."""
    import json
    if not isinstance(inp, dict) or not inp:
        return ""
    for k in ("path", "file", "file_path", "query", "name", "pattern",
              "q", "command", "cmd", "predicate"):
        v = inp.get(k)
        if v:
            return f"{k}={str(v).replace(chr(10), ' ')[:160]}"
    try:
        return json.dumps(inp, default=str)[:160]
    except Exception:
        return str(inp)[:160]


def _agent_logger(span):
    """A Strands callback_handler that streams the agent's tool calls (with their
    arguments) and reasoning to the live trace, instead of only stdout.

    The tool NAME arrives on ``contentBlockStart``; the tool INPUT does NOT — it
    streams as partial-JSON fragments in subsequent ``contentBlockDelta`` events
    (``delta.toolUse.input``), and is also sometimes exposed pre-parsed as
    ``current_tool_use``. We accumulate the fragments, prefer the parsed form when
    present, and flush each tool — name + args — once it's done (next tool starts,
    text resumes, or the run ends)."""
    import json
    st = {"buf": "", "n": 0, "pending": None, "logged": set()}

    def _flush_tool():
        p = st["pending"]
        st["pending"] = None
        if not p or p["id"] in st["logged"]:
            return
        st["logged"].add(p["id"])
        st["n"] += 1
        inp = p.get("input")
        if inp is None and p.get("raw"):           # parse the accumulated delta JSON
            try:
                inp = json.loads(p["raw"])
            except Exception:
                inp = None
        args = _fmt_tool_args(inp) or (p["raw"][:160] if p.get("raw") else "")
        span.log(f"\U0001f527 tool #{st['n']}: {p['name']}" + (f"  {args}" if args else ""))

    def cb(**kw):
        try:
            ev = kw.get("event") or {}
            # 1) a tool call begins — name only, no input yet
            start_tu = ev.get("contentBlockStart", {}).get("start", {}).get("toolUse")
            if start_tu and start_tu.get("name"):
                _flush_tool()
                st["pending"] = {"id": start_tu.get("toolUseId"), "name": start_tu["name"],
                                 "raw": "", "input": None}
            # 2) tool input streams in as partial-JSON fragments
            d = ev.get("contentBlockDelta", {}).get("delta", {})
            if isinstance(d.get("toolUse"), dict) and st["pending"] is not None:
                st["pending"]["raw"] += d["toolUse"].get("input", "") or ""
            # 3) some versions also pass a pre-parsed current_tool_use (prefer it)
            ctu = kw.get("current_tool_use")
            if ctu and ctu.get("name"):
                if not st["pending"] or st["pending"]["id"] != ctu.get("toolUseId"):
                    _flush_tool()
                    st["pending"] = {"id": ctu.get("toolUseId"), "name": ctu["name"],
                                     "raw": "", "input": ctu.get("input")}
                elif ctu.get("input"):
                    st["pending"]["input"] = ctu["input"]

            text = kw.get("data") or kw.get("reasoningText") or ""
            if text:
                _flush_tool()                   # text resuming → the tool call is done
                st["buf"] += text
                while "\n" in st["buf"]:
                    line, st["buf"] = st["buf"].split("\n", 1)
                    line = line.strip()
                    if line:
                        span.log(line[:400])
            if kw.get("complete") or kw.get("result") is not None:
                _flush_tool()
                if st["buf"].strip():
                    span.log(st["buf"].strip()[:400])
                    st["buf"] = ""
        except Exception:
            pass

    return cb


def generate(ticket_id: str, ticket_text: str, diff: str, app_id: str,
             workspace_dir: str, framework: str, cfg, trace,
             source_dir: Optional[str] = None) -> GenerateResult:
    if not cfg.has_bedrock:
        raise ConfigError("generate needs BEDROCK_MODEL_ARN (the agent loop).")

    import os
    with trace.span("generate", ticket=ticket_id, app_id=app_id, framework=framework) as sp:
        from coding_agent.boundary import run_with_boundary
        from coding_agent.kb.facts import KBClient
        from coding_agent.schemas import AgentTask, Scope
        from eval import EvalContext, ExecCase, evaluate
        from eval.grounding import Resolver

        env = make_exec_env(cfg, trace=sp, framework=framework)
        primary, changed_lines = _parse_diff(diff)
        sp.set(primary_changed_file=primary)

        # Seed the workspace with the post-change source (so the SUT exists and the
        # baseline run passes). Best-effort: a run is never blocked if it can't patch.
        if source_dir and os.path.isdir(source_dir):
            try:
                _seed_workspace(workspace_dir, source_dir, diff, list(changed_lines), sp)
            except Exception as exc:
                sp.log(f"workspace seed failed (continuing): {exc}")

        # The KB client IS the eval's gate-2 resolver: it already exposes
        # resolve(query, kind, app_id, limit) -> result.candidates, exactly the
        # Resolver protocol eval/grounding.py expects.
        kb = KBClient.from_env()

        def external_eval(bundle) -> Tuple[bool, List[str]]:
            """The injected gate cascade — runs after the agent's cheap gates pass."""
            with trace.span("eval.cascade", ticket=ticket_id) as es:
                import os, glob
                # The agent writes its test files to the workspace during its loop
                # (and runs behave against them). Materialize the bundle only to FILL
                # GAPS — never clobber the agent's on-disk files, and never write a
                # bundle field that is a path/placeholder rather than real content.
                wrote = 0
                for sf in getattr(bundle, "step_files", []):
                    fp = os.path.join(workspace_dir, sf.path)
                    if os.path.exists(fp) or "\n" not in (sf.content or ""):
                        continue                         # already on disk, or not real content
                    os.makedirs(os.path.dirname(fp) or workspace_dir, exist_ok=True)
                    with open(fp, "w") as fh:
                        fh.write(sf.content)
                    wrote += 1
                feature = getattr(bundle, "feature_file", None) or ""
                features_dir = os.path.join(workspace_dir, "features")
                has_feature = glob.glob(os.path.join(features_dir, "*.feature"))
                if "Feature:" in feature and not has_feature:    # valid Gherkin, none on disk
                    os.makedirs(features_dir, exist_ok=True)
                    with open(os.path.join(features_dir, "change.feature"), "w") as fh:
                        fh.write(feature)
                    wrote += 1
                es.set(materialized=wrote)

                # the SUT is the primary changed file (in the workspace); the test is
                # the step-definitions file (it holds the asserts) — NOT behave's
                # environment.py setup hook, which has none.
                sut_path = os.path.join(workspace_dir, primary) if primary else ""
                py = [sf for sf in getattr(bundle, "step_files", []) if sf.language == "python"]
                chosen = (next((sf for sf in py if "step" in sf.path.lower()), None)
                          or next((sf for sf in py if "environment" not in sf.path.lower()), None)
                          or (py[0] if py else None))
                test_path = os.path.join(workspace_dir, chosen.path) if chosen else ""
                case = ExecCase(sut_path=sut_path, test_path=test_path)
                # gate 5 looks up changed lines by the SUT's full path; the diff
                # keys them by the relative file — re-key to the SUT path.
                changed_for_eval = ({sut_path: changed_lines[primary]}
                                    if primary and primary in changed_lines else changed_lines)
                ctx = EvalContext.from_bundle(
                    bundle, app_id=app_id, case=case,
                    changed_lines=changed_for_eval, steps_root=workspace_dir,
                )
                verdict = evaluate(ctx, env=env, resolver=kb)
                es.set(deliver=verdict.deliver, failed_gate=verdict.failed_gate)
                reasons = []
                if not verdict.deliver:
                    reasons = [f"eval gate {verdict.failed_gate} failed"] + [
                        f.message for g in verdict.gates for f in getattr(g, "findings", [])
                    ]
                return verdict.deliver, reasons

        try:
            task = AgentTask(ticket_id=ticket_id, ticket_text=ticket_text, diff=diff,
                             framework=framework, scope=Scope(app_id=app_id),
                             workspace_dir=workspace_dir)
            outcome = run_with_boundary(task, max_repairs=cfg.max_repairs,
                                        external_eval=external_eval,
                                        agent_callback=_agent_logger(sp))
        finally:
            kb.close()

        sp.set(delivered=outcome.delivered, attempts=outcome.attempts,
               routed_to_human=outcome.routed_to_human)
        return GenerateResult(
            ticket_id=ticket_id, delivered=outcome.delivered, attempts=outcome.attempts,
            routed_to_human=outcome.routed_to_human, failed_gate=None,
            reasons=outcome.gate_reasons, bundle=outcome.bundle,
        )
