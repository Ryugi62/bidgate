"""Write data/*/source.txt as one CSV (doc,n,text) for Zetaris to query in place.

usage: python3 tools/build_doc_lines.py <out.csv>
Writes in place (same inode) so a read-only bind mount of the folder keeps seeing it.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
out = sys.argv[1]
with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh, quoting=csv.QUOTE_ALL)
    w.writerow(["doc", "n", "text"])
    for d in sorted((ROOT / "data").iterdir()):
        src = d / "source.txt"
        if src.exists():
            for i, t in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
                w.writerow([d.name, i, t])
