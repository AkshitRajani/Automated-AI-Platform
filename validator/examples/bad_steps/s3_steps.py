"""Reproduces standup bug #2: names used but never imported (NameError)."""
import json
import os

from behave import then


@then('the chunked S3 file "{key}" exists')
def step_s3_file_exists(context, key):
    body = context.s3.get_object(Bucket=context.bucket, Key=key)["Body"].read()
    if re.match(r"^chunk", key):          # `re` is never imported
        buffer = BytesIO(body)            # `BytesIO` is never imported
        context.chunk_size = len(buffer.getvalue())
