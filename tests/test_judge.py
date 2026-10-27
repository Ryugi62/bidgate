import hashlib
from datetime import datetime, timezone

from bidgate.domain.judge import judge
from bidgate.domain.model import Claim, Line, Receipt

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)
PROFILE = {"age": 21, "can_attend_onsite": False, "budget_usd": 0.0,
           "can_produce": frozenset({"video", "deck", "repo", "proposal"})}

TEXT = [
    "Deadline Oct 27, 2026, 23:45 UTC",
    "Open worldwide to anyone aged 16 or older",
    "Fully online. 22-27 October 2026",
    "Registration and submission are all free.",
    "A demo video of 1-4 minutes and a GitHub repository",
]


def lines(texts=TEXT):
    return [Line(i + 1, t) for i, t in enumerate(texts)]


def receipts(ls):
    return [Receipt("d", l.n, hashlib.sha256(l.text.encode()).hexdigest()) for l in ls]


def good_claims():
    return [Claim("deadline", 1, TEXT[0]), Claim("min_age", 2, TEXT[1]), Claim("mode", 3, TEXT[2]),
            Claim("fee", 4, TEXT[3]), Claim("deliverables", 5, TEXT[4])]


def run(claims, texts=TEXT, profile=PROFILE, now=NOW, rcpts=None):
    ls = lines(texts)
    return judge("d", ls, rcpts if rcpts is not None else receipts(ls), claims, profile, now)


def status(v, name):
    return next(c.status for c in v.checks if c.criterion == name)


def test_all_pass_is_go():
    v = run(good_claims())
    assert v.decision == "GO"
    assert all(c.status == "PASS" for c in v.checks)


def test_every_pass_has_quote_and_receipt():
    v = run(good_claims())
    for c in v.checks:
        assert c.findings
        for f in c.findings:
            assert f.quote in TEXT[f.line - 1]
            assert len(f.receipt) == 64


def test_deadline_passed_is_no():
    late = datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc)
    v = run(good_claims(), now=late)
    assert status(v, "deadline") == "FAIL"
    assert v.decision == "NO"


def test_fabricated_quote_rejected_and_hold():
    cl = good_claims()
    cl[0] = Claim("deadline", 1, "Deadline Oct 30, 2026, 23:45 UTC")
    v = run(cl)
    assert status(v, "deadline") == "MISSING"
    assert v.decision == "HOLD"
    assert len(v.rejected) == 1 and "verbatim" in v.rejected[0].reason


def test_claim_on_unread_line_rejected():
    ls = lines()
    rc = [r for r in receipts(ls) if r.line != 1]
    v = judge("d", ls, rc, good_claims(), PROFILE, NOW)
    assert status(v, "deadline") == "MISSING"
    assert any("receipt" in r.reason for r in v.rejected)
    assert v.decision == "HOLD"


def test_claim_on_nonexistent_line_rejected():
    v = run([Claim("deadline", 99, "x")] + good_claims()[1:])
    assert status(v, "deadline") == "MISSING"
    assert v.rejected


def test_claim_whose_quote_has_no_value_rejected():
    v = run([Claim("deadline", 3, TEXT[2])] + good_claims()[1:])
    assert status(v, "deadline") == "MISSING"
    assert any("value" in r.reason for r in v.rejected)


def test_no_claims_is_hold_never_go():
    v = run([])
    assert v.decision == "HOLD"
    assert all(c.status == "MISSING" for c in v.checks)


def test_missing_detail_tells_person_to_check_another_page():
    v = run([])
    n = len(TEXT)
    expected = "not stated on this page (%d/%d lines read) - check another source page before you apply" % (n, n)
    assert all(c.detail == expected for c in v.checks)


def test_onsite_with_profile_no_is_no():
    texts = list(TEXT)
    texts[2] = "The batch will take place in-person at the campus"
    cl = good_claims()
    cl[2] = Claim("mode", 3, texts[2])
    v = run(cl, texts=texts)
    assert status(v, "mode") == "FAIL"
    assert v.decision == "NO"


def test_onsite_with_profile_yes_passes():
    texts = list(TEXT)
    texts[2] = "The batch will take place in-person at the campus"
    cl = good_claims()
    cl[2] = Claim("mode", 3, texts[2])
    p = dict(PROFILE, can_attend_onsite=True)
    assert status(run(cl, texts=texts, profile=p), "mode") == "PASS"


def test_conflicting_deadlines_is_conflict_hold():
    texts = list(TEXT) + ["Final deadline Oct 29, 2026, 10:00 UTC"]
    cl = good_claims() + [Claim("deadline", 6, texts[5])]
    v = run(cl, texts=texts)
    assert status(v, "deadline") == "CONFLICT"
    assert v.decision == "HOLD"


def test_age_below_minimum_fails():
    v = run(good_claims(), profile=dict(PROFILE, age=15))
    assert status(v, "min_age") == "FAIL"
    assert v.decision == "NO"


def test_fee_above_budget_fails():
    texts = list(TEXT)
    texts[3] = "A registration fee of $25 applies"
    cl = good_claims()
    cl[3] = Claim("fee", 4, texts[3])
    v = run(cl, texts=texts)
    assert status(v, "fee") == "FAIL"


def test_unproducible_deliverable_fails():
    v = run(good_claims(), profile=dict(PROFILE, can_produce=frozenset({"repo"})))
    assert status(v, "deliverables") == "FAIL"


def test_duplicate_equal_findings_do_not_conflict():
    texts = list(TEXT) + ["Deadline Oct 27, 2026, 23:45 UTC"]
    cl = good_claims() + [Claim("deadline", 6, texts[5])]
    assert status(run(cl, texts=texts), "deadline") == "PASS"


def test_lying_reader_never_yields_unquoted_finding():
    import random
    rnd = random.Random(7)
    for _ in range(50):
        cl = [Claim(rnd.choice(["deadline", "fee", "mode", "min_age", "deliverables"]),
                    rnd.randint(1, 6), "".join(rnd.choice("abc ") for _ in range(8))) for _ in range(5)]
        v = run(cl)
        for c in v.checks:
            for f in c.findings:
                assert f.quote in TEXT[f.line - 1]
