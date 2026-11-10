"""Every check kind: passes on true evidence, fails on false evidence, and cannot be talked round."""
import hashlib
import json

import pytest

import claim_gate
from claim_gate import CONTRADICTED, MISSING, REJECTED, STALE, UNBACKED, UNCHECKED, VERIFIED, to_number

JUNIT_OK = '<testsuites><testsuite tests="12" failures="0" errors="0"/></testsuites>'
JUNIT_BAD = '<testsuites><testsuite tests="12" failures="1" errors="0"/></testsuites>'

CASES = [
    ("exists", "a.txt", "x", {"kind": "exists"}, None),
    ("contains", "a.txt", "TOTAL 10\nTOTAL 10\n", {"kind": "contains", "text": "TOTAL 10", "min": 2}, "TOTAL 10\n"),
    ("absent", "a.txt", "final text", {"kind": "absent", "text": "DRAFT"}, "DRAFT final text"),
    ("count", "a.txt", "page 1/3\npage 2/3\npage 3/3\n", {"kind": "count", "pattern": r"page \d+/3", "equals": 3}, "page 1/3\n"),
    ("number", "a.txt", "Total: 128,450.00", {"kind": "number", "pattern": r"Total: ([\d,.]+)", "equals": 128450}, "Total: 128,400.00"),
    ("json", "a.json", json.dumps({"run": {"status": "ok"}}), {"kind": "json", "pointer": "/run/status", "equals": "ok"}, json.dumps({"run": {"status": "failed"}})),
    ("json-index", "a.json", json.dumps({"rows": [1, 2, 3]}), {"kind": "json", "pointer": "/rows/2", "equals": 3}, json.dumps({"rows": [1, 2]})),
    ("junit", "a.xml", JUNIT_OK, {"kind": "junit", "min_tests": 12}, JUNIT_BAD),
]


@pytest.mark.parametrize("name,rel,good,check,bad", CASES, ids=[c[0] for c in CASES])
def test_check_follows_the_evidence(ws, name, rel, good, check, bad):
    ws.write(rel, good)
    ws.claim("C-1", name, {**check, "path": rel})
    assert ws.status("C-1") == VERIFIED
    if bad is not None:
        ws.write(rel, bad)
        assert ws.status("C-1") == CONTRADICTED
    (ws.root / rel).unlink()
    assert ws.status("C-1") == MISSING
    assert not ws.gate().ok


def test_sha256_binds_to_the_exact_bytes(ws):
    ws.write("pack.bin", b"\x00\x01payload")
    ws.claim("C-1", "archive", {"kind": "sha256", "path": "pack.bin", "hex": hashlib.sha256(b"\x00\x01payload").hexdigest().upper()})
    assert ws.status("C-1") == VERIFIED
    ws.write("pack.bin", b"\x00\x01payload ")
    assert ws.status("C-1") == CONTRADICTED


def test_junit_needs_enough_tests_and_no_errors(ws):
    ws.write("r.xml", '<testsuite tests="3" failures="0" errors="0"/>')
    ws.claim("C-1", "suite ran", {"kind": "junit", "path": "r.xml", "min_tests": 10})
    assert ws.status("C-1") == CONTRADICTED
    ws.write("r.xml", '<testsuite tests="30" failures="0" errors="2"/>')
    assert ws.status("C-1") == CONTRADICTED
    ws.write("r.xml", "<testsuite tests=")
    assert ws.status("C-1") == CONTRADICTED


def test_declared_verified_without_a_check_is_unbacked(ws):
    ws.claim("C-1", "trust me")
    assert ws.status("C-1") == UNBACKED
    assert not ws.gate().ok


def test_estimates_pass_the_gate_but_are_not_verified(ws):
    ws.claim("C-1", "about 600 to print", declared="estimated")
    ws.claim("C-2", "the office accepts duplex", declared="hypothesis")
    r = ws.gate()
    assert r.ok and {v.status for v in r.verdicts} == {UNCHECKED}


def test_an_estimate_with_a_failing_check_is_still_contradicted(ws):
    ws.write("a.txt", "pages: 85")
    ws.claim("C-1", "83 pages, roughly", {"kind": "number", "path": "a.txt", "pattern": r"pages: (\d+)", "equals": 83}, declared="estimated")
    assert ws.status("C-1") == CONTRADICTED


def test_evidence_older_than_its_source_is_stale(ws):
    ws.write("src/checklist.md", "print 82 pages")
    ws.write("out/checklist.txt", "print 82 pages")
    ws.claim("C-1", "checklist rebuilt", {"kind": "contains", "path": "out/checklist.txt", "text": "82 pages"}, sources=["src/checklist.md"])
    assert ws.status("C-1") == VERIFIED
    ws.write("src/checklist.md", "print 83 pages")  # the source moved on, the output did not
    assert ws.status("C-1") == STALE
    ws.write("out/checklist.txt", "print 82 pages")  # rebuilt after the source: fresh again
    assert ws.status("C-1") == VERIFIED


def test_a_missing_source_is_stale_not_verified(ws):
    ws.write("out/a.txt", "ok")
    ws.claim("C-1", "built", {"kind": "exists", "path": "out/a.txt"}, sources=["src/gone.md"])
    assert ws.status("C-1") == STALE


@pytest.mark.parametrize("path", ["../outside.txt", "sub/../../outside.txt", "/etc/hostname", "C:/Windows/win.ini", "", None, 7])
def test_checks_cannot_leave_the_workspace(ws, path):
    (ws.tmp / "outside.txt").write_text("OK", encoding="utf-8")
    ws.claim("C-1", "looks fine", {"kind": "contains", "path": path, "text": "OK"})
    assert ws.status("C-1") == REJECTED


def test_a_source_cannot_leave_the_workspace(ws):
    ws.write("a.txt", "x")
    ws.claim("C-1", "built", {"kind": "exists", "path": "a.txt"}, sources=["../ledger.jsonl"])
    assert ws.status("C-1") == REJECTED


BAD_CHECKS = [
    ("unknown-kind", {"kind": "shell", "path": "a.txt", "cmd": "true"}),
    ("broken-pattern", {"kind": "count", "path": "a.txt", "pattern": "(", "equals": 1}),
    ("long-pattern", {"kind": "count", "path": "a.txt", "pattern": "a" * 201, "equals": 1}),
    ("count-without-equals", {"kind": "count", "path": "a.txt", "pattern": "a"}),
    ("number-without-group", {"kind": "number", "path": "a.txt", "pattern": r"\d+", "equals": 1}),
    ("number-equals-word", {"kind": "number", "path": "a.txt", "pattern": r"(\d+)", "equals": "many"}),
    ("contains-empty", {"kind": "contains", "path": "a.txt", "text": ""}),
    ("contains-min-zero", {"kind": "contains", "path": "a.txt", "text": "a", "min": 0}),
    ("absent-empty", {"kind": "absent", "path": "a.txt", "text": ""}),
    ("sha256-without-hex", {"kind": "sha256", "path": "a.txt"}),
]


@pytest.mark.parametrize("name,check", BAD_CHECKS, ids=[c[0] for c in BAD_CHECKS])
def test_unacceptable_checks_are_rejected_not_passed(ws, name, check):
    ws.write("a.txt", "a 1")
    ws.claim("C-1", name, check)
    assert ws.status("C-1") == REJECTED


def test_oversized_evidence_is_rejected(ws, monkeypatch):
    monkeypatch.setattr(claim_gate, "MAX_BYTES", 10)
    ws.write("a.txt", "x" * 11)
    ws.claim("C-1", "big", {"kind": "contains", "path": "a.txt", "text": "x"})
    assert ws.status("C-1") == REJECTED


NUMBERS = [
    ("83", "83"), ("128,450.10", "128450.10"), ("128 450,10", "128450.10"), ("128.450,10", "128450.10"),
    ("1,234,567", "1234567"), ("0,5", "0.5"), ("12,5", "12.5"), ("128" + chr(160) + "450", "128450"), ("abc", None), ("", None),
]


@pytest.mark.parametrize("text,want", NUMBERS, ids=[repr(n[0]) for n in NUMBERS])
def test_numbers_are_read_in_both_notations(text, want):
    got = to_number(text)
    assert (got is None) if want is None else str(got) == want
