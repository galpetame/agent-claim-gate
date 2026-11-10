"""Properties the gate must keep on every workspace, whatever the agent wrote into the ledger."""
import hashlib
from pathlib import Path

from claim_gate import BLOCKING, VERIFIED, gate

INVARIANTS = {
    "INV-1": "Sound pass: if the gate passes, no claim is contradicted, stale, missing, unbacked or rejected",
    "INV-2": "Evidence binds: change or remove the evidence behind a verified claim and the gate fails on that claim",
    "INV-3": "History binds: edit, remove, insert or reorder a ledger record and the chain check reports it",
    "INV-4": "No free assertions: a report passes only if every assertive sentence cites a verified claim or is hedged",
    "INV-5": "Read-only: checking changes no file in the workspace and not the ledger",
    "INV-6": "Deterministic: the same workspace gives the same result twice",
    "INV-7": "Confined: a check that points outside the workspace is rejected, even if that file would satisfy it",
}


def snapshot(*roots):
    """Content hash and mtime of every file under the given paths."""
    out = {}
    for root in roots:
        root = Path(root)
        for p in sorted([root] if root.is_file() else root.rglob("*")):
            if p.is_file():
                out[str(p)] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return out


def assert_invariants(ledger, root, report=None):
    """INV-1, INV-5 and INV-6 on the current state. Returns the gate result."""
    before = snapshot(root, ledger, *([report] if report else []))
    first = gate(ledger, root, report)
    second = gate(ledger, root, report)
    assert first == second, "INV-6: two runs disagree"
    assert snapshot(root, ledger, *([report] if report else [])) == before, "INV-5: the gate changed a file"
    if first.ok:
        bad = [v for v in first.verdicts if v.status in BLOCKING]
        assert not bad and not first.problems and not first.lint, f"INV-1: passed with {bad}"
    return first


def status_of(result, claim_id):
    return next(v.status for v in result.verdicts if v.id == claim_id)


def is_verified(result, claim_id):
    return status_of(result, claim_id) == VERIFIED
