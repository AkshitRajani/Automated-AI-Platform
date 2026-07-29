import boto3


def invoke_worker(payload):
    client = boto3.client("lambda")
    return client.invoke(FunctionName="worker-fn", Payload=payload)   # INVOKES_LAMBDA (literal)


def read_dynamic(bucket, key):
    s3 = boto3.client("s3")
    return s3.get_object(Bucket=bucket, Key=key)                      # READS_FROM_S3 (symbolic)
