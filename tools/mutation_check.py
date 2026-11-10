"""Mutation check: plant known bugs in claim_gate.py one at a time and confirm the tests catch each.

Usage: python tools/mutation_check.py   (a few minutes; exits non-zero if any planted bug survives)
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable
M = [
    ("ledger chain is not checked", 'if rec.get("prev") != prev:', "if False:"),
    ("expected head hash is ignored", "if expect_head is not None and not problems and head(ledger) != expect_head:", "if False:"),
    ("check may read outside the workspace", "if base != full and base not in full.parents:", "if False:"),
    ("verified without a check passes", 'return Verdict(claim.id, UNBACKED, "declared verified, but no check was supplied")', 'return Verdict(claim.id, VERIFIED, "declared verified")'),
    ("stale evidence passes", "stale = _stale(claim, root, evidence)", "stale = None"),
    ("missing source is ignored", 'if not src.exists():\n            return f"source is missing: {s}"', "if not src.exists():\n            continue"),
    ("missing evidence passes", "return Verdict(claim.id, MISSING, str(e))", "return Verdict(claim.id, VERIFIED, str(e))"),
    ("unacceptable check passes", "return Verdict(claim.id, REJECTED, str(e))", "return Verdict(claim.id, VERIFIED, str(e))"),
    ("oversized evidence is read", "if full.stat().st_size > MAX_BYTES:", "if False:"),
    ("pattern length is not limited", " or len(p) > MAX_PATTERN:", ":"),
    ("sha256 is not compared", 'return got == want, f"sha256', 'return True, f"sha256'),
    ("contains ignores the minimum", 'return n >= need, f"found {n}, need at least {need}"', 'return n >= 1, f"found {n}, need at least {need}"'),
    ("absent never fails", 'return n == 0, f"found {n}, expected none"', 'return True, f"found {n}, expected none"'),
    ("count accepts extra matches", 'return n == want, f"counted', 'return n >= want, f"counted'),
    ("number is read but not compared", "return got is not None and got == want,", "return got is not None,"),
    ("json value is not compared", 'return node == check["equals"],', "return True,"),
    ("junit ignores failures", "return tests >= need and bad == 0,", "return tests >= need,"),
    ("report: bare assertion passes", "            if not hedged:\n                errors.append(f\"line {n}: says '{word}' without citing a claim: {s[:90]}\")", "            if False:\n                pass"),
    ("report: unknown claim id passes", '                errors.append(f"line {n}: cites {cid}, which is not in the ledger")\n                continue', "                continue"),
    ("report: unverified claim stated as fact", "if v.status != VERIFIED and not hedged:", "if False:"),
    ("report: wrong number passes", "if to_number(said) != want:", "if False:"),
    ("gate ignores the report", "ok = not problems and not lint and all(", "ok = not problems and all("),
    ("gate ignores ledger problems", "ok = not problems and not lint and all(", "ok = not lint and all("),
]
FAST = ["tests/test_checks.py", "tests/test_ledger.py", "tests/test_report.py"]
caught = 0
for name, old, new in M:
    d = pathlib.Path(tempfile.mkdtemp())
    shutil.copytree(REPO, d / "r", ignore=shutil.ignore_patterns(".git", "__pycache__", "out"))
    p = d / "r" / "claim_gate.py"
    src = p.read_text(encoding="utf-8")
    assert src.count(old) == 1, f"mutant anchor must occur exactly once: {name}"
    p.write_text(src.replace(old, new, 1), encoding="utf-8")
    by = []
    for label, suite in (("examples", FAST), ("fuzz", ["tests/test_fuzz.py"])):
        r = subprocess.run([PY, "-m", "pytest", "-q", "-x", *suite], cwd=d / "r", capture_output=True, text=True)
        if r.returncode != 0:
            by.append(label)
    caught += bool(by)
    print(f"{'CAUGHT' if by else 'MISSED'}  {name:42s} by {', '.join(by) or '-'}", flush=True)
    shutil.rmtree(d, ignore_errors=True)
print(f"{caught}/{len(M)} planted bugs caught")
sys.exit(0 if caught == len(M) else 1)
