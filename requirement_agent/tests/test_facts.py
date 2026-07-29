"""AnalyzerFacts: loading the quad file, inventory, per-unit facts, grounding."""
from requirement_agent.facts import AnalyzerFacts
from requirement_agent.tests.fakes import write_quad


def test_inventory_groups_by_type(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    inv = facts.inventory()
    assert inv.app_id == "DEMO"
    assert set(inv.groups) == {"LambdaHandler", "Function", "APIEndpoint"}
    assert inv.groups["LambdaHandler"] == ["LambdaHandler:handler_a"]
    assert inv.endpoints == ["APIEndpoint:GET /x"]
    assert inv.note == ""


def test_facts_for_unit(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    fs = facts.facts_for("LambdaHandler:handler_a")
    preds = {f.predicate for f in fs}
    objs = {f.object for f in fs}
    assert preds == {"WRITES_TO_S3", "CALLS"}
    assert "s3://bucket/key.csv" in objs


def test_resolve_real_and_fake(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    # entity id, entity name, and a quad object are all real
    assert facts.resolve("LambdaHandler:handler_a")
    assert facts.resolve("handler_a")
    assert facts.resolve("s3://bucket/key.csv")
    # an invented name is not
    assert not facts.resolve("s3://nope/invented.csv")
    assert not facts.resolve("")


def test_unit_ids_is_the_coverage_denominator(tmp_path):
    facts = AnalyzerFacts.from_file(write_quad(tmp_path))
    assert set(facts.unit_ids()) == {
        "LambdaHandler:handler_a", "Function:helper_x", "APIEndpoint:GET /x"}
    assert facts.entity("Function:helper_x").type == "Function"
