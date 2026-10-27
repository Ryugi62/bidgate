"""Use case: analyze one opportunity folder into a report dict (JSON-serializable, deterministic)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..domain.judge import judge, sha
from ..domain.model import Line, Receipt


def load_profile(source) -> Dict[str, Any]:
    kv = dict(source.query("SELECT key, value FROM profile"))
    return {
        "age": int(kv["age"]),
        "can_attend_onsite": kv["can_attend_onsite"].strip().lower() in ("yes", "true", "1"),
        "budget_usd": float(kv["budget_usd"]),
        "can_produce": frozenset(x for x in kv["can_produce"].split(";") if x),
    }


def analyze_case(case_dir, source, reader, now: datetime) -> Dict[str, Any]:
    case_dir = Path(case_dir)
    meta = json.loads((case_dir / "meta.json").read_text(encoding="utf-8"))
    doc = meta["case"]
    source.load_document(doc, (case_dir / "source.txt").read_text(encoding="utf-8"))
    # reading goes through the data port; every delivered line earns a receipt
    rows = source.query("SELECT n, text FROM doc_lines WHERE doc=? ORDER BY n", (doc,))
    lines = [Line(int(n), t) for n, t in rows]
    receipts = [Receipt(doc, l.n, sha(l.text)) for l in lines]
    total = source.query("SELECT COUNT(*) FROM doc_lines WHERE doc=?", (doc,))[0][0]
    claims = reader.propose(doc, lines)
    profile = load_profile(source)
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
