"""Bridge: bidgate HttpSqlSource wire ({"sql","params"} -> {"rows"}) -> Zetaris REST (ui:3000 proxy).
Rewrites table names to BIDGATE.* and inlines params. Run from the repo root:
  ZETARIS_USER=... ZETARIS_PASSWORD=... python3 tools/bridge.py   (listens on 127.0.0.1:8765, logs every SQL to docs/live/)"""
import json, re, sys, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zt
LOG = os.environ.get("BRIDGE_LOG", "docs/live/zetaris-bridge-queries.log")
def lit(v): return "'" + str(v).replace("'", "''") + "'" if not isinstance(v,(int,float)) else str(v)
def rewrite(sql, params):
    for p in params: sql = sql.replace("?", lit(p), 1)
    sql = re.sub(r"\b(FROM|JOIN)\s+(profile|doc_lines)\b", r"\1 BIDGATE.\2", sql, flags=re.I)
    sql = re.sub(r"ORDER BY (d\.)?n\b", lambda m: "ORDER BY CAST(%sn AS INT)" % (m.group(1) or ""), sql, flags=re.I)
    return sql
def ordered_values(sql, record):
    """Return record values in SELECT-list order (Zetaris may shuffle keys); cast n/count to int.
    If the SELECT list cannot be matched to the record keys (e.g. COUNT(*) comes back as `count(1)`), keep the record order."""
    m = re.search(r"SELECT\s+(.*?)\s+FROM\s", sql, re.I | re.S)
    cols = []
    if m:
        for part in m.group(1).split(","):
            part = part.strip()
            as_m = re.search(r"\bAS\s+(\w+)\s*$", part, re.I)
            cols.append(as_m.group(1) if as_m else part.split(".")[-1].strip())
    if sorted(cols) != sorted(record):
        cols = list(record)
    return [int(record[c]) if c == "n" or c.lower().startswith("count") else record[c] for c in cols]
def run(sql):
    l = zt.login(); tok = l["idToken"]
    r = zt.post("/api/proxy/query/sql/start", {"select": sql, "pageLimit": 1000},
                {"Authorization": "Bearer " + tok, "X-Org-ID": str(l["orgId"]), "X-Request-ID": "11111111-2222-3333-4444-555555555555"})
    if "records" not in r: raise RuntimeError(json.dumps(r)[:300])
    return [ordered_values(sql, rec) for rec in r["records"]]
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            sql = rewrite(body["sql"], body.get("params", [])); rows = run(sql); code = 200; resp = {"rows": rows}
        except Exception as e:
            sql = body.get("sql"); code = 500; resp = {"error": str(e)}
        with open(LOG, "a") as f: f.write("%s %d rows=%s SQL> %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), code, len(resp.get("rows", [])), sql[:200]))
        b = json.dumps(resp).encode(); self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self,*a): pass
if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(os.environ.get("BRIDGE_PORT", "8765"))), H).serve_forever()
