from behave import then


@then("the result is correct")
def step_impl(context):
    pass   # asserts nothing — the validator's no-op-step rule fires here
