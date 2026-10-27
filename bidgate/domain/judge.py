"""Verify claims against receipts and verbatim text, then decide GO / HOLD / NO."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Sequence

from .interpret import interpret
from .model import FIELDS, Check, Claim, Finding, Line, Receipt, Rejected, Verdict


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify(doc: str, lines: Sequence[Line], receipts: Sequence[Receipt],
           claims: Sequence[Claim], now: datetime):
    by_line = {l.n: l for l in lines}
    rc = {r.line: r for r in receipts if r.doc == doc}
    findings: List[Finding] = []
    rejected: List[Rejected] = []
    for c in claims:
        line = by_line.get(c.line)
        if line is None:
            rejected.append(Rejected(c, "no such line"))
        elif c.line not in rc or rc[c.line].sha256 != sha(line.text):
            rejected.append(Rejected(c, "no reading receipt for this line"))
        elif not c.quote or c.quote not in line.text:
            rejected.append(Rejected(c, "quote is not verbatim in the cited line"))
        else:
            v = interpret(c.field, c.quote, now)
            if v is None:
                rejected.append(Rejected(c, "quote yields no value for this field"))
            else:
                findings.append(Finding(c.field, v, c.quote, doc, c.line, rc[c.line].sha256))
    return findings, rejected


def _distinct(fs: Sequence[Finding]):
    out: List[Any] = []
    for f in fs:
        if f.value not in out:
            out.append(f.value)
    return out


def _check(name: str, fs: List[Finding], profile: Dict[str, Any], now: datetime) -> Check:
    if not fs:
        return Check(name, "MISSING", "no accepted quote with a receipt", ())
    vals = _distinct(fs)
    if name != "deliverables" and len(vals) > 1:
        return Check(name, "CONFLICT", "sources disagree: " + "; ".join(str(v) for v in vals), tuple(fs))
    v = vals[0]
    t = tuple(fs)
    if name == "deadline":
        ok = now <= v
        return Check(name, "PASS" if ok else "FAIL",
                     ("open until " if ok else "closed at ") + v.strftime("%Y-%m-%d %H:%M UTC"), t)
    if name == "min_age":
        ok = profile["age"] >= v
        return Check(name, "PASS" if ok else "FAIL", "minimum age %d, applicant %d" % (v, profile["age"]), t)
    if name == "mode":
        ok = v == "online" or bool(profile["can_attend_onsite"])
        return Check(name, "PASS" if ok else "FAIL",
                     "%s; applicant can attend onsite: %s" % (v, "yes" if profile["can_attend_onsite"] else "no"), t)
    if name == "fee":
        ok = v <= profile["budget_usd"]
        return Check(name, "PASS" if ok else "FAIL", "fee $%.2f, budget $%.2f" % (v, profile["budget_usd"]), t)
    need = frozenset().union(*vals)
    miss = sorted(need - frozenset(profile["can_produce"]))
    return Check(name, "FAIL" if miss else "PASS",
                 ("cannot produce: " + ", ".join(miss)) if miss else "needs: " + ", ".join(sorted(need)), t)


def judge(doc: str, lines: Sequence[Line], receipts: Sequence[Receipt], claims: Sequence[Claim],
          profile: Dict[str, Any], now: datetime) -> Verdict:
    findings, rejected = verify(doc, lines, receipts, claims, now)
    checks = tuple(_check(f, [x for x in findings if x.field == f], profile, now) for f in FIELDS)
    if any(c.status == "FAIL" for c in checks):
        decision = "NO"
    elif all(c.status == "PASS" for c in checks):
        decision = "GO"
    else:
        decision = "HOLD"
    return Verdict(decision, checks, tuple(rejected))
