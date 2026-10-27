"""LLM port adapters. A reader only *points* (field, line, quote); the domain verifies and computes values.

Port: ``propose(doc, lines) -> list[Claim]``.
- RuleReader: deterministic regex reader (default, offline).
- OpenAICompatReader: any OpenAI-compatible /chat/completions endpoint. This is the slot where a
  Meterless endpoint plugs in (BIDGATE_LLM_BASE_URL). Wire format = standard chat completions.
- FallbackReader: tries a primary reader, falls back and records a note.
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
        body = json.dumps({"model": self.model, "temperature": 0,
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
