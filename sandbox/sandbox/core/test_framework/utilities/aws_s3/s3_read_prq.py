import io
import os
from urllib.parse import urlparse
import boto3
import pandas as pd
from .._endpoints import boto3_kwargs


def _split(bucket_or_uri, key=None):
    if key is None and bucket_or_uri.startswith("s3://"):
        u = urlparse(bucket_or_uri)
        return u.netloc, u.path.lstrip("/")
    return bucket_or_uri, (key or "")


def _list_keys(s3, bucket, prefix):
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            k = obj["Key"]
            if k.endswith(".parquet") or k.endswith(".pq"):
                keys.append(k)
    return keys


def read_parquet_files_from_s3(bucket_or_uri, key=None):
    s3 = boto3.client(**boto3_kwargs("s3"))
    bucket, key = _split(bucket_or_uri, key)
    if key and (key.endswith(".parquet") or key.endswith(".pq")):
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return pd.read_parquet(io.BytesIO(body))
    keys = _list_keys(s3, bucket, key or "")
    if not keys:
        raise FileNotFoundError(f"no parquet files under s3://{bucket}/{key}")
    frames = []
    for k in keys:
        body = s3.get_object(Bucket=bucket, Key=k)["Body"].read()
        frames.append(pd.read_parquet(io.BytesIO(body)))
    return pd.concat(frames, ignore_index=True)


def read_parquet_files_from_s3_with_partitions(bucket_or_uri, key=None):
    return read_parquet_files_from_s3(bucket_or_uri, key)
