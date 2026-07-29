"""
Minimal Gherkin parser — Feature / Scenario / step extraction.

Pure stdlib. Handles the common Behave/Cucumber subset used in this repo:
Feature, Background, Scenario, Scenario Outline, tags, Examples, and Given/When/Then/And/But.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .models import Scenario, Step

_STEP = re.compile(
    r"^\s*(Given|When|Then|And|But|\*)\s+(.*)$",
    re.IGNORECASE,
)
_TAG = re.compile(r"^\s*@([\w-]+)")
_FEATURE = re.compile(r"^\s*Feature:\s*(.*)$", re.IGNORECASE)
_SCENARIO = re.compile(
    r"^\s*Scenario(?:\s+Outline)?:\s*(.*)$",
    re.IGNORECASE,
)
_BACKGROUND = re.compile(r"^\s*Background:\s*(.*)$", re.IGNORECASE)
_EXAMPLES = re.compile(r"^\s*Examples:\s*$", re.IGNORECASE)
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


def _rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def load_features(path: str | Path) -> List[Scenario]:
    """Load all scenarios from a ``.feature`` file or a directory tree."""
    root = Path(path)
    if root.is_file():
        return parse_feature_file(root, _rel_path(root.parent, root))
    if not root.is_dir():
        raise FileNotFoundError(f"not a file or directory: {root}")

    scenarios: List[Scenario] = []
    for feature_path in sorted(root.rglob("*.feature")):
        rel = _rel_path(root, feature_path)
        scenarios.extend(parse_feature_file(feature_path, rel))
    return scenarios


def parse_feature_file(path: Path, feature_file: Optional[str] = None) -> List[Scenario]:
    text = path.read_text(encoding="utf-8")
    rel = feature_file or path.name
    return parse_feature_text(text, rel)


def _parse_table_row(line: str) -> Tuple[str, ...]:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return tuple(cells)


def _is_table_separator(cells: Tuple[str, ...]) -> bool:
    return bool(cells) and all(set(c) <= {"-", ":"} for c in cells if c)


def parse_feature_text(text: str, feature_file: str = "inline.feature") -> List[Scenario]:
    feature_name = ""
    background_steps: List[Step] = []
    pending_tags: List[str] = []
    scenarios: List[Scenario] = []

    current_name: Optional[str] = None
    current_tags: List[str] = []
    current_steps: List[Step] = []
    current_is_outline = False
    in_examples = False
    examples_header: Tuple[str, ...] = ()
    examples_rows: List[Tuple[str, ...]] = []
    examples_lines: List[str] = []

    def flush_scenario() -> None:
        nonlocal current_name, current_tags, current_steps, current_is_outline
        nonlocal in_examples, examples_header, examples_rows, examples_lines
        if current_name is None:
            return
        steps = tuple(background_steps + current_steps)
        scenarios.append(Scenario(
            feature_file=feature_file,
            feature_name=feature_name or feature_file,
            name=current_name,
            tags=tuple(current_tags),
            steps=steps,
            is_outline=current_is_outline,
            examples_header=examples_header,
            outline_examples=tuple(examples_rows),
            examples_block="\n".join(examples_lines).strip(),
        ))
        current_name = None
        current_tags = []
        current_steps = []
        current_is_outline = False
        in_examples = False
        examples_header = ()
        examples_rows = []
        examples_lines = []

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith('"""') or line.startswith("'''"):
            continue

        if in_examples and current_name is not None:
            if _TABLE_ROW.match(raw):
                cells = _parse_table_row(raw)
                examples_lines.append(raw.rstrip())
                if not examples_header:
                    examples_header = cells
                elif _is_table_separator(cells):
                    continue
                else:
                    examples_rows.append(cells)
                continue
            if not line:
                continue
            in_examples = False

        tag_match = _TAG.match(raw)
        if tag_match and current_name is None:
            pending_tags.append(tag_match.group(1))
            continue

        feat = _FEATURE.match(raw)
        if feat:
            flush_scenario()
            feature_name = feat.group(1).strip()
            pending_tags = []
            continue

        bg = _BACKGROUND.match(raw)
        if bg:
            flush_scenario()
            background_steps = []
            pending_tags = []
            if bg.group(1).strip():
                background_steps.append(Step("Background", bg.group(1).strip(), line_no))
            continue

        scen = _SCENARIO.match(raw)
        if scen:
            flush_scenario()
            current_name = scen.group(1).strip() or "Unnamed scenario"
            current_tags = list(pending_tags)
            pending_tags = []
            current_steps = []
            current_is_outline = "outline" in raw.lower()
            in_examples = False
            examples_header = ()
            examples_rows = []
            examples_lines = []
            continue

        if _EXAMPLES.match(raw):
            in_examples = True
            examples_lines = [raw.rstrip()]
            continue

        step = _STEP.match(raw)
        if step:
            keyword = _canonical_keyword(step.group(1))
            body = step.group(2).strip()
            new_step = Step(keyword, body, line_no)
            if current_name is None:
                background_steps.append(new_step)
            else:
                current_steps.append(new_step)
            continue

        pending_tags = []

    flush_scenario()
    return scenarios


def _canonical_keyword(raw: str) -> str:
    token = raw.strip().lower()
    if token == "*":
        return "Step"
    return token.capitalize()
