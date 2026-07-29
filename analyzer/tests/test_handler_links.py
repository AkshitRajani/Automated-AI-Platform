"""
Adversarial tests for A13 — the lambda→code translation.

The disease: 15 folders each holding `lambda_handler.py` with `main`, every
terraform entry declaring the identical handler string — and the old join wrote
15 edges to `Function:lambda_handler.main`, a node that exists nowhere.

The law under test: an edge either lands on a REAL code function (unique
suffix, or the entry's own path hint deciding) — or it does not exist, and the
question is recorded in `handler_unlinked`. Never a ghost.
"""
import textwrap

from analyzer.emit import to_dict
from analyzer.extract import analyze


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text), encoding="utf-8")


def _handled(qf):
    return {q.subject: q for q in qf.quads if q.predicate == "HANDLED_BY"}


def _lambda_code(root, folders):
    for f in folders:
        _write(root, f"src/{f}/lambda_handler.py", """
            import os, boto3
            def main(event, context):
                boto3.client('s3').put_object(Bucket=os.environ['B'], Key='out.json')
        """)


class TestHintDisambiguation:
    def test_s3_key_hint_links_each_lambda_to_its_folder(self, tmp_path):
        _lambda_code(tmp_path, ["ex0-data-pull", "ex0-data-upload"])
        _write(tmp_path, "tfe/vars.tfvars", """
            lambda-list = {
              "ex0-data-pull" = {
                function_name = "data-pull-tf"
                handler = "lambda_handler.main"
                s3_key = "FORKLIFT/ex0-data-pull-FORKLIFT_MARKER.zip"
              }
              "ex0-data-upload" = {
                function_name = "data-upload-tf"
                handler = "lambda_handler.main"
                s3_key = "FORKLIFT/ex0-data-upload-FORKLIFT_MARKER.zip"
              }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        links = _handled(qf)
        assert links["LambdaFunction:data-pull-tf"].object \
            == "Function:src.ex0-data-pull.lambda_handler.main"
        assert links["LambdaFunction:data-upload-tf"].object \
            == "Function:src.ex0-data-upload.lambda_handler.main"
        assert qf.handler_unlinked == []

    def test_no_hint_means_no_edge_and_a_visible_question(self, tmp_path):
        _lambda_code(tmp_path, ["ex0-data-pull", "ex0-data-upload"])
        _write(tmp_path, "tfe/vars.tfvars", """
            lambda-list = {
              "ex0-data-pull" = {
                function_name = "data-pull-tf"
                handler = "lambda_handler.main"
              }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        assert _handled(qf) == {}                       # NO ghost edge, at all
        (entry,) = qf.handler_unlinked
        assert entry["lambda"] == "LambdaFunction:data-pull-tf"
        assert entry["handler"] == "lambda_handler.main"
        assert len(entry["candidates"]) == 2            # both folders listed
        assert any("NOT linked by guesswork" in n for n in qf.analyzer_notes)

    def test_ghost_target_never_appears_anywhere(self, tmp_path):
        _lambda_code(tmp_path, ["a", "b"])
        _write(tmp_path, "tfe/vars.tfvars", """
            lambda-list = {
              "a" = { function_name = "a-tf"
                      handler = "lambda_handler.main" }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        entity_ids = {e.id for e in qf.entities}
        for q in qf.quads:
            if q.predicate == "HANDLED_BY":
                assert q.object in entity_ids           # every survivor is real

    def test_hint_matching_multiple_candidates_stays_unlinked(self, tmp_path):
        # The hint names a PARENT folder both candidates share — that decides
        # nothing, and deciding anyway would be a guess.
        _lambda_code(tmp_path, ["etl/step-one", "etl/step-two"])
        _write(tmp_path, "tfe/vars.tfvars", """
            lambda-list = {
              "one" = { function_name = "one-tf"
                        handler = "lambda_handler.main"
                        s3_key = "FORKLIFT/etl-bundle.zip" }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        assert _handled(qf) == {}
        assert len(qf.handler_unlinked) == 1

    def test_code_absent_from_repo_is_a_listed_question(self, tmp_path):
        # EMR-utility style: the lambda's code simply isn't in this upload.
        _write(tmp_path, "tfe/vars.tfvars", """
            lambda-list = {
              "emr-check" = { function_name = "emr-check-tf"
                              handler = "MoveS3ToPg.lambda_handler" }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        assert _handled(qf) == {}
        (entry,) = qf.handler_unlinked
        assert entry["handler"] == "MoveS3ToPg.lambda_handler"
        assert entry["candidates"] == []                # honestly: nothing to link

    def test_distinctive_handler_needs_no_hint(self, tmp_path):
        # Field-observed convention: handler = "<module-named-after-folder>.lambda_handler"
        _write(tmp_path, "src/lambda/ex0-athena-envs-compare/ex0-athena-envs-compare.py", """
            def lambda_handler(event, context):
                return event
        """)
        _write(tmp_path, "tfe/vars.tfvars", """
            lambda-list = {
              "ex0-athena-envs-compare" = {
                function_name = "athena-envs-compare-tf"
                handler = "ex0-athena-envs-compare.lambda_handler"
              }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        links = _handled(qf)
        assert links["LambdaFunction:athena-envs-compare-tf"].object \
            == "Function:src.lambda.ex0-athena-envs-compare.ex0-athena-envs-compare.lambda_handler"

    def test_sampleapp_scale_fifteen_folders_all_link_via_hints(self, tmp_path):
        folders = [f"ex0-step-{i:02d}" for i in range(15)]
        _lambda_code(tmp_path, folders)
        entries = "\n".join(
            f'  "{f}" = {{ function_name = "{f[4:]}-tf"\n'
            f'    handler = "lambda_handler.main"\n'
            f'    s3_key = "FORKLIFT/{f}-FORKLIFT_MARKER.zip" }}'
            for f in folders)
        _write(tmp_path, "tfe/vars.tfvars", "lambda-list = {\n%s\n}\n" % entries)
        qf = analyze(str(tmp_path), "t")
        links = _handled(qf)
        assert len(links) == 15
        for f in folders:
            assert links[f"LambdaFunction:{f[4:]}-tf"].object \
                == f"Function:src.{f}.lambda_handler.main"
        assert qf.handler_unlinked == []

    def test_journey_reaches_code_facts_through_the_link(self, tmp_path):
        # The point of it all: journey -> lambda -> code -> S3 fact, end to end.
        _lambda_code(tmp_path, ["ex0-uploader"])
        _write(tmp_path, "tfe/vars.tfvars", """
            B = "real-bucket"
            lambda-list = {
              "ex0-uploader" = {
                function_name = "uploader-tf"
                handler = "lambda_handler.main"
                s3_key = "FORKLIFT/ex0-uploader-x.zip"
              }
            }
        """)
        _write(tmp_path, "wf/machine.asl.json", """
        {
          "StartAt": "Upload",
          "States": {
            "Upload": { "Type": "Task", "Resource": "uploader-tf", "End": true }
          }
        }
        """)
        qf = analyze(str(tmp_path), "t")
        links = _handled(qf)
        fn = links["LambdaFunction:uploader-tf"].object
        s3 = [q for q in qf.quads
              if q.subject == fn and q.predicate == "WRITES_TO_S3"]
        assert s3 and s3[0].object == "S3Object:real-bucket/out.json"

    def test_metadata_carries_the_unlinked_list(self, tmp_path):
        _lambda_code(tmp_path, ["a", "b"])
        _write(tmp_path, "tfe/vars.tfvars", """
            lambda-list = {
              "a" = { function_name = "a-tf"
                      handler = "lambda_handler.main" }
            }
        """)
        qf = analyze(str(tmp_path), "t")
        meta = to_dict(qf)["metadata"]
        assert meta["handler_unlinked"] and \
            meta["handler_unlinked"][0]["lambda"] == "LambdaFunction:a-tf"
