import os
import boto3

app = object()
API_KEY = os.getenv("API_KEY")          # module-level env read


def get_client():
    return boto3.client("s3")


@app.get("/items")
def list_items():
    s3 = get_client()                    # internal CALLS edge
    return s3.get_object(Bucket="my-bucket", Key="items.json")   # READS_FROM_S3 (literal)


@app.post("/items")
def create_item(item):
    log_event(item)                      # internal CALLS edge
    return {"ok": True}


def log_event(event):
    pass
