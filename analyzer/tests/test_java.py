"""
Java extraction tests.

Two layers, mirroring the bridge's own split:
  - unit tests for the Python bridge (no JDK needed — canned helper records);
  - an integration test over the java_demo fixture (skipped when the JDK or the
    built helper is absent, never silently green).
"""
import os
import shutil

import pytest

from analyzer import java_extract
from analyzer.emit import to_dict
from analyzer.models import Entity, Quad, QuadFile

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "java_demo")

_helper_ready = shutil.which("java") is not None and java_extract.helper_classpath() is not None
needs_helper = pytest.mark.skipif(not _helper_ready,
                                  reason="JDK or built java_helper not available")


# --- unit: bridge conversion (no JDK) ----------------------------------------
def test_aws_s3_put_classified_as_write():
    quads, notes = java_extract._aws_quads([{
        "subject": "Method:a.B.m", "service": "s3", "operation": "putObject",
        "literals": {"bucket": "b1", "key": "k1"}, "file": "f.java", "line": 3,
    }])
    assert len(quads) == 1 and not notes
    q = quads[0]
    assert q.predicate == "WRITES_TO_S3"
    assert q.object == "S3Object:b1/k1"
    assert q.resolved and q.language == "java"


def test_aws_s3_get_classified_as_read():
    quads, _ = java_extract._aws_quads([{
        "subject": "Method:a.B.m", "service": "s3", "operation": "getObject",
        "literals": {"bucket": "b1", "key": "k1"}, "file": "f.java", "line": 3,
    }])
    assert quads[0].predicate == "READS_FROM_S3"


def test_aws_lambda_invoke():
    quads, _ = java_extract._aws_quads([{
        "subject": "Method:a.B.m", "service": "lambda", "operation": "invoke",
        "literals": {"functionName": "fn-x"}, "file": "f.java", "line": 9,
    }])
    assert quads[0].predicate == "INVOKES_LAMBDA"
    assert quads[0].object == "LambdaFunction:fn-x"


def test_aws_unknown_service_becomes_note_not_guess():
    quads, notes = java_extract._aws_quads([{
        "subject": "Method:a.B.m", "service": "no-such-svc", "operation": "doThing",
        "literals": {}, "file": "f.java", "line": 2,
    }])
    assert not quads
    assert len(notes) == 1 and "no-such-svc.doThing" in notes[0].text


def test_aws_builder_literal_not_in_shape_is_dropped():
    quads, _ = java_extract._aws_quads([{
        "subject": "Method:a.B.m", "service": "s3", "operation": "putObject",
        "literals": {"bucket": "b1", "notAMember": "x"}, "file": "f.java", "line": 3,
    }])
    assert quads[0].object == "S3Object:b1"          # bogus key validated away


def test_sql_quads_via_sqlglot_including_concat():
    quads = java_extract._sql_quads([
        {"subject": "Method:a.B.m", "sql":
         "SELECT o.id FROM orders o JOIN customers c ON o.cid = c.id",
         "resolved": True, "file": "f.java", "line": 5},
        {"subject": "Method:a.B.m", "sql":
         "INSERT INTO audit_log (e) VALUES ('?')",
         "resolved": False, "file": "f.java", "line": 8},
    ])
    by_obj = {q.object: q for q in quads}
    assert by_obj["Table:orders"].predicate == "QUERIES_DATABASE"
    assert by_obj["Table:customers"].predicate == "QUERIES_DATABASE"
    assert by_obj["Table:audit_log"].predicate == "WRITES_DATABASE"
    assert not by_obj["Table:audit_log"].resolved      # concat SQL stays honest


def test_missing_helper_raises_never_skips(monkeypatch, tmp_path):
    java_file = tmp_path / "A.java"
    java_file.write_text("public class A {}")
    monkeypatch.setenv("ANALYZER_JAVA_HELPER", str(tmp_path / "nowhere"))
    with pytest.raises(RuntimeError, match="never silently skipped"):
        java_extract.extract_java(str(tmp_path))


# --- unit: emit carries per-fact language -------------------------------------
def test_emit_stamps_true_language_per_quad():
    qf = QuadFile(app_id="mix")
    qf.entities.append(Entity(id="Class:a.B", type="Class", name="a.B", language="java"))
    qf.quads.append(Quad("Class:a.B", "DEFINES", "Method:a.B.m", language="java"))
    qf.quads.append(Quad("Module:m", "DEFINES", "Function:m.f"))      # python default
    d = to_dict(qf)
    langs = {q["context"]["source_language"] for q in d["quads"]}
    assert langs == {"java", "python"}
    assert d["metadata"]["languages_detected"] == ["java", "python"]


# --- integration: the whole pass over the fixture ------------------------------
@needs_helper
def test_fixture_end_to_end():
    from analyzer.extract import analyze
    qf = analyze(FIXTURE, "java-demo")

    ids = {e.id for e in qf.entities}
    assert "Class:com.demo.api.OrderController" in ids
    assert "Method:com.demo.svc.OrderService.findOrder" in ids
    # every SOURCE entity is java; the derived journey layer rides on top
    assert all(e.language == "java" for e in qf.entities if e.language != "journey")

    facts = {(q.subject, q.predicate, q.object) for q in qf.quads}
    # cross-file call resolution (the hard requirement)
    assert ("Method:com.demo.api.OrderController.getOrder", "CALLS",
            "Method:com.demo.svc.OrderService.findOrder") in facts
    assert ("Method:com.demo.api.OrderController.createOrder", "CALLS",
            "Method:com.demo.svc.AuditService.record") in facts
    # intra-class private call
    assert ("Method:com.demo.svc.OrderService.createOrder", "CALLS",
            "Method:com.demo.svc.OrderService.archiveKey") in facts
    # Spring endpoint with class-level base path joined
    assert ("Method:com.demo.api.OrderController.getOrder", "EXPOSES_ENDPOINT",
            "APIEndpoint:GET /api/orders/{id}") in facts
    # env var, S3 write with builder literals, lambda invoke
    assert ("Method:com.demo.svc.OrderService.findOrder", "READS_ENV_VAR",
            "Parameter:DB_HOST") in facts
    assert ("Method:com.demo.svc.OrderService.createOrder", "WRITES_TO_S3",
            "S3Object:order-archive/orders/latest.json") in facts
    assert ("Method:com.demo.svc.OrderService.createOrder", "INVOKES_LAMBDA",
            "LambdaFunction:order-notifier") in facts
    # SQL via sqlglot: JOIN pulls both tables; concat write is unresolved
    assert ("Method:com.demo.svc.OrderService.findOrder", "QUERIES_DATABASE",
            "Table:customers") in facts
    concat = [q for q in qf.quads
              if q.predicate == "WRITES_DATABASE" and q.object == "Table:audit_log"]
    assert concat and not concat[0].resolved

    assert all(q.language == "java" for q in qf.quads if q.language != "journey")


@needs_helper
def test_fixture_deterministic():
    from analyzer.extract import analyze
    from analyzer.emit import to_yaml
    assert to_yaml(analyze(FIXTURE, "java-demo")) == to_yaml(analyze(FIXTURE, "java-demo"))


# --- stress fixture: the cases the quality run surfaced -------------------------
STRESS = os.path.join(os.path.dirname(__file__), "fixtures", "java_stress")


@needs_helper
def test_stress_broken_file_never_leaks():
    """A file that doesn't parse is skipped entirely — JavaParser's error
    recovery must not leak partial facts (regression: it once leaked a Module)."""
    from analyzer.extract import analyze
    qf = analyze(STRESS, "java-stress")
    assert not any("Broken" in e.id for e in qf.entities)
    assert not any("Broken" in (e.source.file_path if e.source else "") for e in qf.entities)
    assert not any("Broken" in q.file_path for q in qf.quads)


@needs_helper
def test_stress_hard_resolution_cases():
    from analyzer.extract import analyze
    qf = analyze(STRESS, "java-stress")
    facts = {(q.subject, q.predicate, q.object) for q in qf.quads}
    # call through an interface-typed field resolves to the interface method
    assert ("Method:com.lend.api.LoanController.getLoan", "CALLS",
            "Method:com.lend.svc.LoanService.findLoan") in facts
    # sfn package name maps to stepfunctions via AWS's own serviceId metadata
    assert any(p == "INVOKES_STEP_FUNCTION" and "loan-boarding" in o
               for _, p, o in facts)
    # `var`-declared JDBC connection still yields SQL facts (JSS type inference),
    # and a multi-line SQL string (concat of pure literals) stays fully resolved
    assert ("Method:com.lend.svc.LoanServiceImpl.findLoan", "QUERIES_DATABASE",
            "Table:loan_balances") in facts
    multiline = [q for q in qf.quads
                 if q.subject == "Method:com.lend.svc.LoanServiceImpl.findLoan"
                 and q.predicate == "QUERIES_DATABASE"]
    assert multiline and all(q.resolved for q in multiline)
    # RequestMapping(method = PUT) + class base path
    assert ("Method:com.lend.api.LoanController.updateLoan", "EXPOSES_ENDPOINT",
            "APIEndpoint:PUT /loans/{id}") in facts
    # v1 SDK positional args degrade honestly to a symbolic bucket
    v1 = [q for q in qf.quads if q.subject == "Method:com.lend.batch.NightlyJob.run"
          and q.predicate == "READS_FROM_S3"]
    assert v1 and not v1[0].resolved and v1[0].object == "S3Object:<bucket>"
