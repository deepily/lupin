# 21 — Tiberius 👑 Post-Checkpoint Rehydration Memento (deploy incidents resolved → fleet ready)

> **For:** a fresh-context Tiberius (manager) re-spawned after Rick's `/clear`, at the GO-FOR-FLEET point.
> **Written:** 2026-06-03 ~02:30Z (session `1333e106`), by Tiberius, at Rick's checkpoint.
> **Supersedes memento 19** (which was pre-grind; two incidents + Gate-Zero happened since).
> **TL;DR:** the messaging deploy landed, TWO production-surface incidents hit and were both root-caused + fixed + committed, and **Gate-Zero is GREEN**. You are at the fleet-spawn gate. Resume at the cold-start runbook §15 + read the full checkpoint doc 20 first.

---

## 1. ▶ START HERE (resume order)

1. **Read `20-session-checkpoint-incidents-and-gate-zero.md`** (this dir) — full detail on both incidents + the Gate-Zero repair, root causes, fixes, commits, 2 reusable lessons.
2. **Cold-start runbook §15** — `02-cold-start-runbook.md` (the standalone execution doc). Gate-Zero is now DONE, so skip to the heartbeat-poker + fleet-spawn steps.
3. **Hand fresh-María the current state** if she DMs (both her holds are cleared — see §3).

## 2. What shipped/landed this session (all committed, HELD — nothing pushed)

- **Messaging deploy is LIVE** (MCP restart + `:7999`/`:8000` bounces done). The age cap + backfill closed the drain-storm.
- **Commits (mine, today):** `8447eec` (drain age-cap fix), `72ff343` (integration test count-delta), `d9ae862` (Gate-Zero test batch + docs). LOC: +449/-44 net +405 (prod +63/-11, tests +225/-33, config +9, docs +152).
- **Gate-Zero: GREEN** — full unit baseline under the **cosa `.venv` (py3.11/pytest9)** = **12,536 passed / 0 failed / 2 xfailed**.
- (Mr. Radio committed GCP M1 work interleaved on the branch: `32c0373`, `0fd09a7` — not mine.)

## 3. State of the two holds (María's steward division)

- **Hold #1 (messaging :8000 probe):** CLEARED — :8000 integration green + restart zero-storm.
- **Hold #2 (Gate-Zero green):** CLEARED — 12,536 passed.
- ⇒ **Fleet-spawn is UNBLOCKED.** I paused at Rick's "checkpoint" instruction; do NOT spawn until Rick greenlights (he asked to checkpoint, not to launch).

## 4. ▶ NEXT STEPS (the grind, gated on Rick's go)

1. **Heartbeat poker live-tap (§7.3)** — HARD gate before trusting unattended. **HYGIENE RULE (FM-21, learned the hard way 3× today):** poker tests/live-taps MUST use a test recipient / suppress TTS / run on :8000 — NEVER poke real personas on live `:7999` at priority=high (that was the recurring flood: a unit test's live notify seam). Verify the live tap without flooding Rick.
2. **Spawn fleet** — 3 authors + 1 adversarial reviewer, disjoint Tier-1 partition (memory / repo / utils+config+tools+crud). Cold-brief each at the runbook.
3. **Grind loop** — per-batch reviewer-gate + green-gate (cosa venv) + **test-only** commits. Deadline ramp 2026-06-05.

## 5. Operating doctrine to carry (apply from turn 1)

- **Canonical interpreter = cosa `.venv`** (py3.11/pytest9), NEVER lupin `.venv` (py3.13/pytest8 masks reds). Green-gate: `PYTHONPATH=src src/cosa/.venv/bin/python -m pytest src/tests/unit/ src/cosa/tests/unit/ -q`.
- **TTS cap is LIVE** (~500 chars spoken); headline + one takeaway, detail in `abstract`.
- **Test-isolation lessons (today):** (a) `patch.dict(sys.modules, {"pkg.mod": fake})` is defeated once `pkg` is imported with `mod` as a parent attribute — see `src/conftest.py` global eviction fixture; (b) raw class-attribute monkeypatching never self-restores — use patch.object/monkeypatch/restore-fixture.
- **Harvest-on-unproductive; reap promptly; difficulty≠defer; mandated work never user-gated.**
- **Don't surface push-readiness** — everything stays HELD silently for Rick's session-end push.

## 6. Open / deferred (not blockers)

- FM-21 (poker-test live-notify hygiene) → fold into the framework (María owns framework synthesis).
- Optional `:8000` load/storm test for the messaging plane.
- TODO.md + .claude-session.md showed modified at checkpoint but were NOT my edits (parallel session / hook) — left unstaged.
