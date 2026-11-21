"""Tests for google-one-tools-offer-reconcile.

Run:  python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "google-one-offer-reconcile"
EXAMPLES_IN = ROOT / "examples" / "in"
EXAMPLES_OUT = ROOT / "examples" / "out" / "report.json"


def _load_module():
    loader = SourceFileLoader("offer_reconcile", str(BIN))
    spec = importlib.util.spec_from_loader("offer_reconcile", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


mod = _load_module()


def clean_record(tag="us"):
    return {
        "serial": "127.0.0.1:****",
        "tag": tag,
        "candidates": 2,
        "offers": [
            {
                "ev": "offer",
                "product": "g1.2tb",
                "title": "2 TB",
                "id": "paid",
                "token": "<REDACTED>",
                "tags": "",
                "phases": [
                    {
                        "micros": "9990000",
                        "cur": "USD",
                        "period": "P1M",
                        "cycles": 0,
                        "free": False,
                        "fmt": "US$9.99",
                    }
                ],
            }
        ],
    }


def write_tmp(tmpdir, record, name="scan_result_x.json"):
    path = Path(tmpdir) / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return str(path)


class UnitChecks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_record_has_no_findings(self):
        report = mod.reconcile([write_tmp(self.tmp, clean_record())])
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["error"], 0)

    def test_stale_delisted_sku_is_error(self):
        record = clean_record()
        record["offers"][0]["product"] = "g1.30tb"
        report = mod.reconcile([write_tmp(self.tmp, record)], inline_delisted=["g1.30tb"])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("stale_delisted_sku", codes)
        self.assertEqual(report["summary"]["error"], 1)
        self.assertFalse(report["ok"])

    def test_amount_value_mismatch_is_error(self):
        record = clean_record()
        record["offers"][0]["phases"][0]["micros"] = "5000000"  # says 9.99
        report = mod.reconcile([write_tmp(self.tmp, record)])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("amount_coherence", codes)

    def test_symbol_currency_mismatch_is_error(self):
        record = clean_record()
        record["offers"][0]["phases"][0]["cur"] = "EUR"  # fmt still US$
        report = mod.reconcile([write_tmp(self.tmp, record)])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("amount_coherence", codes)

    def test_bad_period_is_schema_error(self):
        record = clean_record()
        record["offers"][0]["phases"][0]["period"] = "one-month"
        report = mod.reconcile([write_tmp(self.tmp, record)])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("schema", codes)

    def test_duplicate_offer_is_warning_only(self):
        record = clean_record()
        record["offers"].append(json.loads(json.dumps(record["offers"][0])))
        report = mod.reconcile([write_tmp(self.tmp, record)])
        codes = [(f["code"], f["severity"]) for f in report["findings"]]
        self.assertIn(("duplicate_offer", "warning"), codes)
        self.assertEqual(report["summary"]["error"], 0)

    def test_region_divergence_is_info(self):
        a = clean_record("us")
        b = clean_record("gb")
        b["offers"][0]["phases"][0]["micros"] = "1990000"
        b["offers"][0]["phases"][0]["fmt"] = "US$1.99"
        report = mod.reconcile([write_tmp(self.tmp, a, "scan_result_us.json"),
                                write_tmp(self.tmp, b, "scan_result_gb.json")])
        codes = [(f["code"], f["severity"]) for f in report["findings"]]
        self.assertIn(("region_divergence", "info"), codes)

    def test_missing_field_is_schema_error(self):
        record = clean_record()
        del record["offers"][0]["phases"][0]["cur"]
        report = mod.reconcile([write_tmp(self.tmp, record)])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("schema", codes)


class CliBehaviour(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, args):
        return subprocess.run(
            [sys.executable, str(BIN), *args],
            capture_output=True, text=True,
        )

    def test_cli_exit_0_on_clean(self):
        path = write_tmp(self.tmp, clean_record())
        proc = self._run([path, "--json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cli_exit_1_on_error(self):
        record = clean_record()
        record["offers"][0]["product"] = "g1.30tb"
        path = write_tmp(self.tmp, record)
        proc = self._run([path, "--json", "--delisted-sku", "g1.30tb"])
        self.assertEqual(proc.returncode, 1, proc.stderr)

    def test_cli_exit_2_on_missing_file(self):
        proc = self._run([str(Path(self.tmp) / "nope.json"), "--json"])
        self.assertEqual(proc.returncode, 2)

    def test_cli_json_is_parseable(self):
        record = clean_record()
        record["offers"][0]["product"] = "g1.30tb"
        path = write_tmp(self.tmp, record)
        proc = self._run([path, "--json", "--delisted-sku", "g1.30tb"])
        payload = json.loads(proc.stdout)  # must not raise
        self.assertEqual(payload["summary"]["error"], 1)

    def test_cli_out_file_written(self):
        path = write_tmp(self.tmp, clean_record())
        out = str(Path(self.tmp) / "report.json")
        proc = self._run([path, "--json", "--out", out])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(Path(out).read_text()))

    def test_examples_out_matches_regeneration(self):
        proc = self._run(["examples/in", "--json",
                          "--delisted", str(EXAMPLES_IN / "delisted.txt")])
        self.assertEqual(proc.returncode, 1, proc.stderr)
        generated = proc.stdout
        expected = EXAMPLES_OUT.read_text(encoding="utf-8")
        self.assertEqual(json.loads(generated), json.loads(expected))

    def test_run_is_deterministic(self):
        proc1 = self._run(["examples/in", "--json",
                           "--delisted", str(EXAMPLES_IN / "delisted.txt")])
        proc2 = self._run(["examples/in", "--json",
                           "--delisted", str(EXAMPLES_IN / "delisted.txt")])
        self.assertEqual(proc1.stdout, proc2.stdout)


if __name__ == "__main__":
    unittest.main()
