"""Meterless Markovian engine as the reading path.

The document is cut into chunks of at most 1000 characters (line numbers kept). A Node process runs the vendored
Markovian reference runtime (``vendor/markovian/reference``, Apache-2.0): every chunk is one bounded step that
sees the goal plus the compressed carryover of the previous step, and the injected generator is a Nightshift
chat completion (one user message). Python only supplies chunks and merges the answers.

Pointer mode: the model answers only (field, line). The adapter copies that line's text as the quote, so the
model never has to copy words; the domain still checks the line, the receipt and whether the line really states
the field (a wrong line is rejected there).

Merge rule: the rules reader's claims are always kept; LLM claims are added when they fill a gap or agree with
the rules value. A verbatim LLM quote that would put a second, different value on a single-valued field is
dropped and counted, so the model can only add information, never turn a rules PASS into a CONFLICT.
The domain still verifies every claim against the delivered line (quote + receipt).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from ..domain.interpret import interpret
from ..domain.model import FIELDS, Claim, Line
from .llm import split_lines

ROOT = Path(__file__).resolve().parent.parent.parent
RUNNER = ROOT / "tools" / "markovian_run.mjs"
ENGINE_PATH = "vendor/markovian/reference/src"
GOAL = "Find the lines of this rules text that state the deadline, minimum age, mode, fee and deliverables."
# Plain-language prompt: on this Nightshift build, wording like "Answer ONLY JSON" or "for each field ... write" was
# routed to a lane that is not loaded (HTTP 502 model_load_failed); this wording was answered in 3 to 5 s (measured).
PROMPT = ("Read this text. Each line starts with its line number. For each of these five things, name the line number "
          "that states it: the deadline, the minimum age, whether it is online, the fee, what must be delivered. If no "
          "line states a thing, say none for it. One short line each, in the form: deadline | none")
_REF = datetime(2000, 1, 1, tzinfo=timezone.utc)


def node_binary() -> Optional[str]:
    found = os.environ.get("BIDGATE_NODE") or shutil.which("node")
    if found:
        return found
    local = Path.home() / ".local" / "node" / "bin" / "node"
    return str(local) if local.exists() else None


def _value(field: str, quote: str):
    try:
        return interpret(field, quote, _REF)
    except Exception:
        return None


def merge_claims(rules: Sequence[Claim], llm: Sequence[Claim]) -> Tuple[List[Claim], List[Claim]]:
    """Union of rules claims and LLM claims; returns (merged, dropped_llm_claims)."""
    out: List[Claim] = list(rules)
    seen = set(out)
    known = {}
    for c in rules:
        v = _value(c.field, c.quote)
        if v is not None:
            known.setdefault(c.field, []).append(v)
    dropped: List[Claim] = []
    for c in llm:
        if c in seen:
            continue
        v = _value(c.field, c.quote)
        if v is not None and c.field != "deliverables" and known.get(c.field) and v not in known[c.field]:
            dropped.append(c)
            continue
        out.append(c)
        seen.add(c)
        if v is not None:
            known.setdefault(c.field, []).append(v)
    return out, dropped


def pointers_to_claims(pointers: Sequence[dict], lines: Sequence[Line]) -> Tuple[List[Claim], dict]:
    """(field, line) pointers -> Claims whose quote is that line's own text. Bad pointers are counted by reason."""
    by_line = {l.n: l for l in lines}
    out: List[Claim] = []
    bad: dict = {}
    for p in pointers:
        field = str(p.get("field"))
        n = p.get("line")
        if field not in FIELDS:
            reason = "unknown_field"
        elif isinstance(n, bool) or not isinstance(n, int):
            reason = "line_not_a_number"
        elif n not in by_line or not by_line[n].text.strip():
            reason = "line_out_of_range"
        else:
            c = Claim(field, n, by_line[n].text)
            if c not in out:
                out.append(c)
            continue
        bad[reason] = bad.get(reason, 0) + 1
    return out, bad


def run_node(payload: dict, timeout: float) -> dict:
    node = node_binary()
    if node is None:
        raise RuntimeError("node not found (set BIDGATE_NODE)")
    p = subprocess.run([node, "--experimental-transform-types", "--no-warnings", str(RUNNER)],
                       input=json.dumps(payload).encode(), capture_output=True, timeout=timeout, cwd=str(ROOT))
    if p.returncode != 0:
        raise RuntimeError("node exited %d: %s" % (p.returncode, p.stderr.decode(errors="replace")[-200:]))
    return json.loads(p.stdout)


class MarkovianReader:
    def __init__(self, fallback, base_url: str = "", api_key: str = "", model: str = "default",
                 max_chars: int = 1000, timeout: float = 90.0, deadline: float = 480.0,
                 warmup: bool = True,
                 runner: Optional[Callable[[dict], dict]] = None):
        self.fallback = fallback
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.max_chars, self.timeout = min(max_chars, 1000), min(timeout, 90.0)
        self.deadline, self.warmup = min(deadline, 480.0), warmup
        self.runner = runner
        self.name = "Meterless Markovian engine (%s) via Nightshift @ %s" % (ENGINE_PATH, self.base_url or "?")
        self.note = ""
        self.stats: dict = {}
        self.rules_claims: List[Claim] = []
        self.model_claims: List[Claim] = []
        self.model_dropped: List[Claim] = []

    def _chunks(self, lines: Sequence[Line]) -> List[List[Line]]:
        size = self.max_chars
        chunks = split_lines(lines, size)
        while len(chunks) > 32:           # engine bound: maxChunks <= 32
            size *= 2
            chunks = split_lines(lines, size)
        return chunks

    def propose(self, doc: str, lines: Sequence[Line]) -> List[Claim]:
        rules = self.fallback.propose(doc, lines)
        chunks = self._chunks(lines)
        payload = {
            "goal": GOAL, "instructions": PROMPT, "fields": FIELDS,
            "chunks": [{"lines": [{"n": l.n, "text": l.text} for l in c]} for c in chunks],
            "llm": {"base_url": self.base_url, "api_key": self.api_key, "model": self.model,
                    "timeout": self.timeout},
            "deadline_s": self.deadline, "warmup": self.warmup,
        }
        run = self.runner or (lambda p: run_node(p, self.deadline + 30))
        try:
            res = run(payload)
        except Exception as e:  # runner missing, crashed, bad JSON: rules read everything, no silent failure
            self.stats = {"chunks": len(chunks), "primary_chunks": 0,
                          "fallback_chunks": list(range(1, len(chunks) + 1)), "retries": 0, "primary_calls": 0,
                          "errors": {}, "markovian": {"engine": ENGINE_PATH, "status": "runner-failed",
                                                      "steps": [], "error": str(e)[:200]}}
            self.note = "markovian runner failed (%s); whole document read by %s" % (str(e)[:120], self.fallback.name)
            return rules
        steps = res.get("steps", [])
        llm, bad = pointers_to_claims(res.get("claims", []), lines)
        merged, dropped = merge_claims(rules, llm)
        self.rules_claims, self.model_claims = list(rules), list(llm)
        self.model_dropped = list(dropped)
        failed = [s["step"] for s in steps if not s.get("ok")]
        self.stats = {
            "chunks": len(steps), "primary_chunks": len(steps) - len(failed), "fallback_chunks": failed,
            "retries": sum(max(0, s.get("attempts", 1) - 1) for s in steps),
            "primary_calls": sum(s.get("attempts", 1) for s in steps),
            "errors": {str(s["step"]): s.get("error", "")[:80] for s in steps if not s.get("ok")},
            "model_claims_proposed": len(llm), "model_pointers_dropped": bad,
            "markovian": {"engine": res.get("engine", ENGINE_PATH), "status": res.get("status"),
                          "steps": steps, "warmup": res.get("warmup"), "llm_claims": len(llm), "rules_claims": len(rules),
                          "merged_claims": len(merged), "llm_claims_dropped_as_conflicting": len(dropped),
                          "max_carryover_chars": max([s.get("carryover_in_chars", 0) for s in steps] or [0])},
        }
        by = {i: c for i, c in enumerate(chunks, 1)}
        self.note = "; ".join("chunk %d/%d (lines %d-%d) had no model answer (%s), rules reader covered it" % (
            i, len(steps), by[i][0].n, by[i][-1].n, self.stats["errors"].get(str(i), "")) for i in failed if i in by)
        return merged
