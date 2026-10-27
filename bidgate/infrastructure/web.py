"""One local screen for the demo. Standard library only, bound to loopback."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from ..application.analyze import analyze_case
from .wiring import DATA, build_reader, build_source

COLORS = {"GO": "#0a7d33", "HOLD": "#9a6700", "NO": "#b3261e", "PASS": "#0a7d33", "FAIL": "#b3261e",
          "MISSING": "#9a6700", "CONFLICT": "#9a6700"}


def reports(now):
    src, rd = build_source(), build_reader()
    return [analyze_case(d, src, rd, now) for d in sorted(DATA.iterdir()) if (d / "meta.json").exists()]


def badge(t):
    return '<b style="color:#fff;background:%s;padding:2px 8px;border-radius:4px">%s</b>' % (
        COLORS.get(t, "#555"), html.escape(t))


def page(rs):
    e = html.escape
    parts = ["<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>BidGate</title>"
             "<style>body{font:15px system-ui;margin:24px auto;max-width:1100px;padding:0 16px}"
             "table{border-collapse:collapse;width:100%;margin:8px 0 28px}td,th{border:1px solid #ccc;padding:6px;"
             "vertical-align:top;text-align:left}code{font-size:12px}.tag{background:#eee;padding:1px 6px;"
             "border-radius:4px;font-size:12px}</style><h1>BidGate</h1><p>Submit or not? Every conclusion needs a "
             "verbatim quote and a reading receipt, otherwise HOLD.</p>"]
    for r in rs:
        parts.append("<h2>%s %s</h2><p><a href='%s'>%s</a> | fetched %s | as of %s<br>reader: <span class=tag>%s</span> "
                     "data: <span class=tag>%s</span> %s lines read %d/%d</p>" % (
                         e(r["case"]), badge(r["decision"]), e(r["url"] or ""), e(r["url"] or ""),
                         e(r["fetched_utc"] or ""), e(r["now"]), e(r["reader"]), e(r["data_source"]),
                         e(r["reader_note"]), r["coverage"]["lines_read"], r["coverage"]["lines_total"]))
        parts.append("<table><tr><th>check<th>status<th>why<th>quote (verbatim)<th>doc:line<th>receipt</tr>")
        for c in r["checks"]:
            ev = c["evidence"][0] if c["evidence"] else None
            parts.append("<tr><td>%s<td>%s<td>%s<td>%s<td>%s<td><code>%s</code></tr>" % (
                e(c["criterion"]), badge(c["status"]), e(c["detail"]),
                e('"%s"' % ev["quote"]) if ev else "<i>no evidence: HOLD rule</i>",
                e("%s:%d" % (ev["doc"], ev["line"])) if ev else "-", e(ev["receipt"][:16]) if ev else "-"))
        parts.append("</table>")
        if r["rejected"]:
            parts.append("<p>rejected claims: %d</p>" % len(r["rejected"]))
    return "".join(parts)


def make_screen(port: int, now=None):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            rs = reports(now or datetime.now(timezone.utc))
            if self.path.startswith("/api"):
                body, ct = json.dumps(rs, indent=2).encode(), "application/json"
            else:
                body, ct = page(rs).encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return HTTPServer(("127.0.0.1", port), H)


def run_screen(port: int, now=None):
    httpd = make_screen(port, now)
    print("BidGate screen: http://127.0.0.1:%d" % httpd.server_port)
    httpd.serve_forever()
