"""README claims must match the committed run json and pytest log (tools/check_readme.py)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_readme  # noqa: E402


def _case(chunks, primary, proposed, accepted, model_only, statuses):
    return {"case": "c", "checks": [{"status": s} for s in statuses],
            "reader_stats": {"chunks": chunks, "primary_chunks": primary, "model_claims_proposed": proposed,
                             "model_claims_accepted": accepted, "cells_decided_by_model_only": model_only}}


def _repo(tmp_path, readme, runs=None, passed=78):
    live = tmp_path / "docs" / "live"
    live.mkdir(parents=True)
    for name, cases in (runs or {"run-pointer-2026-10-28c": [_case(19, 2, 7, 1, 0, ["PASS", "FAIL", "MISSING"])]}).items():
        (live / f"{name}.json").write_text(json.dumps(cases))
    (live / "pytest-2026-10-28.txt").write_text(f"....\n{passed} passed in 1.00s\n")
    (tmp_path / "README.md").write_text(readme)
    return tmp_path


GOOD = ("Latest run ([run-pointer-2026-10-28c](x)): **2 of 3** check cells decided. "
        "**7 pointers proposed, 1 accepted by the domain**, **0 cells decided by the model alone**. "
        "**2 of 19 chunks** were answered. `python3 -m pytest -q` runs 78 tests.")


def test_given_matching_readme_then_no_problems(tmp_path):
    assert check_readme.problems(_repo(tmp_path, GOOD)) == []


def test_given_stale_latest_run_name_then_problem(tmp_path):
    runs = {"run-pointer-2026-10-28c": [_case(19, 2, 7, 1, 0, ["PASS", "FAIL", "MISSING"])],
            "run-pointer-2026-10-28d": [_case(19, 2, 7, 1, 0, ["PASS", "FAIL", "MISSING"])]}
    assert any("Latest run" in p for p in check_readme.problems(_repo(tmp_path, GOOD, runs=runs)))


def test_given_wrong_pointer_count_then_problem(tmp_path):
    assert any("pointers" in p for p in check_readme.problems(_repo(tmp_path, GOOD.replace("7 pointers", "9 pointers"))))


def test_given_wrong_test_count_then_problem(tmp_path):
    assert any("tests" in p for p in check_readme.problems(_repo(tmp_path, GOOD, passed=80)))

