"""Use case: analyze one opportunity folder into a report dict (JSON-serializable, deterministic)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..domain.judge import judge, sha
from ..domain.model import Line, Receipt


PROFILE_KEYS = ("age", "can_attend_onsite", "budget_usd", "can_produce")

# Key JOIN: every document line, tagged with the field it states (regexp_like in the ON clause),
# and the profile fact attached only where the field names one (p.key = f.pkey).
# Patterns are lowercase supersets of interpret.py; no backslashes; {0,1} instead of ? so the
# sole "?" placeholder remains the document id for the bridge.
JOIN_SQL = (
    "SELECT d.n, f.field, d.text, p.key, p.value "
    "FROM doc_lines d "
    "LEFT JOIN (SELECT 'min_age' AS field, 'age' AS pkey, "
    "'aged{0,1} [0-9]+ or older|at least [0-9]+ years|[0-9]+ years (of age ){0,1}or older|[0-9]+ years old' AS pat "
    "UNION ALL SELECT 'mode', 'can_attend_onsite', 'in-person|in person|onsite|on-site|online|remote' "
    "UNION ALL SELECT 'fee', 'budget_usd', 'fee|free|cost|[$][0-9]' "
    "UNION ALL SELECT 'deliverables', 'can_produce', "
    "'video|deck|slides|github|repository|source code|proposal|application form|essay' "
    "UNION ALL SELECT 'deadline', CAST(NULL AS STRING), 'deadline|clos|due|submit') f "
    "ON regexp_like(LOWER(d.text), f.pat) "
    "LEFT JOIN profile p ON p.key = f.pkey "
    "WHERE d.doc=? ORDER BY d.n, f.field"
)


def _profile_from_kv(kv) -> Dict[str, Any]:
    return {
        "age": int(kv["age"]),
        "can_attend_onsite": kv["can_attend_onsite"].strip().lower() in ("yes", "true", "1"),
        "budget_usd": float(kv["budget_usd"]),
        "can_produce": frozenset(x for x in kv["can_produce"].split(";") if x),
    }


def load_profile(source) -> Dict[str, Any]:
    return _profile_from_kv(dict(source.query("SELECT key, value FROM profile")))


def analyze_case(case_dir, source, reader, now: datetime) -> Dict[str, Any]:
    case_dir = Path(case_dir)
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
    doc = meta["case"]
    source.load_document(doc, (case_dir / "source.txt").read_text(encoding="utf-8"))
    # reading goes through the data port; every delivered line earns a receipt
    joined = source.query(JOIN_SQL, (doc,))
    lines, kv = [], {}
    for n, field, text, key, value in joined:  # a line repeats when it states two fields: keep once
        if not lines or lines[-1].n != int(n):
            lines.append(Line(int(n), text))
        if key is not None:
            kv[key] = value
    if any(k not in kv for k in PROFILE_KEYS):
        for k, v in source.query("SELECT key, value FROM profile"):
            kv.setdefault(k, v)
    receipts = [Receipt(doc, l.n, sha(l.text)) for l in lines]
    total = source.query("SELECT COUNT(*) FROM doc_lines WHERE doc=?", (doc,))[0][0]
    claims = reader.propose(doc, lines)
    profile = _profile_from_kv(kv)
    verdict = judge(doc, lines, receipts, claims, profile, now)
    stats = dict(getattr(reader, "stats", {}))
    if "model_claims_proposed" in stats:
        refused = {r.claim for r in verdict.rejected}
        dropped = set(getattr(reader, "model_dropped", []))
        stats["model_claims_accepted"] = sum(1 for c in reader.model_claims if c not in refused and c not in dropped)
        rules_only = judge(doc, lines, receipts, reader.rules_claims, profile, now)
        decided = lambda v: {c.criterion for c in v.checks if c.status in ("PASS", "FAIL")}
        stats["cells_decided_by_model_only"] = len(decided(verdict) - decided(rules_only))
        stats["cells_decided_by_rules_alone"] = len(decided(rules_only))
    return {
        "case": doc,
        "url": meta.get("url"),
        "fetched_utc": meta.get("fetched_utc"),
        "now": now.isoformat(),
        "decision": verdict.decision,
        "checks": [{
            "criterion": c.criterion, "status": c.status, "detail": c.detail,
            "evidence": [{"quote": f.quote, "doc": f.doc, "line": f.line, "receipt": f.receipt}
                         for f in c.findings],
        } for c in verdict.checks],
        "rejected": [{"field": r.claim.field, "line": r.claim.line, "quote": r.claim.quote, "reason": r.reason}
                     for r in verdict.rejected],
        "coverage": {"lines_read": len(lines), "lines_total": int(total)},
        "reader": getattr(reader, "name", "unknown"),
        "reader_note": getattr(reader, "note", ""),
        "reader_stats": stats,
        "data_source": source.name,
    }
