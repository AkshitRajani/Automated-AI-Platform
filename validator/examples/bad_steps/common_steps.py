"""Reproduces standup bug #5: `then` steps with empty bodies. They assert
nothing, so every scenario using them passes vacuously."""
from behave import then


@then('CloudWatch Logs contain message "{message}"')
def step_logs_contain_pattern(context, message):
    pass


@then('CloudWatch Logs do not contain "{pattern}"')
def step_logs_do_not_contain_pattern(context, pattern):
    pass


@then("Acme upload_file was called {count:d} times")
def step_acme_upload_file_called_count(context, count):
    # TODO: implement
    pass
