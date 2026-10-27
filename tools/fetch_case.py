"""Fetch a public page and store it as data/<case>/{source.txt,meta.json}. Stdlib only.

usage: python3 tools/fetch_case.py <case> <url>
Public pages only. For Next.js pages the collapsed 'rules' sections embedded in the page payload
are appended as extra lines (one rule per line) so the text a human can read is the text we read.
"""
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def visible_text(raw: str) -> str:
    s = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", "", raw, flags=re.S)
    s = re.sub(r"<(br|/p|/div|/li|/h\d|/tr|/section)[^>]*>", "\n", s)
    t = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return "\n".join(" ".join(l.split()) for l in t.split("\n") if len(l.split()) > 3 or re.search(r"\d", l) and l.strip())


def embedded_rules(raw: str) -> list:
    out = []
    pushes = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', raw, flags=re.S)
    blob = "".join(pushes)
    try:
        blob = json.loads('"' + blob + '"')
    except Exception:
        return out
    dec = json.JSONDecoder()
    for m in re.finditer(r'"sections":(?=\[\{"number":1)', blob):
        try:
            secs, _ = dec.raw_decode(blob, m.end())
        except Exception:
            continue
        for s in secs:
            for b in s.get("blocks", []):
                for it in b.get("items", []):
                    out.append("Rule %s %s: %s" % (s["number"], s["title"], it))
    return out


def main(case: str, url: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 bidgate-fetch"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    lines = visible_text(raw).split("\n") + embedded_rules(raw)
    text = "\n".join(lines) + "\n"
    d = Path(__file__).resolve().parent.parent / "data" / case
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.txt").write_text(text, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({
        "case": case, "url": url, "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(), "lines": len(lines)}, indent=2) + "\n")
    print(case, len(lines), "lines")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
