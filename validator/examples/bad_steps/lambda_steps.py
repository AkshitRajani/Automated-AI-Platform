"""Reproduces standup bug #1 (a step that always raises) and the screenshot's
over-mocking pattern (the system under test replaced by a stand-in)."""
from unittest.mock import patch, MagicMock

from behave import when, then


@when("uploadProcess is invoked with the event")
def step_invoke_upload_process(context):
    raise NotImplementedError("test through lambda_handler instead")


@when("the lambda_handler is invoked")
def step_invoke_lambda_handler(context):
    with patch("boto3.client") as mock_boto_client:
        mock_uploader = MagicMock()
        mock_uploader.upload_file.return_value = None
        context.result = mock_uploader.upload_file(context.event)


@then("lambda_handler returns no value")
def step_lambda_handler_returns(context):
    assert context.result is None
