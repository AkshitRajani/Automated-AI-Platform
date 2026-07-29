import boto3
from .._endpoints import boto3_kwargs


class ExecutionStatusStepFunction:
    def __init__(self, execution_arn):
        self.execution_arn = execution_arn

    def status(self):
        client = boto3.client(**boto3_kwargs("stepfunctions"))
        return client.describe_execution(executionArn=self.execution_arn)

    def execution_status(self):
        return self.status()
