from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from ..application.analyze import analyze_case
from ..application.render import to_markdown
from .wiring import build_reader, build_source


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bidgate")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="judge one or more opportunity folders")
    r.add_argument("cases", nargs="+")
    r.add_argument("--now", help="ISO time with offset (default: current UTC time)")
    r.add_argument("--json", help="write JSON report(s) to this path")
    s = sub.add_parser("serve", help="local web screen on 127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--now")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else datetime.now(timezone.utc)
    if a.cmd == "serve":
        from .web import run_screen
        run_screen(a.port, now if a.now else None)
        return 0
    src, rd = build_source(), build_reader()
    reps = [analyze_case(c, src, rd, now) for c in a.cases]
    for rep in reps:
        sys.stdout.write(to_markdown(rep) + "\n")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(reps[0] if len(reps) == 1 else reps, f, indent=2, sort_keys=True)
    return 0
