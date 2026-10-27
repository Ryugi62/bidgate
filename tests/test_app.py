import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bidgate.adapters.llm import RuleReader
from bidgate.adapters.source import StandInSource
from bidgate.application.analyze import analyze_case, load_profile
from bidgate.application.render import to_markdown

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NOW = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)


def report(case):
    src = StandInSource(DATA)
    return analyze_case(DATA / case, src, RuleReader(), NOW)


def test_profile_loaded_from_csv_through_port():
    p = load_profile(StandInSource(DATA))
    assert p["age"] >= 16 and p["can_attend_onsite"] is False and p["budget_usd"] == 0.0


def test_oah_is_go():
    r = report("oah-2026")
    assert r["decision"] == "GO", r["checks"]


def test_yc_is_no_because_onsite():
    r = report("yc-w2027")
    assert r["decision"] == "NO"
    assert any(c["criterion"] == "mode" and c["status"] == "FAIL" for c in r["checks"])


def test_gsoc_is_hold():
    r = report("gsoc-how-it-works")
    assert r["decision"] == "HOLD"


def test_report_has_receipts_and_stand_in_label():
    r = report("oah-2026")
    for c in r["checks"]:
        for e in c["evidence"]:
            assert e["quote"] and e["line"] >= 1 and len(e["receipt"]) == 64
    assert "stand-in" in r["data_source"]
    assert r["coverage"]["lines_read"] == r["coverage"]["lines_total"] > 10


def test_report_is_deterministic_json():
    a = json.dumps(report("oah-2026"), sort_keys=True)
    b = json.dumps(report("oah-2026"), sort_keys=True)
    assert a == b


def test_markdown_contains_verdict_and_quotes():
    md = to_markdown(report("yc-w2027"))
    assert "NO" in md and "|" in md and "in-person" in md


def test_demo_set_has_all_three_verdicts():
    ds = {report(c)["decision"] for c in ("oah-2026", "yc-w2027", "gsoc-how-it-works")}
    assert ds == {"GO", "HOLD", "NO"}


def test_cli_run_outputs_markdown_and_json(tmp_path):
    out = subprocess.run([sys.executable, "-m", "bidgate", "run", str(DATA / "oah-2026"),
                          "--now", "2026-10-27T15:00:00+00:00", "--json", str(tmp_path / "o.json")],
                         cwd=ROOT, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    assert "GO" in out.stdout
    assert json.loads((tmp_path / "o.json").read_text())["decision"] == "GO"


def test_domain_has_no_io_imports():
    for f in (ROOT / "bidgate" / "domain").glob("*.py"):
        t = f.read_text()
        for bad in ("import sqlite3", "import urllib", "import socket", "import http", "import os", "open("):
            assert bad not in t, (f.name, bad)


def test_web_screen_serves_html_and_json():
    import threading
    import urllib.request
    from bidgate.infrastructure.web import make_screen
    httpd = make_screen(0, NOW)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % httpd.server_port
    html = urllib.request.urlopen(base + "/").read().decode()
    api = json.loads(urllib.request.urlopen(base + "/api").read())
    httpd.shutdown()
    assert "stand-in" in html and "BidGate" in html and "GO" in html
    assert {r["decision"] for r in api} == {"GO", "HOLD", "NO"}


def test_cli_falls_back_when_llm_endpoint_down():
    out = subprocess.run([sys.executable, "-m", "bidgate", "run", str(DATA / "yc-w2027"),
                          "--now", "2026-10-27T15:00:00+00:00"], cwd=ROOT, capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "BIDGATE_LLM_BASE_URL": "http://127.0.0.1:9/v1",
                              "BIDGATE_LLM_READER": "chunked"})
    assert out.returncode == 0 and "read by rules" in out.stdout and "failed twice" in out.stdout and "NO" in out.stdout


def test_cli_markovian_engine_down_rules_still_decide():
    out = subprocess.run([sys.executable, "-m", "bidgate", "run", str(DATA / "yc-w2027"),
                          "--now", "2026-10-27T15:00:00+00:00"], cwd=ROOT, capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "BIDGATE_LLM_BASE_URL": "http://127.0.0.1:9/v1"})
    assert out.returncode == 0 and "rules reader covered" in out.stdout and "NO" in out.stdout


def test_oah_after_deadline_is_no():
    src = StandInSource(DATA)
    r = analyze_case(DATA / "oah-2026", src, RuleReader(), datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc))
    assert r["decision"] == "NO"
