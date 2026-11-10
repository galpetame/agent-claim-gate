"""The README is part of the contract: it must list every check kind, verdict and invariant the code has."""
import pathlib
import re

import claim_gate
from invariants import INVARIANTS

README = (pathlib.Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_every_check_kind_is_documented():
    missing = [k for k in claim_gate.KINDS if f"| `{k}` |" not in README]
    assert not missing, f"check kinds missing from the README table: {missing}"


def test_every_verdict_is_documented():
    names = [claim_gate.VERIFIED, claim_gate.UNCHECKED, *sorted(claim_gate.BLOCKING)]
    missing = [n for n in names if f"| `{n}` |" not in README]
    assert not missing, f"verdicts missing from the README table: {missing}"


def test_every_invariant_is_documented_word_for_word():
    for key, text in INVARIANTS.items():
        assert f"| {key} | {text} |" in README, f"{key} differs between invariants.py and the README"


def test_the_readme_does_not_promise_more_mutants_than_exist():
    listed = len(re.findall(r'^    \("', (pathlib.Path(__file__).resolve().parent.parent / "tools" / "mutation_check.py").read_text(encoding="utf-8"), re.M))
    claimed = int(re.search(r"(\d+)/(\d+) planted bugs caught", README).group(2))
    assert claimed == listed
