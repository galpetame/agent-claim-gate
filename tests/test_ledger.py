"""The ledger is append-only: rewriting history is reported, whoever does it."""
import json

import pytest

from claim_gate import GENESIS, VERIFIED, head, line_hash, load


def three(ws):
    ws.write("a.txt", "alpha")
    for i in (1, 2, 3):
        ws.claim(f"C-{i}", f"claim {i}", {"kind": "exists", "path": "a.txt"})
    return ws.ledger.read_text(encoding="utf-8").splitlines()


def rewrite(ws, lines):
    ws.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_clean_ledger_chains_from_genesis(ws):
    lines = three(ws)
    assert json.loads(lines[0])["prev"] == GENESIS
    assert json.loads(lines[1])["prev"] == line_hash(lines[0])
    claims, problems = load(ws.ledger)
    assert list(claims) == ["C-1", "C-2", "C-3"] and not problems
    assert ws.gate().ok


def test_editing_a_record_breaks_the_chain(ws):
    lines = three(ws)
    lines[0] = lines[0].replace("claim 1", "claim one")
    rewrite(ws, lines)
    r = ws.gate()
    assert not r.ok and any("line 2: chain broken" in p for p in r.problems)


def test_removing_a_record_breaks_the_chain(ws):
    lines = three(ws)
    rewrite(ws, [lines[0], lines[2]])
    assert any("chain broken" in p for p in ws.gate().problems)


def test_inserting_a_record_breaks_the_chain(ws):
    lines = three(ws)
    forged = json.dumps({"id": "C-9", "text": "slipped in", "declared": "estimated", "check": None, "sources": [], "prev": line_hash(lines[0])})
    rewrite(ws, [lines[0], forged, lines[1], lines[2]])
    assert any("line 3: chain broken" in p for p in ws.gate().problems)


def test_reordering_records_breaks_the_chain(ws):
    lines = three(ws)
    rewrite(ws, [lines[1], lines[0], lines[2]])
    assert not ws.gate().ok


def test_a_cut_tail_needs_the_head_hash(ws):
    lines = three(ws)
    kept = head(ws.ledger)
    rewrite(ws, lines[:2])
    assert ws.gate().ok                      # a hash chain alone cannot see a missing tail
    r = ws.gate(head=kept)                   # the head stored outside the workspace can
    assert not r.ok and "tail was cut" in r.problems[0]


def test_an_edited_last_record_needs_the_head_hash(ws):
    lines = three(ws)
    kept = head(ws.ledger)
    lines[2] = lines[2].replace("claim 3", "claim three")
    rewrite(ws, lines)
    assert not ws.gate(head=kept).ok


BAD_RECORDS = [
    ("not-json", "{nope"),
    ("not-an-object", "[1, 2]"),
    ("bad-id", json.dumps({"id": "claim 1", "text": "x", "declared": "verified", "check": None, "prev": GENESIS})),
    ("empty-text", json.dumps({"id": "C-1", "text": " ", "declared": "verified", "check": None, "prev": GENESIS})),
    ("made-up-status", json.dumps({"id": "C-1", "text": "x", "declared": "certain", "check": None, "prev": GENESIS})),
    ("check-not-object", json.dumps({"id": "C-1", "text": "x", "declared": "verified", "check": "exists", "prev": GENESIS})),
    ("sources-not-list", json.dumps({"id": "C-1", "text": "x", "declared": "verified", "check": None, "sources": "a.txt", "prev": GENESIS})),
]


@pytest.mark.parametrize("name,line", BAD_RECORDS, ids=[b[0] for b in BAD_RECORDS])
def test_malformed_records_fail_the_gate(ws, name, line):
    rewrite(ws, [line])
    r = ws.gate()
    assert not r.ok and r.problems and not r.verdicts


def test_an_empty_or_absent_ledger_fails(ws):
    assert not ws.gate().ok
    ws.ledger.write_text("", encoding="utf-8")
    assert "ledger is empty" in ws.gate().problems


def test_a_later_record_replaces_an_earlier_one(ws):
    ws.write("a.txt", "pages: 83")
    ws.claim("C-1", "85 pages", {"kind": "number", "path": "a.txt", "pattern": r"pages: (\d+)", "equals": 85})
    assert not ws.gate().ok
    ws.claim("C-1", "83 pages", {"kind": "number", "path": "a.txt", "pattern": r"pages: (\d+)", "equals": 83})
    r = ws.gate()
    assert r.ok and [(v.id, v.status) for v in r.verdicts] == [("C-1", VERIFIED)]
    assert len(ws.ledger.read_text(encoding="utf-8").splitlines()) == 2  # the correction is on the record
