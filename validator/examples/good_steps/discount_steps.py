"""A clean step file — every name grounded, each step unique, each `then`
asserts a concrete value, no stubs, no mocking. Passes all checks."""
from behave import given, when, then

from checkout.discount import apply_discount


@given("an order with total {total:d}")
def step_order_with_total(context, total):
    context.order = {"order_total_amount": total}


@when("the discount is applied")
def step_apply_discount(context):
    context.charge = apply_discount(context.order, context.gateway)


@then("the gateway is charged {amount:d}")
def step_gateway_charged(context, amount):
    assert context.charge["amount"] == amount
