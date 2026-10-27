import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from bidgate.adapters.llm import FallbackReader, OpenAICompatReader, RuleReader
from bidgate.adapters.source import HttpSqlSource, StandInSource
from bidgate.domain.model import Line

LINES = [Line(1, "Deadline Oct 27, 2026, 23:45 UTC"), Line(2, "Fully online."), Line(3, "Hello")]


def serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_port


def test_rule_reader_points_at_lines_with_quotes():
    claims = RuleReader().propose("d", LINES)
    fields = {(c.field, c.line) for c in claims}
    assert ("deadline", 1) in fields and ("mode", 2) in fields
    for c in claims:
        assert c.quote in LINES[c.line - 1].text


def test_rule_reader_is_deterministic():
    assert RuleReader().propose("d", LINES) == RuleReader().propose("d", LINES)


def test_openai_compat_reader_parses_claims():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            seen["path"] = self.path
            seen["body"] = json.loads(self.rfile.read(n))
            seen["auth"] = self.headers.get("Authorization")
            content = json.dumps({"claims": [{"field": "deadline", "line": 1, "quote": LINES[0].text}]})
            out = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv, url = serve(H)
    r = OpenAICompatReader(url + "/v1", "k", "m")
    claims = r.propose("d", LINES)
    srv.shutdown()
    assert [(c.field, c.line) for c in claims] == [("deadline", 1)]
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["body"]["model"] == "m"


def test_openai_compat_reader_error_raises_and_fallback_used():
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv, url = serve(H)
    fb = FallbackReader(OpenAICompatReader(url + "/v1", "k", "m"), RuleReader())
    claims = fb.propose("d", LINES)
    srv.shutdown()
    assert claims and "fell back" in fb.note


def test_fallback_reader_without_failure_has_empty_note():
    fb = FallbackReader(RuleReader(), RuleReader())
    fb.propose("d", LINES)
    assert fb.note == ""


def test_stand_in_source_queries_csv_in_place(tmp_path):
    (tmp_path / "profile.csv").write_text("key,value\nage,21\nbudget_usd,0\n")
    s = StandInSource(tmp_path)
    assert s.is_stand_in
    assert s.query("SELECT value FROM profile WHERE key=?", ("age",)) == [("21",)]


def test_stand_in_source_loads_document_lines(tmp_path):
    (tmp_path / "profile.csv").write_text("key,value\n")
    s = StandInSource(tmp_path)
    s.load_document("d", "a\nb\n\nc")
    rows = s.query("SELECT n,text FROM doc_lines WHERE doc=? ORDER BY n", ("d",))
    assert rows == [(1, "a"), (2, "b"), (3, ""), (4, "c")]


def test_http_sql_source_posts_sql():
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers["Content-Length"])
            got["body"] = json.loads(self.rfile.read(n))
            out = json.dumps({"rows": [["21"]]}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv, url = serve(H)
    s = HttpSqlSource(url)
    rows = s.query("SELECT 1 WHERE ?", ("x",))
    srv.shutdown()
    assert rows == [("21",)] and got["body"]["sql"].startswith("SELECT") and not s.is_stand_in
