import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("local_tool", HERE / "tool.py")
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)

class Tests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(HERE/'tool.py'), *map(str,args)], capture_output=True, text=True)
    def codes(self, *args):
        return [item['code'] for item in tool.audit(*args)['findings']]
    def test_cli_bad_args(self):
        result = self.cli('--unknown')
        self.assertEqual(result.returncode, 2); self.assertEqual(json.loads(result.stdout)['status'], 'error')
    def test_read_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'big'; path.write_text(' '*(tool.MAX_BYTES+1))
            with self.assertRaises(tool.BadInput): tool.read_text(path)
    def good(self): return (HERE/'examples/pass.xml').read_text()
    def test_pass(self): self.assertEqual(tool.audit(self.good())['status'], 'pass')
    def test_findings(self):
        codes = self.codes((HERE/'examples/fail.xml').read_text())
        self.assertIn('duplicate_test_identity', codes); self.assertIn('count_mismatch', codes); self.assertIn('unsuccessful_test_outcomes', codes)
    def test_cli_examples(self):
        for name, expected in [('pass',0),('fail',1)]:
            result = self.cli(HERE/f'examples/{name}.xml')
            self.assertEqual(result.returncode, expected, result.stdout+result.stderr); json.loads(result.stdout)
    def test_malformed_xml(self):
        with self.assertRaises(tool.BadInput): tool.audit('<testsuite>')
    def test_dtd(self):
        with self.assertRaises(tool.BadInput): tool.audit('<!DOCTYPE testsuite [<!ENTITY x "value">]><testsuite/>')
    def test_external_entity(self):
        with self.assertRaises(tool.BadInput): tool.audit('<!DOCTYPE testsuite SYSTEM "file:///secret"><testsuite/>')
    def test_missing_counts(self): self.assertIn('missing_declared_count', self.codes('<testsuite><testcase name="x"/></testsuite>'))
    def test_conflict(self):
        text='<testsuite tests="1" failures="1" errors="0" skipped="1"><testcase name="x"><failure/><skipped/></testcase></testsuite>'
        self.assertIn('conflicting_or_repeated_outcome', self.codes(text))
    def test_repeated_failure(self):
        text='<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase name="x"><failure/><failure/></testcase></testsuite>'
        self.assertIn('conflicting_or_repeated_outcome', self.codes(text))
    def test_nested_suite_rejected(self):
        with self.assertRaises(tool.BadInput): tool.audit('<testsuite><testsuite/></testsuite>')
    def test_namespaces_rejected(self):
        with self.assertRaises(tool.BadInput): tool.audit('<testsuite xmlns="urn:x"/>')
    def test_negative_count(self):
        with self.assertRaises(tool.BadInput): tool.audit('<testsuite tests="-1"/>')
    def test_aggregate_mismatch(self): self.assertIn('count_mismatch', self.codes(self.good().replace('tests="2"','tests="9"',1)))
    def test_no_suites(self): self.assertIn('no_suites', self.codes('<testsuites/>'))
    def test_cli_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bad.xml'; path.write_text('<secret>')
            result=self.cli(path); self.assertEqual(result.returncode,2); self.assertNotIn('secret',result.stdout)

if __name__ == "__main__": unittest.main()
