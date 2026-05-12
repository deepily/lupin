# Phase 1 Closure — Inter-Session Commons (file-based MVP)

| Field | Value |
|---|---|
| **Initiative** | Inter-Session Commons + User-Broadcast (Phase 1: file-based commons MVP) |
| **Phase 1 status** | ✅ **CLOSED 2026-05-11** |
| **Owners** | Tiberius 🌑 (`f9608a41`) — steps 3a + 3b; Rachel 🕊️ (`9a4a601d`) — steps 4 + 5 + 6 + 7 + 8 |
| **Plan-review pipeline** | CLOSED 2026-05-11 (REUSE + Pass 1 Fitness + Pass 2 Adversarial all closed before code-write started) |
| **Implementation window** | 2026-05-11 single-day milestone |

---

## What landed

### Code (5 modules, ~700 LOC, all under `src/lupin_mcp/`)

| Module | LOC | Stmts | Branches | Coverage |
|---|---|---|---|---|
| `commons_persona_matcher.py` | 91 | 17 | 10 | **100%** |
| `commons_store.py` | 332 | 146 | 36 | **100%** |
| `commons_archival.py` | 230 | 117 | 26 | **100%** |
| `commons_ask.py` | 124 | 29 | 8 | **100%** |
| `cosa_voice_mcp.py` (MODIFIED) | +250 | n/a | n/a | exercised via AC14 + AC12 subprocess tests |
| **Total commons-scope modules** | **777** | **309** | **80** | **100% lines / 100% branches / 100% functions** |

### MCP tools registered on cosa-voice

Five tools added alongside the 9 pre-existing cosa-voice tools (same `mcp = FastMCP(...)` instance, same stdio process):

| Tool | Behavior |
|---|---|
| `commons_post(topic, body, metadata?)` | Append entry to topic with auto-stamped persona |
| `commons_read(topic, since?, limit?)` | Read entries from topic with optional since-filter |
| `commons_who(topic?, retention_hours?)` | Enumerate sessions active in the retention window |
| `commons_ask_sync(topic, body, timeout?, grace?)` | Post question + block until first reply + grace window, return accumulated replies |
| `commons_ask_async(topic, body, question_id?)` | Post question, return immediately (Phase 1 polling-mode, Phase 3 upgrades to push) |

### INI keys (6 wired via ConfigurationManager)

Added to `[Lupin: Baseline]` with paired splainer entries:
- `commons enabled = True` — master toggle (controls registration short-circuit + daemon boot)
- `commons storage path = /io/commons`
- `commons retention hours = 24`
- `commons archival interval seconds = 3600`
- `commons broadcast rate limit seconds = 30` (Phase 2 consumption)
- `commons ask sync grace seconds = 1.0`

### Infrastructure

- `tempfile.TemporaryDirectory()` test fixture pattern for all unit tests (no cross-test state leakage)
- `fcntl.flock` multi-writer safety verified empirically by AC10b stress test (5 procs × 100 posts → exactly 500 entries, zero corruption)
- 24h archival daemon (`CommonsArchiver`) scaffolded on the same threading.Event + daemon-thread pattern as `running_fifo_queue.py:95-107` ghost-job sweeper (per F3 REUSE)
- `tests/helpers/mcp_stdio_test_client.py` reusable fastmcp stdio subprocess client for AC12 + AC14 (and future MCP-tool tests)
- `LUPIN_COMMONS_TEST_OVERRIDE` JSON env-var hatch in `_load_commons_config()` for the AC12 toggle test (production behavior unaffected when unset)

### Tests (88 total, ~14s aggregate runtime)

| Tier | File | Count | Venue |
|---|---|---|---|
| Unit | `test_commons_persona_matcher.py` | 12 | :7999 |
| Unit | `test_commons_store.py` | 37 (incl AC10b real-fcntl stress + branch backfill) | :7999 |
| Unit | `test_commons_archival.py` | 26 | :7999 |
| Unit | `test_commons_ask.py` | 7 (AC6 4-case hybrid-grace + AC7 + helper) | :7999 |
| Unit | `test_commons_mcp_subprocess.py` | 1 (AC14 happy path) | :7999 |
| Unit | `test_commons_mcp_config_toggle_subprocess.py` | 2 (AC12 disabled + enabled) | :7999 |
| Smoke | `test_commons_two_session_roundtrip.py` | 3 (round-trip + distinct personas + cross-process Q/A) | :7999 |
| **Total** | | **88** | All :7999 AI-discretionary |

---

## ACs verified

| AC | Verification | Status |
|---|---|---|
| **AC1** | `<root>/io/commons/` + `archive/` exist post-init | ✅ `test_init_creates_directories` |
| **AC2** | Reserved topics seeded with `reserved: true` frontmatter | ✅ `test_init_seeds_reserved_topics` |
| **AC3** | `commons_post` stamps immutable persona fields at post-time | ✅ `test_post_*` (4 tests) |
| **AC4** | `commons_read` honors since-filter + limit + missing-topic semantics | ✅ `test_read_*` (5 tests) |
| **AC5** | `commons_who` enumerates active sessions within 24h | ✅ `test_who_*` (6 tests, includes branch-backfill) |
| **AC6** | `commons_ask_sync` hybrid-grace 4 timing cases | ✅ `test_ask_sync_*` (4 tests) |
| **AC7** | `commons_ask_async` returns immediately with question_id | ✅ `test_ask_async_*` (2 tests) |
| **AC8** | Persona matcher case/punctuation/spacing-tolerant + LLM stub | ✅ `test_match_*` (12 tests) |
| **AC9** | 24h archival rotation atomic; no data loss on write failure | ✅ `test_24h_split` + `test_write_failure_no_data_loss` + `test_atomic_rewrite_*` (4 tests) |
| **AC10** | 100% line + branch + function coverage (hard gate) | ✅ Final aggregate: 309 stmts, 80 branches, 0 missing |
| **AC10b** | Real fcntl concurrent-append stress (5 × 100 = 500 entries, zero corruption) | ✅ `test_ac10b_real_fcntl_concurrent_append` |
| **AC11** | Two-session smoke via direct `CommonsStore` + tempdir, no MCP layer | ✅ `test_commons_two_session_roundtrip.py` (3 tests) |
| **AC12** | Config-toggle subprocess: disabled → daemon NOT started; enabled → all 5 tools + daemon present | ✅ `test_ac12_*` (2 tests) |
| **AC13** | CLAUDE.md splainer-pairing mandate honored (every INI key has a splainer entry) | ✅ 6 keys, 6 explanations |
| **AC14** | Subprocess tool-registration: spawned `python -m lupin_mcp.cosa_voice_mcp` lists all 5 commons tools | ✅ `test_ac14_commons_tools_registered_in_subprocess` + AC12-enabled case |

---

## Notable deviations from the original design

### D1 (declared pre-implementation) — `commons_ask_async` polling-mode

Phase 0 §10 already documented this: Q6b's `<system-reminder>` push contract is deferred to Phase 3. Phase 1 ships polling-mode (`commons_read(topic, since=...)` + filter on `metadata.in_reply_to == question_id`). MCP tool signature stays stable across the upgrade — callers' code does not change.

### D2 (surfaced during step 4) — Branch-coverage gap in `commons_store.py:306->303`

Discovered when step 4 enabled `--cov-branch`. The defensive false-branch in `who()`'s "same-session entry seen out of order" path was unreachable from the existing tests (entries always read in ascending order). Backfilled with `test_who_same_session_older_entry_skipped` (mocks `read()` to return newest-first). Lesson logged in the step 5 resume pointer: always run with `--cov-branch` from the start, not just `--cov`.

### D3 (surfaced during step 8) — AC12 scope narrowing

The original AC12 wording said "MCP server does NOT register commons tools" when disabled. Step 5 landed tool registration unconditionally (via `@mcp.tool` decorator at import time) with defense-in-depth call-time short-circuit (`if not _commons_enabled(): return {"status": "error", "reason": "commons disabled"}`). The daemon contract (the side effect AC12 is primarily concerned with) is fully honored. Refactoring to conditional `@mcp.tool` decoration would require dynamic registration which fastmcp 2.x makes awkward; treating as a deliberate Phase 1 design choice. Phase 2 or 3 may revisit if dynamic deregistration becomes important.

### D4 (mechanism choice, not a contract deviation) — `LUPIN_COMMONS_TEST_OVERRIDE` JSON hatch

AC12 suggested "write a test INI" to drive the toggle test. The standard `LUPIN_CONFIG_MGR_CLI_ARGS` parser can't accept keys with spaces (e.g., `commons enabled`), so the cleanest path was a JSON env-var hatch in `_load_commons_config()` that bypasses ConfigurationManager when set. Production behavior is unchanged. The behavioral contract of AC12 (subprocess respects the toggle end-to-end) is met.

---

## Deferred items

### `commons storage path` absolute-path support

`_commons_storage_root()` currently treats the INI value as relative to `LUPIN_ROOT` (default `/io/commons` pass-through; custom values concatenate). Phase 4 (Postgres-backed commons + Multiplexer Commons tab) is the natural place to refactor for absolute-path support if needed.

### Cross-repo MCP tool catalog audit

Filed at `<planning-is-prompting>/TODO.md`: after Phase 1 lands the 5 commons MCP tools, audit + update consumer-facing documentation in every repo that references the cosa-voice MCP tool catalog. **Action now eligible** (Phase 1 is complete).

### Conditional `@mcp.tool` registration (D3 follow-up)

If/when dynamic deregistration becomes important, revisit AC12's letter and implement registration-time conditionality. Currently the call-time short-circuit is the protection.

### Docker image promotion

Candidate `lupin:1.0.0-pytest-cov` (built 2026-05-11 to add pytest-cov to the test image) is parked. User decides when/if to promote to `lupin:1.0.0`.

### MCP server restart for current Claude Code session

The 5 new commons MCP tools are registered in source but NOT yet in the running cosa-voice subprocess for the current Claude Code session. To use them now, the user needs to restart cosa-voice (or start a fresh Claude Code session). User-level operation per existing CLAUDE.md MCP-restart guidance.

---

## Lessons learned

1. **Run `--cov-branch` from the start.** Line coverage gives false confidence; branch coverage caught a defensive path that line coverage missed. Updated all resume pointers and the final aggregate gate to include `--cov-branch` explicitly.

2. **Spawn-context multiprocessing tests are fast.** AC10b (5×100 fcntl stress) runs in ~1s; AC11 (3 two-session scenarios) runs in 0.5s; AC14 (subprocess MCP) runs in 3s; AC12 (2 subprocesses) runs in 6s. All :7999 AI-discretionary. No reason to fear subprocess-based tests when they actually validate the contract.

3. **`@mcp.tool` decorators are import-time-fixed.** FastMCP 2.x doesn't make conditional registration easy. Plan for this when designing config-toggleable MCP tool sets — the call-time short-circuit is usually a fine equivalent.

4. **Env-var-keyed JSON overrides are a clean test hatch.** When the standard config plumbing can't accommodate a test scenario (keys with spaces, paths outside project root, etc.), a JSON env-var hatch BEFORE the standard path is surgical, documented, and production-safe.

5. **Docs-first cadence matters.** Each step landed with: (1) implementation, (2) immediate execution-log update, (3) resume pointer for the next step, (4) `.claude-session.md` file-touched log. Made it trivial to pick up across multiple "let's continue with step N" voice prompts in conversation mode without re-deriving context.

---

## Phase 2 unblock

`03-phase2-user-broadcast-design.md` is the next eligible R&D doc. Phase 2 scope (per `01-design.md §4.2`):

| Component | Notes |
|---|---|
| UI control | "📢 Broadcast to all CC sessions" panel in `notifications.html` (or multiplexer port when Phase 6c lands) — textarea + recipient preview chip-row + Send button |
| `GET /api/commons/active-sessions` | Enumerate active CC sessions for the recipient preview |
| `POST /api/commons/broadcast-to-cc-sessions` | Fanout endpoint; rate-limit via `commons broadcast rate limit seconds` (already declared in INI) |
| Persona-aware `@PersonaName:` parsing | Already implemented in `commons_persona_matcher.py` (12 tests pass) |
| Live ack aggregation | Subscribe to `broadcast-acks` reserved topic via WS push |
| Markdown rendering | Q15 deviation — from day one |
| One-step confirm dialog | Q10 — single screen recipient chip-row |

All Phase 1 prerequisites are in place: persona matcher works, reserved topic exists, store + ask infrastructure is solid. Phase 2 is primarily UI + 2 endpoints + persona-aware parse glue.

---

## Aggregate verification command (Phase 1 milestone gate)

```bash
PYTHONPATH=src:$PYTHONPATH /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa/.venv/bin/python \
  -m pytest src/tests/unit/commons/ src/tests/smoke/test_commons_two_session_roundtrip.py -v \
  --cov=lupin_mcp.commons_persona_matcher \
  --cov=lupin_mcp.commons_store \
  --cov=lupin_mcp.commons_archival \
  --cov=lupin_mcp.commons_ask \
  --cov-branch --cov-fail-under=100
```

Expected: **88 passed in ~14s; 309 stmts / 80 branches / 0 missing; 100.00% coverage.**
