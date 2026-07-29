import boto3
from .._endpoints import boto3_kwargs, AWS_REGION


def return_s3_client(region_name=None):
    kw = boto3_kwargs("s3")
    if region_name:
        kw["region_name"] = region_name
    return boto3.client(**kw)


def return_step_function_client(region_name=None):
    kw = boto3_kwargs("stepfunctions")
    if region_name:
        kw["region_name"] = region_name
    return boto3.client(**kw)


def return_emr_client(region_name=None):
    kw = boto3_kwargs("emr")
    if region_name:
        kw["region_name"] = region_name
    return boto3.client(**kw)


def return_lambda_client(region_name=None):
    kw = boto3_kwargs("lambda")
    if region_name:
        kw["region_name"] = region_name
    return boto3.client(**kw)


def return_dynamodb_client(region_name=None):
    kw = boto3_kwargs("dynamodb")
    if region_name:
        kw["region_name"] = region_name
    return boto3.client(**kw)


def return_dynamodb_resource(region_name=None):
    kw = boto3_kwargs("dynamodb")
    if region_name:
        kw["region_name"] = region_name
    return boto3.resource(**kw)
