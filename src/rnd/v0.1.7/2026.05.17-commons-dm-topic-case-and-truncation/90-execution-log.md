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

### Step 2 — mtime + size correlation (ran FIRST, on-disk evidence is fastest)

- **Live file**: `io/commons/dm-maria.md` — Size: 19,733 bytes, mtime: 2026-05-17 19:04:35 EDT
- **Archive bucket**: `io/commons/archive/2026-05-17/dm-maria.md` — Size: 24,169 bytes, mtime: 2026-05-17 19:04 EDT (archived TODAY at ~21:04 UTC)
- Archive entries cover **2026-05-16T20:25→22:20 UTC**; the truncated entry at 2026-05-17T00:18:31Z is NOT in the archive bucket — it lives in the live file
- **Truncated entry IS in the live file** at line 9: `## 2026-05-17T00:18:31.994221+00:00 | Tiberius 🌑 #b714e138` — exact timestamp Tiberius cited

### Step 3 — Trailing-bytes signature (ran SECOND, the decisive evidence)

Extracted the truncated entry's body via `awk` between its header and the next `---` separator. Body content (verbatim):

```
María 🌸 — Tiberius 🌑. Read your prose end-to-end (the 18,630-char `instructions` block + the 6 commons_* docstring updates). Substantive answers to your 5 questions, ranked by impact:
```

**Body length: 195 characters** (Tiberius reported original ~4000 chars → **~3800+ characters lost**).

**Critical signature observation**:
- Header: well-formed `## <ts> | Tiberius 🌑 #b714e138`
- Metadata: well-formed JSON `{"kind": "question", "question_id": "a9ca3290-...", "recipient_persona": "maria", "expect_reply": false, ...}`
- Blank line: present
- Body: 195 chars, ends at `:` with NO trailing newline anomaly
- Entry separator: **clean `\n---\n`** immediately after the body
- Next entry (00:20:55Z): starts normally on the line after the separator

The entry has the EXPECTED on-disk structure of a SUCCESSFULLY WRITTEN entry. There's no partial separator, no header-without-body, no truncation in the middle of a metadata line. The body string was already short WHEN it reached `_format_entry`.

### Step 1 — Docker bounce log (ran THIRD, for completeness)

The architecture-switchover broadcast that Tiberius's hypothesis (a) tied the truncation timing to actually fired around **2026-05-16T22:25 EDT (= 2026-05-17T02:25 UTC)** — based on Docker logs around the time. The truncation incident was at **2026-05-17T00:18:31Z UTC = 2026-05-16 20:18 EDT** — almost **2 hours BEFORE the bounce**.

So the timing correlation Tiberius hypothesized was off — there was no MCP-subprocess kill at the truncation moment.

### Step 4 — fastmcp subprocess logs

Not directly queryable (fastmcp logs go to stdout of the host Claude Code process; not centralized). Skipped; structural evidence from Step 3 is already decisive.

### Decision tree outcome

**Hypothesis ranking AFTER investigation**:

| Hypothesis | Pre-investigation | Post-investigation | Evidence |
|---|---|---|---|
| (a) bounce-mid-write | "most likely" | **RULED OUT** | Clean entry separator, no bounce in the relevant time window |
| (b) fastmcp transport truncation | "hypothetical" | **STRONGLY SUSPECTED** | Body 195 chars vs. claimed ~4000; header + metadata + separator all well-formed; truncation upstream of `_format_entry` |
| (c) silent `CommonsStore.post()` body cap | "hypothetical" | **RULED OUT** (already by code review) | No length-capping logic in the store; sequential append-under-flock |

**Where this leaves the §3.3 fix-shape candidates**:

| Candidate | Addresses transport truncation? |
|---|---|
| I — full atomic temp+rename | **No** — protects against kill-mid-write, but body is already short by the time we write |
| II — fsync after write | **No** — same reason, write completes successfully; problem is upstream |
| III — defer fix entirely | Acceptable ONLY if recurrence is rare enough to live with |

**The design's Candidate set doesn't squarely address the actual root cause**. New candidates needed:

| New Candidate | Description | Pros | Cons |
|---|---|---|---|
| **IV — wrapper-side body-length telemetry** | Log every body length entering `_commons_ask_async_dispatch`. Add a warn-level log if body < some threshold. Doesn't fix anything but gives forensic data for the NEXT occurrence. | Cheap, low-risk, fast to land | Doesn't actually fix the bug; relies on next-occurrence to gather more data |
| **V — fastmcp transport probe** | Write a controlled test: post bodies of escalating length (1k / 4k / 16k / 64k bytes) via `commons_send_to`, inspect what survives on disk. If a clear cap surfaces, file upstream OR patch locally. | Pins the root cause definitively | Time-consuming; requires live MCP subprocess; may not reproduce if transport state-dependent |
| **VI — wrapper-side checksum + size header** | Wrapper computes sha256(body) + `len(body)` and stamps both into the metadata. Receiver-side post-write check: if `len(stored_body) != metadata.body_len`, log a CRITICAL. | Catches future truncation as it happens, attributable | Adds metadata bloat; defensive engineering for a transport-layer bug |

**My recommendation**: ship Candidate IV NOW (cheap, low-risk, immediate value) as instrumentation. Schedule Candidate V as a follow-up investigation when an MCP subprocess can be safely held open for the probe. Defer Candidate VI unless V doesn't find the root cause.

**Awaiting Rick's go-or-no on**:
1. The hypothesis (a) → (b) conclusion (does my evidence convince him?)
2. The Candidate IV+V combined approach (or push back to a different fix shape?)
3. Timing: do these new candidates land in this assignment's scope, or split to a new task?

---

## Phase 4 — Sub-bug B fix-shape decision (RATIFIED — Candidate V first)

### Rick's verdict (2026-05-17 evening, post-investigation):

- **Sub-bug B path**: **Candidate V — fastmcp transport probe first**. Pin root cause definitively before writing any production code. Skip the IV+V combination I recommended in favor of certainty over speed.
- **CoSA commit**: **Rick handles manually** — he commits `src/cosa/rest/routers/commons.py:100` from a CoSA-context shell. I leave the working-tree edit in place.

### Probe design (Candidate V)

**Goal**: send `commons_post` calls with bodies of escalating length, observe what survives on disk, identify any cutoff.

**Why `commons_post` not `commons_send_to`**:
- `commons_send_to` goes through the wrapper, which currently is the OLD code in the running MCP subprocess (the helper I just landed hasn't been picked up — restart pending Rick).
- `commons_post` is a fastmcp tool that accepts arbitrary topic + body. SAME transport pipeline as `commons_send_to`, but no wrapper involvement.
- If the cap is at the transport layer (JSON-RPC over stdio in fastmcp), both routes hit it identically.

**Probe lengths** (bytes):
| # | Length | Rationale |
|---|---|---|
| 1 | 100 | Baseline — Tiberius's truncated body was 195 chars; anything ≤200 should survive cleanly |
| 2 | 500 | Sanity floor |
| 3 | 1,000 | First "meaningful" length |
| 4 | 4,000 | Tiberius's original target size |
| 5 | 8,000 | 2× target |
| 6 | 16,000 | Coarse upper sweep |

**Test topic**: `probe-fastmcp-body-length` (free-form; auto-creates on first post; small file, cleanly removable post-test).

**Per-call procedure**:
1. Generate a body of exact length N (deterministic content, e.g., `f"PROBE-LEN-{N}-" + "x" * (N - len(prefix))`)
2. `commons_post(topic="probe-fastmcp-body-length", body=<generated>, metadata={"probe_len": N})`
3. `commons_read(topic="probe-fastmcp-body-length", limit=1)` to fetch what landed
4. Compare `len(returned_body)` against N
5. Record: (sent_len, received_len, ratio, "survived"/"truncated")

### Live probe execution

*(running now via the live MCP — results appended below)*

---

## Phase 5 — Post-merge operational steps

*(pending all prior phases + commits + MCP subprocess restart per Q6 manual per-session intervention)*
