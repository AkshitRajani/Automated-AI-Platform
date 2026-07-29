"""Doc 10 name resolution — repo-declared harvest + env-var tokenization. Pure."""
import os

from analyzer.extract import analyze
from analyzer.wiring import harvest_environment


def test_harvest_takes_only_word_for_word_literals():
    doc = {
        "provider": {"environment": {"GLOBAL_BUCKET": "real-bucket"}},
        "functions": {
            "f": {"handler": "a.h",
                  "environment": {"TABLE": "real_table",
                                  "DERIVED": "${self:custom.x}",   # unresolved itself
                                  "NUM": 8}},
        },
    }
    got = harvest_environment(doc)
    assert got == {"GLOBAL_BUCKET": "real-bucket", "TABLE": "real_table", "NUM": "8"}


def test_env_indirection_resolved_by_the_declared_answer(tmp_path):
    """v = os.environ["K"] used as a resource name becomes ${K}; the manifest
    declares K word-for-word, and the analyzer now APPLIES that answer before
    journeys (resolve-first-then-walk) — so the emitted fact carries the real
    name, fully resolved, and nothing is pending. The token and the answer still
    meet on one string; the meeting just happens inside the analyzer."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "h.py").write_text(
        "import os, boto3\n"
        "s3 = boto3.client('s3')\n"
        "def handler(event, context):\n"
        "    bucket = os.environ['OUT_BUCKET']\n"
        "    s3.put_object(Bucket=bucket, Key='a/b.csv')\n")
    (app / "serverless.yml").write_text(
        "functions:\n  f:\n    handler: h.handler\n"
        "    environment:\n      OUT_BUCKET: real-out-bucket\n")
    qf = analyze(str(app), "T")
    writes = [q for q in qf.quads if q.predicate == "WRITES_TO_S3"]
    assert writes and writes[0].object == "S3Object:real-out-bucket/a/b.csv"
    assert writes[0].resolved and writes[0].confidence == 1.0
    assert qf.bindings == {"OUT_BUCKET": "real-out-bucket"}
    assert qf.pending_names == []                      # nothing left to ask


def test_unanswered_token_blocks_journeys(tmp_path):
    """A ${token} nobody answers is the unskippable gate: it lands in
    pending_names and the quad gets NO journey entities at all."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "h.py").write_text(
        "import os, boto3\n"
        "s3 = boto3.client('s3')\n"
        "def handler(event, context):\n"
        "    bucket = os.environ['MYSTERY_BUCKET']\n"
        "    s3.put_object(Bucket=bucket, Key='a/b.csv')\n")
    (app / "serverless.yml").write_text(
        "functions:\n  f:\n    handler: h.handler\n"
        "    events:\n      - httpApi:\n          method: post\n          path: /go\n")
    qf = analyze(str(app), "T")
    assert qf.pending_names == ["MYSTERY_BUCKET"]
    assert not [e for e in qf.entities if e.type in ("Journey", "BehaviorGroup")]


def test_worksheet_answer_unblocks_journeys(tmp_path):
    """The human's worksheet answer resolves the blank and the journey pass runs
    on the completed graph (resolve first, then walk)."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "h.py").write_text(
        "import os, boto3\n"
        "s3 = boto3.client('s3')\n"
        "def handler(event, context):\n"
        "    bucket = os.environ['MYSTERY_BUCKET']\n"
        "    s3.put_object(Bucket=bucket, Key='a/b.csv')\n")
    (app / "serverless.yml").write_text(
        "functions:\n  f:\n    handler: h.handler\n"
        "    events:\n      - httpApi:\n          method: post\n          path: /go\n")
    sheets = tmp_path / "sheets"
    sheets.mkdir()
    (sheets / "t_worksheet.yaml").write_text("MYSTERY_BUCKET: real-bucket\n")
    qf = analyze(str(app), "T", names_dir=str(sheets))
    assert qf.pending_names == []
    writes = [q for q in qf.quads if q.predicate == "WRITES_TO_S3"]
    assert writes and writes[0].object == "S3Object:real-bucket/a/b.csv"
    assert [e for e in qf.entities if e.type in ("Journey", "BehaviorGroup")]
