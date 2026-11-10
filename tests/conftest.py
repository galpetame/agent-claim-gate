import os

import pytest

from claim_gate import append, gate


class Workspace:
    """A throwaway workspace with explicit file times, so staleness tests do not depend on the clock."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.root = tmp / "work"
        self.root.mkdir()
        self.ledger = tmp / "ledger.jsonl"
        self.report = tmp / "report.md"
        self._t = 1_700_000_000

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        self.touch(rel)
        return p

    def touch(self, rel):
        self._t += 10
        os.utime(self.root / rel, ns=(self._t * 10**9, self._t * 10**9))

    def claim(self, id, text, check=None, declared="verified", sources=()):
        return append(self.ledger, id, text, declared, check, sources)

    def say(self, text):
        self.report.write_text(text, encoding="utf-8")

    def gate(self, head=None):
        return gate(self.ledger, self.root, self.report if self.report.exists() else None, head)

    def status(self, id):
        return next(v.status for v in self.gate().verdicts if v.id == id)


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path)
