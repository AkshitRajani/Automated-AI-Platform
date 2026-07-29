"""
Run log — capture the agent's full activity to a plain-text file.

Whoever runs the agent gets a complete, human-readable trace of what it did and
why: every reasoning line and every tool call with its arguments, in order. Wired
on by default in the boundary; the file lands next to the generated tests as
``<workspace>/agent_log.txt``.

The event shapes come from Strands' streaming ``callback_handler``: the tool NAME
arrives on ``contentBlockStart``; the tool INPUT streams as partial-JSON fragments
in ``contentBlockDelta`` (``delta.toolUse.input``) and is sometimes pre-parsed as
``current_tool_use``. We accumulate the fragments, prefer the parsed form, and flush
each tool once it's complete.
"""
from __future__ import annotations

import json
import os
from typing import Optional


def _fmt_tool_args(inp) -> str:
    """One-line summary of a tool's input — the informative field, else compact JSON."""
    if not isinstance(inp, dict) or not inp:
        return ""
    for k in ("path", "file", "file_path", "query", "name", "pattern", "q",
              "command", "cmd", "predicate", "app_id", "glob", "start", "kind"):
        v = inp.get(k)
        if v:
            return f"{k}={str(v).replace(chr(10), ' ')[:200]}"
    try:
        return json.dumps(inp, default=str)[:200]
    except Exception:
        return str(inp)[:200]


class RunLogger:
    """Streams reasoning + tool calls to a file. Use ``.callback`` as the agent's
    Strands callback_handler and call ``.close()`` when the run is done."""

    def __init__(self, path: str, header: str = ""):
        self._fh = None
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._fh = open(path, "w", encoding="utf-8")
        except OSError:
            self._fh = None
        if header:
            self._w(header)
        self._buf = ""
        self._n = 0
        self._pending = None
        self._logged: set = set()

    # -- output ----------------------------------------------------------------

    def _w(self, line: str) -> None:
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()   # flush every line so the log is complete even mid-run

    def _flush_tool(self) -> None:
        p = self._pending
        self._pending = None
        if not p or p["id"] in self._logged:
            return
        self._logged.add(p["id"])
        self._n += 1
        inp = p.get("input")
        if inp is None and p.get("raw"):
            try:
                inp = json.loads(p["raw"])
            except Exception:
                inp = None
        args = _fmt_tool_args(inp) or (p["raw"][:200] if p.get("raw") else "")
        self._w(f"  \U0001f527 tool #{self._n}: {p['name']}" + (f"  {args}" if args else ""))

    # -- the Strands callback_handler -----------------------------------------

    def callback(self, **kw) -> None:
        try:
            ev = kw.get("event") or {}
            start_tu = ev.get("contentBlockStart", {}).get("start", {}).get("toolUse")
            if start_tu and start_tu.get("name"):
                self._flush_tool()
                self._pending = {"id": start_tu.get("toolUseId"), "name": start_tu["name"],
                                 "raw": "", "input": None}
            d = ev.get("contentBlockDelta", {}).get("delta", {})
            if isinstance(d.get("toolUse"), dict) and self._pending is not None:
                self._pending["raw"] += d["toolUse"].get("input", "") or ""
            ctu = kw.get("current_tool_use")
            if ctu and ctu.get("name"):
                if not self._pending or self._pending["id"] != ctu.get("toolUseId"):
                    self._flush_tool()
                    self._pending = {"id": ctu.get("toolUseId"), "name": ctu["name"],
                                     "raw": "", "input": ctu.get("input")}
                elif ctu.get("input"):
                    self._pending["input"] = ctu["input"]

            text = kw.get("data") or kw.get("reasoningText") or ""
            if text:
                self._flush_tool()                 # text resuming → the tool call is done
                self._buf += text
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._w(line[:600])
            if kw.get("complete") or kw.get("result") is not None:
                self._flush_tool()
                if self._buf.strip():
                    self._w(self._buf.strip()[:600])
                    self._buf = ""
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._flush_tool()
            if self._buf.strip():
                self._w(self._buf.strip()[:600])
            if self._fh:
                self._fh.close()
        except Exception:
            pass


def tee(*cbs):
    """Combine callbacks into one (each called in order, errors isolated). Returns
    None if all are None, so the agent gets no callback rather than a no-op."""
    cbs = [c for c in cbs if c]
    if not cbs:
        return None

    def cb(**kw):
        for c in cbs:
            try:
                c(**kw)
            except Exception:
                pass

    return cb
