"""Reproduces standup bug #3: two steps share an identical decorator pattern.
behave keeps the last registration, so the first function is dead code."""
from behave import then


@then('Acme API received PUT to "{url_pattern}" with:')
def step_impl_acme_put_request(context, url_pattern):
    assert context.last_put_url == url_pattern


@then('Acme API received PUT to "{url_pattern}" with:')
def step_impl_acme_put_with_table(context, url_pattern):
    assert context.last_put_table == context.expected_table
