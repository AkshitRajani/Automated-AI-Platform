"""Multipart parser (Python 3.13+ compatible)."""
from __future__ import annotations

from scoring.multipart import parse_multipart_form


def test_parse_multipart_form_files_and_field():
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="golden_zip"; filename="a.zip"\r\n'
        f"Content-Type: application/zip\r\n\r\n"
        f"PKgolden\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="generated_zip"; filename="b.zip"\r\n'
        f"Content-Type: application/zip\r\n\r\n"
        f"PKgenerated\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="threshold"\r\n\r\n'
        f"0.55\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    fields = parse_multipart_form(
        body,
        f"multipart/form-data; boundary={boundary}",
    )
    assert fields["golden_zip"] == b"PKgolden"
    assert fields["generated_zip"] == b"PKgenerated"
    assert fields["threshold"] == b"0.55"
