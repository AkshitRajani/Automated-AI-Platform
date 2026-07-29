"""Renderer: load_doc round-trip + the nine-section markdown has all 9 sections."""
import json
import os

from requirement_agent.render import load_doc, render_markdown, render_set
from requirement_agent.tests.fakes import make_doc, write_doc


def test_load_doc_validates(tmp_path):
    rel = write_doc(tmp_path)
    doc = load_doc(os.path.join(str(tmp_path), rel))
    assert doc.unit == "LambdaHandler:handler_a"
    assert doc.missing_sections() == []        # all nine canonical sections present


def test_render_markdown_has_all_sections():
    md = render_markdown(make_doc())
    for heading in ["## 1. System Overview", "## 2. Input Specification",
                    "## 3. Consolidated Requirements", "## 4. Output Specification",
                    "## 5. Function Specification", "## 6. User Stories",
                    "## 7. Traceability Matrix", "## 8. Confidence Mapping",
                    "## 9. Gap Analysis"]:
        assert heading in md
    # grounded names + the negative path + the code-derived stamp are visible
    assert "s3://bucket/key.csv" in md
    assert "negative path" in md
    assert "code-derived" in md


def test_render_set_writes_markdown_files(tmp_path):
    rel = write_doc(tmp_path)
    written = render_set(str(tmp_path), [rel])
    assert len(written) == 1
    assert written[0].endswith(".md")
    assert os.path.isfile(written[0])


def test_load_doc_raises_on_garbage(tmp_path):
    bad = os.path.join(str(tmp_path), "bad.json")
    with open(bad, "w") as fh:
        json.dump({"not": "a requirement doc"}, fh)   # missing required 'unit'
    try:
        load_doc(bad)
        assert False, "expected validation error"
    except Exception:
        pass
