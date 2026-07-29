"""
Scripted end-to-end tests of the INTERACTIVE CLI — the real `python -m analyzer`
run as a subprocess with piped answers (`--ask` forces interactive without a
TTY). Found live on 2026-07-22: the environment answer fell through into
pre-environment questions, and running out of input crashed with a raw
EOFError. Both are pinned here.
"""
import json
import os
import subprocess
import sys
import textwrap

import yaml


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


def _full_app(tmp_path):
    """Every question kind at once: env competition + declared names + a blank."""
    _write(tmp_path, "app/tfe/workspace_vars.test.tfvars", """
        B = "test-bucket"
        lambda-list = {
          "ex0-pull" = { function_name = "pull-tf"
                         handler = "lambda_handler.main"
                         s3_key = "FORKLIFT/ex0-pull-x.zip" }
        }
    """)
    _write(tmp_path, "app/tfe/workspace_vars.devl.tfvars", """
        B = "devl-bucket"
        lambda-list = {
          "ex0-pull" = { function_name = "pull-devl-tf"
                         handler = "lambda_handler.main"
                         s3_key = "FORKLIFT/ex0-pull-x.zip" }
        }
    """)
    _write(tmp_path, "app/src/ex0-pull/lambda_handler.py", """
        import os, boto3
        def main(e, c):
            boto3.client('s3').put_object(Bucket=os.environ['B'], Key='out.json')
    """)
    _write(tmp_path, "app/wf/machine.asl.json", json.dumps({
        "StartAt": "Run",
        "States": {"Run": {"Type": "Task", "Resource": "${runner_arn}",
                           "End": True}}}))


def _run(tmp_path, stdin_text):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    return subprocess.run(
        [sys.executable, "-m", "analyzer", "app", "--app-id", "t",
         "--out", "q.yaml", "--ask", "--names", "sheets"],
        input=stdin_text, capture_output=True, text=True,
        cwd=str(tmp_path), env=env, timeout=120)


class TestInteractiveConversation:
    def test_full_three_round_conversation_completes(self, tmp_path):
        _full_app(tmp_path)
        # round 1: choose env "2" (test file, alphabetically second)
        # round 2: accept the declared names ("y")
        # round 3: answer the one remaining blank
        r = _run(tmp_path, "2\ny\nreal-runner-tf\n")
        assert r.returncode == 0, r.stderr
        assert "journeys:" in r.stderr
        sheet = yaml.safe_load(open(tmp_path / "sheets" / "t_worksheet.yaml"))
        assert sheet["environment_file"].endswith("workspace_vars.test.tfvars")
        assert str(sheet["confirm_lambda_names"]).lower() in ("yes", "true")
        assert sheet["runner_arn"] == "real-runner-tf"
        quad = yaml.safe_load(open(tmp_path / "q.yaml"))
        meta = quad["metadata"]
        assert meta["journeys_computed"] is True
        assert meta["environment_file"].endswith("workspace_vars.test.tfvars")
        # the chosen environment's binding answered ${B} — no human ever
        # answered it, because the env round returned before asking blanks:
        assert "B" not in sheet
        assert any(q["object"] == "S3Object:test-bucket/out.json"
                   for q in quad["quads"] if q["predicate"] == "WRITES_TO_S3")

    def test_env_round_never_asks_pre_environment_blanks(self, tmp_path):
        _full_app(tmp_path)
        # Supply ONLY the environment choice; the process then runs out of
        # input. The ${B} question must never have been asked in round 1 —
        # the env answer returns immediately.
        r = _run(tmp_path, "2\n")
        assert "${B}" not in r.stdout          # not asked pre-environment
        sheet = yaml.safe_load(open(tmp_path / "sheets" / "t_worksheet.yaml"))
        assert "B" not in sheet

    def test_input_running_out_halts_cleanly_never_tracebacks(self, tmp_path):
        _full_app(tmp_path)
        r = _run(tmp_path, "2\n")              # answers dry up mid-conversation
        assert r.returncode == 2               # clean checkpoint halt
        assert "Traceback" not in r.stderr
        assert "no more input" in r.stderr
        # ... and the answer given so far was saved:
        sheet = yaml.safe_load(open(tmp_path / "sheets" / "t_worksheet.yaml"))
        assert sheet["environment_file"].endswith("workspace_vars.test.tfvars")

    def test_headless_stays_headless(self, tmp_path):
        _full_app(tmp_path)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))
        r = subprocess.run(
            [sys.executable, "-m", "analyzer", "app", "--app-id", "t",
             "--out", "q.yaml", "--no-ask", "--names", "sheets"],
            input="", capture_output=True, text=True,
            cwd=str(tmp_path), env=env, timeout=120)
        assert r.returncode == 2
        assert "HALT" in r.stderr
        assert "Traceback" not in r.stderr
