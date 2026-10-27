# BidGate

**Before you spend hours on an application, contest or grant: submit or not?** BidGate answers with one of three verdicts, GO, HOLD or NO. Every conclusion carries a quote copied verbatim from the opportunity's own rules text and a reading receipt (document, line, sha256 of the line) proving that line was actually read. A conclusion without both is rejected, and a missing fact gives HOLD, never a guess.

Open Agent Hackathon 2026, Track 02 "The Agent That Can Explain Why". Spec: [SPEC.md](SPEC.md).

## What runs for real

| Layer | Real product | What BidGate does with it | Evidence |
|---|---|---|---|
| Data layer | **Zetaris** (local platform stack, Docker/colima) | Opportunity text (`doc_lines`) and the applicant profile live in Zetaris and are queried in place over its REST SQL proxy; 26 queries, 26 answered 200, 0 errors in the log. | [bridge query log](docs/live/zetaris-bridge-queries.log), [SQL log](docs/live/zetaris-sql-2026-10-27.log), [3-case run](docs/live/run-engine-down-2026-10-28.md) |
| AI provider | **Meterless Nightshift M1-M4** 0.92.7 (local `http://127.0.0.1:8088/v1`) | The reader sends the document to `meterless/auto` in chunks of at most 2000 characters (line numbers kept) and asks only for claims `(field, line, quote)`. | [chat completion with compute receipt](docs/live/meterless-chat-2026-10-27.json), [502 diagnosis](docs/live/meterless-502-diagnosis.txt) |

Honest status of the Meterless reader (the reader never decides a verdict, it only points; the domain verifies every quote against the delivered line):

- The only lane on this machine is a 1B local model (Llama 3.2 1B, WebLLM). Short prompts succeed (about 2 to 40 s); prompts of roughly 3000 characters and more failed with `model_load_failed` (HTTP 502) in our measurements, and the full 12k-character rules page failed outright.
- Therefore the reader is chunked. A chunk that fails is retried once; if it fails again, only that chunk is read by the deterministic rules reader and the chunk number and line range are written to `reader_note` and `reader_stats` in the report. No silent failure.
- Reader share per run is reported in `reader_stats` (`primary_chunks` vs `fallback_chunks`). The latest run log is [run-engine-down-2026-10-28](docs/live/run-engine-down-2026-10-28.md): the Nightshift engine had disconnected (its window needs to be on screen), so 0 of 12 chunks were read by Meterless and all 12 by the rules reader; the verdicts there (GO / HOLD / NO) therefore come from the rules reader plus Zetaris data. See the log index in [docs/live/](docs/live/) for any later run with Meterless-read chunks.

## Verdicts

```
python3 -m bidgate run data/oah-2026 data/gsoc-how-it-works data/yc-w2027 --now 2026-10-27T14:00:00+00:00
```

Public opportunity text only (three public pages saved under `data/`). The demo applicant in `data/profile.csv` is generic, no personal data. Demo set yields GO, HOLD and NO. `python3 -m bidgate serve` opens a local screen on 127.0.0.1.

## Setup

1. **Python 3.9+**, no third-party dependencies. `python3 -m pytest -q` runs 50 tests (offline, deterministic).
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
# optional: BIDGATE_LLM_CHUNK_CHARS=2000  BIDGATE_LLM_TIMEOUT=240
```

Then `set -a; . ./.env.local; set +a; python3 -m bidgate run data/oah-2026`.

## Sponsor technology explanation

- **Zetaris: used, as the data layer.** Every document line and profile fact BidGate reads is fetched by SQL from Zetaris (`BIDGATE.doc_lines`, `BIDGATE.profile`), queried in place from the files where they live. Each line delivered earns a receipt. The bridge in `tools/bridge.py` is ours (a thin translator); the query engine and file store are Zetaris.
- **Meterless Nightshift: used, as the primary AI provider, with a stated limit.** The reader calls the local Nightshift OpenAI-compatible endpoint (`meterless/auto`) and every call returns a Meterless compute receipt. On this machine the routed lane is a 1B model, so some chunks fail and are read by the rules reader instead; that share is printed in every report (see "What runs for real").
- **Cursor: not used.** No Cursor product is part of BidGate's runtime or data path.

## Pre-existing components

None. All code in this repository was written during the hackathon window; the first commit is `2026-10-27 21:38 +0900` (12:38 UTC on 27 Oct 2026), after the 22 Oct 00:00 UTC start. The opportunity texts in `data/` are public web pages fetched with `tools/fetch_case.py`.

## Layout

`bidgate/domain` (pure rules: no I/O) <- `application` (use case, rendering) <- `adapters` (reader and data ports) <- `infrastructure` (CLI, web, wiring from environment). `tools/` has the page fetcher, the CSV builder for Zetaris and the Zetaris bridge. `docs/live/` holds the real-run logs.
