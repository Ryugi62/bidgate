"""Key JOIN: document lines are joined to profile facts by a KEY (line -> field -> profile key), not crossed.

The statement keeps every line (each earns a receipt), tags a line with the field it states
(regexp_like pattern in the ON clause) and attaches the profile fact only where the field names one
(`p.key = f.pkey`). The old statement was a CROSS JOIN: every line x every profile field.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bidgate.adapters.llm import RuleReader
from bidgate.adapters.source import StandInSource
from bidgate.application.analyze import JOIN_SQL, analyze_case
from bidgate.domain.model import Line

DATA = Path(__file__).resolve().parent.parent / "data"
NOW = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)
PROFILE_KEYS = {"age", "can_attend_onsite", "budget_usd", "can_produce"}
FIELD_OF_KEY = {"age": "min_age", "can_attend_onsite": "mode", "budget_usd": "fee", "can_produce": "deliverables"}


def _rows(case):
    src = StandInSource(DATA)
    src.load_document(case, (DATA / case / "source.txt").read_text(encoding="utf-8"))
    return src.query(JOIN_SQL, (case,))  # (n, field, text, key, value)


def test_statement_is_a_key_join_not_a_cross_join():
    s = JOIN_SQL.upper()
    assert "CROSS JOIN" not in s
    assert s.count(" ON ") >= 2
    assert "P.KEY = F.PKEY" in s
    assert JOIN_SQL.count("?") == 1  # only the document id is a parameter (the bridge inlines params one by one)
    assert "doc_lines" in JOIN_SQL and "profile" in JOIN_SQL


def test_rows_shrink_from_cross_product_to_about_one_per_line():
    case = "oah-2026"
    n_lines = len((DATA / case / "source.txt").read_text(encoding="utf-8").splitlines())
    rows = _rows(case)
    assert {r[0] for r in rows} == set(range(1, n_lines + 1))   # every line is still delivered
    assert len(rows) < n_lines * 4 // 3                          # was lines x 4 = 704; now about one row per line
    matched = [r for r in rows if r[3] is not None]
    assert 0 < len(matched) < n_lines // 3                       # only lines that name a profile field carry a fact


def test_profile_fact_is_attached_by_key():
    for r in _rows("oah-2026"):
        n, field, text, key, value = r
        if key is None:
            assert value is None
        else:
            assert key in PROFILE_KEYS and FIELD_OF_KEY[key] == field and value not in (None, "")


def test_deadline_lines_are_tagged_without_a_profile_fact():
    rows = _rows("oah-2026")
    deadline = [r for r in rows if r[1] == "deadline"]
    assert deadline and all(r[3] is None and r[4] is None for r in deadline)
    assert any("Oct 27, 2026, 23:45 UTC" in r[2] for r in deadline)


@pytest.mark.parametrize("case", ["oah-2026", "gsoc-how-it-works", "yc-w2027"])
def test_every_rules_claim_sits_on_a_line_the_join_tagged_with_that_field(case):
    rows = _rows(case)
    tagged = {(r[0], r[1]) for r in rows if r[1]}
    lines = [Line(n, t) for n, t in sorted({(r[0], r[2]) for r in rows})]
    claims = RuleReader().propose(case, lines)
    assert claims
    missing = [(c.field, c.line) for c in claims if (c.line, c.field) not in tagged]
    assert missing == []


@pytest.mark.parametrize("case,verdict", [("oah-2026", "GO"), ("gsoc-how-it-works", "HOLD"), ("yc-w2027", "NO")])
def test_key_join_path_gives_the_same_verdicts_and_reads_every_line(case, verdict):
    rep = analyze_case(DATA / case, StandInSource(DATA), RuleReader(), NOW)
    assert rep["decision"] == verdict
    assert rep["coverage"]["lines_read"] == rep["coverage"]["lines_total"]


def test_one_profile_statement_only():
    class Rec(StandInSource):
        sqls = []

        def query(self, sql, params=()):
            self.sqls.append(sql)
            return super().query(sql, params)

    src = Rec(DATA)
    analyze_case(DATA / "oah-2026", src, RuleReader(), NOW)
    assert sum(1 for s in src.sqls if "profile" in s) == 1


def test_missing_profile_keys_fall_back_to_one_extra_profile_query(tmp_path):
    import json
    (tmp_path / "profile.csv").write_text(
        "key,value\nage,21\ncan_attend_onsite,no\nbudget_usd,0\ncan_produce,video;deck\n",
        encoding="utf-8",
    )
    case = tmp_path / "blank"
    case.mkdir()
    (case / "meta.json").write_text(json.dumps({"case": "blank", "url": "u", "fetched_utc": "t"}), encoding="utf-8")
    (case / "source.txt").write_text("Hello world.\nNothing relevant here.\n", encoding="utf-8")

    class Rec(StandInSource):
        sqls = []

        def query(self, sql, params=()):
            self.sqls.append(sql)
            return super().query(sql, params)

    src = Rec(tmp_path)
    rep = analyze_case(case, src, RuleReader(), NOW)
    assert sum(1 for s in src.sqls if "profile" in s) == 2  # JOIN + load_profile fallback
    assert "SELECT key, value FROM profile" in src.sqls
    assert rep["coverage"]["lines_read"] == rep["coverage"]["lines_total"] == 2


def test_bridge_keeps_values_in_select_list_order():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from bridge import rewrite, ordered_values
    sql = rewrite(JOIN_SQL, ("oah-2026",))
    assert "BIDGATE.doc_lines" in sql and "BIDGATE.profile" in sql and "d.doc='oah-2026'" in sql
    assert "CAST(d.n AS INT)" in sql
    # Zetaris returned record keys in its own order (n, field, text, key, value); the wire needs the SELECT order
    rec = {"n": "5", "field": "fee", "text": "Free to enter", "key": "budget_usd", "value": "0"}
    assert ordered_values(JOIN_SQL, rec) == [5, "fee", "Free to enter", "budget_usd", "0"]
