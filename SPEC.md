# BidGate SPEC v0

## Purpose (목적)
Before a person spends hours on an application, contest or grant, BidGate answers
"submit or not?" with one of three verdicts: **GO**, **HOLD**, **NO**. Every
conclusion must carry (1) a *quote* copied verbatim from the opportunity's own
rules text and (2) a *reading receipt* proving which document line was read.
A conclusion without both is rejected; if a required fact then has no accepted
conclusion the verdict is **HOLD** ("not enough evidence"), never a guess.

Track fit: Open Agent Hackathon 2026, Track 02 "The Agent That Can Explain Why".

## Ubiquitous language (code names match)
- **Opportunity**: one call for entries, stored as a folder `data/<case>/` with `source.txt` and `meta.json`.
- **Line**: one numbered line of `source.txt` (1-based).
- **Receipt**: `(doc, line, sha256-of-line)`, issued only when a line was delivered to a reader through the data port.
- **Claim**: a reader's pointer `(field, line, quote)`. A reader (LLM or rules) only points; it never supplies the value.
- **Finding**: a Claim that passed verification; its value is computed by the domain from the quote.
- **Field**: `deadline`, `min_age`, `mode` (online/onsite), `fee`, `deliverables`.
- **Check**: one criterion (deadline open, age eligible, mode attendable, fee affordable, deliverables producible) with status PASS / FAIL / MISSING / CONFLICT.
- **Profile**: the applicant's facts, `data/profile.csv` (generic demo applicant, no personal data).
- **Verdict**: GO / HOLD / NO plus the check table.

## Verdict rules
1. NO  if at least one check is FAIL (evidence-backed hard stop).
2. GO  if all five checks are PASS.
3. HOLD otherwise (any MISSING or CONFLICT, no FAIL).

## Success conditions (성공 조건, numbers)
- S1: `python3 -m bidgate run data/<case>` prints a verdict table (Markdown) and JSON for 3 public opportunities; each decided check shows quote + `doc:line` + receipt hash.
- S2: 0 accepted findings whose quote is not a verbatim substring of the cited line (property tested with a lying reader).
- S3: 0 decided checks without a receipt; a reader that cites an unread line gets the claim rejected.
- S4: demo set yields all three verdict kinds: >= 1 GO, >= 1 HOLD, >= 1 NO.
- S5: `pytest` passes; >= 25 tests; domain package imports no I/O, no network, no sqlite.
- S6: with `BIDGATE_LLM_BASE_URL` unset the run is fully deterministic and offline (same input -> same JSON byte for byte, given `--now`).
- S7: swapping the LLM reader or the data source changes no domain file (ports only).

## Scenarios (Given / When / Then)
1. Given a line "Deadline Oct 27, 2026, 23:45 UTC" and now = Oct 27 15:00 UTC, when analyzed, then deadline is PASS with that exact quote and receipt.
2. Given the same line and now = Oct 28 00:00 UTC, then deadline is FAIL and the verdict is NO.
3. Given a reader claiming a quote that is not in the cited line, then the claim is rejected, listed under `rejected`, and the check is MISSING (verdict HOLD at best).
4. Given a reader citing a line it never received, then the claim is rejected (no receipt).
5. Given a text with no deadline at all, then deadline is MISSING and the verdict is HOLD, not GO.
6. Given "in-person" and a profile `can_attend_onsite=no`, then mode is FAIL and the verdict is NO.
7. Given two lines with different deadlines, then deadline is CONFLICT and the verdict is HOLD.
8. Given `BIDGATE_LLM_BASE_URL` set to an OpenAI-compatible server returning claims, then those claims are used and still verified; if the server errors, the run falls back to the rules reader and says so in `reader_note`.
9. Given a CSV profile, the data port answers `SELECT value FROM profile WHERE key=?` in place (stand-in for Zetaris) and labels itself `stand-in`.
10. Given the web screen (`python3 -m bidgate serve`), then it lists the cases, shows each verdict table and the "stand-in" badges.

## Non-goals (비목표)
- No real users and no private data: public opportunity text only.
- No sending, no real submission, no accounts, no payments, no uploads.
- No ranking of opportunities, no legal advice, no learning/training of models.
- The offline defaults (SQLite+CSV, rules reader) remain stand-ins for tests; the shipped run path was verified against the real products on 2026-10-27/28 (local Zetaris stack via tools/bridge.py, local Meterless Nightshift) - see README "What runs for real" and docs/live/.
