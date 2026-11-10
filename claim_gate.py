"""claim_gate: an agent may state as fact only what a re-runnable check confirms.

An agent records each claim in an append-only ledger together with a check against an
artifact in the workspace. The gate re-runs every check, verifies the ledger's hash chain
and lints the agent's report: an assertive sentence must cite a claim that verified.

Standard library only. The gate never executes commands and never writes to the workspace:
the ledger is written by the agent under test, so it is treated as untrusted input.

Usage: python claim_gate.py LEDGER [--root DIR] [--report REPORT.md] [--head HASH]
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

VERIFIED = "verified"
UNCHECKED = "unchecked"        # declared an estimate or a hypothesis; no check supplied
CONTRADICTED = "contradicted"  # the check ran and the evidence says otherwise
STALE = "stale"                # the evidence is older than a source it was built from
MISSING = "missing"            # the evidence file is not there
UNBACKED = "unbacked"          # declared verified, but no check was supplied
REJECTED = "rejected"          # the check is not acceptable: path escape, bad pattern, unknown kind
BLOCKING = frozenset({CONTRADICTED, STALE, MISSING, UNBACKED, REJECTED})

DECLARED = ("verified", "estimated", "hypothesis")
GENESIS = "0" * 64
MAX_BYTES = 5_000_000
MAX_PATTERN = 200
ID = re.compile(r"C-[\w.-]+\Z")


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    declared: str
    check: dict | None
    sources: tuple


@dataclass(frozen=True)
class Verdict:
    id: str
    status: str
    detail: str


@dataclass(frozen=True)
class Result:
    ok: bool
    verdicts: tuple
    problems: tuple  # ledger level: broken chain, bad records
    lint: tuple      # report level: sentences that say more than the ledger proves


class _Missing(Exception):
    pass


class _Reject(Exception):
    pass


# ---------------------------------------------------------------- ledger

def line_hash(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def append(ledger, id, text, declared="verified", check=None, sources=()):
    """Helper for the agent side: add one record, chained to the previous line."""
    ledger = Path(ledger)
    lines = ledger.read_text(encoding="utf-8").splitlines() if ledger.exists() else []
    rec = {"id": id, "text": text, "declared": declared, "check": check,
           "sources": list(sources), "prev": line_hash(lines[-1]) if lines else GENESIS}
    with ledger.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def head(ledger) -> str:
    """Hash of the last record. Store it outside the workspace to detect a cut tail."""
    lines = Path(ledger).read_text(encoding="utf-8").splitlines()
    return line_hash(lines[-1]) if lines else GENESIS


def _schema_error(rec):
    if not isinstance(rec.get("id"), str) or not ID.match(rec["id"]):
        return "id must look like C-1"
    if not isinstance(rec.get("text"), str) or not rec["text"].strip():
        return "text must be a non-empty string"
    if rec.get("declared") not in DECLARED:
        return f"declared must be one of {DECLARED}"
    check = rec.get("check")
    if check is not None and not (isinstance(check, dict) and isinstance(check.get("kind"), str)):
        return "check must be null or an object with a kind"
    sources = rec.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        return "sources must be a list of paths"
    return None


def load(ledger):
    """Return (claims by id, problems). A later record with the same id replaces the earlier one."""
    claims, problems, prev = {}, [], GENESIS
    try:
        raw = Path(ledger).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {}, [f"ledger unreadable: {e}"]
    if not raw.strip():
        problems.append("ledger is empty")
    for n, line in enumerate(raw.splitlines(), 1):
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError("not an object")
        except ValueError as e:
            problems.append(f"line {n}: not a valid record ({e})")
            prev = line_hash(line)
            continue
        if rec.get("prev") != prev:
            problems.append(f"line {n}: chain broken (a record was edited, removed, inserted or reordered)")
        prev = line_hash(line)
        err = _schema_error(rec)
        if err:
            problems.append(f"line {n}: {err}")
            continue
        claims[rec["id"]] = Claim(rec["id"], rec["text"], rec["declared"], rec.get("check"), tuple(rec.get("sources", [])))
    return claims, problems


# ---------------------------------------------------------------- checks

def to_number(value):
    """Parse 128,450.10 / 128 450,10 / 83 into a Decimal; None if it is not a number."""
    s = str(value).strip().replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        left, _, right = s.rpartition(",")
        s = left.replace(",", "") + right if len(right) == 3 and left else s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _resolve(root: Path, rel) -> Path:
    if not isinstance(rel, str) or not rel:
        raise _Reject("path must be a non-empty string")
    p = Path(rel)
    if p.is_absolute() or p.drive:
        raise _Reject(f"path must be relative to the workspace: {rel}")
    base, full = root.resolve(), (root / p).resolve()
    if base != full and base not in full.parents:
        raise _Reject(f"path escapes the workspace: {rel}")
    return full


def _bytes(full: Path) -> bytes:
    if not full.is_file():
        raise _Missing(f"no such file: {full.name}")
    if full.stat().st_size > MAX_BYTES:
        raise _Reject(f"file is larger than {MAX_BYTES} bytes: {full.name}")
    return full.read_bytes()


def _text(full: Path) -> str:
    return _bytes(full).decode("utf-8", errors="replace")


def _pattern(p):
    if not isinstance(p, str) or not p or len(p) > MAX_PATTERN:
        raise _Reject(f"pattern must be a string of 1..{MAX_PATTERN} characters")
    try:
        return re.compile(p)
    except re.error as e:
        raise _Reject(f"bad pattern: {e}")


def _exists(check, full):
    if not full.exists():
        raise _Missing(f"no such file: {full.name}")
    return True, "present"


def _sha256(check, full):
    got, want = hashlib.sha256(_bytes(full)).hexdigest(), str(check["hex"]).lower()
    return got == want, f"sha256 {got[:12]}, expected {want[:12]}"


def _contains(check, full):
    needle, need = check["text"], int(check.get("min", 1))
    if not isinstance(needle, str) or not needle or need < 1:
        raise _Reject("text must be a non-empty string and min at least 1")
    n = _text(full).count(needle)
    return n >= need, f"found {n}, need at least {need}"


def _absent(check, full):
    needle = check["text"]
    if not isinstance(needle, str) or not needle:
        raise _Reject("text must be a non-empty string")
    n = _text(full).count(needle)
    return n == 0, f"found {n}, expected none"


def _count(check, full):
    n, want = len(_pattern(check["pattern"]).findall(_text(full))), int(check["equals"])
    return n == want, f"counted {n}, expected {want}"


def _number(check, full):
    rx = _pattern(check["pattern"])
    if rx.groups < 1:
        raise _Reject("pattern needs one capturing group around the number")
    want = to_number(check["equals"])
    if want is None:
        raise _Reject("equals must be a number")
    m = rx.search(_text(full))
    if not m:
        return False, "pattern not found"
    got = to_number(m.group(1))
    return got is not None and got == want, f"read {m.group(1)}, expected {check['equals']}"


def _json(check, full):
    try:
        node = json.loads(_text(full))
    except ValueError:
        return False, "evidence is not valid JSON"
    for token in [t for t in str(check["pointer"]).split("/") if t]:
        try:
            node = node[int(token)] if isinstance(node, list) else node[token]
        except (KeyError, IndexError, ValueError, TypeError):
            return False, f"pointer not found: {check['pointer']}"
    return node == check["equals"], f"read {node!r}, expected {check['equals']!r}"


def _junit(check, full):
    try:
        root = ET.fromstring(_text(full))
    except ET.ParseError:
        return False, "evidence is not valid XML"
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    tests = sum(int(s.get("tests", 0)) for s in suites)
    bad = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    need = int(check.get("min_tests", 1))
    return tests >= need and bad == 0, f"{tests} tests, {bad} failed or errored, need at least {need} and none failing"


KINDS = {"exists": _exists, "sha256": _sha256, "contains": _contains, "absent": _absent,
         "count": _count, "number": _number, "json": _json, "junit": _junit}


def _stale(claim: Claim, root: Path, evidence: Path):
    for s in claim.sources:
        src = _resolve(root, s)
        if not src.exists():
            return f"source is missing: {s}"
        if src.stat().st_mtime_ns > evidence.stat().st_mtime_ns:
            return f"{s} changed after {claim.check['path']} was produced: rebuild, then check again"
    return None


def verify(claim: Claim, root) -> Verdict:
    root = Path(root)
    if claim.check is None:
        if claim.declared == "verified":
            return Verdict(claim.id, UNBACKED, "declared verified, but no check was supplied")
        return Verdict(claim.id, UNCHECKED, f"declared {claim.declared}; not checked")
    try:
        kind = claim.check.get("kind")
        if kind not in KINDS:
            raise _Reject(f"unknown check kind: {kind!r}")
        evidence = _resolve(root, claim.check.get("path"))
        ok, detail = KINDS[kind](claim.check, evidence)
        if ok:
            stale = _stale(claim, root, evidence)
            if stale:
                return Verdict(claim.id, STALE, stale)
    except _Missing as e:
        return Verdict(claim.id, MISSING, str(e))
    except _Reject as e:
        return Verdict(claim.id, REJECTED, str(e))
    except (KeyError, TypeError, ValueError) as e:
        return Verdict(claim.id, REJECTED, f"bad check parameters: {e!r}")
    return Verdict(claim.id, VERIFIED if ok else CONTRADICTED, detail)


# ---------------------------------------------------------------- report lint

ASSERTIVE = re.compile(
    r"(?<![\w-])(done|complete|completed|finished|verified|confirmed|passed|passes|fixed|sent|delivered|deployed|"
    r"published|submitted|shipped|готово|сделано|выполнено|проверено|подтверждено|исправлено|отправлено|"
    r"доставлено|опубликовано|подано|проходят|прошли|работает)(?![\w-])", re.I)
NEGATED = re.compile(
    r"(?<![\w-])(not|never|cannot|can't|isn't|wasn't|aren't|weren't|hasn't|haven't|didn't|не|нет)"
    r"\s+(?:(?:yet|been|be|ещё|еще|было|были)\s+)*(?:\w+\s+(?:or|nor|или|ни)\s+)*\Z", re.I)
NOTHING = re.compile(r"\s*(nothing|none of|nobody|no one|ничего|никто|ни один|ни одно)(?![\w-])", re.I)
HEDGE = re.compile(
    r"(estimate|approximately|probably|likely|hypothesis|assum|unverified|not verified|not checked|unknown|"
    r"оценк|оценочно|гипотез|предположительно|вероятно|не проверен|неизвестно|не подтвержд)", re.I)
CITE = re.compile(r"\[(C-[\w.-]+)\]")
ONLY_CITES = re.compile(r"(\[C-[\w.-]+\]\s*)+\Z")
CONTRAST = re.compile(r";\s*|,?\s+(?:but|however|yet|но|однако|зато)\s+", re.I)


def _sentences(report: str):
    fenced = False
    for n, line in enumerate(report.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced or not line.strip():
            continue
        out = []
        for part in re.split(r"(?<=[.!?])\s+", line.strip()):
            if out and ONLY_CITES.match(part):
                out[-1] += " " + part
            elif part:
                out.append(part)
        for s in out:  # a hedge or a citation covers its own clause only, not the one after "but"
            for clause in CONTRAST.split(s):
                if clause.strip():
                    yield n, clause.strip()


def lint_report(report: str, claims: dict, verdicts: dict) -> list:
    """Return the sentences that say more than the ledger proves."""
    errors = []
    for n, s in _sentences(report):
        asserted = [m for m in ASSERTIVE.finditer(s) if not NEGATED.search(s[:m.start()])]
        if not asserted or NOTHING.match(s):
            continue
        cited, hedged = CITE.findall(s), bool(HEDGE.search(s))
        word = asserted[0].group(1)
        if not cited:
            if not hedged:
                errors.append(f"line {n}: says '{word}' without citing a claim: {s[:90]}")
            continue
        for cid in cited:
            if cid not in claims:
                errors.append(f"line {n}: cites {cid}, which is not in the ledger")
                continue
            v = verdicts[cid]
            if v.status != VERIFIED and not hedged:
                errors.append(f"line {n}: says '{word}' as fact, but {cid} is {v.status}")
            check = claims[cid].check or {}
            unit = check.get("unit")
            if unit and check.get("kind") in ("number", "count"):
                want = to_number(check["equals"])
                for m in re.finditer(r"(\d[\d  ,.]*)\s*" + re.escape(str(unit)), s, re.I):
                    said = m.group(1).rstrip(" ,. ")
                    if to_number(said) != want:
                        errors.append(f"line {n}: says {said} {unit}, but {cid} checked {check['equals']}")
    return errors


# ---------------------------------------------------------------- gate

def gate(ledger, root, report=None, expect_head=None) -> Result:
    claims, problems = load(ledger)
    if expect_head is not None and not problems and head(ledger) != expect_head:
        problems.append("ledger head differs from the expected hash (the tail was cut or replaced)")
    verdicts = tuple(verify(c, root) for c in claims.values())
    lint = ()
    if report is not None:
        try:
            text = Path(report).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            problems.append(f"report unreadable: {e}")
        else:
            lint = tuple(lint_report(text, claims, {v.id: v for v in verdicts}))
    ok = not problems and not lint and all(v.status not in BLOCKING for v in verdicts)
    return Result(ok, verdicts, tuple(problems), lint)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Re-run the checks behind an agent's claims.")
    ap.add_argument("ledger")
    ap.add_argument("--root", default=".")
    ap.add_argument("--report")
    ap.add_argument("--head", help="expected hash of the last ledger record")
    a = ap.parse_args(argv)
    claims, _ = load(a.ledger)
    r = gate(a.ledger, a.root, a.report, a.head)
    for v in r.verdicts:
        print(f"{v.status.upper():13s}{v.id:8s}{claims[v.id].text}  ({v.detail})")
    for p in r.problems:
        print(f"LEDGER       {p}")
    for e in r.lint:
        print(f"REPORT       {e}")
    print(f"head {head(a.ledger) if Path(a.ledger).exists() else '-'}")
    print("GATE PASSED" if r.ok else "GATE FAILED")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
