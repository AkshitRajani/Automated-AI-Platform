"""
Adversarial tests for the 3.4.2 capture expansion (registry A8 / A9 / A10).

Discipline: every test runs REAL code through the REAL analyze() on a temp
tree — no mocking of the extractor. Each issue gets its happy path, its
adversarial variants, and its must-NOT-fire cases (false-positive guards).
"""
import os
import textwrap

import pytest

from analyzer.extract import analyze


def _app(tmp_path, code, tfvars=None):
    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    (src / "handler.py").write_text(textwrap.dedent(code), encoding="utf-8")
    if tfvars:
        tfe = tmp_path / "tfe"
        tfe.mkdir()
        (tfe / "vars.tfvars").write_text(textwrap.dedent(tfvars), encoding="utf-8")
    return analyze(str(tmp_path), "t")


def _objs(qf, pred):
    return [q.object for q in qf.quads if q.predicate == pred]


def _quads(qf, pred):
    return [q for q in qf.quads if q.predicate == pred]


# --------------------------------------------------------------------------
# A10 — inline env reads resolve exactly like the two-step style
# --------------------------------------------------------------------------
TFVARS = 'OUT_BUCKET = "real-bucket-us-east-1"\n'


class TestA10InlineEnv:
    def test_two_step_still_resolves(self, tmp_path):
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c):
                b = os.environ['OUT_BUCKET']
                boto3.client('s3').put_object(Bucket=b, Key='out/r.json')
        """, TFVARS)
        assert "S3Object:real-bucket-us-east-1/out/r.json" in _objs(qf, "WRITES_TO_S3")

    def test_inline_subscript_resolves(self, tmp_path):
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c):
                boto3.client('s3').put_object(Bucket=os.environ['OUT_BUCKET'], Key='out/r.json')
        """, TFVARS)
        assert "S3Object:real-bucket-us-east-1/out/r.json" in _objs(qf, "WRITES_TO_S3")

    def test_inline_getenv_resolves(self, tmp_path):
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c):
                boto3.client('s3').put_object(Bucket=os.getenv('OUT_BUCKET'), Key='k')
        """, TFVARS)
        assert "S3Object:real-bucket-us-east-1/k" in _objs(qf, "WRITES_TO_S3")

    def test_inline_environ_get_with_default_resolves(self, tmp_path):
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c):
                boto3.client('s3').get_object(Bucket=os.environ.get('OUT_BUCKET', 'fallback'), Key='k')
        """, TFVARS)
        assert "S3Object:real-bucket-us-east-1/k" in _objs(qf, "READS_FROM_S3")

    def test_fstring_key_with_env_bucket(self, tmp_path):
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c):
                boto3.client('s3').put_object(
                    Bucket=os.environ['OUT_BUCKET'],
                    Key=f"out/{os.environ['OUT_BUCKET']}/r.json")
        """, TFVARS)
        assert ("S3Object:real-bucket-us-east-1/out/real-bucket-us-east-1/r.json"
                in _objs(qf, "WRITES_TO_S3"))

    def test_unharvested_env_stays_visible_token(self, tmp_path):
        # No terraform declares NOWHERE — the token must SURVIVE as a visible
        # blank (pending name), never silently resolve or vanish.
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c):
                boto3.client('s3').put_object(Bucket=os.environ['NOWHERE'], Key='k')
        """)
        assert "S3Object:${NOWHERE}/k" in _objs(qf, "WRITES_TO_S3")
        assert "NOWHERE" in qf.pending_names

    def test_dynamic_key_variable_never_invented(self, tmp_path):
        # A variable that is NOT an env read must stay raw source text —
        # resolving it would be a guess.
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c, name):
                boto3.client('s3').put_object(Bucket=os.environ['OUT_BUCKET'], Key=name + '.csv')
        """, TFVARS)
        (obj,) = _objs(qf, "WRITES_TO_S3")
        assert obj.startswith("S3Object:real-bucket-us-east-1/")
        assert "name" in obj                      # raw expression kept, visibly
        q = _quads(qf, "WRITES_TO_S3")[0]
        assert q.resolved is False


# --------------------------------------------------------------------------
# A8 — outbound web calls, detected by the URL's own scheme
# --------------------------------------------------------------------------
class TestA8HttpCalls:
    def test_requests_post_literal(self, tmp_path):
        qf = _app(tmp_path, """
            import requests
            def main(e, c):
                requests.post("https://api.planner.com/2/0/models/import", json=e)
        """)
        assert "APIEndpoint:POST https://api.planner.com/2/0/models/import" \
            in _objs(qf, "CALLS_HTTP_API")

    def test_urlopen_positional(self, tmp_path):
        qf = _app(tmp_path, """
            from urllib.request import urlopen
            def main(e, c):
                urlopen("http://internal.example/status")
        """)
        assert "APIEndpoint:http://internal.example/status" in _objs(qf, "CALLS_HTTP_API")

    def test_url_kwarg(self, tmp_path):
        qf = _app(tmp_path, """
            import httpx
            def main(e, c):
                httpx.request("GET", url="https://svc.example/v1/x")
        """)
        assert any("https://svc.example/v1/x" in o for o in _objs(qf, "CALLS_HTTP_API"))

    def test_fstring_url_with_env_host_becomes_token(self, tmp_path):
        qf = _app(tmp_path, """
            import os, requests
            def main(e, c):
                requests.get(f"https://{os.environ['API_HOST']}/v2/jobs")
        """)
        (obj,) = _objs(qf, "CALLS_HTTP_API")
        assert obj == "APIEndpoint:GET https://${API_HOST}/v2/jobs"
        assert "API_HOST" in qf.pending_names

    def test_non_url_first_arg_never_fires(self, tmp_path):
        qf = _app(tmp_path, """
            def main(e, c):
                print("http status was fine")
                e.update("https ok")
        """)
        assert _objs(qf, "CALLS_HTTP_API") == []

    def test_s3_ops_and_aws_ops_never_double_fire(self, tmp_path):
        # An SQS-style AWS call carrying a URL-valued parameter is an AWS
        # resource address, not an outbound API call.
        qf = _app(tmp_path, """
            import boto3
            def main(e, c):
                boto3.client('sqs').send_message(
                    QueueUrl="https://sqs.us-east-1.amazonaws.com/1/q", MessageBody="x")
        """)
        assert _objs(qf, "CALLS_HTTP_API") == []

    def test_internal_helper_with_url_still_gets_call_edge(self, tmp_path):
        qf = _app(tmp_path, """
            def fetch(url):
                return url
            def main(e, c):
                fetch("https://svc.example/ping")
        """)
        assert "APIEndpoint:https://svc.example/ping" in _objs(qf, "CALLS_HTTP_API")
        assert any(o.endswith(".fetch") for o in _objs(qf, "CALLS"))


# --------------------------------------------------------------------------
# A9 — secrets / parameters / SNS, via botocore's own model
# --------------------------------------------------------------------------
class TestA9AwsResourceOps:
    def test_get_secret_value_records_name_only(self, tmp_path):
        qf = _app(tmp_path, """
            import boto3
            def main(e, c):
                boto3.client('secretsmanager').get_secret_value(SecretId="redshift-secret-name")
        """)
        assert "Secret:redshift-secret-name" in _objs(qf, "READS_SECRET")

    def test_get_parameter(self, tmp_path):
        qf = _app(tmp_path, """
            import boto3
            def main(e, c):
                boto3.client('ssm').get_parameter(Name="/sampleapp/config/sm-arn", WithDecryption=True)
        """)
        assert "Parameter:/sampleapp/config/sm-arn" in _objs(qf, "READS_SSM_PARAMETER")

    def test_get_parameters_list_each_literal(self, tmp_path):
        qf = _app(tmp_path, """
            import boto3
            def main(e, c):
                boto3.client('ssm').get_parameters(Names=["/a/one", "/a/two"])
        """)
        objs = _objs(qf, "READS_SSM_PARAMETER")
        assert "Parameter:/a/one" in objs and "Parameter:/a/two" in objs

    def test_sns_publish_topic_arn_collapses(self, tmp_path):
        qf = _app(tmp_path, """
            import boto3
            def main(e, c):
                boto3.client('sns').publish(
                    TopicArn="arn:aws:sns:us-east-1:1:ex0-etl-status", Message="done")
        """)
        assert "Topic:ex0-etl-status" in _objs(qf, "PUBLISHES_TO_SNS")

    def test_secret_name_from_env_becomes_token(self, tmp_path):
        qf = _app(tmp_path, """
            import os, boto3
            def main(e, c):
                boto3.client('secretsmanager').get_secret_value(
                    SecretId=os.environ['SECRET_NAME'])
        """)
        assert "Secret:${SECRET_NAME}" in _objs(qf, "READS_SECRET")
        assert "SECRET_NAME" in qf.pending_names

    def test_generic_publish_without_topic_never_fires(self, tmp_path):
        # `publish` is a common method name; without the operation's own
        # parameter shape it must NOT be read as SNS.
        qf = _app(tmp_path, """
            def main(e, bus):
                bus.publish("user.created", payload=e)
        """)
        assert _objs(qf, "PUBLISHES_TO_SNS") == []

    def test_secret_value_content_never_captured(self, tmp_path):
        # The VALUE returned by a secret fetch must never appear in any fact.
        qf = _app(tmp_path, """
            import boto3, json
            def main(e, c):
                s = boto3.client('secretsmanager').get_secret_value(SecretId="db-cred")
                pw = json.loads(s["SecretString"])["password"]
                return pw
        """)
        assert "Secret:db-cred" in _objs(qf, "READS_SECRET")
        joined = " ".join(q.object for q in qf.quads)
        assert "password" not in joined and "SecretString" not in joined
