"""Domain model. No I/O, no framework, no network (SPEC: Ubiquitous language)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Tuple


@dataclass(frozen=True)
class Line:
    n: int  # 1-based
    text: str


@dataclass(frozen=True)
class Receipt:
    doc: str
    line: int
    sha256: str


@dataclass(frozen=True)
class Claim:
    """A reader's pointer. It never carries a value; the domain computes it from the quote."""
    field: str
    line: int
    quote: str


@dataclass(frozen=True)
class Finding:
    field: str
    value: Any
    quote: str
    doc: str
    line: int
    receipt: str


@dataclass(frozen=True)
class Rejected:
    claim: Claim
    reason: str


@dataclass(frozen=True)
class Check:
    criterion: str
    status: str  # PASS | FAIL | MISSING | CONFLICT
    detail: str
    findings: Tuple[Finding, ...] = ()


@dataclass(frozen=True)
class Verdict:
    decision: str  # GO | HOLD | NO
    checks: Tuple[Check, ...]
    rejected: Tuple[Rejected, ...] = field(default=())


FIELDS: List[str] = ["deadline", "min_age", "mode", "fee", "deliverables"]
CRITERIA = {"deadline": "deadline", "min_age": "min_age", "mode": "mode", "fee": "fee",
            "deliverables": "deliverables"}
