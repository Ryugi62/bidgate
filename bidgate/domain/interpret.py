"""Turn a verbatim quote into a typed value. Pure functions."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

try:  # zoneinfo exists on 3.9+, tz database may be missing
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
DEADLINE_WORDS = re.compile(r"deadline|clos(?:e|es|ing)|\bdue\b|submit", re.I)

_FULL = re.compile(r"([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4}),? (\d{1,2}):(\d{2}) ?UTC")
_NOYEAR = re.compile(r"([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)? at (\d{1,2})(?::(\d{2}))? ?(am|pm) ?(PT|PST|PDT|UTC)", re.I)


def _month(name: str) -> Optional[int]:
    return MONTHS.get(name[:3].lower())


def _zone_to_utc(naive: datetime, zone: str) -> datetime:
    z = zone.upper()
    if z == "UTC":
        return naive.replace(tzinfo=timezone.utc)
    if ZoneInfo is not None:
        try:
            return naive.replace(tzinfo=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)
        except Exception:
            pass
    return (naive + timedelta(hours=8)).replace(tzinfo=timezone.utc)


def _deadline(q: str, now: datetime) -> Optional[datetime]:
    if not DEADLINE_WORDS.search(q):
        return None
    m = _FULL.search(q)
    if m and _month(m.group(1)):
        return datetime(int(m.group(3)), _month(m.group(1)), int(m.group(2)),
                        int(m.group(4)), int(m.group(5)), tzinfo=timezone.utc)
    m = _NOYEAR.search(q)
    if m and _month(m.group(1)):
        hour = int(m.group(3)) % 12 + (12 if m.group(5).lower() == "pm" else 0)
        minute = int(m.group(4) or 0)
        for year in (now.year, now.year + 1):
            try:
                cand = _zone_to_utc(datetime(year, _month(m.group(1)), int(m.group(2)), hour, minute), m.group(6))
            except ValueError:
                return None
            if cand >= now:
                return cand
        return cand
    return None


def _min_age(q: str) -> Optional[int]:
    for pat in (r"aged? (\d{1,2}) or older", r"at least (\d{1,2}) years", r"(\d{1,2}) years (?:of age )?or older"):
        m = re.search(pat, q, re.I)
        if m:
            return int(m.group(1))
    return None


def _mode(q: str) -> Optional[str]:
    onsite = re.search(r"in[- ]person|on-?site", q, re.I)
    online = re.search(r"fully online|fully remote|online only|100% online", q, re.I)
    if onsite and online:
        return None
    return "onsite" if onsite else "online" if online else None


def _fee(q: str) -> Optional[float]:
    m = re.search(r"fee of \$(\d+(?:\.\d+)?)|\$(\d+(?:\.\d+)?)[^.]*\bfee\b", q, re.I)
    if m:
        return float(m.group(1) or m.group(2))
    if re.search(r"cost anything[^.]*\?\s*[-−–]?\s*No\b", q, re.I):
        return 0.0
    if re.search(r"\bfree\b", q, re.I) and re.search(r"fee|cost|regist|entry|enter|admission|submission", q, re.I):
        return 0.0
    return None


def _deliverables(q: str) -> Optional[frozenset]:
    found = set()
    if re.search(r"video(?! conference| call)", q, re.I):
        found.add("video")
    if re.search(r"slide deck|pitch deck|\bdeck\b|\bslides\b", q, re.I):
        found.add("deck")
    if re.search(r"github|repository|source code", q, re.I):
        found.add("repo")
    if re.search(r"proposal|application form|essay", q, re.I):
        found.add("proposal")
    return frozenset(found) or None


def interpret(field: str, quote: str, now: datetime) -> Optional[Any]:
    if field == "deadline":
        return _deadline(quote, now)
    if field == "min_age":
        return _min_age(quote)
    if field == "mode":
        return _mode(quote)
    if field == "fee":
        return _fee(quote)
    if field == "deliverables":
        return _deliverables(quote)
    return None
