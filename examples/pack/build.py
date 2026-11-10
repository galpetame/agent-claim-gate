"""A toy build of a document pack that has to be printed and signed, gated by claim_gate.

    python examples/pack/build.py             honest build: GATE PASSED
    python examples/pack/build.py --overflow  two sections spill onto extra pages
    python examples/pack/build.py --stale     the checklist source is edited after the checklist is built
    python examples/pack/build.py --boast     the report says more than the ledger holds

The three faults are the ones a real 83-page pack ran into; see docs/case-study.md.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from claim_gate import append, main  # noqa: E402

PAGES, TOTAL, SIGNATURES = 83, "128,450.00", 79

ap = argparse.ArgumentParser()
ap.add_argument("--overflow", action="store_true")
ap.add_argument("--stale", action="store_true")
ap.add_argument("--boast", action="store_true")
a = ap.parse_args()

out = HERE / "out"
shutil.rmtree(out, ignore_errors=True)
(out / "src").mkdir(parents=True)
(out / "print").mkdir()
ledger, report = out / "ledger.jsonl", out / "report.md"


def stamp(path, t):
    os.utime(path, ns=(t * 10**9, t * 10**9))


# --- the build an agent would run -------------------------------------------------
pages = PAGES + (2 if a.overflow else 0)  # the bug: two sections no longer fit their page
body = []
for n in range(1, pages + 1):
    body.append(f"--- page {n}/{pages} ---")
    if n in (3, 9, 12, 40, 61, 80):
        body.append(f"Total: {TOTAL}")
    if n <= SIGNATURES:
        body.append("Signature: ____________")
(out / "src" / "checklist.md").write_text(f"Print 4 sets of {PAGES} pages.\n", encoding="utf-8")
(out / "print" / "pack.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
(out / "print" / "checklist.txt").write_text(f"Print 4 sets of {PAGES} pages.\n", encoding="utf-8")
stamp(out / "src" / "checklist.md", 1_700_000_000)
stamp(out / "print" / "pack.txt", 1_700_000_100)
stamp(out / "print" / "checklist.txt", 1_700_000_100)
if a.stale:  # someone edits the source afterwards; the printed checklist still says the old thing
    (out / "src" / "checklist.md").write_text("Print 4 sets of 85 pages.\n", encoding="utf-8")
    stamp(out / "src" / "checklist.md", 1_700_000_200)

# --- what the agent claims, each with a check the gate can re-run ------------------
P = "print/pack.txt"
append(ledger, "C-1", f"the pack has {PAGES} pages", check={"kind": "count", "path": P, "pattern": r"--- page \d+/\d+ ---", "equals": PAGES, "unit": "page"})
append(ledger, "C-2", f"every page is stamped N/{PAGES}", check={"kind": "count", "path": P, "pattern": rf"--- page \d+/{PAGES} ---", "equals": PAGES})
append(ledger, "C-3", f"the total {TOTAL} appears in all six places", check={"kind": "contains", "path": P, "text": f"Total: {TOTAL}", "min": 6})
append(ledger, "C-4", f"{SIGNATURES} signature places", check={"kind": "count", "path": P, "pattern": r"Signature: _+", "equals": SIGNATURES, "unit": "signature"})
append(ledger, "C-5", "no draft marks left", check={"kind": "absent", "path": P, "text": "DRAFT"})
append(ledger, "C-6", "the print checklist matches its source", check={"kind": "contains", "path": "print/checklist.txt", "text": f"{PAGES} pages"}, sources=["src/checklist.md"])
append(ledger, "C-7", "printing four sets costs about 700", declared="estimated")

report.write_text("\n".join([
    "# Build report",
    "",
    f"The pack is built and verified: {PAGES} pages [C-1], each stamped [C-2].",
    f"The total is confirmed in all six places [C-3], with {SIGNATURES} signature places verified [C-4].",
    "Draft marks: checked, none left; passed [C-5].",
    "The print checklist is rebuilt and verified against its source [C-6].",
    "Printing cost is an estimate, not verified [C-7].",
    "Nothing has been printed or sent." if not a.boast else "Printed, signed and delivered.",
]) + "\n", encoding="utf-8")

sys.exit(main([str(ledger), "--root", str(out), "--report", str(report)]))
