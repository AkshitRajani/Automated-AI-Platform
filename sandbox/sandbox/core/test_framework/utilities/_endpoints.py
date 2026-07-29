import os

AWS_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "test")
AWS_SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

PG_HOST = os.environ.get("PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("PG_PORT", "5433"))
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "postgres")
PG_DATABASE = os.environ.get("PG_DATABASE", "aap_sandbox")


def boto3_kwargs(service_name: str) -> dict:
    return {
        "service_name": service_name,
        "endpoint_url": AWS_ENDPOINT,
        "region_name": AWS_REGION,
        "aws_access_key_id": AWS_KEY,
        "aws_secret_access_key": AWS_SECRET,
    }
