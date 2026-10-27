"""One real JOIN statement against the Zetaris bridge: prints SQL, HTTP status, row count; writes json + log.

usage: python3 tools/join_probe.py <bridge-url> <out-prefix>   (e.g. http://127.0.0.1:8766/ docs/live/zetaris-join-2026-10-28)
"""
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bidgate.adapters.llm import RuleReader  # noqa: E402
from bidgate.adapters.source import HttpSqlSource  # noqa: E402
from bidgate.application.analyze import JOIN_SQL, analyze_case  # noqa: E402

url, prefix = sys.argv[1], sys.argv[2]
out = {"bridge": url, "sql": JOIN_SQL, "cases": []}
log = ["SQL> " + JOIN_SQL]
for case in ["oah-2026", "gsoc-how-it-works", "yc-w2027"]:
    body = json.dumps({"sql": JOIN_SQL, "params": [case]}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            status, data = r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        status, data = e.code, {"rows": [], "error": e.read().decode()[:300]}
    rows = data.get("rows", [])
    entry = {"case": case, "params": [case], "http_status": status, "rows": len(rows),
             "distinct_lines": len({r[0] for r in rows}), "profile_fields": sorted({r[2] for r in rows}),
             "seconds": round(time.time() - t0, 2), "first_row": rows[0] if rows else None}
    # same verdict through the full use case on the real data layer
    rep = analyze_case(ROOT / "data" / case, HttpSqlSource(url), RuleReader(),
                       datetime(2026, 10, 27, 14, tzinfo=timezone.utc))
    entry["verdict_via_zetaris_join"] = rep["decision"]
    entry["data_source"] = rep["data_source"]
    out["cases"].append(entry)
    log.append("%s HTTP %s rows=%d distinct_lines=%d fields=%s %.1fs verdict=%s" % (
        case, status, len(rows), entry["distinct_lines"], ",".join(entry["profile_fields"]), entry["seconds"],
        rep["decision"]))
out["utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
Path(prefix + ".json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
Path(prefix + ".log").write_text("\n".join(log) + "\n", encoding="utf-8")
print("\n".join(log))
