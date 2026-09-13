#!/usr/bin/env python3
"""Tests for the skill's scripts. Stdlib only — `python3 -m unittest discover tests`.

These cover the logic that surrounds the SAP calls: parsing, guards, URL derivation
and the repo/skill invariants. The SAP calls themselves are not mocked; they are
verified live against a sandbox and recorded in SKILL.md.
"""
import importlib.util
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "sap-gui-control" / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rfc = load("sap_rfc")
adt = load("sap_adt")
ctl = load("sap_control")
db  = load("sap_db")


class TableParsing(unittest.TestCase):
    def test_splits_on_delimiter_and_strips(self):
        out = {"FIELDS": [{"FIELDNAME": "MANDT"}, {"FIELDNAME": "MTEXT"}],
               "DATA": [{"WA": "100 |Demo client  "}]}
        self.assertEqual(rfc.parse_table(out), [{"MANDT": "100", "MTEXT": "Demo client"}])

    def test_empty_result_is_empty_list(self):
        self.assertEqual(rfc.parse_table({"FIELDS": [], "DATA": []}), [])

    def test_value_containing_spaces_is_preserved(self):
        out = {"FIELDS": [{"FIELDNAME": "T"}], "DATA": [{"WA": "Ready-to-activate client"}]}
        self.assertEqual(rfc.parse_table(out), [{"T": "Ready-to-activate client"}])


class BapiErrorDetection(unittest.TestCase):
    """The reason writes are guarded: a BAPI reports failure in RETURN, not by raising."""

    def test_error_type_is_detected(self):
        out = {"RETURN": [{"TYPE": "E", "ID": "V1", "NUMBER": "312", "MESSAGE": "bad doc type"}]}
        self.assertIn("bad doc type", rfc.bapi_error(out))

    def test_abort_type_is_detected(self):
        self.assertIsNotNone(rfc.bapi_error({"RETURN": [{"TYPE": "A", "MESSAGE": "abort"}]}))

    def test_success_and_warning_are_not_errors(self):
        for t in ("S", "W", "I"):
            self.assertIsNone(rfc.bapi_error({"RETURN": [{"TYPE": t, "MESSAGE": "ok"}]}))

    def test_single_structure_not_only_a_list(self):
        self.assertIsNotNone(rfc.bapi_error({"RETURN": {"TYPE": "E", "MESSAGE": "x"}}))

    def test_missing_or_empty_return(self):
        self.assertIsNone(rfc.bapi_error({}))
        self.assertIsNone(rfc.bapi_error({"RETURN": []}))

    def test_error_found_after_leading_success_rows(self):
        out = {"RETURN": [{"TYPE": "S", "MESSAGE": "fine"}, {"TYPE": "E", "MESSAGE": "boom"}]}
        self.assertIn("boom", rfc.bapi_error(out))


class ProdGuard(unittest.TestCase):
    """CREDS_ENV is authoritative. A SID is NOT: the landscape here contains a
    sandbox whose SID is literally PRD."""

    def setUp(self):
        self._saved = dict(__import__("os").environ)

    def tearDown(self):
        import os
        os.environ.clear()
        os.environ.update(self._saved)

    def _env(self, **kw):
        import os
        os.environ.update({k: v for k, v in kw.items()})

    def test_prd_is_production(self):
        self._env(CREDS_ENV="prd")
        self.assertTrue(rfc.is_prod())

    def test_case_and_whitespace_tolerated(self):
        for v in ("PRD", " prd ", "Prd"):
            self._env(CREDS_ENV=v)
            self.assertTrue(rfc.is_prod(), v)

    def test_non_prod_envs(self):
        for v in ("sbx", "dev", "qas", "tst", ""):
            self._env(CREDS_ENV=v)
            self.assertFalse(rfc.is_prod(), v)

    def test_sandbox_named_prd_is_not_production(self):
        # universitimalaya-sbx-abap-prd: sid=PRD but env=sbx
        self._env(CREDS_ENV="sbx", CREDS_SID="PRD")
        self.assertFalse(rfc.is_prod())

    def test_guard_raises_on_prod_without_override(self):
        self._env(CREDS_ENV="prd")
        with self.assertRaises(SystemExit):
            rfc.guard_prod(allow_prod=False)

    def test_guard_permits_with_override(self):
        self._env(CREDS_ENV="prd")
        rfc.guard_prod(allow_prod=True)  # must not raise

    def test_guard_permits_non_prod(self):
        self._env(CREDS_ENV="sbx")
        rfc.guard_prod(allow_prod=False)  # must not raise


class AdtUrls(unittest.TestCase):
    def setUp(self):
        import os
        os.environ["CREDS_HOST"] = "host.example"
        os.environ["CREDS_SYSNR"] = "10"

    def test_icm_port_follows_instance_number(self):
        self.assertEqual(adt.base_url(None, False), "http://host.example:8010/sap/bc/adt")

    def test_https_port_follows_instance_number(self):
        self.assertEqual(adt.base_url(None, True), "https://host.example:44310/sap/bc/adt")

    def test_explicit_port_wins(self):
        self.assertTrue(adt.base_url("8000", False).startswith("http://host.example:8000/"))

    def test_single_digit_sysnr_is_padded(self):
        import os
        os.environ["CREDS_SYSNR"] = "0"
        self.assertIn(":8000/", adt.base_url(None, False))

    def test_strip_ns(self):
        self.assertEqual(adt.strip_ns("{http://www.sap.com/adt}collection"), "collection")
        self.assertEqual(adt.strip_ns("plain"), "plain")


class SapControlEndpoints(unittest.TestCase):
    def setUp(self):
        import os
        os.environ["CREDS_HOST"] = "h.example"
        os.environ["CREDS_SYSNR"] = "00"

    def test_http_port_is_5nn13(self):
        self.assertEqual(ctl.endpoint(None, None, False), "http://h.example:50013/")

    def test_https_port_is_5nn14(self):
        self.assertEqual(ctl.endpoint(None, None, True), "https://h.example:50014/")

    def test_instance_argument_overrides_and_pads(self):
        self.assertEqual(ctl.endpoint("x", "1", False), "http://x:50113/")

    def test_double_digit_instance(self):
        self.assertEqual(ctl.endpoint("x", "10", False), "http://x:51013/")

    def test_rows_flattens_item_elements(self):
        import xml.etree.ElementTree as ET
        xml = ET.fromstring("<r><item><a>1</a><b>two</b></item>"
                            "<item><a>3</a><b></b></item></r>")
        self.assertEqual(ctl.rows(xml), [{"a": "1", "b": "two"}, {"a": "3", "b": ""}])

    def test_rows_on_empty_response(self):
        import xml.etree.ElementTree as ET
        self.assertEqual(ctl.rows(ET.fromstring("<r/>")), [])


class DbReadOnlyGuard(unittest.TestCase):
    """Enforced, not advised: writing behind the application server is never correct."""

    def _refused(self, sql):
        with self.assertRaises(SystemExit, msg=sql):
            db.guard_read_only(sql)

    def test_select_is_allowed(self):
        db.guard_read_only("SELECT * FROM T000")
        db.guard_read_only("  select a from b where c = 'd'")

    def test_dml_and_ddl_refused(self):
        for sql in ("DELETE FROM T000", "UPDATE T000 SET X=1", "INSERT INTO T000 VALUES(1)",
                    "DROP TABLE T000", "TRUNCATE TABLE T000", "ALTER TABLE T000 ADD X INT",
                    "CREATE TABLE X (A INT)", "MERGE INTO T000", "GRANT ALL TO X",
                    "CALL SOME_PROC()"):
            self._refused(sql)

    def test_case_insensitive(self):
        self._refused("drop table t000")
        self._refused("DeLeTe FROM t000")

    def test_statement_chaining_refused(self):
        self._refused("SELECT 1; DROP TABLE T000")

    def test_select_with_forbidden_keyword_in_it_is_refused(self):
        # Conservative on purpose: a SELECT mentioning a DML keyword is rejected
        # rather than parsed. False negatives are cheaper than a write.
        self._refused("SELECT * FROM T WHERE NAME = 'delete me'")

    def test_trailing_semicolon_is_tolerated(self):
        db.guard_read_only("SELECT 1;")


class SkillIntegrity(unittest.TestCase):
    def test_every_script_referenced_in_skill_md_exists(self):
        import re
        text = (SCRIPTS.parent / "SKILL.md").read_text()
        for name in sorted(set(re.findall(r"\$SK/([A-Za-z0-9_.]+)", text))):
            self.assertTrue((SCRIPTS / name).exists(), f"SKILL.md references missing {name}")

    def test_shell_scripts_are_syntactically_valid(self):
        for sh in SCRIPTS.glob("*.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", str(sh)]).returncode, 0, sh.name)

    def test_scripts_are_executable(self):
        import os
        for f in list(SCRIPTS.glob("*.sh")) + list(SCRIPTS.glob("*.py")):
            self.assertTrue(os.access(f, os.X_OK), f"{f.name} is not executable")

    def test_no_secrets_committed(self):
        import re
        bad = re.compile(r"CREDS_PASSWORD\s*=\s*['\"][^'\"]+['\"]|passwd\s*=\s*['\"][A-Za-z0-9]{6,}")
        for f in list(SCRIPTS.iterdir()) + [SCRIPTS.parent / "SKILL.md"]:
            if f.is_file():
                self.assertIsNone(bad.search(f.read_text(errors="ignore")), f)


if __name__ == "__main__":
    unittest.main()
