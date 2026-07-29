"""
The observability backbone — a tiny, dependency-free event stream.

The core emits structured events at every meaningful step (a stage starting, a
component returning, a gate's verdict, an agent message). It knows nothing about
*where* those events go: listeners are registered from outside. The web layer
attaches an MLflow sink and a live-feed sink; the CLI attaches a stdout sink;
tests attach a list. This is what lets you "see everything happening behind the
scenes" without the core depending on any observability library.

Pure stdlib. Nested spans give the tree structure (stage → component → tool call).
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Event:
    kind: str                       # "span.start" | "span.end" | "log" | "metric" | "artifact"
    name: str                       # e.g. "onboard", "analyzer.parse", "gate.6", "agent.tool"
    span_id: int                    # this event's span
    parent_id: Optional[int] = None # enclosing span (None at the root)
    ts: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    status: Optional[str] = None    # "ok" | "fail" | "skip" on span.end


Listener = Callable[[Event], None]


class _Span:
    """Context manager: emits span.start on enter, span.end on exit (with status
    and any data accumulated). Yields itself so callers can attach data/logs."""

    def __init__(self, emitter: "TraceEmitter", name: str, data: Dict[str, Any]):
        self._em = emitter
        self.name = name
        self.id = next(emitter._ids)
        self._data = dict(data)
        self.status = "ok"

    def log(self, message: str, **data: Any) -> None:
        self._em._emit(Event("log", self.name, self.id, self._em._current,
                             data={"message": message, **data}))

    def set(self, **data: Any) -> None:
        self._data.update(data)

    def metric(self, key: str, value: Any) -> None:
        self._em._emit(Event("metric", self.name, self.id, self._em._current,
                             data={key: value}))

    def __enter__(self) -> "_Span":
        self._parent = self._em._current
        self._em._emit(Event("span.start", self.name, self.id, self._parent, data=self._data))
        self._em._current = self.id
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.status = "fail"
            self._data["error"] = f"{exc_type.__name__}: {exc}"
        self._em._emit(Event("span.end", self.name, self.id, self._parent,
                             data=self._data, status=self.status))
        self._em._current = self._parent
        return False        # never swallow exceptions


class TraceEmitter:
    """Holds the listeners and the current span. Thread-simple (one run at a time)."""

    def __init__(self) -> None:
        self._listeners: List[Listener] = []
        self._ids = itertools.count(1)
        self._current: Optional[int] = None

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def span(self, name: str, **data: Any) -> _Span:
        return _Span(self, name, data)

    def log(self, message: str, **data: Any) -> None:
        self._emit(Event("log", "root", 0, self._current,
                         data={"message": message, **data}))

    def _emit(self, event: Event) -> None:
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass        # a broken sink must never break the core run


def stdout_listener(event: Event) -> None:
    """A simple CLI sink — indented by span depth-ish, good enough for a terminal."""
    if event.kind == "span.start":
        print(f"▶ {event.name}  {event.data or ''}")
    elif event.kind == "span.end":
        mark = {"ok": "✓", "fail": "✗", "skip": "–"}.get(event.status, "·")
        print(f"{mark} {event.name}  {event.data or ''}")
    elif event.kind == "log":
        print(f"  · {event.data.get('message', '')}")
    elif event.kind == "metric":
        print(f"  # {event.name}: {event.data}")
