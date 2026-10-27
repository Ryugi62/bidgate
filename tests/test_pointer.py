"""Pointer mode: the model only says (field, line); the adapter copies that line's text as the quote."""
from datetime import datetime, timezone

from bidgate.adapters.markovian import MarkovianReader
from bidgate.application.analyze import analyze_case
from bidgate.domain.model import Claim, Line

LINES = [
    Line(1, "Deadline Oct 27, 2026, 23:45 UTC"),
    Line(2, "Open worldwide to anyone aged 16 or older at the start of the build window."),
    Line(3, "Fully online."),
    Line(4, "Welcome to the event, we are glad you are here."),
]


class NoRules:
    name = "no rules"

    def propose(self, doc, lines):
        return []


def runner(claims):
    def run(payload):
        return {"engine": "e", "status": "completed", "claims": claims,
                "steps": [{"step": i, "lines": [1, 1], "ok": True, "attempts": 1, "error": "", "claims": 0}
                          for i in range(1, len(payload["chunks"]) + 1)]}
    return run


def test_pointer_becomes_claim_with_exact_line_text_as_quote():
    r = MarkovianReader(NoRules(), runner=runner([{"field": "mode", "line": 3}]))
    got = r.propose("d", LINES)
    assert got == [Claim("mode", 3, "Fully online.")]
    assert r.stats["model_claims_proposed"] == 1


def test_model_quote_text_is_ignored_even_if_wrong():
    r = MarkovianReader(NoRules(), runner=runner([{"field": "mode", "line": 3, "quote": "totally made up"}]))
    assert r.propose("d", LINES) == [Claim("mode", 3, "Fully online.")]


def test_bad_pointers_are_dropped_with_reasons():
    ptrs = [{"field": "mode", "line": 99}, {"field": "modee", "line": 3}, {"field": "mode", "line": None},
            {"field": "fee", "line": 0}, {"field": "mode", "line": 3}]
    r = MarkovianReader(NoRules(), runner=runner(ptrs))
    got = r.propose("d", LINES)
    assert got == [Claim("mode", 3, "Fully online.")]
    st = r.stats
    assert st["model_pointers_dropped"] == {"line_out_of_range": 2, "unknown_field": 1, "line_not_a_number": 1}
    assert st["model_claims_proposed"] == 1


def _case(tmp_path):
    import json
    d = tmp_path / "c"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"case": "d", "url": "u", "fetched_utc": "t"}))
    (d / "source.txt").write_text("\n".join(l.text for l in LINES))
    return d


class Src:
    name = "mem"

    def __init__(self, lines):
        self.lines = lines

    def load_document(self, doc, text):
        pass

    def query(self, sql, params=()):
        if "FROM profile" in sql:
            return [("age", "21"), ("can_attend_onsite", "no"), ("budget_usd", "0"), ("can_produce", "deck")]
        if "COUNT" in sql:
            return [(len(self.lines),)]
        return [(l.n, l.text) for l in self.lines]


NOW = datetime(2026, 10, 27, 14, tzinfo=timezone.utc)


def test_right_line_is_accepted_and_decides_a_cell_alone(tmp_path):
    r = MarkovianReader(NoRules(), runner=runner([{"field": "mode", "line": 3}]))
    rep = analyze_case(_case(tmp_path), Src(LINES), r, NOW)
    st = rep["reader_stats"]
    assert st["model_claims_proposed"] == 1 and st["model_claims_accepted"] == 1
    assert st["cells_decided_by_model_only"] == 1
    assert [c["status"] for c in rep["checks"] if c["criterion"] == "mode"] == ["PASS"]


def test_wrong_line_is_rejected_by_the_domain(tmp_path):
    r = MarkovianReader(NoRules(), runner=runner([{"field": "mode", "line": 4}]))
    rep = analyze_case(_case(tmp_path), Src(LINES), r, NOW)
    st = rep["reader_stats"]
    assert st["model_claims_proposed"] == 1 and st["model_claims_accepted"] == 0
    assert st["cells_decided_by_model_only"] == 0
    assert rep["rejected"][0]["reason"] == "quote yields no value for this field"
