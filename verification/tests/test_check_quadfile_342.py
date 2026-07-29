"""
The verification kit must SHOW everything analyzer 3.4.2 captures — and stay
honest about quads produced by older analyzers. Runs the real script as a
subprocess, exactly as the client runs it.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve()
IMPL = HERE.parents[2]
SCRIPT = IMPL / "verification" / "check_quadfile.py"


def _build_rich_quad(tmp_path):
    app = tmp_path / "app"
    (app / "tfe").mkdir(parents=True)
    (app / "src" / "f0n-job").mkdir(parents=True)
    (app / "config").mkdir()
    (app / "tfe" / "vars.tfvars").write_text(textwrap.dedent("""
        B = "real-bucket-us-east-1"
        lambda-list = {
          "f0n-job" = { function_name = "job-tf"
                        handler = "lambda_handler.main"
                        s3_key = "FORKLIFT/f0n-job-x.zip" }
        }
    """))
    (app / "src" / "f0n-job" / "lambda_handler.py").write_text(textwrap.dedent("""
        import os, boto3, requests
        def main(e, c):
            requests.post("https://api.partner.example/v2/import", json=e)
            boto3.client('secretsmanager').get_secret_value(SecretId="warehouse-cred")
            boto3.client('ssm').get_parameter(Name="/app/config/rate")
            boto3.client('sns').publish(TopicArn="arn:aws:sns:us-east-1:1:job-status", Message="ok")
            boto3.client('s3').put_object(Bucket=os.environ['B'], Key='out/result.json')
            return e["control_count_check"]
    """))
    (app / "config" / "sqls.json").write_text(json.dumps({
        "control_count_check":
            "SELECT control_count FROM dbm.import_control WHERE run_id = 1"}))
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    (sheets / "app_worksheet.yaml").write_text("confirm_lambda_names: yes\n")
    env = dict(os.environ, PYTHONPATH=str(IMPL))
    subprocess.run([sys.executable, "-m", "analyzer", "app", "--app-id", "app",
                    "--out", "rich_q.yaml", "--no-ask", "--names", "sheets"],
                   cwd=str(tmp_path), env=env, check=True, capture_output=True)
    return tmp_path / "rich_q.yaml"


def _run_kit(tmp_path, *argv):
    r = subprocess.run([sys.executable, str(SCRIPT), *argv],
                       cwd=str(tmp_path), capture_output=True, text=True,
                       timeout=120)
    reports = sorted((tmp_path / "verification_report").glob("*.json"))
    data = json.loads(reports[-1].read_text()) if reports else None
    return r, data


def _check(data, name):
    for row in data["results"]:
        if row["check"] == name:
            return row
    raise AssertionError(f"check '{name}' missing from report")


class TestRichQuad:
    def test_every_capture_section_reports_real_values(self, tmp_path):
        quad = _build_rich_quad(tmp_path)
        r, data = _run_kit(tmp_path, str(quad))
        assert r.returncode == 0
        assert _check(data, "analyzer version")["summary"].endswith("3.4.2")
        read = _check(data, "what this run read")
        assert "terraform 1" in read["summary"] and "python 1/1" in read["summary"]
        assert read["data"]["manifest"]["config_files_with_sql"] == 1
        assert "api.partner.example" in str(_check(data, "web calls (outbound APIs)")["data"])
        row = _check(data, "secrets read (names only)")
        assert "warehouse-cred" in str(row["data"])
        assert "never read" in row["summary"]
        assert "/app/config/rate" in str(_check(data, "parameters read")["data"])
        assert "job-status" in str(_check(data, "notifications published")["data"])
        db = _check(data, "database tables")
        assert "import_control" in str(db["data"]) and "config" in db["summary"]
        s3 = _check(data, "bucket names readable")
        assert s3["status"] == "PASS" and "real-bucket-us-east-1" in str(s3["data"])
        links = _check(data, "lambda code links")
        assert links["status"] == "PASS"
        assert _check(data, "lambda names confirmed")["status"] == "PASS"
        assert _check(data, "ready to ingest")["status"] == "PASS"

    def test_secret_values_absent_from_entire_report(self, tmp_path):
        quad = _build_rich_quad(tmp_path)
        _r, data = _run_kit(tmp_path, str(quad))
        assert "SecretString" not in json.dumps(data)


def _build_old_quad(tmp_path):
    """A pre-3.4.2 quad: valid shape, no analyzer_version, no capture kinds."""
    import yaml
    old = {
        "metadata": {"app_id": "legacy", "journeys_computed": True,
                     "pending_names": [], "human_answers": {"X": "v"},
                     "decisions": {}, "unwired": ["Journey:StateMachine:m2"],
                     "analyzer_notes": []},
        "summary": {"entity_count": 2, "quad_count": 2, "note_count": 0},
        "entities": [
            {"id": "StateMachine:m1", "type": "StateMachine", "name": "m1",
             "language": "wiring"},
            {"id": "Journey:StateMachine:m1", "type": "Journey",
             "name": "Journey:StateMachine:m1", "language": "journey"}],
        "quads": [
            {"subject": "Journey:StateMachine:m1", "predicate": "STARTS_AT",
             "object": "StateMachine:m1", "relationship_type": "STARTS_AT",
             "context": {"resolved": True, "confidence": 1.0}},
            {"subject": "StateMachine:m1", "predicate": "FEEDS",
             "object": "State:m1::A", "relationship_type": "FEEDS",
             "context": {"resolved": False, "confidence": 0.5}}],
        "notes": [], "bindings": {},
    }
    p = tmp_path / "old_quad.yaml"
    p.write_text(yaml.safe_dump(old, sort_keys=False))
    return p


class TestOldQuadDegradation:
    def test_missing_version_is_named_not_blamed(self, tmp_path):
        r, data = _run_kit(tmp_path, str(_build_old_quad(tmp_path)))
        row = _check(data, "analyzer version")
        assert row["status"] == "WARN" and "OLDER than" in row["summary"]
        # empty capture sections are INFO (absence explained), never FAIL:
        for name in ("web calls (outbound APIs)", "secrets read (names only)",
                     "parameters read", "database tables"):
            assert _check(data, name)["status"] == "INFO"

    def test_against_old_file_never_crashes(self, tmp_path):
        quad = _build_rich_quad(tmp_path)
        old = _build_old_quad(tmp_path)
        r, data = _run_kit(tmp_path, str(quad), "--against", str(old))
        assert r.returncode == 0
        row = _check(data, "compared with previous run")
        assert "web calls" in row["summary"]
