# BidGate

**Before you spend hours on an application, contest or grant: submit or not?** BidGate answers with one of three verdicts, GO, HOLD or NO. Every conclusion carries a quote copied verbatim from the opportunity's own rules text and a reading receipt (document, line, sha256 of the line) proving that line was actually read. A conclusion without both is rejected, and a missing fact gives HOLD, never a guess.

Open Agent Hackathon 2026, Track 02 "The Agent That Can Explain Why". Spec: [SPEC.md](SPEC.md).

## What runs for real

| Layer | Real product | What BidGate does with it | Evidence |
|---|---|---|---|
| Data layer | **Zetaris** (local platform stack, Docker/colima) | Opportunity text (`doc_lines`) and the applicant profile live in Zetaris. One Zetaris SQL statement joins them (every document line x every applicant profile field, see "One JOIN" below); the data layer reads the document and attaches the profile, nothing is combined in Python. Queried in place over its REST SQL proxy; 172 queries, 172 answered 200, 0 errors in the log. | [JOIN statement, HTTP 200 and row counts](docs/live/zetaris-join-2026-10-28.log) ([json](docs/live/zetaris-join-2026-10-28.json), [bridge log](docs/live/zetaris-join-bridge-2026-10-28.log)), [bridge query log](docs/live/zetaris-bridge-queries.log), [SQL log](docs/live/zetaris-sql-2026-10-27.log), [3-case run](docs/live/run-engine-down-2026-10-28.md) |
| AI provider | **Meterless Nightshift M1-M4** 0.92.7 (local `http://127.0.0.1:8088/v1`) | The reader sends the document to `meterless/auto` in chunks of at most 400 characters (line numbers kept) and asks only which line states each field (a field name and a line number); the model copies no words. | [chat completion with compute receipt](docs/live/meterless-chat-2026-10-27.json), [reading call with document lines and receipt](docs/live/meterless-reading-call-2026-10-28.json), [502 diagnosis](docs/live/meterless-502-diagnosis.txt) |
| Reasoning engine | **Meterless Markovian** (reference runtime, Apache-2.0, `vendor/markovian/reference/src`, run by `node` through `tools/markovian_run.mjs`) | Each chunk is one bounded Markovian step: the runtime builds the step prompt from the goal and the compressed carryover of the previous step (fields located so far with line numbers, fields still missing); our generator is the Nightshift chat completion. Carryover is capped at 300 characters per step (cap added in 123d758; the earlier committed runs predate it and peaked at 326). | [3-case run](docs/live/run-markovian-2026-10-28.md) ([json](docs/live/run-markovian-2026-10-28.json) with per-step carryover size), [tests](tests/test_markovian.py) |

Markovian reading path (default when `BIDGATE_LLM_BASE_URL` is set and `node` exists; `BIDGATE_LLM_READER=chunked` switches back to the plain chunk loop). Python cuts the chunks and merges; `node --experimental-transform-types tools/markovian_run.mjs` runs the vendored engine. Every request has a 90 s limit, the whole run 8 minutes, and one warm-up call ("Reply OK") precedes the chain; a chunk with no answer is covered by the rules reader and named in `reader_note`. **Merge rule**: the rules reader's claims are always kept, the model's claims are added when they fill a gap or agree with the rules value (a model quote that would put a second value on a single-valued field is dropped and counted in `llm_claims_dropped_as_conflicting`), so the model can add information but never turn a rules PASS into MISSING or CONFLICT. The domain still checks every quote and receipt.

One JOIN (2026-10-28): the reader gets the document and the applicant profile from one statement:

```sql
SELECT d.n, d.text, p.key, p.value FROM doc_lines d CROSS JOIN profile p
WHERE d.doc=? AND p.key IN ('age', 'can_attend_onsite', 'budget_usd', 'can_produce') ORDER BY d.n, p.key
```

Real call through the bridge: HTTP 200, 704 rows for oah-2026 (176 lines x 4 profile fields), 80 rows for gsoc-how-it-works, 116 rows for yc-w2027, and the same verdicts GO, HOLD, NO ([log](docs/live/zetaris-join-2026-10-28.log), reproduce with `python3 tools/join_probe.py <bridge-url> <out-prefix>`). The offline stand-in answers the same statement (`tests/test_join.py`). The rules text is mounted as one CSV (`doc_lines.csv`) built from the public page text by `tools/build_doc_lines.py`: the page files are not mounted raw, so that CSV build is a conversion step before the query. The profile CSV is mounted as it is.

Pointer mode (new, 2026-10-28): the model never copies a quote. It answers `field | line number`; the adapter copies that line's own text as the quote, and the domain still checks the line, the reading receipt and whether the line really states the field (a wrong line is rejected as "quote yields no value"). A line number out of range, a non-number or an unknown field name is dropped and counted by reason in `reader_stats.model_pointers_dropped`. Reason for the change: in the earlier runs the 1B model could not copy words verbatim, so its claims were rejected ("not verbatim") and the report showed no model contribution.

Latest run ([run-pointer-2026-10-28c](docs/live/run-pointer-2026-10-28c.md), [json](docs/live/run-pointer-2026-10-28c.json), as of 2026-10-27T14:00Z, pointer mode, 400-character chunks): oah-2026 **GO**, gsoc-how-it-works **HOLD**, yc-w2027 **NO**; **8 of 15** check cells decided (PASS or FAIL), all 8 by the rules reader. Measured contribution of the model: **47 pointers proposed, 2 accepted by the domain** (they agreed with a rules finding), **45 rejected or dropped** because the pointed line does not state that field, and **0 cells decided by the model alone**. **13 of 40 chunks** were answered by Meterless; the other 27 (68%) got HTTP 502 from the 1B lane and were read by the rules reader. So the model's help is not measurable yet: it mostly points at lines that do not hold the field, and the domain rejects them, which is the intended behaviour. Why 502: [nightshift-502-cause-2026-10-28.txt](docs/live/nightshift-502-cause-2026-10-28.txt) (the router refuses in 10-30 ms with `model_load_failed` on all three candidate lanes, same 1B model; it is deterministic per chunk text, and pauses between retries did not change it). Real reading call with its compute receipt (document lines inside the request body): [meterless-reading-call-2026-10-28.json](docs/live/meterless-reading-call-2026-10-28.json). All runs, one table (numbers copied from each run's json):

| Run | Chunks | Answered by model | Failed: HTTP 502 | Failed: other | Read by rules reader instead | Cells decided by the model alone |
|---|---|---|---|---|---|---|
| [Engine disconnected (chunked reader)](docs/live/run-engine-down-2026-10-28.md) | 12 | 0 | 0 | 12 | 12 | not recorded in that run |
| [Chunked reader, whole-quote answers](docs/live/run-meterless-2026-10-28.md) | 12 | 3 | 9 | 0 | 9 | not recorded in that run |
| [Markovian, model-copied quotes](docs/live/run-markovian-2026-10-28.md) | 23 | 4 | 19 | 0 | 19 | not recorded in that run |
| [Markovian, pointer mode](docs/live/run-pointer-2026-10-28.md) | 23 | 3 | 20 | 0 | 20 | 0 |
| [Pointer mode, 1000-char chunks, 3 attempts with 8 s pauses](docs/live/run-pointer-2026-10-28b.md) | 23 | 3 | 20 | 0 | 20 | 0 |
| [Pointer mode, 400-char chunks, 3 attempts with 4 s pauses](docs/live/run-pointer-2026-10-28c.md) | 40 | 13 | 27 | 0 | 27 | 0 |

The decided cells are the same 8 of 15 in every run: the model never lowered them (rules alone decide) and never raised them. Failed attempts kept for the record: [Nightshift restarting](docs/live/run-markovian-attempt1-nightshift-restarting-2026-10-28.md), [model not loaded](docs/live/run-markovian-attempt2-model-not-loaded-2026-10-28.md), [JSON wording](docs/live/run-markovian-attempt3-json-wording-502-2026-10-28.md), [earlier carryover wording](docs/live/run-markovian-attempt4-carryover-wording-before-2026-10-28.md), and two pointer-prompt drafts that were replaced ([plain pointer prompt](docs/live/run-pointer-attempt1-plain-pointer-prompt-2026-10-28.md), [example-number leak](docs/live/run-pointer-attempt2-example-number-leak-2026-10-28.md)). Nightshift routing note: some prompt wordings are refused with 502 while others are answered in 1 to 5 s, so the prompt is plain language.

Honest status of the Meterless reader (the reader never decides a verdict, it only points; the domain verifies every quote against the delivered line):

- The only lane on this machine is a 1B local model (Llama 3.2 1B, WebLLM). Short prompts succeed (about 2 to 40 s); prompts of roughly 3000 characters and more failed with `model_load_failed` (HTTP 502) in our measurements, and the full 12k-character rules page failed outright.
- Therefore the reader is chunked. A chunk that fails is retried once; if it fails again, only that chunk is read by the deterministic rules reader and the chunk number and line range are written to `reader_note` and `reader_stats` in the report. No silent failure.
- Reader share per run is reported in `reader_stats` (`primary_chunks` vs `fallback_chunks`). The latest run is the one in the table above. Earlier run (chunked reader, before pointer mode): [run-meterless-2026-10-28](docs/live/run-meterless-2026-10-28.md), 3 of 12 chunks read by Meterless Nightshift (oah-2026 1/7, yc-w2027 2/3, gsoc 0/2); the other 9 returned HTTP 502 `model_load_failed` and were read by the rules reader, which the report names chunk by chunk. Fix found on the way: a separate `system` message made every Nightshift call fail, so instructions now travel inside one `user` message (test `test_openai_compat_reader_parses_claims`). Run with the engine disconnected: [run-engine-down-2026-10-28](docs/live/run-engine-down-2026-10-28.md) (0 of 12).

## Verdicts

```
python3 -m bidgate run data/oah-2026 data/gsoc-how-it-works data/yc-w2027 --now 2026-10-27T14:00:00+00:00
```

Public opportunity text only (three public pages saved under `data/`). The demo applicant in `data/profile.csv` is generic, no personal data. Demo set yields GO, HOLD and NO. `python3 -m bidgate serve` opens a local screen on 127.0.0.1.

## Setup

1. **Python 3.9+**, runtime: standard library only · tests: pytest (+ node for the Markovian runner). `python3 -m pytest -q` runs 76 tests (offline, deterministic; the Markovian ones use a local fake endpoint and need `node`).
2. **Offline default**: with no environment variables BidGate uses the rules reader and a local SQLite+CSV data source labelled `stand-in`.
3. **Meterless Nightshift** (M1 or newer Mac): download the app from https://meterless.ai/Nightshift/M1+/ (a dmg), copy it to Applications and start it; keep its window open (the engine runs in the window). It serves an OpenAI-compatible API on `127.0.0.1:8088/v1`. The bearer token is in `~/Library/Application Support/ai.meterless.nightshift.m1m4/runtime-token`.
4. **Zetaris** local platform (registry login and terms from the hackathon's Zetaris download page; Docker or colima with 8 GB RAM, 4 CPUs). Mount a folder holding `doc_lines.csv` (built by `python3 tools/build_doc_lines.py <folder>/doc_lines.csv`) and `profile.csv` read-only under the engine's `customer-data/shared` path, then create the file-store tables `BIDGATE.doc_lines` and `BIDGATE.profile` over those files.
5. **Bridge**: `ZETARIS_USER=... ZETARIS_PASSWORD=... python3 tools/bridge.py` translates BidGate's tiny SQL wire (`{"sql","params"}` to `{"rows"}`) into Zetaris REST calls and logs every SQL statement to `docs/live/`.
6. **Environment** (copy to `.env.local`, which is git-ignored):

```
BIDGATE_LLM_BASE_URL=http://127.0.0.1:8088/v1
BIDGATE_LLM_API_KEY=<contents of runtime-token>
BIDGATE_LLM_MODEL=meterless/auto
BIDGATE_DATA_URL=http://127.0.0.1:8765/
BIDGATE_DATA_TOKEN=local-bridge
# optional: BIDGATE_LLM_CHUNK_CHARS=400 (default)  BIDGATE_LLM_RETRY_WAIT=8 (seconds between retries, default)  BIDGATE_LLM_TIMEOUT=240
```

Then `set -a; . ./.env.local; set +a; python3 -m bidgate run data/oah-2026`.

## Sponsor technology explanation

- **Zetaris: used, as the data layer.** Every document line and profile fact BidGate reads is fetched by SQL from Zetaris (`BIDGATE.doc_lines`, `BIDGATE.profile`), queried in place from the files where they live. Each line delivered earns a receipt. The bridge in `tools/bridge.py` is ours (a thin translator); the query engine and file store are Zetaris.
- **Meterless Nightshift: used, as the primary AI provider, with a stated limit.** The reader calls the local Nightshift OpenAI-compatible endpoint (`meterless/auto`) and every call returns a Meterless compute receipt. On this machine the routed lane is a 1B model, so some chunks fail and are read by the rules reader instead; that share is printed in every report (see "What runs for real").
- **Meterless Markovian engine: used, in the reading path.** `vendor/markovian/` is the engine repository folder (Apache-2.0, LICENSE and notices kept) fetched with `npx degit meterless/meterless/engines/markovian`; `tools/markovian_run.mjs` runs its reference runtime on `node` and injects the Nightshift generator. Measured in the latest run: 13 of 40 chunks answered by the model, 47 pointers proposed, 2 accepted, 0 cells decided by the model alone; carryover passed on every later step; decided cells never below the rules-only 8/15 (see "What runs for real").
- **Cursor: used for development** - Cursor Agent CLI made commits 123d758 (carryover limit), c47aa1f (HOLD next-step wording); session log [docs/live/cursor-session-2026-10-28.txt](docs/live/cursor-session-2026-10-28.txt). Most earlier code was written with Claude Code. Cursor is not part of BidGate's runtime or data path.

## Pre-existing components

All our code is new for this event; the Markovian runtime is vendored unmodified (Apache-2.0): `vendor/markovian/` (Meterless, fetched 2026-10-28 as the hackathon's engine). All code in this repository was written during the hackathon window; the first commit is `2026-10-27 21:38 +0900` (12:38 UTC on 27 Oct 2026), after the 22 Oct 00:00 UTC start. The opportunity texts in `data/` are public web pages fetched with `tools/fetch_case.py`.

## Layout

`bidgate/domain` (pure rules: no I/O) <- `application` (use case, rendering) <- `adapters` (reader and data ports) <- `infrastructure` (CLI, web, wiring from environment). `tools/` has the page fetcher, the CSV builder for Zetaris and the Zetaris bridge. `docs/live/` holds the real-run logs.
