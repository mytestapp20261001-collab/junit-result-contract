#!/usr/bin/env python3
"""Offline, bounded contract audit. Python 3.12 standard library only."""
import argparse
import json
import math
import sys
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 10000
class BadInput(ValueError):
    pass
class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BadInput("invalid command arguments")

def require(condition, message):
    if not condition:
        raise BadInput(message)

def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result

def reject_constant(value):
    raise BadInput("nonfinite JSON number")

def read_text(path):
    require(Path(path).is_file(), "input must be a regular file")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "input exceeds 2 MiB limit")
    return raw.decode("utf-8-sig")

def finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "nonfinite JSON number")
    return parsed

def load_json(path):
    return json.loads(read_text(path), object_pairs_hook=pairs, parse_constant=reject_constant, parse_float=finite_float)

def report(findings, **summary):
    return {"schema_version": 1, "tool": TOOL, "status": "findings" if findings else "pass", "summary": summary, "findings": findings}

def finding(code, **where):
    return {"code": code, **where}

def run(build_parser, action):
    try:
        parser = Parser(description=__doc__)
        build_parser(parser)
        result = action(parser.parse_args())
        status = 1 if result["status"] == "findings" else 0
    except (ValueError, OSError, UnicodeError, RecursionError, OverflowError) as exc:
        message = str(exc) if isinstance(exc, BadInput) else "unreadable or malformed input"
        result = {"schema_version": 1, "tool": TOOL, "status": "error", "error": message}
        status = 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return status

import re
import xml.etree.ElementTree as ET
TOOL = "junit-result-contract"

def audit(text):
    require(isinstance(text, str), "expected XML text")
    require(len(text.encode("utf-8")) <= MAX_BYTES, "input exceeds 2 MiB limit")
    require(re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.I) is None, "DTD/entity declarations are forbidden")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise BadInput("malformed XML") from None
    require(root.tag in ("testsuite", "testsuites"), "expected unnamespaced testsuite or testsuites root")
    require(sum(1 for _ in root.iter()) <= 50000, "XML element budget exceeded")
    if root.tag == "testsuites":
        require(all(child.tag == "testsuite" for child in root), "testsuites must contain flat testsuite elements")
        suites = list(root)
    else:
        suites = [root]
    require(len(suites) <= 1000, "suite budget exceeded")
    findings, identities, grand = [], set(), dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    if not suites:
        findings.append(finding("no_suites"))
    def compare_counts(element, actual, suite_index=None, required=True):
        for key, count in actual.items():
            where = {"metric": key}
            if suite_index is not None:
                where["suite_index"] = suite_index
            value = element.get(key)
            if value is None:
                if required:
                    findings.append(finding("missing_declared_count", **where))
                continue
            require(re.fullmatch(r"[0-9]{1,12}", value) is not None, "declared counts must be nonnegative integers")
            if int(value) != count:
                findings.append(finding("count_mismatch", **where, declared=int(value), observed=count))
    case_total = 0
    for suite_index, suite in enumerate(suites):
        require(all(c.tag in ("testcase", "properties", "system-out", "system-err") for c in suite), "nested suites or unknown suite children are outside supported subset")
        cases = [child for child in suite if child.tag == "testcase"]
        actual = dict.fromkeys(grand, 0); actual["tests"] = len(cases)
        case_total += len(cases); require(case_total <= MAX_ITEMS, "testcase budget exceeded")
        if not cases:
            findings.append(finding("empty_suite", suite_index=suite_index))
        for case_index, case in enumerate(cases):
            name = case.get("name")
            require(isinstance(name, str) and 0 < len(name) <= 1024, "testcase requires a bounded nonempty name")
            identity = (suite.get("name", ""), case.get("classname", ""), name)
            if identity in identities:
                findings.append(finding("duplicate_test_identity", suite_index=suite_index, case_index=case_index))
            identities.add(identity)
            require(all(c.tag in ("failure", "error", "skipped", "properties", "system-out", "system-err") for c in case), "unknown testcase child outside supported subset")
            statuses = {tag: sum(c.tag == tag for c in case) for tag in ("failure", "error", "skipped")}
            if sum(statuses.values()) > 1:
                findings.append(finding("conflicting_or_repeated_outcome", suite_index=suite_index, case_index=case_index))
            for tag, metric in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
                actual[metric] += bool(statuses[tag])
        compare_counts(suite, actual, suite_index)
        for key in grand:
            grand[key] += actual[key]
    if root.tag == "testsuites":
        compare_counts(root, grand, required=False)
    if grand["failures"] or grand["errors"]:
        findings.append(finding("unsuccessful_test_outcomes", failures=grand["failures"], errors=grand["errors"]))
    return report(findings, suites=len(suites), **grand)

def configure(parser):
    parser.add_argument("input", help="local JUnit-style XML report")
if __name__ == "__main__":
    sys.exit(run(configure, lambda args: audit(read_text(args.input))))
