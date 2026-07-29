"""Shared fixtures for the requirement-agent tests — a small analyzer quad file and a
valid requirement doc (section-map shape), written under a tmp dir. No Strands needed."""
from __future__ import annotations

import json
import os

from requirement_agent.schemas import CANONICAL_SECTIONS, RequirementDoc

# A tiny but realistic analyzer output: one handler (a unit), one internal helper
# (not a unit), one endpoint. Two facts hang off the handler.
SAMPLE_QUAD = """
metadata:
  app_id: DEMO
entities:
  - id: "LambdaHandler:handler_a"
    type: LambdaHandler
    name: handler_a
    source: {file_path: a.py, line_start: 10, line_end: 40}
  - id: "Function:helper_x"
    type: Function
    name: helper_x
    source: {file_path: a.py, line_start: 50}
  - id: "APIEndpoint:GET /x"
    type: APIEndpoint
    name: "GET /x"
quads:
  - subject: "LambdaHandler:handler_a"
    predicate: WRITES_TO_S3
    object: "s3://bucket/key.csv"
    context: {resolved: true}
  - subject: "LambdaHandler:handler_a"
    predicate: CALLS
    object: "Function:helper_x"
    context: {resolved: true}
"""


def write_quad(tmp_path) -> str:
    """Write the sample analyzer quad YAML; return its path."""
    p = os.path.join(str(tmp_path), "demo_quad.yaml")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(SAMPLE_QUAD)
    return p


# Section bodies that exercise the visible-content assertions (negative path + the
# code-derived stamp + a grounded name). Every canonical section is non-empty so the
# doc-validity gate passes.
_SECTION_BODIES = {
    "System Overview": "Handler A writes a file to S3.",
    "Input Specification": "| Data Source | Field | Type | Purpose | Example |\n"
                           "|---|---|---|---|---|\n"
                           "| Lambda Event | event['key'] | string | object key | key.csv |",
    "Consolidated Requirements": "- The system shall write the file to s3://bucket/key.csv.",
    "Output Specification": "| Field | Type | Values | Meaning |\n|---|---|---|---|\n"
                            "| statusCode | integer | 200 | success |",
    "Function Specification": "| Function | Purpose | Params | Returns | Raises |\n"
                              "|---|---|---|---|---|\n"
                              "| handler_a | write the file | event | statusCode | error |",
    "User Stories": "### US-1 Write file (Story Points: 3)\n"
                    "_As an operator, I want the file written._\n\n"
                    "1. **Given** a valid key **When** the handler runs **Then** the file "
                    "lands at s3://bucket/key.csv  `[code-derived]`\n"
                    "2. **Given** a missing key **When** the handler runs **Then** it raises "
                    "an error  `[code-derived, conf 0]` _(negative path)_",
    "Traceability Matrix": "| Category | Functions | Story |\n|---|---|---|\n"
                           "| Output | handler_a | US-1 |",
    "Confidence Mapping": "| Tag | Confidence | Story | Explanation |\n|---|---|---|---|\n"
                          "| US-1 | 0 | US-1 | No backing requirement; CODE-DERIVED |",
    "Gap Analysis": "**Coverage:** 0%\n\n- The CSV schema is not grounded in facts.",
}


def make_doc(unit: str = "LambdaHandler:handler_a") -> RequirementDoc:
    """A valid, fully-grounded RequirementDoc (all nine canonical sections non-empty)."""
    sections = {name: _SECTION_BODIES[name] for name in CANONICAL_SECTIONS}
    return RequirementDoc(
        unit=unit,
        unit_type="LambdaHandler",
        title="Handler A",
        provenance="code-derived",
        requirement_backed=False,
        grounding="grounded in 2 analyzer fact(s); no raw source",
        grounded_identifiers=["s3://bucket/key.csv"],
        sections=sections,
    )


def write_doc(tmp_path, unit: str = "LambdaHandler:handler_a", name: str = "handler_a.json") -> str:
    """Write a valid requirement doc JSON under <tmp>/requirements/; return its REL path."""
    rel = os.path.join("requirements", name)
    full = os.path.join(str(tmp_path), rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        json.dump(make_doc(unit).model_dump(), fh)
    return rel
