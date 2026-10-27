"""Render a report dict as Markdown."""
from __future__ import annotations

from typing import Any, Dict


def _cell(s: str, n: int = 140) -> str:
    s = s.replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def to_markdown(r: Dict[str, Any]) -> str:
    out = ["## %s: **%s**" % (r["case"], r["decision"]), "",
           "source: %s (fetched %s) | as of %s" % (r["url"], r["fetched_utc"], r["now"]),
           "reader: %s | data: %s%s" % (r["reader"], r["data_source"],
                                         (" | note: " + r["reader_note"]) if r["reader_note"] else ""),
           "read %d/%d lines" % (r["coverage"]["lines_read"], r["coverage"]["lines_total"]), "",
           "| check | status | why | quote (verbatim) | doc:line | receipt |", "|---|---|---|---|---|---|"]
    for c in r["checks"]:
        if c["evidence"]:
            e = c["evidence"][0]
            more = " (+%d more)" % (len(c["evidence"]) - 1) if len(c["evidence"]) > 1 else ""
            out.append("| %s | %s | %s | \"%s\"%s | %s:%d | %s |" % (
                c["criterion"], c["status"], _cell(c["detail"], 60), _cell(e["quote"]), more,
                e["doc"], e["line"], e["receipt"][:12]))
        else:
            out.append("| %s | %s | %s | (none: HOLD rule, no evidence) | - | - |" % (
                c["criterion"], c["status"], _cell(c["detail"], 60)))
    if r["rejected"]:
        out += ["", "rejected claims: %d" % len(r["rejected"])]
        out += ["- %s line %d: %s" % (x["field"], x["line"], x["reason"]) for x in r["rejected"][:10]]
    return "\n".join(out) + "\n"
