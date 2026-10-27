"""Data port adapters: ``query(sql, params) -> list[tuple]``, ``name``, ``is_stand_in``.

- StandInSource: loads CSV files in place into SQLite and answers the same SQL. Stand-in for
  Zetaris-style "query where the data lives" (BIDGATE_DATA_URL swaps in HttpSqlSource).
- HttpSqlSource: posts {"sql","params"} to an endpoint and expects {"rows": [[...]]}. The wire
  format is an assumption (unverified against Zetaris).
"""
from __future__ import annotations

import csv
import json
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any, List, Sequence, Tuple


class StandInSource:
    is_stand_in = True
    name = "stand-in: SQLite + CSV queried in place (Zetaris slot)"

    def __init__(self, data_dir):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE doc_lines (doc TEXT, n INTEGER, text TEXT)")
        for f in sorted(Path(data_dir).glob("*.csv")):
            with open(f, newline="", encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            if not rows:
                continue
            cols = ", ".join('"%s" TEXT' % c for c in rows[0])
            self.db.execute('CREATE TABLE "%s" (%s)' % (f.stem, cols))
            ph = ",".join("?" * len(rows[0]))
            self.db.executemany('INSERT INTO "%s" VALUES (%s)' % (f.stem, ph), rows[1:])

    def load_document(self, doc: str, text: str) -> None:
        self.db.execute("DELETE FROM doc_lines WHERE doc=?", (doc,))
        self.db.executemany("INSERT INTO doc_lines VALUES (?,?,?)",
                            [(doc, i + 1, t) for i, t in enumerate(text.splitlines())])

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple]:
        return [tuple(r) for r in self.db.execute(sql, tuple(params)).fetchall()]


class HttpSqlSource:
    is_stand_in = False

    def __init__(self, url: str, token: str = "", timeout: float = 60.0):
        self.url, self.token, self.timeout = url, token, timeout
        self.name = "remote SQL endpoint " + url

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple]:
        req = urllib.request.Request(self.url, data=json.dumps({"sql": sql, "params": list(params)}).encode(),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return [tuple(x) for x in json.loads(r.read())["rows"]]

    def load_document(self, doc: str, text: str) -> None:
        """No-op: a remote source is expected to expose documents itself as table doc_lines(doc, n, text)."""
