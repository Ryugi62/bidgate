import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from bidgate.adapters.llm import RuleReader
from bidgate.adapters.markovian import MarkovianReader, merge_claims, node_binary
from bidgate.domain.model import Claim, Line

ROOT = Path(__file__).resolve().parent.parent

LINES = [
    Line(1, "Deadline Oct 27, 2026, 23:45 UTC"),
    Line(2, "Open worldwide to anyone aged 16 or older at the start of the build window."),
    Line(3, "Fully online."),
    Line(4, "Registration, the platform workspace, mentor office hours and submission are all free."),
    Line(5, "A demo video of 1-4 minutes and a repo are required."),
]


def steps_for(n, failed=()):
    return [{"step": i, "lines": [i, i], "carryover_in_chars": 0 if i == 1 else 40 * i,
             "carryover_level": "none" if i == 1 else "marker", "ok": i not in failed,
             "attempts": 2 if i in failed else 1, "error": "HTTP 502" if i in failed else "", "claims": 0}
            for i in range(1, n + 1)]


def fake_runner(claims, failed=()):
    def run(payload):
        return {"engine": "markovian-reference", "status": "completed", "claims": claims,
                "steps": steps_for(len(payload["chunks"]), failed)}
    return run


def test_merge_keeps_every_rules_claim_and_adds_new_llm_claims():
    rules = [Claim("fee", 4, "are all free")]
    llm = [Claim("mode", 3, "Fully online")]
    out, dropped = merge_claims(rules, llm)
    assert rules[0] in out and llm[0] in out and dropped == []


def test_merge_drops_llm_claim_that_would_conflict_with_rules_value_and_reports_it():
    rules = RuleReader().propose("d", LINES)
    bad = Claim("min_age", 2, "aged 16")  # same value: corroboration, kept
    worse = Claim("min_age", 2, "older")   # yields no value: harmless, domain rejects
    out, dropped = merge_claims(rules, [bad])
    assert bad in out and dropped == []
    # a verbatim quote with a different value for a single-valued field must not create CONFLICT
    lines = [Line(1, "Open worldwide to anyone aged 16 or older."), Line(2, "Mentors must be aged 18 or older.")]
    rr = RuleReader().propose("d", lines[:1])
    conflicting = Claim("min_age", 2, "aged 18 or older")
    out, dropped = merge_claims(rr, [conflicting])
    assert conflicting not in out and dropped == [conflicting]


def test_rules_pass_survives_llm_failure_and_empty_answer():
    base = RuleReader().propose("d", LINES)
    for runner in (fake_runner([], failed=(1, 2, 3, 4, 5)), fake_runner([])):
        r = MarkovianReader(RuleReader(), runner=runner, max_chars=1000)
        got = r.propose("d", LINES)
        assert set(base) <= set(got)


def test_runner_crash_falls_back_to_rules_with_note():
    def boom(payload):
        raise RuntimeError("node exited 1")
    r = MarkovianReader(RuleReader(), runner=boom, max_chars=1000)
    got = r.propose("d", LINES)
    assert set(RuleReader().propose("d", LINES)) <= set(got)
    assert "markovian runner failed" in r.note and "node exited 1" in r.note
    assert r.stats["markovian"]["status"] == "runner-failed"


def test_stats_record_steps_carryover_and_fallback_chunks():
    r = MarkovianReader(RuleReader(), runner=fake_runner([Claim("mode", 3, "Fully online").__dict__], failed=(2,)),
                        max_chars=40)
    r.propose("d", LINES)
    st = r.stats
    assert st["chunks"] == len(st["markovian"]["steps"]) >= 2
    assert st["fallback_chunks"] == [2]
    assert st["primary_chunks"] == st["chunks"] - 1
    assert st["markovian"]["steps"][1]["carryover_in_chars"] > 0
    assert "markovian" in r.name.lower()
    assert "chunk 2" in r.note and "502" in r.note


def test_llm_claims_arrive_as_claim_objects():
    r = MarkovianReader(RuleReader(), runner=fake_runner([{"field": "mode", "line": 3, "quote": "Fully online"}]),
                        max_chars=1000)
    assert Claim("mode", 3, "Fully online.") in r.propose("d", LINES)


# --- real node runtime against a local fake OpenAI endpoint (no Nightshift needed) ---

class Fake(BaseHTTPRequestHandler):
    seen = []
    warm = 0

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = body["messages"][0]["content"]
        assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
        if user == "Reply OK":
            Fake.warm += 1
            data = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
            return
        Fake.seen.append(body)
        first = [l for l in user.split("\n") if l[:1].isdigit()][0]
        n = int(first.split("\t")[0])
        out = {"claims": [{"field": "mode", "line": n, "quote": first.split("\t")[1][:6]}]}
        data = json.dumps({"choices": [{"message": {"content": json.dumps(out)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(node_binary() is None, reason="node not installed")
def test_real_markovian_runtime_passes_carryover_between_chunks():
    Fake.seen = []
    Fake.warm = 0
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = MarkovianReader(RuleReader(), base_url="http://127.0.0.1:%d/v1" % srv.server_port, api_key="k",
                            model="m", max_chars=1000, timeout=20)
        lines = [Line(i, ("L%d " % i) + "x" * 300) for i in range(1, 9)]
        r.propose("d", lines)
    finally:
        srv.shutdown()
    steps = r.stats["markovian"]["steps"]
    assert len(steps) >= 3 and all(s["ok"] for s in steps)
    assert steps[0]["carryover_in_chars"] == 0
    assert all(s["carryover_in_chars"] > 0 for s in steps[1:])
    assert "vendor/markovian/reference" in r.stats["markovian"]["engine"]
    assert "COMPLETED" in Fake.seen[1]["messages"][0]["content"]   # carryover reached the model
    assert r.stats["primary_chunks"] == len(steps)
    assert Fake.warm == 1 and r.stats["markovian"]["warmup"]["ok"]


class Stall(BaseHTTPRequestHandler):
    def do_POST(self):
        import time
        time.sleep(6)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(node_binary() is None, reason="node not installed")
def test_stalled_engine_hits_run_deadline_and_rules_still_decide():
    import time
    srv = HTTPServer(("127.0.0.1", 0), Stall)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = MarkovianReader(RuleReader(), base_url="http://127.0.0.1:%d/v1" % srv.server_port, model="m",
                            max_chars=1000, timeout=2, deadline=5, warmup=True)
        lines = [Line(i, ("L%d " % i) + "x" * 300) for i in range(1, 13)]
        t0 = time.time()
        got = r.propose("d", lines)
    finally:
        srv.shutdown()
    assert time.time() - t0 < 25
    assert r.stats["primary_chunks"] == 0 and len(r.stats["fallback_chunks"]) == r.stats["chunks"]
    errs = " ".join(r.stats["errors"].values())
    assert "aborted" in errs or "time limit" in errs
    assert set(RuleReader().propose("d", lines)) <= set(got)


def test_timeouts_are_capped_at_90s_and_8min():
    r = MarkovianReader(RuleReader(), timeout=500, deadline=9999)
    assert r.timeout == 90 and r.deadline == 480


class Pipe(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = body["messages"][0]["content"]
        if user == "Reply OK":
            out = "OK"
        else:
            out = "Here you go:\n\n1. Online | 3\n2. Fee | line 4\n3. Colour | 1\n4. Deadline | 99"
        data = json.dumps({"choices": [{"message": {"content": out}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.mark.skipif(node_binary() is None, reason="node not installed")
def test_pipe_format_answer_is_parsed_into_pointers_and_bad_ones_counted():
    srv = HTTPServer(("127.0.0.1", 0), Pipe)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = MarkovianReader(RuleReader(), base_url="http://127.0.0.1:%d/v1" % srv.server_port, model="m",
                            max_chars=1000, timeout=20)
        r.propose("d", LINES)
    finally:
        srv.shutdown()
    st = r.stats["markovian"]
    assert st["llm_claims"] == 2           # mode@3 and fee@4 parsed
    assert r.stats["model_pointers_dropped"] == {"unknown_field": 1, "line_out_of_range": 1}
    assert st["warmup"]["ok"] and r.stats["primary_chunks"] == r.stats["chunks"]
