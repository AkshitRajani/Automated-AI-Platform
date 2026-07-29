"""
Adversarial tests for A11 — SQL kept in config files.

The rule under test: a config string is SQL only if sqlglot's grammar parses it
as a real statement touching a table. Prose, paths, workflow docs, and
SQL-looking noise must never produce facts.
"""
import json
import textwrap

from analyzer.extract import analyze, _strict_sql_facts


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text) if rel.endswith(".py") else text,
                 encoding="utf-8")


def _objs(qf, pred, subject_prefix=None):
    return [q.object for q in qf.quads if q.predicate == pred
            and (subject_prefix is None or q.subject.startswith(subject_prefix))]


class TestStrictSqlGuard:
    def test_real_select(self):
        assert _strict_sql_facts(
            "SELECT control_count FROM dbm.import_control WHERE run_id = 1")

    def test_real_insert(self):
        facts = _strict_sql_facts("INSERT INTO audit_log (a) VALUES (1)")
        assert ("audit_log", True) in facts

    def test_prose_rejected(self):
        assert _strict_sql_facts("Please select the correct environment from the list") == []

    def test_path_rejected(self):
        assert _strict_sql_facts("config/app/emr/datasets.json") == []

    def test_bare_identifier_rejected(self):
        assert _strict_sql_facts("import_control_check") == []

    def test_tableless_select_rejected(self):
        assert _strict_sql_facts("SELECT 1") == []

    def test_url_rejected(self):
        assert _strict_sql_facts("https://api.planner.com/2/0/models") == []


class TestConfigFileFacts:
    def test_json_notebook_yields_table_facts(self, tmp_path):
        _write(tmp_path, "config/etl_import_sqls.json", json.dumps({
            "import_control_check":
                "SELECT control_count FROM dbm.import_control WHERE run_id = %s",
            "load_status_update":
                "UPDATE dbm.load_status SET state = 'DONE' WHERE id = %s",
            "greeting": "hello there, operator",
            "s3_path": "inbound/api/pull.csv",
        }))
        qf = analyze(str(tmp_path), "t")
        assert "Table:import_control" in _objs(qf, "QUERIES_DATABASE", "ConfigFile:")
        assert "Table:load_status" in _objs(qf, "WRITES_DATABASE", "ConfigFile:")
        cfgs = [e for e in qf.entities if e.type == "ConfigFile"]
        assert len(cfgs) == 1 and cfgs[0].id == "ConfigFile:config/etl_import_sqls.json"

    def test_config_without_sql_creates_nothing(self, tmp_path):
        _write(tmp_path, "config/app.json", json.dumps(
            {"bucket": "ex0-test", "path": "a/b/c.csv", "note": "select wisely"}))
        qf = analyze(str(tmp_path), "t")
        assert not any(e.type == "ConfigFile" for e in qf.entities)

    def test_sql_file_whole_content(self, tmp_path):
        _write(tmp_path, "sql/report.sql",
               "SELECT total FROM finance.balance_fact WHERE period = '2026-06'")
        qf = analyze(str(tmp_path), "t")
        assert "Table:balance_fact" in _objs(qf, "QUERIES_DATABASE", "ConfigFile:")

    def test_yaml_config_also_read(self, tmp_path):
        _write(tmp_path, "config/queries.yaml",
               'checks:\n  row_count: "SELECT count(*) FROM dbm.rows_loaded"\n')
        qf = analyze(str(tmp_path), "t")
        assert "Table:rows_loaded" in _objs(qf, "QUERIES_DATABASE", "ConfigFile:")

    def test_state_machine_doc_untouched(self, tmp_path):
        # A workflow definition's strings must not become SQL facts.
        _write(tmp_path, "wf/machine.asl.json", json.dumps({
            "StartAt": "A",
            "States": {"A": {"Type": "Task", "Resource": "real-a-tf", "End": True}},
        }))
        qf = analyze(str(tmp_path), "t")
        assert not any(e.type == "ConfigFile" for e in qf.entities)


class TestKeyLiteralJoin:
    CONFIG = json.dumps({
        "import_control_check":
            "SELECT control_count FROM dbm.import_control WHERE run_id = %s",
        "unrelated_note": "just words",
    })

    def test_function_naming_the_key_gets_the_tables(self, tmp_path):
        _write(tmp_path, "config/sqls.json", self.CONFIG)
        _write(tmp_path, "src/job.py", """
            import json
            def validate(run_id):
                sqls = json.load(open('config/sqls.json'))
                q = sqls["import_control_check"]
                return q
        """)
        qf = analyze(str(tmp_path), "t")
        fn = "Function:src.job.validate"
        assert "Table:import_control" in _objs(qf, "QUERIES_DATABASE", fn)
        assert "ConfigFile:config/sqls.json" in _objs(qf, "READS_FILE", fn)

    def test_function_not_naming_any_key_gets_nothing(self, tmp_path):
        _write(tmp_path, "config/sqls.json", self.CONFIG)
        _write(tmp_path, "src/other.py", """
            def unrelated():
                return "something else entirely"
        """)
        qf = analyze(str(tmp_path), "t")
        assert _objs(qf, "QUERIES_DATABASE", "Function:src.other") == []
        assert _objs(qf, "READS_FILE", "Function:src.other") == []

    def test_no_duplicate_facts_when_key_named_twice(self, tmp_path):
        _write(tmp_path, "config/sqls.json", self.CONFIG)
        _write(tmp_path, "src/job.py", """
            def a(s):
                return s["import_control_check"]
            def b(s):
                return s.get("import_control_check")
        """)
        qf = analyze(str(tmp_path), "t")
        for fn in ("Function:src.job.a", "Function:src.job.b"):
            assert _objs(qf, "QUERIES_DATABASE", fn) == ["Table:import_control"]
