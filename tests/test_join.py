"""One SQL JOIN (document lines x applicant profile fields) replaces two SELECTs combined in Python."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from bidgate.adapters.llm import RuleReader
from bidgate.adapters.source import StandInSource
from bidgate.application.analyze import JOIN_SQL, analyze_case

DATA = Path(__file__).resolve().parent.parent / "data"
NOW = datetime(2026, 10, 27, 15, 0, tzinfo=timezone.utc)


class Recording(StandInSource):
    def __init__(self, d):
        super().__init__(d)
        self.sqls = []

    def query(self, sql, params=()):
        self.sqls.append(sql)
        return super().query(sql, params)


def test_reading_and_profile_come_from_one_join_statement():
    src = Recording(DATA)
    analyze_case(DATA / "oah-2026", src, RuleReader(), NOW)
    assert JOIN_SQL in src.sqls
    assert sum(1 for s in src.sqls if "profile" in s) == 1
    assert "JOIN profile" in JOIN_SQL and "doc_lines" in JOIN_SQL


def test_join_rows_pair_every_line_with_every_profile_field():
    src = StandInSource(DATA)
    src.load_document("oah-2026", (DATA / "oah-2026" / "source.txt").read_text(encoding="utf-8"))
    rows = src.query(JOIN_SQL, ("oah-2026",))
    n_lines = len((DATA / "oah-2026" / "source.txt").read_text(encoding="utf-8").splitlines())
    assert len(rows) == n_lines * 4
    assert {r[2] for r in rows} == {"age", "can_attend_onsite", "budget_usd", "can_produce"}


@pytest.mark.parametrize("case,verdict", [("oah-2026", "GO"), ("gsoc-how-it-works", "HOLD"), ("yc-w2027", "NO")])
def test_join_path_gives_the_same_verdicts(case, verdict):
    assert analyze_case(DATA / case, StandInSource(DATA), RuleReader(), NOW)["decision"] == verdict


def test_bridge_rewrites_both_tables_of_the_join_to_zetaris_names():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from bridge import rewrite
    sql = rewrite(JOIN_SQL, ("oah-2026",))
    assert "FROM BIDGATE.doc_lines d CROSS JOIN BIDGATE.profile p" in sql
    assert "ORDER BY CAST(d.n AS INT), p.key" in sql and "d.doc='oah-2026'" in sql
