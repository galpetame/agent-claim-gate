"""300 random workspaces. Each starts honest and must pass; then one thing goes wrong and the gate must say so.

The faults are the ordinary ones: an output was deleted or changed after it was checked, a source moved on
and nobody rebuilt, the ledger was edited, or the report says more than the ledger holds.
"""
import hashlib
import json
import os
import random

import pytest

from claim_gate import CONTRADICTED, MISSING, REJECTED, STALE, UNBACKED, append, gate, head
from invariants import assert_invariants, status_of

T0 = 1_700_000_000
WORDS = "invoice ledger roster shift visit slot parcel batch order ticket".split()


def put(path, data, t):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
    os.utime(path, ns=(t * 10**9, t * 10**9))


def make(kind, rng, i):
    """Return (file name, honest content, check, report sentence, content that makes the claim false)."""
    k, word = rng.randint(2, 40), rng.choice(WORDS)
    if kind == "exists":
        return f"f{i}.txt", word, {"kind": "exists"}, "The {w} export is done [{c}].", None
    if kind == "sha256":
        data = f"{word}-{k}"
        return f"f{i}.bin", data, {"kind": "sha256", "hex": hashlib.sha256(data.encode()).hexdigest()}, "Archive verified [{c}].", data + "x"
    if kind == "contains":
        return f"f{i}.txt", f"TOTAL {k}\n" * 3, {"kind": "contains", "text": f"TOTAL {k}", "min": 3}, "The {w} total is confirmed in three places [{c}].", f"TOTAL {k}\n" * 2
    if kind == "absent":
        return f"f{i}.txt", f"{word} final\n", {"kind": "absent", "text": "DRAFT"}, "The {w} file passed the draft-mark check [{c}].", f"{word} DRAFT\n"
    if kind == "count":
        body = "".join(f"page {n}/{k}\n" for n in range(1, k + 1))
        return f"f{i}.txt", body, {"kind": "count", "pattern": r"page \d+/\d+", "equals": k, "unit": "page"}, f"The pack is verified: {k} pages [{{c}}].", body + "page 999/999\n"
    if kind == "number":
        return f"f{i}.txt", f"Total: {k},500.50\n", {"kind": "number", "pattern": r"Total: ([\d,.]+)", "equals": k * 1000 + 500.5}, "The {w} total is confirmed [{c}].", f"Total: {k},400.50\n"
    if kind == "json":
        return f"f{i}.json", json.dumps({"rows": k, "status": "ok"}), {"kind": "json", "pointer": "/rows", "equals": k}, "The {w} import finished [{c}].", json.dumps({"rows": k + 1})
    return f"f{i}.xml", f'<testsuite tests="{k}" failures="0" errors="0"/>', {"kind": "junit", "min_tests": k}, "All tests passed [{c}].", f'<testsuite tests="{k}" failures="1" errors="0"/>'


KINDS = ["exists", "sha256", "contains", "absent", "count", "number", "json", "junit"]


def build(tmp, rng):
    root, ledger, report = tmp / "work", tmp / "ledger.jsonl", tmp / "report.md"
    items, lines, t = [], ["# Run report", ""], T0
    for i in range(rng.randint(2, 6)):
        kind, cid = rng.choice(KINDS), f"C-{i + 1}"
        name, good, check, sentence, bad = make(kind, rng, i)
        sources = []
        if rng.random() < 0.5:
            t += 10
            put(root / "src" / f"s{i}.md", "source", t)
            sources = [f"src/s{i}.md"]
        t += 10
        put(root / "out" / name, good, t)
        append(ledger, cid, f"{kind} claim", "verified", {**check, "path": f"out/{name}"}, sources)
        lines.append(sentence.format(w=rng.choice(WORDS), c=cid))
        items.append({"id": cid, "kind": kind, "path": root / "out" / name, "bad": bad, "sources": sources, "check": check})
    append(ledger, "C-est", "printing cost", "estimated")
    lines += ["Printing cost is an estimate [C-est].", "The courier has not confirmed pickup."]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root, ledger, report, items, t


def break_one(rng, tmp, root, ledger, report, items, t):
    """Apply one fault. Return (name, check(result))."""
    it = rng.choice(items)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    faults = ["delete", "unbacked", "escape", "ledger_edit", "ledger_drop", "ledger_swap", "say_unbacked", "say_unknown"]
    if it["bad"] is not None:
        faults.append("change")
    if it["sources"]:
        faults.append("stale")
    if it["kind"] == "count":
        faults.append("say_drift")
    f = rng.choice(faults)
    if f == "delete":
        it["path"].unlink()
        return f, lambda r: status_of(r, it["id"]) == MISSING
    if f == "change":
        put(it["path"], it["bad"], t + 100)
        return f, lambda r: status_of(r, it["id"]) == CONTRADICTED
    if f == "stale":
        os.utime(root / it["sources"][0], ns=((t + 100) * 10**9, (t + 100) * 10**9))
        return f, lambda r: status_of(r, it["id"]) == STALE
    if f == "unbacked":
        append(ledger, "C-new", "also fine, honestly")
        return f, lambda r: status_of(r, "C-new") == UNBACKED
    if f == "escape":
        (tmp / "outside.txt").write_text("OK", encoding="utf-8")
        append(ledger, "C-out", "checked elsewhere", "verified", {"kind": "contains", "path": "../outside.txt", "text": "OK"})
        return f, lambda r: status_of(r, "C-out") == REJECTED
    if f == "ledger_edit":
        n = rng.randrange(len(lines) - 1)
        lines[n] = lines[n].replace(" claim", " claim (edited)")
    elif f == "ledger_drop":
        del lines[rng.randrange(len(lines) - 1)]
    elif f == "ledger_swap":
        n = rng.randrange(len(lines) - 1)
        lines[n], lines[n + 1] = lines[n + 1], lines[n]
    if f.startswith("ledger"):
        ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f, lambda r: any("chain broken" in p for p in r.problems)
    extra = {"say_unbacked": "Everything else is done and delivered.",
             "say_unknown": "Upload finished [C-404].",
             "say_drift": f"Reminder: the pack is verified at {it['check'].get('equals', 0) + 1} pages [{it['id']}]."}[f]
    report.write_text(report.read_text(encoding="utf-8") + extra + "\n", encoding="utf-8")
    return f, lambda r: len(r.lint) == 1


@pytest.mark.parametrize("seed", range(300))
def test_an_honest_run_passes_and_one_fault_fails(tmp_path, seed):
    rng = random.Random(seed)
    root, ledger, report, items, t = build(tmp_path, rng)
    clean = assert_invariants(ledger, root, report)
    assert clean.ok, (clean.problems, clean.lint, [v for v in clean.verdicts if v.status != "verified"])
    kept = head(ledger)

    fault, noticed = break_one(rng, tmp_path, root, ledger, report, items, t)
    broken = assert_invariants(ledger, root, report)
    assert not broken.ok, f"seed {seed}: fault '{fault}' went unnoticed"
    assert noticed(broken), f"seed {seed}: fault '{fault}' was reported as something else: {broken}"
    if fault.startswith("ledger") or fault in ("unbacked", "escape"):
        assert head(ledger) != kept or broken.problems


@pytest.mark.parametrize("seed", range(40))
def test_cutting_the_tail_is_caught_with_the_head_hash(tmp_path, seed):
    rng = random.Random(1000 + seed)
    root, ledger, report, items, t = build(tmp_path, rng)
    kept = head(ledger)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text("\n".join(lines[:rng.randrange(1, len(lines))]) + "\n", encoding="utf-8")
    assert not gate(ledger, root, None, kept).ok
