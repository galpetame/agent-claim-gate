"""The report may not say more than the ledger proves."""
import pytest

from claim_gate import lint_report


@pytest.fixture
def pack(ws):
    ws.write("out/pack.txt", "".join(f"page {i}/83\n" for i in range(1, 84)) + "Total: 128,450.00\n")
    ws.write("out/junit.xml", '<testsuite tests="64" failures="0" errors="0"/>')
    ws.claim("C-1", "the pack has 83 pages", {"kind": "count", "path": "out/pack.txt", "pattern": r"page \d+/83", "equals": 83, "unit": "page"})
    ws.claim("C-2", "tests pass", {"kind": "junit", "path": "out/junit.xml", "min_tests": 60})
    ws.claim("C-3", "printing costs about 600", declared="estimated")
    ws.claim("C-4", "the total is 128,400", {"kind": "number", "path": "out/pack.txt", "pattern": r"Total: ([\d,.]+)", "equals": 128400})
    return ws


def lint(ws, text):
    ws.say(text)
    return ws.gate().lint


GOOD = [
    "The pack is built and verified: 83 pages [C-1].",
    "All 64 tests passed [C-2].",
    "Tests passed. [C-2]",
    "| Tests | passed [C-2] |",
    "Комплект собран и проверено: 83 страницы [C-1].",
    "Printing is not done yet.",
    "Письмо не отправлено.",
    "The upload was never confirmed.",
    "Nothing has been printed or sent.",
    "The pack has not been printed or sent.",
    "Ничего не отправлено и не подано.",
    "Printing cost is an estimate, not verified: about 600 [C-3].",
    "Delivery is probably done; that is a hypothesis.",
    "Next step: print four sets.",
    "```\nall done, trust me\n```",
]


@pytest.mark.parametrize("text", GOOD, ids=range(len(GOOD)))
def test_honest_sentences_pass(pack, text):
    assert lint(pack, text) == ()


BAD = [
    ("Everything is done.", "without citing a claim"),
    ("Готово.", "without citing a claim"),
    ("Все письма отправлено и проверено.", "without citing a claim"),
    ("No errors, all tests passed.", "without citing a claim"),
    ("The build did not fail and everything passed.", "without citing a claim"),
    ("Not verified by hand, but the upload is done.", "without citing a claim"),
    ("Upload finished [C-99].", "not in the ledger"),
    ("Printing cost confirmed [C-3].", "C-3 is unchecked"),
    ("The total is verified [C-4].", "C-4 is contradicted"),
    ("The pack is verified: 82 pages [C-1].", "says 82 page, but C-1 checked 83"),
    ("Проверено: 85 page в комплекте [C-1].", "says 85 page"),
]


@pytest.mark.parametrize("text,why", BAD, ids=[b[1] + str(i) for i, b in enumerate(BAD)])
def test_overclaiming_sentences_are_reported(pack, text, why):
    errors = lint(pack, text)
    assert len(errors) == 1 and why in errors[0]
    assert not pack.gate().ok


def test_one_bad_line_is_found_in_a_long_report(pack):
    errors = lint(pack, "# Run 7\n\nThe pack is verified: 83 pages [C-1].\nTests passed [C-2].\n\nDeployed to production.\n")
    assert len(errors) == 1 and errors[0].startswith("line 6:")


def test_a_hedge_does_not_rescue_an_unknown_claim(pack):
    assert "not in the ledger" in lint(pack, "Probably sent, an estimate [C-77].")[0]


def test_lint_alone_needs_no_files():
    assert lint_report("Shipped.", {}, {}) == ["line 1: says 'Shipped' without citing a claim: Shipped."]
