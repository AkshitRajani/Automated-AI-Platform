import boto3
from .._endpoints import boto3_kwargs


class ExecuteStepFunction:
    def __init__(self, state_machine_arn, input_payload):
        self.state_machine_arn = state_machine_arn
        self.input_payload = input_payload

    def step_function_execution(self):
        client = boto3.client(**boto3_kwargs("stepfunctions"))
        return client.start_execution(
            stateMachineArn=self.state_machine_arn,
            input=self.input_payload,
        )
