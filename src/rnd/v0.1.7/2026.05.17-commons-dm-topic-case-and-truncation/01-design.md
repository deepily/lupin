# Commons DM — Topic-Case Mismatch, Persona-Space-in-Topic, and Write-Truncation

**Status:** 🟡 v3 — Rick's 4 Q-decisions ratified (2026-05-17 via Tiberius coordinator walkthrough); 2 diverged from my recs and have been folded into this revision. Plan-only awaiting Rick's explicit go for code-write.
**Author:** Mr. Radio 🦉 (Lupin session `9ea36cbe`)
**Coordinator:** Tiberius 🌑 (Lupin session `225e5b2d`) — task triage + sub-bug C surfacing
**Original filers:**
- Sub-bug A (topic-case) — María 🌸 session `3c9fce51`, 2026-05-16
- Sub-bug B (write truncation) — Tiberius 🌑 session `b714e138`, 2026-05-17T00:22Z
- Sub-bug C (persona-space) — Tiberius 🌑 session `225e5b2d`, 2026-05-17T18:53Z
**TODO source:** L58-83 of `TODO.md`
**Related (do not subsume):** `bug-fix-queue.md` L115-205 — `commons_send_to` FunctionTool wrapper bug (ALREADY fixed in commit `f4e0370` — superseded, not in scope here)
**Constraint:** Plan only — no code lands without Rick's explicit go.

---

## TL;DR

Three sibling bugs all live within ~3 lines of `src/lupin_mcp/cosa_voice_mcp.py:2291`. Two of them (A topic-case, C persona-space) are mechanical fixes that share a single corrected line. The third (B write-truncation) is an investigation, not a clean fix — the strongest hypothesis points outside the wrapper entirely (MCP subprocess killed mid-write during a bounce).

Recommended landing order:

| # | Sub-bug | Fix size | Risk | Notes |
|---|---|---|---|---|
| 1 | **A + C combined** | ~5 LOC | Low | Unified regex-sanitize at `cosa_voice_mcp.py:2291`, + migration-by-union-merge-on-read for existing capitalized topic files |
| 2 | **B investigation** | n/a — diagnostic | Medium | Probe hypothesis (a) bounce-mid-write FIRST; only instrument `CommonsStore.post()` if (a) is ruled out |
| 3 | **B fix** | TBD by investigation | TBD | Likely atomic-write semantics in `CommonsStore.post()` regardless of root cause — defense-in-depth |

Coverage floor: 100% Lupin-wide per `feedback_100pct_coverage_multiplexer` (scope-expanded 2026-05-16).

---

## Section 1 — Context and reproducers

### Sub-bug A — topic-case mismatch (María, 2026-05-16)

**Reproducer**:
1. Session A: `commons_send_to(recipient="Tiberius", body="...")` — wrapper at line 2291 forms `target_topic = "dm-Tiberius"` (capital T)
2. Session B (Tiberius): replies via `commons_send_to(recipient="maria", ...)` — wrapper forms `"dm-maria"` (lowercase)
3. The two halves of one logical thread land on TWO topic files: `dm-Tiberius.md` and `dm-maria.md`
4. Push-mode persona resolution is case-insensitive on the server, so DM delivery still works — but the on-disk thread is fragmented

**Why now (severity bump)**: With multi-session coordination becoming the norm (broadcasts to all personas, cross-session task handoff), fragmented thread files make audit + retrospective harder. Not lethal but actively degrading the value of the commons archive.

### Sub-bug B — write-level truncation (Tiberius, 2026-05-17T00:22Z)

**Observation**: Tiberius authored a ~4000-char reply to María with 5 Q&A sections. The on-disk file `io/commons/dm-maria.md` (34,542 bytes total) genuinely ends mid-sentence at:

> "Substantive answers to your 5 questions, ranked by impact:"

with NO body text below. Confirmed via direct `cat` inspection, not via `commons_read` (which could have masked it).

**Three hypotheses, ranked by Tiberius**:

| Rank | Hypothesis | Evidence FOR | Evidence AGAINST |
|---|---|---|---|
| (a) | Bounce mid-write killed MCP subprocess between header flush and body write | Timing of truncated write coincides with architecture-switchover broadcast that triggered a Docker bounce | Need to correlate exact timestamp vs Docker process restart log |
| (b) | fastmcp transport-layer truncation at write time | Hypothetical | None confirmed; fastmcp wraps strings opaquely |
| (c) | Silent `CommonsStore.post()` body-length cap | Hypothetical | Code inspection (this doc §3.2) shows NO body-length cap in `CommonsStore.post()` — write is `fcntl.flock` + sequential `f.write` of frontmatter + separator + entry text; no length truncation logic. Hypothesis (c) is effectively ruled out by code review unless there's an OS-level write cap |

### Sub-bug C — persona-with-space breaks derived topic (Tiberius, 2026-05-17T18:53Z, in-flight discovery)

**Reproducer**: Tiberius attempted `commons_send_to(recipient="mr radio", body="...")` to send my (Mr. Radio's) assignment. The wrapper formed `target_topic = "dm-mr radio"` (literal space), which then failed the server-side `register_question` topic pattern check `^[A-Za-z0-9_-]+$` → HTTP 422 `string_pattern_mismatch`.

**Tiberius's workaround**: Re-routed via `commons_ask_async` with an explicit `topic="dm-radio"` override (chose `dm-radio` as a short-form alias, not the derived `dm-mr_radio` or `dm-Mr Radio`). This worked — the DM reached me on topic `dm-radio` and the system-reminder fired correctly.

**Surface impact**: Any persona name with a space in it (currently just "Mr. Radio") cannot be the target of `commons_send_to` without the workaround. The wrapper IS broken for me specifically.

---

## Section 2 — Design: Sub-bug A + Sub-bug C unified fix

### 2.1 The fix line (ratified Q8: broaden to unicode)

> **⚠️ SUPERSEDED for persona-derived topics (Rick ratified 2026-06-22).** The Q8
> "unicode all the way down" directive below — keep the persona's exact unicode
> spelling so `María` → `dm-maría` — has been **reversed for persona-derived DM
> topics**. Carrying accents into the topic slug produced the **split-topic** bug:
> the SAME persona keyed as both `dm-maría` and `dm-maria` depending on which
> sub-system slugged the name, fragmenting the very thread this doc set out to
> unify (live evidence: both `io/commons/dm-maría.md` and `dm-maria.md` existed).
> Persona-derived topics now slug through the ONE canonical root
> `lupin_mcp.persona_normalization.persona_slug` (NFKD accent-strip → `María` →
> `dm-maria`), so every producer converges on a single topic file. See
> `src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md`
> (Phase 4). The unicode-preserving form is retained only for genuinely
> non-persona, free-text topic names (none currently).

`src/lupin_mcp/cosa_voice_mcp.py:2291` currently reads:

```python
target_topic = topic or f"dm-{recipient}"
```

**Proposed replacement (v3 — unicode-aware per Rick's Q8 ratification)**:

```python
# At module top (with other imports)
import re

# Helper near top of module
def _derive_dm_topic( recipient: str ) -> str:
    """
    Derive a server-pattern-safe DM topic from a recipient persona name.

    Per Rick's Q8 architectural directive (2026-05-17): unicode all the way
    down — topic file names preserve the persona's exact unicode spelling
    (e.g., `María` → `dm-maría`). The `re.UNICODE` flag treats letters in
    any Unicode script as word characters; only path-dangerous chars and
    whitespace collapse to `_`.
    """
    sanitized = re.sub( r"[^\w-]+", "_", recipient.lower(), flags=re.UNICODE )
    return f"dm-{sanitized}"

# At line 2291 inside commons_send_to
target_topic = topic or _derive_dm_topic( recipient )
```

**Cross-file change required** — server-side topic pattern at `src/cosa/rest/routers/commons.py:100`:

```python
# BEFORE
_TOPIC_OR_QID_PATTERN = r"^[A-Za-z0-9_-]+$"

# AFTER (unicode-aware, allow letters/digits in any script)
_TOPIC_OR_QID_PATTERN = r"^[\w-]+$"   # re.UNICODE is on by default in Python 3
```

Server-side broadening is mandatory — if the wrapper derives `dm-maría` but the server still validates against ASCII-only, the `register_question` endpoint 422s and we've moved the bug, not fixed it. **Audit point in the execution log**: confirm no callers of `_TOPIC_OR_QID_PATTERN` rely on ASCII-only assumptions downstream.

Behavior matrix (v3):

| `recipient` input | `target_topic` output (v3 unicode) | v2 ASCII-only output | Before any fix |
|---|---|---|---|
| `"tiberius"` | `dm-tiberius` ✅ | `dm-tiberius` ✅ | `dm-tiberius` ✅ |
| `"Tiberius"` | `dm-tiberius` ✅ | `dm-tiberius` ✅ | `dm-Tiberius` ❌ fragments |
| `"mr radio"` | `dm-mr_radio` ✅ | `dm-mr_radio` ✅ | `dm-mr radio` ❌ 422 |
| `"María"` | `dm-maría` ✅ NEW (v3) | `dm-mar_a` ⚠️ lossy | `dm-María` ❌ case-fragments |
| `"José Ruiz"` | `dm-josé_ruiz` ✅ NEW (v3) | `dm-jos__ruiz` ⚠️ lossy | `dm-José Ruiz` ❌ 422 |
| `"中文"` | `dm-中文` ✅ NEW (v3) | `dm-__` ⚠️ fully lost | `dm-中文` ❌ 422 |

**Path-safety note**: `\w` in `re.UNICODE` mode matches `[A-Za-z0-9_]` plus letters/digits in any Unicode script, plus the underscore character. We retain the literal `-` in the character class. Path separators (`/`, `\`), control chars, and shell metacharacters all collapse to `_`. Topic files live under a tightly-scoped directory (`io/commons/`); filesystem-level unicode handling is universal on Linux (UTF-8) and ext4.

### 2.2 Migration plan for existing capitalized topic files

The fix above silently routes new traffic to lowercase. The legacy files on disk look something like:

```
io/commons/
├── dm-Tiberius.md         # legacy capitalized, has María's outbound
├── dm-Maria.md            # legacy capitalized variant
├── dm-maria.md            # lowercase canonical, has Tiberius's outbound
├── dm-tiberius.md         # lowercase canonical
├── dm-radio.md            # workaround topic (Tiberius → Mr Radio)
└── dm-Mr Radio.md         # MAY exist if anyone bypassed the 422 server check
```

### Ratified: Option α — rename-and-merge (Q4 walkthrough 2026-05-17)

**Rick's call**: long-term filesystem cleanliness + single canonical files. Diverged from my β recommendation and from Tiberius's β rec — but I yield. Filesystem-cleanliness is the right anchor when the alternative is permanently fragmented topic files.

**α implementation steps**:

1. **Scan** `io/commons/dm-*.md` (and `io/commons/archive/dm-*.md` if it exists) for any case-variant. Build a map `canonical → [variants]` where canonical = `dm-{derived}` per `_derive_dm_topic`.
2. **For each canonical-with-variants group**:
   - If only ONE file exists at the canonical name → no-op (already canonical, e.g., `dm-tiberius.md` if no `dm-Tiberius` exists).
   - If a capitalized / mixed-case variant exists alongside the canonical → **merge**: parse entries from all variants, dedupe by `(ts, sender_session_id, body)` hash, sort by ts, rewrite canonical with the unified content, then `os.unlink` the variants.
   - If only the variant exists (no canonical yet) → `os.rename(variant, canonical)`. No merge needed.
3. **Archive handling**: apply the same logic to `io/commons/archive/` so retrospective reads against archived topics also see unified files.
4. **Frontmatter regeneration**: the merged file's frontmatter `created_at` becomes the earliest entry's ts; the rest of the frontmatter follows the existing `_frontmatter_block` shape.
5. **Bridge file refs / cached references**: grep `lupin_mcp/`, `cosa/rest/`, and any test/fixture code for hard-coded topic name strings (e.g., `"dm-Tiberius"`). Update or note no-op as appropriate.

**Rollback story**: pre-migration, write the variant files to a sibling backup directory (`io/commons/.pre-migration-backup/<ts>/`) before any `unlink` or `rename`. If post-migration we discover the merge corrupted ordering or lost an entry, restore from the backup directory and revert the §2.1 wrapper fix to the pre-fix one-liner.

**Migration script location**: `src/scripts/migrate-dm-topic-case.py` (one-shot, idempotent — re-running on a clean tree finds zero variants and is a no-op).

**Test coverage for the migration**:

- Unit test: given a fixture with `dm-Foo.md` + `dm-foo.md` containing interleaved entries, assert the post-migration `dm-foo.md` contains all entries sorted by ts with no dupes, and `dm-Foo.md` is gone.
- Unit test: given a fixture with only `dm-Bar.md`, assert post-migration `dm-bar.md` exists and `dm-Bar.md` is gone.
- Unit test: given a fixture with only `dm-baz.md` (already canonical), assert no-op.
- Integration test: end-to-end run of the migration script against a synthetic `io/commons/` snapshot, assert the resulting tree is exactly what the unit tests expect.

**Note on the `dm-radio` alias topic**: under α, the existing `dm-radio` workaround file gets merged into `dm-mr_radio.md` (the post-fix canonical for me) as part of step 2. After merge, anyone reading `dm-radio` will get an empty/not-found (file gone); anyone reading `dm-mr_radio` gets the unified history. **One-time migration alias**: add a fallback in `CommonsStore.read` that — for a transition window of 7 days — returns the canonical's contents when `dm-radio` is requested. After 7 days, the fallback retires and the topic is truly gone.

### Alternatives kept for forensic record (NOT chosen)

| Option | Pros | Cons | Reason rejected |
|---|---|---|---|
| **β — Union-merge-on-read** | Zero data-mutation risk, trivial rollback (revert read-helper), honors append-only contract | Read path slightly slower (glob + filter on every read), two physical files for one logical thread persists forever | Rick's filesystem-cleanliness preference rules out the persistent two-file state |
| **γ — Leave alone** | Zero migration risk | Permanent fragmentation; María's specific UX/audit complaint unresolved | Doesn't actually fix the symptom |

**Flip condition back to β**: if the migration script reveals materially more variant groups than expected (>50 thread pairs) AND the merge logic surfaces non-trivial edge cases (interleaving conflicts, orphan archives), retreat to β as a safer ship + revisit α later.

### 2.3 Operational caveat — MCP subprocess restart required

Per `bug-fix-queue.md` L115-205 commentary on the `f4e0370` FunctionTool fix: **fastmcp does NOT auto-reload like uvicorn**. After the fix lands, Rick (or the AI per the dev-server bounce courtesy rule) must restart the cosa-voice MCP subprocess so the new wrapper code is loaded. The Lupin REST server on :7999 will pick up code changes via uvicorn reload, but the MCP subprocess is a separate process tree.

**Action item**: Document the restart procedure in the implementation log (the 90-NN execution-log companion to this 01-design doc, per `feedback_plans_include_tracking_docs`).

---

## Section 3 — Design: Sub-bug B investigation

### 3.1 Investigation order (probe hypothesis (a) FIRST — ratified Q5)

**Ratified at the 2026-05-17 coordinator walkthrough (Q5 supplementary)**: hypothesis (a) bounce-mid-write is probed first; (b) fastmcp transport only if (a) is ruled out. Atomic-write fix shape (§3.3 / §6 Q2) is deferred to the post-investigation execution log per Q7 — the concrete fix shape (full atomic temp+rename vs lightweight fsync vs other) is chosen once root-cause is in hand.

The strongest evidence we have is **timing** — the truncated write at 2026-05-17T00:18:31Z coincided with the architecture-switchover broadcast which triggered a Docker bounce. Before instrumenting `CommonsStore.post()`, prove or rule out the bounce-mid-write hypothesis.

**Steps**:

1. **Pull the Docker container lifecycle log** for the cosa-voice MCP subprocess around 2026-05-17T00:18:00Z–00:19:00Z. Specifically look for:
   - `docker stop` / `docker kill` / SIGTERM signals
   - Process restart timestamps
   - Any "container restarted" log line
2. **Correlate against the on-disk file `mtime`**: `stat io/commons/dm-maria.md` — does the modification time match the truncation point, or a later resumption?
3. **Examine the file's trailing bytes** — is there a partial entry separator `---` at the end, or does it cut cleanly at the colon of "ranked by impact:"? Partial separator → mid-write kill. Clean cut → write completed but body was already truncated upstream.
4. **Check fastmcp subprocess logs** (if captured by Docker stdout) for any `BrokenPipeError`, `KeyboardInterrupt`, or `SIGTERM` traceback around that timestamp.

**Decision tree**:
- If steps 1+2+3 confirm subprocess died mid-write → root cause is hypothesis (a). Fix design pivots to atomic-write semantics (write-to-temp + atomic-rename, OR fsync-after-write + restart-resilient retry).
- If logs show NO subprocess restart and the file `mtime` precedes any restart → hypothesis (a) is ruled out. Move to hypothesis (b) (fastmcp transport).
- If hypothesis (b) is suspected → write a controlled test: post a known-length body, vary lengths (1k / 4k / 16k / 64k bytes), check what survives.

### 3.2 Why hypothesis (c) is effectively ruled out by code review

`CommonsStore.post()` at `src/lupin_mcp/commons_store.py:196-253` (read above):

```python
with open( path, "a+", encoding="utf-8" ) as f:
    fcntl.flock( f.fileno(), fcntl.LOCK_EX )
    try:
        f.seek( 0, os.SEEK_END )
        empty_file = f.tell() == 0
        if empty_file:
            f.write( _frontmatter_block( topic, False, ts ) )
        f.write( ENTRY_SEPARATOR )
        f.write( entry_text )
    finally:
        fcntl.flock( f.fileno(), fcntl.LOCK_UN )
```

There is **no body-length cap** anywhere in the store. The only way (c) could be the cause is an OS-level write limit (which would be wildly unusual on Linux for a 4k file write). Document the code-review finding in the investigation log so we don't re-investigate (c) later.

### 3.3 Defense-in-depth fix (DEFERRED to post-investigation execution log per Q7)

Per Q7 ratification, the concrete atomic-write fix shape is **deferred** until §3.1 investigation pins the root cause. The candidates surveyed below are kept as forensic context — final selection lands in `90-execution-log.md` once Sub-bug B hypothesis (a) is confirmed or ruled out.

**Candidate I — Full atomic-write via temp+rename (kill-resilient regardless of root cause)**:
1. Build the entry text in memory (frontmatter + separator + body as one string)
2. Acquire flock on the canonical file
3. Open a sibling `<topic>.md.partial-{pid}-{ts}` file
4. Copy current contents → partial file
5. Append entry text → partial file
6. `os.fsync(partial_file.fileno())`
7. `os.rename(partial_file, canonical_file)` — atomic on POSIX
8. Release flock

Pros: subprocess kill anywhere in steps 3-6 leaves the canonical file unchanged. Cons: 2-3× write latency (build-in-memory + fsync + rename).

**Candidate II — Lightweight fsync-after-write (cheap; doesn't fully eliminate mid-write corruption)**:
1. Acquire flock
2. Write frontmatter + separator + entry text (current behavior)
3. `os.fsync(f.fileno())` BEFORE releasing flock
4. Release flock

Pros: minimal latency overhead. Cons: subprocess kill between separator-write and body-write still leaves a corrupted entry on disk; doesn't fully address hypothesis (a).

**Candidate III — Defer the fix entirely (only correct if hypothesis (a) is RULED OUT)**:
Relies on bounce-mid-write being rare. Pros: zero code change. Cons: silent data-loss future-recurrence if (a) is the actual root cause.

**Selection criteria** (to be applied in the execution log):
- If (a) is **confirmed** → Candidate I (the kill-resilience cost is justified)
- If (a) is **ruled out** and (b) is **suspected** → Candidate II is likely sufficient (transport-layer issues benefit from sync-to-disk visibility)
- If both (a) and (b) are ruled out → Candidate III, file a separate ticket if recurrence later emerges

### 3.4 Recovery of the truncated data

**Correction added 2026-05-17 per Tiberius redline**: the truncated ~4000-char reply WAS recovered. Tiberius's session-internal follow-up at 2026-05-17T00:20:55Z re-posted the missing content (cross-ref TODO L81: "his 00:20:55Z follow-up"). María's downstream 01:57:20Z final reply confirmed all six redline items had been applied — she received the full content via the recovery write.

Net data-loss: zero. The truncation incident is a write-side resilience signal worth fixing, not a content-recovery problem.

**No action item for re-send** — Tiberius's earlier follow-up already closed the loop.

---

## Section 4 — Test pyramid (per CLAUDE.md §TESTING VENUES)

Routing per the rubric (no state mutation + ≤2min + no monopoly → `:7999`; else → `:8000` scheduled).

### 4.1 Unit tests (`:7999` AI-discretionary)

`src/tests/unit/test_commons_send_to_topic_derivation.py` (NEW):

| Test | Asserts |
|---|---|
| `test_lowercase_persona_preserved` | `_derive_dm_topic("tiberius")` == `"dm-tiberius"` |
| `test_capitalized_persona_lowercased` | `_derive_dm_topic("Tiberius")` == `"dm-tiberius"` |
| `test_space_in_persona_becomes_underscore` | `_derive_dm_topic("Mr Radio")` == `"dm-mr_radio"` |
| `test_punctuation_becomes_underscore` | `_derive_dm_topic("Dr. Strange-Love")` == `"dm-dr__strange-love"` |
| `test_unicode_persona_lossy_but_safe` | `_derive_dm_topic("maría")` matches `^dm-[A-Za-z0-9_-]+$` (locks server-pattern compatibility) |
| `test_topic_override_bypasses_derivation` | `commons_send_to(recipient="Mr Radio", topic="dm-radio", body="x")` writes to `dm-radio`, NOT the derived topic |

`src/tests/unit/test_commons_store_union_merge_read.py` (NEW, only if option β migration chosen):

| Test | Asserts |
|---|---|
| `test_read_merges_case_variants` | Given `dm-foo.md` + `dm-Foo.md` both containing entries, `CommonsStore.read("dm-foo")` returns the union sorted by timestamp |
| `test_read_dedupes_identical_entries` | Same `(ts, sender, body)` in both variants returns one entry |
| `test_read_lowercase_only_when_no_legacy` | Files like `dm-tiberius.md` (no capitalized sibling) read normally with no glob overhead |
| `test_write_still_goes_to_lowercase_canonical` | After §2.1 fix, every new post lands on the lowercase file regardless of input case |

`src/tests/unit/test_commons_post_atomic_write.py` (NEW, only if §3.3 atomic-write lands):

| Test | Asserts |
|---|---|
| `test_atomic_write_via_rename_pattern` | Killing the writer process between fsync and rename leaves the canonical file unchanged |
| `test_atomic_write_preserves_history` | Concurrent writers via separate processes don't lose entries (extends F6 fcntl test) |

### 4.2 Smoke tests (`:7999` AI-discretionary, inline `quick_smoke_test()` in the modified files)

`src/lupin_mcp/cosa_voice_mcp.py` already has a smoke test scaffold per the COSA convention. Extend it:

- New `quick_smoke_test()` case: round-trip a DM via `commons_send_to(recipient="Mr Radio", body="...")` against an ephemeral CommonsStore, assert the topic on disk is `dm-mr_radio.md` and the entry roundtrips through `commons_read("dm-mr_radio")`

### 4.3 Integration tests (`:8000` scheduled monopolize)

`src/tests/integration/test_dm_cross_case_thread_visibility.py` (NEW):

- Two-session simulation: session A (`commons_send_to(recipient="Tiberius", body="A1")`) + session B (`commons_send_to(recipient="maria", body="B1")`)
- After both posts, `CommonsStore.read("dm-tiberius")` returns BOTH A1 (outbound from A) and any traffic that landed on the case-variant via legacy. Same for `CommonsStore.read("dm-maria")`.
- Asserts the thread-fragmentation symptom María filed no longer manifests post-fix

`src/tests/integration/test_dm_persona_with_space_roundtrip.py` (NEW):

- One session calls `commons_send_to(recipient="Mr Radio", body="...")`
- Asserts no 422 error
- Asserts the system-reminder injected into the recipient session contains the expected `question_id`
- Mr Radio's session replies via `commons_post(topic="dm-mr_radio", body="...", metadata={"in_reply_to": ...})`
- Asserts the reply pushes back to asker's session via Phase 3 watcher

### 4.4 E2E (`:8000` scheduled monopolize) — defer

No UI surface in scope. The Recent Activity panel renders DM badges + chips already (covered by the earlier `test_dm_recent_activity.py` and the new `test_commons_activity_broadcast_acks.py` in Mr Radio's pending tree). The DM-topic fix doesn't change the render path.

### 4.5 Coverage (binding rule ratified Q9 — 100% across the board, no PR with failing tests)

**Rick's binding clarification (Q9, 2026-05-17)** — verbatim from the coordinator walkthrough:

> "I already demand 100% coverage. There is no PR that's going to happen if I have outstanding tests that are failing. So call it whatever you want but tests are going to get passed before PR has happened."

**What this means for this plan**:

- **100% line + branch + function coverage** on every new file written for this assignment (per `feedback_100pct_coverage_multiplexer`, scope-expanded 2026-05-16)
- **Zero failing tests** in any touched file at PR time. Any pre-existing test failure that surfaces in `commons_store.py`, `cosa_voice_mcp.py`, `routers/commons.py`, or any of the test files this plan adds — gets fixed in the same phase. No "deferred to follow-up" tickets. (Aligns with `feedback_fix_all_failing_tests`.)
- The migration script `src/scripts/migrate-dm-topic-case.py` is itself test-covered at 100%, treated as production code.
- E2E surface unchanged (no UI work), so no E2E baseline re-capture needed.

The 5-LOC fix at `cosa_voice_mcp.py:2291` (plus the cross-file widening at `routers/commons.py:100`) lifts coverage on the affected lines from N/A to 100% — every test in §4.1 exercises the derivation helper. Server-pattern widening gets its own parametrized unit test covering ASCII + unicode + path-dangerous-char rejection.

---

## Section 5 — Implementation order (when Rick says go)

| Step | Layer | Files | Estimated risk |
|---|---|---|---|
| 1 | Fix Sub-bug A + C combined | `src/lupin_mcp/cosa_voice_mcp.py` (new helper + line 2291) | Very Low |
| 2 | Unit tests for derivation helper | `src/tests/unit/test_commons_send_to_topic_derivation.py` | Very Low |
| 3 | (β only) Union-merge-on-read | `src/lupin_mcp/commons_store.py` (CommonsStore.read) | Low |
| 4 | (β only) Union-merge unit tests | `src/tests/unit/test_commons_store_union_merge_read.py` | Low |
| 5 | Restart cosa-voice MCP subprocess | Operational (Rick or via the dev-server bounce courtesy) | Low |
| 6 | Integration test for cross-case thread | `src/tests/integration/test_dm_cross_case_thread_visibility.py` | Low — scheduled on :8000 |
| 7 | Integration test for persona-with-space | `src/tests/integration/test_dm_persona_with_space_roundtrip.py` | Low — scheduled on :8000 |
| 8 | Sub-bug B investigation (separate sub-arc) | Diagnostic only — no code | Medium |
| 9 | Sub-bug B fix (atomic write) — gated on §3.1 conclusions | `src/lupin_mcp/commons_store.py` (post method) | Medium |
| 10 | Sub-bug B test coverage | `src/tests/unit/test_commons_post_atomic_write.py` | Medium |
| 11 | Execution log | `src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/90-execution-log.md` | n/a |

**Cross-session conflict map** (per Tiberius's coordination):
- ❌ Does NOT conflict with Mr Radio's uncommitted pending tree (notifications.js / broadcast-panel.js / e2e_ui broadcast+dm / broadcast-acks transform)
- ❌ Does NOT conflict with Tiberius's task #1 (model-server carve-out Phases 4-8)
- ❌ Does NOT conflict with Arnold's task #3 (owner_user_id stamper writer-side)

No merge-order coordination needed.

---

## Section 5a — Post-merge operational checklist (Q6 ratified — manual per-session intervention)

cosa-voice MCP subprocess does NOT auto-reload code changes. After steps 1-3 land, the MCP subprocess(es) running the old `commons_send_to` wrapper must be restarted so the new `_derive_dm_topic` helper is picked up. Without restart, the running subprocess continues serving the old wrapper code → fix appears not to land.

### Ratified restart path: manual per-session intervention via Claude Code CLI (Q6)

**Rick's call (Q6 supplementary ratification, 2026-05-17)**: do NOT use shell-level `pkill` or other process-tree commands. Rick will restart each session's MCP subprocess from within the running Claude Code session — the operational intervention is per-session, not host-level. This sidesteps any concerns about killing MCP subprocesses serving sessions that aren't ready to lose state.

**What this looks like in practice** (to be confirmed with Rick at implementation time, since the exact CLI command depends on the Claude Code MCP supervisor behavior):

- Within each running Claude Code session that has the cosa-voice MCP loaded, Rick issues the in-session command that triggers the MCP subprocess restart (likely a slash command or CLI directive — Rick will know the precise invocation for his install topology).
- Each session refreshes its cosa-voice connection independently, on Rick's schedule.
- Sessions that don't need the fix urgently can defer the restart; sessions actively using `commons_send_to` get refreshed first.

**Implementation log responsibility**: capture the exact CLI command Rick used during the first session-refresh in `90-execution-log.md` so future fixes don't have to re-discover the procedure.

### Verification post-restart

- Any session that DMs another via `commons_send_to(recipient="Mr Radio")` should land on `dm-mr_radio.md`, NOT on `dm-mr radio.md` (which would 422) and NOT on `dm-Mr Radio.md` (which would be a case-variant fragment).
- Confirm via `ls io/commons/dm-*.md` post-DM that the canonical lowercase+underscore file was the write target.
- A `commons_read("dm-mr_radio")` from a third session should return the entry.

**Roll-back checklist**:

If post-restart verification fails:
1. Revert the commit at `cosa_voice_mcp.py:2291` to the pre-fix one-liner
2. Restart MCP subprocess via the same option used to apply the fix
3. The β union-merge-on-read in `CommonsStore.read` is harmless on its own (no writes; just reads union files) — does not need rollback unless explicitly broken

---

## Section 6 — Q-decisions (RATIFIED 2026-05-17 — for historical record)

**All 4 formal questions ratified at the coordinator walkthrough on 2026-05-17.** Full ratification record at `src/rnd/v0.1.7/2026.05.17-coordinator-walkthrough-ratifications.md`. Each question kept below with the verdict marked. Q1 and Q3 diverged from my initial recommendation; the body of this v3 doc reflects the ratified positions.

### Q1 — Migration approach for legacy capitalized topic files → **α RATIFIED ⚠️ DIVERGED**

- **(α) Active rename + merge** ✅ **RATIFIED** — Rick chose long-term filesystem cleanliness + single canonical files. See §2.2 for the implementation detail and rollback story.
- (β) Union-merge-on-read — my original rec; kept in §2.2 "Alternatives" as forensic record
- (γ) Leave alone — rejected

**Flip condition back to β**: if migration script reveals >50 variant groups with non-trivial merge edge cases.

### Q2 — Sub-bug B atomic-write fix shape → **DEFER RATIFIED**

Rick ratified Q7: concrete fix shape (Candidate I full atomic / II lightweight fsync / III defer) is **deferred to the post-investigation execution log**. Selection criteria per §3.3. Investigation order (§3.1) locks hypothesis (a) first per Q5.

### Q3 — Scope of unicode persona-name support → **BROADEN RATIFIED ⚠️ DIVERGED**

- (P) ASCII-only — my original rec
- **(Q-broad) Unicode-aware via `[\w-]+` with `re.UNICODE`** ✅ **RATIFIED** — Rick's verbatim: *"if we were to use Unicode all the way down to the configuration manager INI file life would be so much simpler. The key values could be the same as the persona's actual name as it is spelled properly, like María, for example."*

See §2.1 for the unicode-aware regex + cross-file widening at `routers/commons.py:100`. New feedback memory `feedback_unicode_persona_keys_all_the_way_down.md` saved post-ratification.

### Q4 — Helper file location → **inline RATIFIED**

- **(X) Inline helper in `cosa_voice_mcp.py`** ✅ **RATIFIED** — minimum surface area; extract later if reuse emerges.
- (Y) Separate `commons_topic_naming.py` — rejected for YAGNI

---

## Section 7 — What I'm NOT touching

- The DM badge / commons-activity-entry / broadcast-acks render path (already in Mr Radio's pending uncommitted tree)
- The broadcast-panel chip-injector (already in Mr Radio's pending uncommitted tree)
- The `commons_send_to` FunctionTool wrapper bug (already fixed in commit `f4e0370`)
- Any cosa-voice MCP code outside `cosa_voice_mcp.py:2291 area` and `commons_store.py` post/read methods
- ANY backend or frontend behavior for the broadcast-to-cc-sessions endpoint (separate concern)

---

## Section 8 — Cross-references

- TODO source: `TODO.md` L58-83 (sub-bug A + B; sub-bug C noted in this doc)
- Bug-fix-queue: `bug-fix-queue.md` L115-205 (related FunctionTool wrapper; already fixed `f4e0370`, NOT in scope here)
- Adjacent R&D: `src/rnd/v0.1.7/2026.05.16-commons-dm-and-git-loc-delta-fix-arc.md` (F-number context)
- Cross-session coordination protocol: `planning-is-prompting → workflow/cross-session-communication.md`
- Pair-doc: `src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/90-execution-log.md` (NOT YET CREATED — pair created post-Rick-go per `feedback_plans_include_tracking_docs`)
- Coverage mandate: `feedback_100pct_coverage_multiplexer` (scope-expanded 2026-05-16)
- Testing venues: CLAUDE.md §TESTING VENUES (`:7999` / `:8000` rubric)

---

## Section 9 — Status checklist

- [x] Sub-bug context loaded from `TODO.md` + `bug-fix-queue.md`
- [x] Wrapper code read at `cosa_voice_mcp.py:2291`
- [x] `CommonsStore.post()` body-length cap hypothesis ruled out by code review
- [x] Conflict-watch confirmed: no overlap with Mr Radio's pending tree, Tiberius's task #1, Arnold's task #3
- [x] Migration options A/β/γ enumerated with pros/cons + recommendation
- [x] Test pyramid drafted (unit + smoke + integration; E2E deferred)
- [x] **Q1-Q4 ratified by Rick** (2026-05-17 coordinator walkthrough via Tiberius) — α migration, defer B fix, broaden to unicode, inline helper
- [x] Q5 (B investigation order) + Q6 (manual per-session restart) + Q7 (B fix deferral) supplementary ratifications folded
- [x] Q9 binding clarification folded into §4.5 (100% across the board, no PR with failing tests)
- [x] Unicode broadening cross-file change identified (`routers/commons.py:100`)
- [x] Migration script location chosen (`src/scripts/migrate-dm-topic-case.py`)
- [x] Feedback memory `feedback_unicode_persona_keys_all_the_way_down.md` to be saved post-doc-update
- [ ] **Rick's explicit go-ahead for CODE work** per the @all broadcast `21bb12cd`
- [ ] Sub-bug B investigation kicked off (§3.1 steps 1-4)
- [ ] Execution log `90-execution-log.md` created post-go
- [ ] Implementation steps 1-11 from §5 executed in order
- [ ] cosa-voice MCP subprocess restart confirmed by Rick per Q6 manual per-session intervention

---

*Drafted by Mr. Radio 🦉 (session 9ea36cbe) on 2026-05-17. v3 reflects the 2026-05-17 coordinator-walkthrough ratifications via Tiberius 🌑. Plan-only pending Rick's explicit go-ahead for code work per the @all broadcast `21bb12cd`. Companion execution log will be created when implementation begins.*
