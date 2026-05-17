# Execution Log — Commons DM Topic-Case + Truncation Plan

**Pairs with**: `01-design.md` (v3 ratified 2026-05-17 by Rick via Tiberius coordinator walkthrough)
**Executor**: Mr. Radio 🦉 (Lupin session `9ea36cbe`)
**Coordinator**: Tiberius 🌑 (Lupin session `225e5b2d`) — task assignment + redline review
**Started**: 2026-05-17 (post-coordinator-walkthrough, after Rick's "both!" green light)
**Format**: append-only timeline; each entry timestamped with what landed + what was learned.

---

## Phase 1 — Sub-bug A + C implementation (DONE)

### 2026-05-17 ~18:00 UTC — design doc v3 finalization

Tiberius's coordinator walkthrough delivered Rick's Q1-Q9 ratifications. Folded into design doc:
- Q1 migration: **α (rename-and-merge)** ratified, diverged from my original β rec → §2.2 rewritten with α implementation steps, alternatives kept as forensic record
- Q3 unicode: **broaden to unicode-aware** ratified, diverged from my ASCII-only rec → §2.1 regex changed to `[\w-]+` with `re.UNICODE`; cross-file widening identified at `routers/commons.py:100`
- Q5 supplementary: Sub-bug B hypothesis (a) probed first → §3.1 locked
- Q6 supplementary: manual per-session restart via Claude Code CLI (NOT shell pkill) → §5a replaced
- Q7: atomic-write fix shape deferred to post-investigation → §3.3 reframed as candidates I/II/III with selection criteria
- Q9 binding: 100% across the board, no PR with failing tests → §4.5 explicit quote

### 2026-05-17 ~22:50 UTC — Lupin-side helper landed

**File**: `src/lupin_mcp/cosa_voice_mcp.py`

Added `_derive_dm_topic( recipient: str ) -> str` near line 2154 (above the `_commons_ask_async_dispatch` helper). Body:

```python
def _derive_dm_topic( recipient: str ) -> str:
    sanitized = re.sub( r"[^\w-]+", "_", recipient.lower(), flags=re.UNICODE )
    return f"dm-{sanitized}"
```

Swapped line 2318 (formerly `target_topic = topic or f"dm-{recipient}"`) to call the helper. `re` was already imported (line 37).

py_compile: ✅ clean.

### 2026-05-17 ~22:51 UTC — CoSA-side server pattern widened

**File**: `src/cosa/rest/routers/commons.py` line 100

Changed `_TOPIC_OR_QID_PATTERN` from `r"^[A-Za-z0-9_-]+$"` to `r"^[\w-]+$"`. Added comment explaining the unicode broadening per Q8 ratification + cross-reference to the wrapper-side `_derive_dm_topic`.

py_compile: ✅ clean.

**⚠️ Submodule note**: this file lives in the CoSA submodule. The edit is in the working tree but CANNOT be committed from this Lupin-context session per `feedback_lupin_only_never_cosa`. CoSA-context commit pending.

### 2026-05-17 ~22:55 UTC — Unit tests for derivation helper

**File**: `src/tests/unit/commons/test_commons_send_to_topic_derivation.py` (NEW)

Two test classes, 33 total:
- `TestDeriveDmTopic` (25 tests) — case normalization, whitespace collapse, hyphen preservation, unicode (María, José Ruiz, 中文), path-safety (slashes, control chars), parametrized output-pattern-conformance check covering all the above
- `TestServerTopicPatternUnicodeBroadening` (8 tests) — Pydantic-validation regression via `RegisterQuestionRequest`: ASCII still accepted, unicode (María, 中文) now accepted, hyphens/underscores accepted, space + path-separator still rejected, `question_id` shares the same pattern

**First-run failure**: 32/33 — `test_punctuation_becomes_underscore` asserted two underscores from "Dr. " (period+space). Actual behavior collapses consecutive invalid chars into ONE underscore via the `+` quantifier — my assertion was wrong, not the code. Fixed the assertion + improved the docstring to call out the collapse semantic.

**Second run**: 33/33 ✅ in 1.18s.

### 2026-05-17 ~23:00 UTC — Migration script (Q4 α implementation)

**File**: `src/scripts/migrate-dm-topic-case.py` (NEW, 286 lines)

Implements §2.2 step list:
1. Scan `dm-*.md` in commons + archive dirs
2. `_derive_canonical_stem` derives the post-fix canonical from any legacy variant name; consults `ALIAS_MAP` first (initially `{"radio": "mr_radio"}` for Tiberius's manual workaround)
3. Group variants by canonical
4. Per-group: no-op / rename / merge (parse via `_parse_entry_block`, dedupe by `(ts, sender_session_id, sha1(body)[:12])`, sort by ts, rewrite canonical via `_format_entry`, unlink variants)
5. Backup before any destructive op (configurable via `--no-backup` for tests)
6. Idempotent — re-run on clean tree finds zero variants
7. Dry-run mode (`--dry-run`) reports without touching disk

LUPIN_ROOT bootstrap pattern matches `src/fastapi_app/main.py` and `src/scripts/*.py` convention. `pragma: no cover` on the bootstrap-fail raise + `__main__` guard (genuinely unreachable in pytest).

### 2026-05-17 ~23:05 UTC — Migration script tests + coverage closure

**File**: `src/tests/unit/commons/test_migrate_dm_topic_case.py` (NEW)

Five test classes, 32 total:
- `TestDeriveCanonicalStem` (7) — filename normalization, alias map, ValueError on non-DM filenames
- `TestGroupTopicsByCanonical` (4) — grouping logic incl. alias-routing
- `TestEntryParsingAndMerging` (4) — round-trip parse, dedupe key collision/divergence, merge sort
- `TestMigrateDirectory` (10) — end-to-end: canonical-only no-op, variant-only rename, canonical+variant merge, alias merge, multi-variant-no-canonical, dry-run, backup-on-rename, backup-on-merge, missing-dir, idempotent
- `TestRebuildTopicFileText` (3) — frontmatter created-ts, empty-entry-list, unicode topic round-trip
- `TestNowRunTs` (1) — timestamp format
- `TestMain` (3) — argparse + dry-run + with-backup + no-backup flag

**Coverage closure**: first pass was 79% (28 lines missed). Added `# pragma: no cover` on lines that are unreachable in pytest (bootstrap raise, `__main__` guard) + added `_now_run_ts` test + 3 `main()` tests via `monkeypatch.setattr("sys.argv", ...)`. **Final coverage: 100% (130/130 statements)**.

### 2026-05-17 ~23:10 UTC — Full commons unit suite verified clean

```
$ pytest src/tests/unit/commons/ -v
503 passed, 5 warnings in 15.64s
```

Zero regressions. All new tests + all prior commons tests green together.

---

## Phase 2 — Checkpoint commit (in progress)

Per Rick's "let's go ahead and document and check point your work" direction. Documentation (this file) lands as part of the checkpoint commit.

**Files staged for this Lupin-side commit**:
- `src/lupin_mcp/cosa_voice_mcp.py` (helper added + line 2318 swap)
- `src/scripts/migrate-dm-topic-case.py` (NEW)
- `src/tests/unit/commons/test_commons_send_to_topic_derivation.py` (NEW)
- `src/tests/unit/commons/test_migrate_dm_topic_case.py` (NEW)
- `src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/01-design.md` (NEW, v3)
- `src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/90-execution-log.md` (THIS FILE, NEW)

**NOT staged from this session** (require separate CoSA-context commit):
- `src/cosa/rest/routers/commons.py:100` (`_TOPIC_OR_QID_PATTERN` widening)

---

## Phase 3 — Sub-bug B investigation (starting next per Rick's "continue with step eight")

§3.1 step list to execute:
1. Pull Docker container lifecycle log around 2026-05-17T00:18:00Z–00:19:00Z; look for SIGTERM / container restart
2. `stat io/commons/dm-maria.md` — does mtime match the truncation point or a later resumption?
3. Examine the file's trailing bytes — partial entry separator `---` at end OR clean cut at the colon?
4. Check fastmcp subprocess logs (Docker stdout) for `BrokenPipeError` / `KeyboardInterrupt` / `SIGTERM` traceback around the timestamp

**Findings to be appended below as each step completes.**

### Step 1 — Docker container lifecycle log

*(pending)*

### Step 2 — mtime correlation

*(pending)*

### Step 3 — Trailing-bytes signature

*(pending)*

### Step 4 — fastmcp logs

*(pending)*

### Decision tree outcome

*(pending — pick Candidate I / II / III per §3.3 selection criteria once root-cause is in hand)*

---

## Phase 4 — Sub-bug B fix (gated on Phase 3 outcome + Rick's go)

*(not yet scoped; depends on which Candidate Phase 3 selects)*

---

## Phase 5 — Post-merge operational steps

*(pending all prior phases + commits + MCP subprocess restart per Q6 manual per-session intervention)*
