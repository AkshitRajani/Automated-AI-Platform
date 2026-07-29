"""
Minimal multipart/form-data parser (stdlib only).

Replaces ``cgi.FieldStorage``, which was removed in Python 3.13.
"""
from __future__ import annotations

import re
from typing import Dict, Union

FieldValue = Union[bytes, str]


def _extract_boundary(content_type: str) -> str | None:
    for token in content_type.split(";"):
        token = token.strip()
        if not token.lower().startswith("boundary="):
            continue
        value = token.split("=", 1)[1].strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value
    return None


def _field_name(headers: str) -> str | None:
    match = re.search(r'name="([^"]+)"', headers, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"name=([^;\s]+)", headers, re.IGNORECASE)
    return match.group(1) if match else None


def parse_multipart_form(body: bytes, content_type: str) -> Dict[str, FieldValue]:
    """Return form field name -> raw body (bytes for files and text fields)."""
    boundary = _extract_boundary(content_type)
    if not boundary:
        raise ValueError("multipart form missing boundary")

    delimiter = b"--" + boundary.encode("latin-1")
    fields: Dict[str, FieldValue] = {}

    for chunk in body.split(delimiter):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue

        header_blob, _, data = chunk.partition(b"\r\n\r\n")
        if not header_blob:
            continue

        name = _field_name(header_blob.decode("utf-8", errors="replace"))
        if not name:
            continue

        if data.endswith(b"\r\n"):
            data = data[:-2]
        fields[name] = data

    return fields
