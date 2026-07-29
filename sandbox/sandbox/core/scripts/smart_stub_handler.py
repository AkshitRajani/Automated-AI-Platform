"""Multi-fidelity Lambda stub handler.

Embedded verbatim into every generated stub zip by build_lambda_stubs.py.
Reads its sibling fidelity.json at module load. The fidelity tier determines
runtime behavior:

    L3  schema-faithful    validates input keys against fidelity.input_schema;
                           returns output_example.json with refreshed dynamic
                           fields (timestamps, UUIDs, execution-ids).
    L2  shape-only         accepts any JSON; returns output_example.json with
                           refreshed dynamic fields. Logs key mismatches but
                           does not reject.
    L1  echo               returns {} (empty). No body, no shape. Forces tests
                           that need a real response to fail loudly so the
                           lambda gets promoted to L2/L3 when material lands.

DESIGN INVARIANTS (locked 2026-05-04):
  * Sandbox-only metadata (`_fidelity`, `_stub`, `_lambda_name`, etc.) MUST NOT
    leak into the response Payload. They go to CloudWatch logs only — the
    response shape mimics the real tenant response so test bundles run
    identically here vs. in tenant env.
  * Every invoke logs `[<lambda_name>] tier=<L1|L2|L3> received_keys=[...]
    returned_shape=<...>` to CloudWatch. Visible in the Inspect drawer.
  * L3 metadata whitelist (hardcoded, narrow): `_test_id`, `request_id`,
    `correlation_id`, `_trace_id`. These four pass strict validation
    regardless of input_schema. No wider pattern, no `_*` blanket.
  * L1 returns `{}`, not a fake-success body. False-rejection is preferable
    to false-acceptance.

For step functions: a separate L2 stub generator writes a one-state Pass ASL
that returns SUCCEEDED. There is no SF-L3 — step function fidelity is binary.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Hardcoded metadata whitelist — locked decision (#4).
_METADATA_WHITELIST = frozenset({
    "_test_id",
    "request_id",
    "correlation_id",
    "_trace_id",
})

# Output fields whose values get refreshed on every invoke (so two back-to-back
# calls don't return identical timestamps/IDs). Anything else copied verbatim
# from output_example.json.
_REFRESH_FIELDS = {
    "execution_id": lambda: str(uuid.uuid4()),
    "executionArn": lambda: f"arn:aws:states:us-east-1:000000000000:execution:stub:{uuid.uuid4()}",
    "request_id": lambda: str(uuid.uuid4()),
    "submitted_at": lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "completed_at": lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "timestamp": lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(),
}


def _load_json(name: str) -> dict | None:
    """Read a sibling JSON file from the lambda zip's root. Returns None if
    missing or malformed (handler stays usable; tier degrades gracefully)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("failed to load %s: %s", name, e)
        return None


# Loaded once at module import. Lambda containers reuse modules across invokes,
# so we pay this cost zero or one time per cold start.
_FIDELITY = _load_json("fidelity.json") or {"tier": "L1", "source": "missing"}
_INPUT_EXAMPLE = _load_json("input_example.json")
_OUTPUT_EXAMPLE = _load_json("output_example.json")
_LAMBDA_NAME = _FIDELITY.get("lambda_name", "unknown")
_TIER = _FIDELITY.get("tier", "L1")


def _validate_l3(event: dict) -> dict | None:
    """Strict validation for L3. Returns an error dict (which the handler
    converts to a 400-shaped response) on failure, or None on success.

    Rules:
      * Every required field must be present.
      * Every present field must be in required ∪ optional ∪ whitelist.
      * Type mismatches surface as "type_mismatch" errors.

    The error dict mirrors what the tenant's real lambda would likely return
    when the API gateway in front rejects the payload.
    """
    schema = _FIDELITY.get("input_schema") or {}
    required = set(schema.get("required_fields") or [])
    optional = set(schema.get("optional_fields") or [])
    types = schema.get("types") or {}
    allowed = required | optional | _METADATA_WHITELIST

    if not isinstance(event, dict):
        return {"error": "type_mismatch", "field": "<root>",
                "expected": "object", "got": type(event).__name__}

    keys = set(event.keys())
    missing = required - keys
    if missing:
        # Stable order so tests asserting on the field name are deterministic.
        return {"error": "missing_field", "field": sorted(missing)[0]}
    extras = keys - allowed
    if extras:
        return {"error": "unknown_field", "field": sorted(extras)[0]}
    for k, expected in types.items():
        if k not in event or event[k] is None:
            continue
        actual = type(event[k]).__name__
        if expected == "string" and not isinstance(event[k], str):
            return {"error": "type_mismatch", "field": k, "expected": "string", "got": actual}
        if expected == "object" and not isinstance(event[k], dict):
            return {"error": "type_mismatch", "field": k, "expected": "object", "got": actual}
        if expected == "array" and not isinstance(event[k], list):
            return {"error": "type_mismatch", "field": k, "expected": "array", "got": actual}
        if expected == "integer" and not isinstance(event[k], int):
            return {"error": "type_mismatch", "field": k, "expected": "integer", "got": actual}
        if expected == "boolean" and not isinstance(event[k], bool):
            return {"error": "type_mismatch", "field": k, "expected": "boolean", "got": actual}
    return None


def _refresh_dynamic(payload):
    """Walk the output example and replace any refreshable fields with fresh
    values. Mutates a deep copy; the original example stays intact."""
    if isinstance(payload, dict):
        return {
            k: (_REFRESH_FIELDS[k]() if k in _REFRESH_FIELDS else _refresh_dynamic(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [_refresh_dynamic(x) for x in payload]
    return payload


def _log(event, response_shape: str, error: str | None = None) -> None:
    keys = sorted(event.keys()) if isinstance(event, dict) else None
    msg = (
        f"[{_LAMBDA_NAME}] tier={_TIER} "
        f"received_keys={keys} "
        f"returned_shape={response_shape}"
    )
    if error:
        msg += f" error={error}"
    logger.info(msg)


def _error_response(err: dict) -> dict:
    """Render a validation error as a response. The shape is configurable via
    fidelity.json `error_responses`, keyed by error type. If the per-lambda
    fidelity.json supplies a template, we use it (tenant-faithful). Otherwise
    we fall back to a generic shape.

    Example fidelity.json entry:
        "error_responses": {
            "missing_field":  {"statusCode": 400, "error": "Missing required keys in event"},
            "unknown_field":  {"statusCode": 400, "error": "Unexpected key in event"},
            "type_mismatch":  {"statusCode": 400, "error": "Type mismatch"}
        }
    """
    templates = (_FIDELITY.get("error_responses") or {})
    template = templates.get(err["error"])
    if template:
        # Caller may want the offending field name visible. Merge but don't
        # overwrite explicit template fields.
        out = dict(template)
        out.setdefault("field", err.get("field"))
        return out
    # Generic fallback — matches what a strict API gateway might emit.
    return {"statusCode": 400, "error": err["error"], "field": err.get("field")}


def lambda_handler(event, context):
    if _TIER == "L3":
        err = _validate_l3(event if isinstance(event, dict) else {})
        if err is not None:
            _log(event, response_shape="error", error=err["error"])
            return _error_response(err)
        if _OUTPUT_EXAMPLE is None:
            _log(event, response_shape="empty", error="no_output_example")
            return {}
        out = _refresh_dynamic(_OUTPUT_EXAMPLE)
        _log(event, response_shape="L3_fixture")
        return out

    if _TIER == "L2":
        # Shape-only: log mismatches against input_example keys but never reject.
        if _INPUT_EXAMPLE and isinstance(event, dict):
            example_keys = set(_INPUT_EXAMPLE.keys())
            event_keys = set(event.keys())
            missing = example_keys - event_keys - _METADATA_WHITELIST
            extras = event_keys - example_keys - _METADATA_WHITELIST
            if missing or extras:
                logger.info(
                    f"[{_LAMBDA_NAME}] L2 shape mismatch: "
                    f"missing={sorted(missing)} extras={sorted(extras)}"
                )
        if _OUTPUT_EXAMPLE is None:
            _log(event, response_shape="empty", error="no_output_example")
            return {}
        out = _refresh_dynamic(_OUTPUT_EXAMPLE)
        _log(event, response_shape="L2_fixture")
        return out

    # L1 echo: return {}. Test code that needs a body fails — that's the signal.
    _log(event, response_shape="L1_empty")
    return {}
