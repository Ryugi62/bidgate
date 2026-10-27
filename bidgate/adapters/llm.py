"""LLM port adapters. A reader only *points* (field, line, quote); the domain verifies and computes values.

Port: ``propose(doc, lines) -> list[Claim]``.
- RuleReader: deterministic regex reader (default, offline).
- OpenAICompatReader: any OpenAI-compatible /chat/completions endpoint. This is the slot where a
  Meterless endpoint plugs in (BIDGATE_LLM_BASE_URL). Wire format = standard chat completions.
- FallbackReader: tries a primary reader, falls back and records a note.
- ChunkedReader: splits the document into <=N-char chunks on line boundaries (line numbers kept), asks the
  primary reader per chunk, retries a failed chunk once, and replaces only that chunk with the fallback reader.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import List, Sequence

from ..domain.interpret import interpret
from ..domain.model import FIELDS, Claim, Line

_REF = datetime(2000, 1, 1, tzinfo=timezone.utc)


class ReaderUnavailable(Exception):
    pass


class RuleReader:
    name = "rules (deterministic)"

    def propose(self, doc: str, lines: Sequence[Line]) -> List[Claim]:
        out: List[Claim] = []
        for line in lines:
            if not line.text.strip():
                continue
            parts = [p for p in re.split(r"(?<=[.?!])\s+", line.text) if p] + [line.text]
            for field in FIELDS:
                for p in parts:
                    if interpret(field, p, _REF) is not None:
                        out.append(Claim(field, line.n, p))
                        break
        return out


PROMPT = (
    "You read the rules text of a contest/grant/application. For each field in "
    "[deadline, min_age, mode, fee, deliverables] return every place where the text states it. "
    "Answer ONLY JSON: {\"claims\":[{\"field\":...,\"line\":<line number>,\"quote\":<exact substring of that line>}]}. "
    "Never paraphrase. If the text does not state a field, return no claim for it."
)


class OpenAICompatReader:
    def __init__(self, base_url: str, api_key: str = "", model: str = "default", timeout: float = 60.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = "llm @ " + self.base_url

    def propose(self, doc: str, lines: Sequence[Line]) -> List[Claim]:
        numbered = "\n".join("%d\t%s" % (l.n, l.text) for l in lines)
        body = json.dumps({"model": self.model, "temperature": 0, "max_tokens": 600,
                           "messages": [{"role": "system", "content": PROMPT},
                                        {"role": "user", "content": numbered}]}).encode()
        req = urllib.request.Request(self.base_url + "/chat/completions", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
            content = data["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
            raw = json.loads(content)["claims"]
            return [Claim(str(c["field"]), int(c["line"]), str(c["quote"])) for c in raw]
        except Exception as e:  # network, HTTP, JSON shape: all mean "reader unavailable"
            raise ReaderUnavailable(str(e)) from e


class FallbackReader:
    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback
        self.note = ""
        self.name = primary.name

    def propose(self, doc: str, lines: Sequence[Line]) -> List[Claim]:
        self.note = ""
        try:
            self.name = self.primary.name
            return self.primary.propose(doc, lines)
        except ReaderUnavailable as e:
            self.name = self.fallback.name
            self.note = "primary reader failed (%s); fell back to %s" % (str(e)[:80], self.fallback.name)
            return self.fallback.propose(doc, lines)


def split_lines(lines: Sequence[Line], max_chars: int) -> List[List[Line]]:
    """Group lines into chunks of at most ``max_chars`` characters (line boundaries only, numbers kept).
    A single line longer than the limit becomes its own chunk."""
    chunks: List[List[Line]] = []
    cur: List[Line] = []
    size = 0
    for l in lines:
        cost = len(l.text) + 8  # line number + tab + newline overhead of the prompt format
        if cur and size + cost > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(l)
        size += cost
    if cur:
        chunks.append(cur)
    return chunks


class ChunkedReader:
    """Primary reader per chunk; a chunk that fails twice is read by the fallback and named in ``note``."""

    def __init__(self, primary, fallback, max_chars: int = 5000):
        self.primary, self.fallback, self.max_chars = primary, fallback, max_chars
        self.name = primary.name
        self.note = ""
        self.stats: dict = {}

    def propose(self, doc: str, lines: Sequence[Line]) -> List[Claim]:
        chunks = split_lines(lines, self.max_chars)
        st = {"chunks": len(chunks), "primary_chunks": 0, "fallback_chunks": [], "retries": 0,
              "primary_calls": 0, "errors": {}}
        out: List[Claim] = []
        for i, chunk in enumerate(chunks, 1):
            got = None
            for attempt in (1, 2):
                st["primary_calls"] += 1
                try:
                    got = self.primary.propose(doc, chunk)
                    break
                except ReaderUnavailable as e:
                    st["errors"][str(i)] = str(e)[:80]
                    if attempt == 1:
                        st["retries"] += 1
            if got is None:
                st["fallback_chunks"].append(i)
                got = self.fallback.propose(doc, chunk)
            else:
                st["primary_chunks"] += 1
            out.extend(got)
        self.stats = st
        self.note = "; ".join("chunk %d/%d (lines %d-%d) read by %s after primary failed twice (%s)" % (
            i, len(chunks), chunks[i - 1][0].n, chunks[i - 1][-1].n, self.fallback.name, st["errors"].get(str(i), ""))
            for i in st["fallback_chunks"])
        return out
