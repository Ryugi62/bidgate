"""Check that README numbers match the committed run json and pytest log.

usage: python3 tools/check_readme.py [repo_root]   -> exit 0 if every claim matches, else prints each mismatch and exits 1
"""
import json
import re
import sys
from pathlib import Path

RUN_RE = re.compile(r"^run-pointer-\d{4}-\d{2}-\d{2}[a-z]?$")


def latest_run(live):
    names = sorted(p.stem for p in live.glob("run-pointer-*.json") if RUN_RE.match(p.stem))
    return names[-1] if names else None


def totals(cases):
    s = lambda k: sum(c["reader_stats"].get(k, 0) for c in cases)
    statuses = [ch.get("status") for c in cases for ch in c["checks"]]
    return {"chunks": s("chunks"), "primary": s("primary_chunks"), "proposed": s("model_claims_proposed"),
            "accepted": s("model_claims_accepted"), "model_only": s("cells_decided_by_model_only"),
            "decided": sum(x in ("PASS", "FAIL") for x in statuses), "cells": len(statuses)}


def _all_equal(readme, pattern, want, label):
    out = []
    for m in re.finditer(pattern, readme):
        got = tuple(int(g) for g in m.groups())
        if got != want:
            out.append(f"{label}: README says {got}, run json says {want}")
    return out


def problems(root):
    root = Path(root)
    readme = (root / "README.md").read_text(encoding="utf-8")
    live = root / "docs" / "live"
    out = []
    name = latest_run(live)
    m = re.search(r"Latest run \(\[([^\]]+)\]", readme)
    if not name or not m or m.group(1) != name:
        out.append(f"Latest run: README names {m.group(1) if m else None}, newest run json is {name}")
    if name:
        t = totals(json.loads((live / f"{name}.json").read_text(encoding="utf-8")))
        # latest-run wording only ("Earlier run ... 3 of 12 chunks read by" is a different run)
        out += _all_equal(readme, r"\*\*(\d+) of (\d+) chunks\*\*", (t["primary"], t["chunks"]), "chunks answered")
        out += _all_equal(readme, r"(\d+) of (\d+) chunks answered", (t["primary"], t["chunks"]), "chunks answered")
        out += _all_equal(readme, r"(\d+) pointers proposed, (\d+) accepted", (t["proposed"], t["accepted"]), "pointers")
        out += _all_equal(readme, r"(\d+) cells decided by the model alone", (t["model_only"],), "model-only cells")
        out += _all_equal(readme, r"\*\*(\d+) of (\d+)\*\* check cells decided", (t["decided"], t["cells"]), "decided cells")
    logs = sorted(live.glob("pytest-*.txt"))
    if logs:
        passed = re.findall(r"(\d+) passed", logs[-1].read_text(encoding="utf-8"))
        want = (int(passed[-1]),) if passed else None
        out += _all_equal(readme, r"runs (\d+) tests", want, "tests") if want else ["tests: no 'N passed' line in " + logs[-1].name]
    return out


if __name__ == "__main__":
    found = problems(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
    for p in found:
        print(p)
    print("README claims match" if not found else f"{len(found)} mismatch(es)")
    sys.exit(1 if found else 0)
