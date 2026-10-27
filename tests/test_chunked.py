from bidgate.adapters.llm import ChunkedReader, ReaderUnavailable, RuleReader, split_lines
from bidgate.domain.model import Claim, Line


def mk(n, w=100):
    return [Line(i, ("L%d " % i) + "x" * w) for i in range(1, n + 1)]


def test_split_respects_limit_line_boundaries_and_numbers():
    lines = mk(30, 100)
    chunks = split_lines(lines, 1000)
    assert len(chunks) > 1
    assert [l for c in chunks for l in c] == lines          # nothing lost, order and numbers kept
    for c in chunks:
        assert sum(len(l.text) + 8 for l in c) <= 1000 + 200  # one line of slack at most


def test_split_single_overlong_line_is_its_own_chunk():
    lines = [Line(1, "a"), Line(2, "b" * 3000), Line(3, "c")]
    chunks = split_lines(lines, 1000)
    assert [[l.n for l in c] for c in chunks] == [[1], [2], [3]]


class Scripted:
    name = "scripted"

    def __init__(self, plan):
        self.plan, self.calls = plan, []

    def propose(self, doc, lines):
        self.calls.append(lines[0].n)
        step = self.plan.pop(0) if self.plan else "ok"
        if step == "fail":
            raise ReaderUnavailable("HTTP 502")
        return [Claim("mode", lines[0].n, "Fully online")]


def test_chunk_failure_retried_once_then_only_that_chunk_falls_back():
    lines = mk(30, 100)
    primary = Scripted(["ok", "fail", "fail"])    # chunk 2 fails twice
    r = ChunkedReader(primary, RuleReader(), 1000)
    r.propose("d", lines)
    nchunks = len(split_lines(lines, 1000))
    assert r.stats["chunks"] == nchunks
    assert r.stats["fallback_chunks"] == [2]
    assert r.stats["primary_chunks"] == nchunks - 1
    assert r.stats["primary_calls"] == nchunks + 1        # one retry on chunk 2, none elsewhere... plus fails counted
    assert "chunk 2" in r.note and "502" in r.note


def test_retry_success_keeps_chunk_on_primary_and_notes_nothing_lost():
    lines = mk(30, 100)
    r = ChunkedReader(Scripted(["fail", "ok"]), RuleReader(), 1000)
    r.propose("d", lines)
    assert r.stats["fallback_chunks"] == []
    assert r.stats["retries"] == 1


def test_all_primary_no_note():
    r = ChunkedReader(Scripted([]), RuleReader(), 1000)
    r.propose("d", mk(30, 100))
    assert r.note == "" and r.stats["fallback_chunks"] == []


def test_claims_from_all_chunks_are_merged_with_original_line_numbers():
    lines = mk(30, 100)
    r = ChunkedReader(Scripted([]), RuleReader(), 1000)
    claims = r.propose("d", lines)
    assert len(claims) == len(split_lines(lines, 1000))
    assert claims[-1].line > claims[0].line > 0
