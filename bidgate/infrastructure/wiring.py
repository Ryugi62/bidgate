"""Compose adapters from environment variables.

BIDGATE_LLM_BASE_URL (+ BIDGATE_LLM_API_KEY, BIDGATE_LLM_MODEL): OpenAI-compatible endpoint (Meterless slot).
BIDGATE_DATA_URL (+ BIDGATE_DATA_TOKEN): remote SQL endpoint (Zetaris slot).
Unset -> deterministic rules reader and local SQLite/CSV stand-in.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..adapters.llm import ChunkedReader, OpenAICompatReader, RuleReader
from ..adapters.source import HttpSqlSource, StandInSource

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"


def build_reader(env=os.environ):
    url = env.get("BIDGATE_LLM_BASE_URL")
    if not url:
        return RuleReader()
    primary = OpenAICompatReader(url, env.get("BIDGATE_LLM_API_KEY", ""), env.get("BIDGATE_LLM_MODEL", "default"),
                                 timeout=float(env.get("BIDGATE_LLM_TIMEOUT", "240")))
    return ChunkedReader(primary, RuleReader(), int(env.get("BIDGATE_LLM_CHUNK_CHARS", "2000")))


def build_source(env=os.environ, data_dir=DATA):
    url = env.get("BIDGATE_DATA_URL")
    if url:
        return HttpSqlSource(url, env.get("BIDGATE_DATA_TOKEN", ""))
    return StandInSource(data_dir)
