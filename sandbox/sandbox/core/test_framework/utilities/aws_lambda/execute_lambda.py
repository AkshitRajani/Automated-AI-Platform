import io
import json

import boto3

from .._endpoints import boto3_kwargs


class _ReplayablePayload(io.BytesIO):
    """boto3's `response['Payload']` is a StreamingBody — read-once. Real tenant
    test code calls `.read()` on it. We give the same interface back, but make
    the bytes replayable so test code that calls `.read()` more than once (or
    pre-parses while keeping a reference) still works."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self._data = data

    def read(self, size: int = -1) -> bytes:
        # Always return the full payload regardless of stream position. boto3's
        # contract says one read; tenant code expects that one read. Subsequent
        # reads return the same bytes (defensive — pristine code reads once).
        return self._data


class ExecuteLambda:
    def __init__(self, lambda_name, payload):
        self.lambda_name = lambda_name
        self.payload = payload

    def lambda_execution(self):
        client = boto3.client(**boto3_kwargs("lambda"))
        body = self.payload if isinstance(self.payload, (bytes, str)) else json.dumps(self.payload)
        if isinstance(body, str):
            body = body.encode("utf-8")
        response = client.invoke(
            FunctionName=self.lambda_name,
            InvocationType="RequestResponse",
            Payload=body,
        )
        # Preserve boto3's response['Payload'].read() contract — tenant code
        # depends on it. We replace the StreamingBody with a replayable
        # equivalent so pristine test code keeps working.
        raw = response["Payload"].read()
        response["Payload"] = _ReplayablePayload(raw)
        return response
