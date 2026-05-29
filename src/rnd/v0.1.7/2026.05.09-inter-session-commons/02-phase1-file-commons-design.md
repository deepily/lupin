# Phase 1 — File-Based Commons MVP — Code-Execution Plan

| Field | Value |
|---|---|
| **Date** | 2026-05-09 |
| **Author** | Tiberius (session `f9608a41`) |
| **Status** | 🟡 **DRAFT — entering plan-review pipeline (REUSE → Pass 1 Fitness → Pass 2 Adversarial)** |
| **Predecessor** | `01-design.md` (Phase 0 — closed 2026-05-09 with all 15 questions ratified) |
| **Successor (planned)** | `03-phase2-user-broadcast-design.md` |
| **Branch** | `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe` |
| **Execution log** | `90-execution-log.md` (created at first phase start) |

---

## 1. TL;DR

Phase 1 ships a **file-based commons MVP** so two or more Claude Code sessions can post status, read each other's posts, query peer presence, and (with caveat) ask peers questions. Zero infrastructure beyond the filesystem. Five MCP tools registered on the existing cosa-voice server. No UI, no WebSocket push, no Postgres. Phase 1 deliberately under-delivers the `commons_ask_async` answer-arrival contract (Q6b ratification specifies `<system-reminder>` injection) — Phase 1 ships the storage + question-id wiring; **Phase 3 wires the actual injection** (this is the only Phase 0 ratification deviation in Phase 1, called out explicitly in §10).

Estimated effort: **1 day of focused work + plan-review pipeline (~2-4 hours of walks).**

---

## 2. Phase 1 scope

### In scope (Phase 1 ships)

1. `commons/` filesystem layout under project root + `commons/archive/` for rotation
2. `src/lupin_mcp/commons_store.py` — file-based store: append, read, rotate
3. `src/lupin_mcp/commons_persona_matcher.py` — case-insensitive + punctuation/space-tolerant persona-name matcher with **stubbed local-LLM fallback hook** (no LLM call in Phase 1)
4. 5 MCP tools registered on `src/lupin_mcp/cosa_voice_mcp.py`:
   - `commons_post(topic, body, metadata=None, ack_required=False)`
   - `commons_read(topic, since=None, limit=50)`
   - `commons_who(topic=None)`
   - `commons_ask_sync(topic, body, timeout=120)`
   - `commons_ask_async(topic, body, question_id=None)`
5. Reserved-set seeding: `broadcast-acks`, `presence`, `system-events` topic files always exist (created on first server-startup if absent)
6. 24h archival rotation (background daemon thread on the MCP server, configurable interval)
7. INI configuration keys + paired splainer entries
8. Tests: unit (store, matcher, parser) + smoke (2-session roundtrip on `:7999`)

### Out of scope (deferred to later phases)

- Real-time WebSocket push for `commons_message` events — **Phase 3**
- The `<system-reminder>` injection mechanism for `commons_ask_async` answer-arrival — **Phase 3** (Phase 1 ships a polling-based degraded mode; see §10)
- LLM-fallback wiring for persona disambiguation — **Phase 3** (Phase 1 stubs the hook)
- User→all broadcast UI + endpoints — **Phase 2**
- Postgres persistence — **Phase 4**
- Multiplexer Commons tab — **Phase 4**
- File-lock / coordination primitives (`commons_claim` / `commons_release`) — **Phase 5**

---

## 3. Acceptance criteria (ACs)

| # | AC | Verification |
|---|---|---|
| **AC1** | `<project_root>/io/commons/` directory + `<project_root>/io/commons/archive/` exist after MCP server startup. (`io/` is already gitignored at `.gitignore:68`, so no separate gitignore line needed.) **Startup verification**: `CommonsStore()` init creates both directories idempotently (no-op if present). | **EXECUTOR: AI** — `test_commons_store::test_directory_init` asserts `os.path.exists(tmpdir + '/io/commons')` and `'/io/commons/archive'` after `CommonsStore(root=tmpdir)` construction |
| **AC2** | Reserved topic files (`io/commons/broadcast-acks.md`, `io/commons/presence.md`, `io/commons/system-events.md`) auto-created **by `CommonsStore.__init__()`** if absent (idempotent — check exists first, no overwrite). First line is a frontmatter block declaring `reserved: true`, `schema_version: 1`, `created: <ISO-8601-now>`. MCP server constructs `CommonsStore` once at module load; tools share the singleton instance. | unit test asserts files + frontmatter; idempotent on repeat startup; reserved-flag distinguishable from free-form |
| **AC3** | `commons_post(topic, body, metadata=None)` appends an entry with: ISO-8601 timestamp, sender session_id, persona name, persona icon, persona color (from `get_session_info()`), the body, and metadata. **Metadata default** when caller omits `metadata=` parameter: `{}`. **`kind` field is OPTIONAL** (semantic label, not enforced by store). **Persona substitution at post-time**: if `persona.name` is None → `'<unknown>'`; if `persona.icon` is None → `💬`; if `persona.color` is None → `#888888`. **Persona fields stored at post-time are immutable** — color/icon/name never re-derived at read-time (per C4 ratification; consistent with per-session-voice-personas immutability invariant). Free-form topics auto-create their file on first post (with `reserved: false` in frontmatter). | **EXECUTOR: AI** — `test_commons_store::test_post_*` (entry shape, metadata-default, persona-substitution, free-form auto-create); smoke test `test_commons_two_session_roundtrip` asserts post is visible to reader via subsequent `commons_read` call |
| **AC4** | `commons_read(topic, since=None, limit=50)` returns a list of parsed entries (newest first when no `since`, ascending when `since` supplied), with each entry as a dict containing all AC3 fields. Honors `limit` strictly. Missing topic → empty list (not error) for free-form; missing reserved topic → error (should never happen post-AC2). | unit tests cover: empty topic, full topic, since-filter, limit-cap, missing topic |
| **AC5** | `commons_who(topic=None)` returns a list of `{session_id, persona_name, persona_icon, persona_color, last_post_ts}` for sessions with at least one post in the last 24h. **24h window calculation**: at call-time as `current_utc_time - entry.timestamp > 3600*24`. If `topic` is provided, scan only that topic file; otherwise scan ALL active topic files. `last_post_ts` is the ISO-8601 timestamp from the most recent entry for that session. | unit test seeds 3-session post history with various ages; verifies enumeration + 24h freshness cutoff |
| **AC6** | `commons_ask_sync(topic, body, timeout=120, grace_seconds=None)` posts the question with `metadata.kind="question"` + auto-generated `question_id` (UUID v4). `grace_seconds` defaults from INI key `commons ask sync grace seconds` (default 1.0) when not supplied — **dependency-injected for test fast-path** (per C3 ratification). **Returns a list** of all matching reply entries received within the response window. **Timing — hybrid first+grace** (per A3b ratification): blocks until the FIRST matching reply arrives, then waits an additional `grace_seconds` to coalesce additional fast replies, then returns the accumulated list. If no replies arrive within `timeout`, returns `[]` (empty list). | **EXECUTOR: AI** — `test_commons_ask::test_ask_sync_*` (4 cases per T2 with injected small timeout/grace for fast wall-clock): (a) one peer answers within timeout → returns `[entry]`; (b) two peers answer within grace → returns `[entry1, entry2]`; (c) two peers answer outside grace → returns `[entry1]` only; (d) timeout with zero answers → returns `[]`. Tests pass `timeout=0.1, grace_seconds=0.05` for fast wall-clock; same code path as production. |
| **AC7** | `commons_ask_async(topic, body, question_id=None)` posts the question with `metadata.kind="question"` + `question_id` (auto-generated UUID v4 if not supplied) and returns immediately with `{question_id, posted_ts}`. **Phase 1 polling-mode contract**: caller MUST poll via `commons_read(topic, since=...)` and manually filter for entries with `metadata.in_reply_to == question_id` to detect answers. Phase 3 automates this via `<system-reminder>` injection. (See §10 Deviation D1 for the full Q6b-vs-Phase-1 explanation.) | **EXECUTOR: AI** — `test_commons_ask::test_ask_async_returns_immediately` asserts return shape + correct question_id; smoke test verifies caller can pick up the answer via polling-style `commons_read` (**Phase 1 degraded mode** per D1 deviation; Phase 3 upgrades to push-based `<system-reminder>` injection per Q6b). |
| **AC8** | Persona matcher: case-insensitive + punctuation/space-tolerant (`Mr. Radio` / `mr radio` / `mrradio` / `MR.RADIO` all match). When mechanical match fails, calls a stub function with stable signature `disambiguate_via_llm(input_str: str, candidate_personas: List[str]) -> Optional[str]` whose Phase 1 body is `return None  # Phase 3 wires actual LLM call` (no LLM call in Phase 1). Matcher logs a warning if both mechanical AND LLM-fallback return None. **Phase 3** wires the actual LLM call by replacing the stub body — signature stays stable, no caller refactor needed. | unit test exhausts mechanical match cases (6+ tests per AC10 list); asserts stub-call signature on miss; asserts log-warn fires on double-miss |
| **AC9** | 24h archival rotation: a daemon thread on the MCP server scans `<project_root>/io/commons/*.md` every `commons_archival_interval_seconds` (default 3600 = 1h); for any topic file with entries older than 24h, those entries are split off into `<project_root>/io/commons/archive/yyyy-mm-dd/topic-X.md` and removed from the active file. Reserved topics rotate but always retain their frontmatter block. **Atomicity**: archival is atomic per-topic — daemon reads all entries, filters >24h, writes remaining to active file, writes aged entries to archive IN A SINGLE BATCH. If write fails (e.g., disk full), no data is removed from active file; daemon logs error and retries at next interval. On success, active file is truncated and rewritten; `fcntl.flock()` (per F6 REUSE) ensures no concurrent MCP tool sees a half-written file. | **EXECUTOR: AI** — `test_commons_archival::test_24h_split` seeds entries with ages 25h / 23h / 1h on a temp dir, runs rotation, asserts split + archive dir creation; `test_commons_archival::test_write_failure_no_data_loss` mocks `flock()` to simulate disk-full, runs rotation, asserts no active-file data lost and no exception escaped |
| **AC10** | Unit tests in `src/tests/unit/commons/` cover store, matcher, archival, ask_sync timing. **Coverage mandate (commons-only scope per C3 ratification)**: 100% lines AND branches AND functions (hard gate). **Minimum test scope**: (a) `commons_store.py` 8+ tests — empty-init, append, read-empty, read-all, read-since, read-limit, missing-topic, concurrent-append-races (mocked); (b) `commons_persona_matcher.py` 6+ tests — exact, case-insensitive, punctuation-tolerant, space-tolerant, unknown-persona, stub-LLM-fallback-on-miss; (c) `commons_archival.py` 5+ tests — 24h-cutoff split, archive-dir creation, reserved-topic retention, rotation idempotence, daemon crash+restart; (d) ask_sync hybrid-grace 4 tests per AC6 verification column. | **EXECUTOR: AI** — `pytest --cov=lupin_mcp.commons_store --cov=lupin_mcp.commons_persona_matcher --cov=lupin_mcp.commons_archival --cov-fail-under=100 src/tests/unit/commons/` (hard gate; halt implementation if <100%) |
| **AC10b** | **Real concurrent-append stress test** (per Design Concern #5 ratification): validates F6 fcntl decision empirically. Five child Python processes each call `commons_post` 100 times to the same topic in a tempdir, racing each other. After 500 total posts, assert EXACTLY 500 entries present in the topic file, no corruption, no lost posts. Distinct from AC10's mocked race test — this exercises actual OS-level fcntl behavior. | **EXECUTOR: AI** — `test_commons_store::test_real_fcntl_concurrent_append` spawns 5 `subprocess.Popen` processes via shared tempdir, each posting 100 entries; AI reads final file and asserts entry count == 500 with no corruption (parseable, all entries valid) |
| **AC11** | Smoke test `src/tests/smoke/test_commons_two_session_roundtrip.py`: two child Python processes (each with distinct persona) directly import `CommonsStore`, both pointed at a shared `tempfile.TemporaryDirectory()`. One posts to `coordination` topic, the other reads and verifies the entry. **No server dependency** — pure local file I/O via tempdir. **Venue: `:7999` AI-discretionary** (per the §TESTING VENUES rubric: non-destructive, fast, isolated; MCP layer bypassed for Phase 1 smoke per T3 ratification — direct `CommonsStore` tests the file-store + matcher + frontmatter logic; MCP-tool-registration end-to-end coverage handled separately by AC12 + AC14 via subprocess-spawn helper). | **EXECUTOR: AI** — `pytest src/tests/smoke/test_commons_two_session_roundtrip.py -v` |
| **AC12** | INI keys present in `src/conf/lupin-app.ini` under `[Lupin: Production]` + paired entries in `src/conf/lupin-app-splainer.ini`. Keys: `commons enabled`, `commons storage path` (default `/io/commons`), `commons retention hours`, `commons archival interval seconds`, `commons broadcast rate limit seconds`, **`commons ask sync grace seconds`** (default `1.0`, per A3b). **Lifecycle**: keys read at MCP server startup via `ConfigurationManager`. If `commons enabled = false`, MCP server does NOT register commons tools and does NOT start archival daemon. **No hot-reload** — config changes require MCP server restart. Tools redundantly check `commons_enabled` at call-time as safety. | **EXECUTOR: AI** — grep both files for each key; **config-toggle subprocess test** (per P2 A1 ratification): AI writes test INI with `commons enabled=false`, spawns `python -m lupin_mcp.cosa_voice_mcp` test subprocess via `subprocess.Popen` with stdio MCP transport, calls `list_tools` and asserts commons tools NOT in response; kills subprocess; repeats with `commons enabled=true` and asserts commons tools ARE present. Uses shared MCP-stdio test helper (~50 LOC). |
| **AC13** | `py_compile` clean for all NEW + MODIFIED files; full import-chain check via `PYTHONPATH=src:$PYTHONPATH python -c "from lupin_mcp.cosa_voice_mcp import mcp; from lupin_mcp.commons_store import CommonsStore; from lupin_mcp.commons_persona_matcher import match_persona; print('OK')"`. | **EXECUTOR: AI** — runs the import chain via `subprocess.run` capturing stdout/stderr; asserts return-code 0 + `'OK'` in stdout + zero exceptions |
| **AC14** | New MCP tools are registered when `cosa_voice_mcp.py` is loaded. Verifies that the 5 new commons tools (post, read, who, ask_sync, ask_async) appear in the MCP tool catalog when a fresh subprocess loads the current code from disk. | **EXECUTOR: AI** — **tool-registration subprocess test** (per P2 A2 ratification): AI spawns fresh `python -m lupin_mcp.cosa_voice_mcp` subprocess via `subprocess.Popen` with stdio MCP transport (loads `cosa_voice_mcp.py` from disk), sends `list_tools` MCP JSON-RPC request, parses response, asserts all 5 commons tools present in catalog; kills subprocess. Uses the same MCP-stdio test helper as AC12. **Note on live-subprocess restart**: the LIVE cosa-voice MCP subprocess this Claude session is connected to is a SEPARATE concern (user runs `claude mcp restart cosa-voice` or relaunches Claude Code when they want to start using the new tools in this session); verification here validates the registration code path, not the user's operational workflow. |

---

## 4. File touchpoints

### NEW files

| Path | Approx LOC | Purpose |
|---|---|---|
| `src/lupin_mcp/commons_store.py` | ~150 | File-based store: append, read, rotate, parse entry frontmatter |
| `src/lupin_mcp/commons_persona_matcher.py` | ~80 | Mechanical matcher + LLM-fallback stub |
| `src/lupin_mcp/commons_archival.py` | ~100 | Daemon thread for 24h rotation |
| `src/tests/unit/commons/__init__.py` | empty | Package marker |
| `src/tests/unit/commons/test_commons_store.py` | ~150 | Unit tests for store; includes AC10b real-fcntl stress test (5 procs × 100 posts → assert 500 entries) |
| `src/tests/unit/commons/test_commons_persona_matcher.py` | ~60 | Unit tests for matcher |
| `src/tests/unit/commons/test_commons_archival.py` | ~80 | Unit tests for rotation |
| `src/tests/unit/commons/test_commons_ask.py` | ~80 | Unit tests for ask_sync hybrid-grace timing (4 cases per AC6 with injected small timeout/grace) + ask_async return-shape |
| `src/tests/unit/commons/test_commons_mcp_subprocess.py` | ~100 | AC12 + AC14 verifications via spawned `cosa_voice_mcp.py` subprocess + MCP stdio protocol |
| `src/tests/smoke/test_commons_two_session_roundtrip.py` | ~100 | 2-session smoke roundtrip (direct CommonsStore import; no MCP layer, no server) |
| `src/tests/helpers/mcp_stdio_test_client.py` | ~50 | Shared helper for spawning cosa_voice_mcp.py as a test subprocess + sending list_tools / call_tool MCP JSON-RPC requests over stdio (reused by AC12 + AC14 + future MCP-tool tests) |

### MODIFIED files

| Path | Change | Approx LOC delta |
|---|---|---|
| `src/lupin_mcp/cosa_voice_mcp.py` | Register 5 new MCP tools (post, read, who, ask_sync, ask_async); start archival daemon at MCP startup; instantiate `CommonsStore` singleton at module load (per AC2 ratification — store owns reserved-topic seeding in `__init__()`) | +60 |
| `src/conf/lupin-app.ini` | Add 6 commons keys under `[Lupin: Production]` (per AC12: enabled, storage path, retention hours, archival interval, broadcast rate limit, **ask_sync grace seconds**) | +7 |
| `src/conf/lupin-app-splainer.ini` | Paired explainer entries for the 6 keys | +14 |

(`.gitignore` is NOT touched — `io/` is already excluded at `.gitignore:68`, so `io/commons/` is automatically gitignored.)

### Files NOT touched (explicitly out of Phase 1 scope)

- Anything in `src/cosa/` — no CoSA edits in Phase 1 (the listener-injection mechanism wiring is Phase 3)
- Anything in `src/fastapi_app/` — no UI work in Phase 1
- Anything in `src/cosa/rest/routers/` — no new HTTP endpoints in Phase 1

---

## 5. Sequencing — order of operations

```mermaid
graph LR
    A[1. Phase 0 ratified] --> B[2. Plan-review pipeline]
    B --> B1[REUSE pass + user gate]
    B1 --> B2[Pass 1 Fitness + user gate]
    B2 --> B3[Pass 2 Adversarial + user gate]
    B3 --> C[3. CommonsStore + matcher + tests]
    C --> D[4. Archival daemon + tests]
    D --> E[5. MCP tool registration]
    E --> F[6. INI keys + splainer]
    F --> G[7. Smoke test on :7999]
    G --> H[8. MCP server restart + verify]
    H --> I[9. Phase 1 closure entry in 90-execution-log.md]
```

**Hard prerequisite**: plan-review pipeline (REUSE → Pass 1 → Pass 2 with user gates) must complete BEFORE step 3. No code is written until the plan is reviewed.

**Within implementation steps 3-8**: execute sequentially; each step has its own verification — **all EXECUTOR: AI** per Pass 2 ratifications:
- step 3 (store + matcher): unit tests under AC10 hard-gate (100% coverage)
- step 4 (archival daemon): unit tests under AC10 + AC10b (real-fcntl stress)
- step 5 (MCP tool registration): AC14 subprocess assertion (AI spawns fresh `cosa_voice_mcp.py` subprocess via `subprocess.Popen`, calls `list_tools` over MCP stdio, asserts 5 new commons tools present, kills subprocess)
- step 6 (INI keys + splainer): grep both files for each key (deterministic)
- step 7 (smoke test on `:7999`): `pytest src/tests/smoke/test_commons_two_session_roundtrip.py -v` (direct CommonsStore + tempdir; no server dependency)
- step 8 (MCP catalog confirmation): AC14 subprocess assertion (same test fixture as step 5)

**Failure handling** (per O2 ratification): If any step 3-8 fails, **HALT implementation**. File the failure as a new bug in `bug-fix-queue.md`. Do NOT proceed to next step or to step 9 (closure) until the failure is root-caused and fixed. Exception: step 8 (MCP server restart verification) may retry up to 3 times with 5-second delays for transient port conflicts; if still failing, halt and investigate. No auto-rollback (would conflict with the project's no-migration policy).

---

## 6. Test contract (per Test Ownership Mandate)

| Tier | Files | Venue | Purpose |
|---|---|---|---|
| Unit | `test_commons_store.py`, `test_commons_persona_matcher.py`, `test_commons_archival.py`, `test_commons_ask.py`, `test_commons_mcp_subprocess.py` (24+ tests minimum, see AC10 for authoritative coverage mandate + minimum test scope) | `:7999` (AI-discretionary) | Isolated module testing — store CRUD, matcher edge cases, rotation logic + real-fcntl stress (AC10b), ask_sync hybrid-grace timing (4 cases via DI per C3), persona substitution at post-time, AC12 config-toggle + AC14 tool-registration via spawned MCP subprocess (per Cluster A P2 ratification) |
| Smoke | `test_commons_two_session_roundtrip.py` | `:7999` (AI-discretionary, fast, non-destructive) | 2-session roundtrip via **direct `CommonsStore` import** (no MCP layer, no server dependency) per T3 ratification; both child processes share a `tempfile.TemporaryDirectory()`. Pure local file I/O — no `:7999` API calls, no `:8000` exposure, nothing outliving the test |
| Integration | (none — Phase 1 has no `:8000` need) | — | — |
| WebSocket smoke | (none — no WS in Phase 1) | — | — |
| E2E UI | (none — no UI in Phase 1) | — | — |

**Why no `:8000` need**: Phase 1 doesn't mutate persistent state outside the test's tempdir, doesn't enqueue jobs, doesn't spend LLM budget, doesn't touch the DB, and runs in well under 2 minutes. All of the rubric's `:8000` triggers fail; the suite belongs on `:7999`.

**Why no MCP-subprocess in smoke** (T3 clarification): the cosa-voice MCP server is a stdio subprocess of Claude Code, NOT a port-bound service. The `:7999` venue label on the smoke test refers to "fast + non-destructive" classification, NOT to any HTTP traffic toward `:7999`. The smoke test is pure local file I/O — direct `CommonsStore` imports + shared tempdir. This bypasses the MCP layer entirely (tool registration coverage deferred to integration tests when needed).

**Why 100% coverage on commons** (per C3 ratification): hard gate — `pytest --cov-fail-under=100`. Extends the multiplexer-TS-only 100% mandate to the new commons Python modules. Coverage scope: `src/lupin_mcp/commons_store.py`, `commons_persona_matcher.py`, `commons_archival.py`. (Whether this becomes a project-wide Python policy is a separate scope-clarification question deferred outside this Phase 1 plan.)

---

## 7. INI configuration keys

Add to `src/conf/lupin-app.ini` under `[Lupin: Production]` (overridable in `[Lupin: Development]` and `[Lupin: Testing]`):

```ini
commons enabled                          = true
commons storage path                     = /io/commons
commons retention hours                  = 24
commons archival interval seconds        = 3600
commons broadcast rate limit seconds     = 30
commons ask sync grace seconds           = 1.0
```

Paired entries in `src/conf/lupin-app-splainer.ini`:

| Key | Splainer text |
|---|---|
| `commons enabled` | Master toggle for the inter-session commons feature. False disables all commons MCP tools and the archival daemon. |
| `commons storage path` | Filesystem path (relative to project root via `cu.get_project_root()`) where commons topic files live. **Default: `/io/commons`** (per S2 ratification — under the project's `io/` directory, which is already gitignored at `.gitignore:68`). |
| `commons retention hours` | How long entries stay in active topic files before being rotated to `io/commons/archive/yyyy-mm-dd/`. Default 24h. |
| `commons archival interval seconds` | How often the archival daemon scans for entries to rotate. Default 3600 (1h). |
| `commons broadcast rate limit seconds` | Minimum interval between broadcasts from the same user (Phase 2 enforcement; Phase 1 reads but does not enforce since broadcasts don't ship until Phase 2). |
| `commons ask sync grace seconds` | Per A3b ratification — `commons_ask_sync` returns a list of all matching replies; after the FIRST reply arrives, an additional grace window opens to coalesce additional fast replies before returning. Default 1.0s. |

**Lifecycle** (per O1 ratification): keys read at MCP server startup via `ConfigurationManager`. If `commons enabled = false`, MCP server does NOT register commons tools and does NOT start archival daemon. **No hot-reload** — config changes require MCP server restart. Tools redundantly check `commons_enabled` at call-time as a safety measure.

---

## 8. Topic file format (frontmatter + entries)

Active topic file (`<project_root>/io/commons/<topic-slug>.md`):

```markdown
---
topic: broadcast-acks
reserved: true
schema_version: 1
created: 2026-05-09T13:00:00-04:00
---

## 2026-05-09T13:42:17-04:00 | Tiberius 🌑 #f9608a41
**metadata**: `{"kind": "ack", "broadcast_id": "...", "status": "complete"}`

Session-end ritual complete. Commit abc1234.

---

## 2026-05-09T13:42:23-04:00 | Maria 🌸 #6825e6af
**metadata**: `{"kind": "ack", "broadcast_id": "...", "status": "skipped"}`

No edits this session; nothing to commit.

---
```

Free-form topic files use the same shape but `reserved: false` in frontmatter.

### Parsing rules (per C1 ratification — inline-JSON-in-markdown format)

`commons_read` splits the topic file on `^---$` boundaries (each entry block separated by `---`). For each entry block:

- **Header line** (regex): `## (ISO-8601-TS) \| (PERSONA-NAME) (emoji) #(SESSION-ID)` — extracts `ts`, `persona_name`, `persona_icon`, `sender_session_id`
- **Body**: all lines after the header, until the next `---` or end-of-block, EXCLUDING the metadata line if present
- **Metadata** (regex): line starting with `**metadata**:` followed by backtick-delimited JSON. Extract via `json.loads(<backtick-content>)`. If no metadata line present, default to `{}`
- **Output**: dict with `{ts, sender_session_id, persona_name, persona_icon, persona_color, body, metadata}` — `persona_color` is stored at post-time per AC3 (immutable per-allocation per C4 ratification + per-session-voice-personas immutability invariant); no read-time re-derivation

---

## 9. Risks + mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| File-write races between concurrent sessions appending to the same topic | Medium | Lost posts (data loss — append-only non-idempotent content) | `commons_store.py` uses POSIX `fcntl.flock()` for append (Linux-only; we're Linux-only per the project's Docker base). **Note on divergence from `session_bridge.py`**: per F6 REUSE finding, `session_bridge.py:1022-1026` deliberately omits fcntl for ITS read-modify-write JSON pattern (idempotent updates → lost writes recoverable via next-event replay). Commons differs because writes are append-only with non-idempotent unique-content posts; lost posts = data loss. Per the F6 investigation, the two modules' choices are both correct for their respective access patterns. |
| Archival daemon thread crashes silently | Low | Active files grow unbounded over weeks | Daemon catches all exceptions, logs via `du.print_banner`, restarts itself with backoff. Per F3 REUSE: templates from `running_fifo_queue._ghost_job_sweep_loop` (canonical daemon pattern) |
| Archival daemon crashes mid-rotation | Low | Possible half-written file | Per AC9 atomicity rule (C5 ratification): atomic per-topic batch — daemon reads all, filters >24h, writes remaining to active, writes aged to archive IN A SINGLE BATCH. If write fails (disk full), no data removed from active; daemon logs error and retries at next interval. `fcntl.flock()` ensures no concurrent MCP tool sees a half-written file. |
| Q6b `commons_ask_async` injection contract under-delivered in Phase 1 | High (this is intentional) | Caller must poll instead of being notified | Documented in §10 D1; flagged as known-deviation with explicit Q6b citation; Phase 3 wires the injection. Phase 1 callers using async mode degrade to polling. Acceptable for: (a) non-blocking background queries (session registers availability, no immediate reply needed), (b) ask-then-read-in-next-task patterns (session asks, continues other work, polls at natural breakpoint). NOT acceptable for: interactive dialogue patterns where the asking session must wait synchronously for an answer (use `commons_ask_sync` instead). |
| Persona matcher false-negative on unusual inputs | Medium | Silent skip of `@PersonaName:` directive | LLM-fallback stub in place per AC8 with stable signature `disambiguate_via_llm(input_str: str, candidate_personas: List[str]) -> Optional[str]` (Phase 1 body returns None; Phase 3 wires the actual LLM call). Matcher logs warning if both mechanical AND LLM-fallback miss. Use case: voice-dictation variants like "the radio guy" → mechanical miss → Phase 3 LLM resolves to "Mr. Radio". |
| Active topic files grow unbounded if archival daemon disabled | Low | Slow `commons_read` over time | Default config enables daemon; INI key documented |
| Cross-session bridge-file lookups for `commons_who()` may stale-read if a session crashes mid-session | Medium | `commons_who()` reports a phantom session | Acceptable for Phase 1; Phase 3 adds explicit `presence` heartbeats per Q1b ratification. Per F7 REUSE: `commons_who()` reuses `session_bridge.find_active_voice_persona_sessions()` which has its own staleness filtering. |

---

## 10. Phase 0 ratification deviations in Phase 1

**Only one deviation, called out explicitly:**

### Deviation D1 — `commons_ask_async` answer-arrival mechanism

**Q6b ratification text** (verbatim from `01-design.md` §13 Q6b row):

> "`commons_ask_async(topic, body, question_id)` returns immediately, and when a peer posts an answer it arrives via system-reminder injection so the asking session can handle it whenever it next picks up control."

**Phase 1 implementation deviates as follows**: returns immediately (✅), posts the question with `question_id` (✅), but the `<system-reminder>` injection mechanism is **NOT wired in Phase 1**. Phase 1 callers must poll `commons_read(topic, since=...)` and filter for entries with `metadata.in_reply_to == question_id` to detect answers.

**Why deferred to Phase 3**: the injection mechanism lives in CoSA (`src/cosa/rest/routers/conversation_mode.py` already implements the displace + self-exit injection pattern — confirmed by F12 REUSE finding). Wiring it for commons answer-arrival requires CoSA-side changes, which expand Phase 1 scope across the submodule git boundary. Phase 3 also brings WebSocket push, which is the natural moment to wire injection-based answer-arrival.

**User-visible Phase 1 contract**: `commons_ask_async` is functionally equivalent to `commons_post(topic, body, metadata={kind: "question", question_id: ...})` — the asking session must poll for replies via subsequent `commons_read` calls. Phase 3 promotes it to the ratified push-based contract **without changing the MCP tool signature** — only the answer-arrival mechanism upgrades.

**Authority**: the ratification statement at `01-design.md` §13 Q6b row remains authoritative. This Phase 1 plan documents the interim Phase 1 behavior and the Phase 3 closure plan.

**Tracking**: this deviation will be recorded in §13 of the Phase 0 design doc as a "Phase 1 implementation note" once this Phase 1 plan completes Pass 2 Adversarial review and is APPROVED for code-write.

---

## 11. REUSE pre-pass — CLOSED 2026-05-10

Walked all 12 findings sequentially via individual `ask_multiple_choice` cards. Verdict distribution: **8 reuse-as-is, 3 extend-existing, 1 genuinely-new (fcntl with documented justification)**. Zero Layer-3 deviations from Phase 0's 15 ratified Q-decisions. Apparent contradiction in finding #6 (fcntl vs session_bridge) resolved via investigation — the session_bridge no-fcntl choice is local to its read-modify-write idempotent JSON pattern and does NOT bind commons' append-only non-idempotent semantics.

### Prior art referenced (apply at code-write time)

| # | Plan component | Verdict | Prior-art reference (file:line) | Implementation note |
|---|---|---|---|---|
| F1 | `commons_store.py` (file-based store + frontmatter) | extend-existing | `src/cosa/training/peft_trainer.py:250-330` (YAML frontmatter via `yaml.dump`); `src/cosa/agents/deep_research_to_podcast/agent.py:save_report_with_frontmatter`; `src/cosa/agents/swe_team/state_files.py` (append-only log) | Adapt frontmatter parser from peft_trainer; append semantics from state_files |
| F2 | `commons_persona_matcher.py` (case-insensitive + punctuation-tolerant matcher) | extend-existing | `src/cosa/rest/voice_persona_helpers.py:52-94` `display_name_for`; `src/cosa/agents/test_fix_expediter/cluster.py` `_normalize_classname`; `src/cosa/agents/notification_proxy/verification.py` (LLM-fallback pattern) | Import `display_name_for` for normalization rules; LLM-fallback hook structured per `notification_proxy/verification.py` |
| F3 | `commons_archival.py` (24h rotation daemon) | reuse-as-is | `src/cosa/rest/running_fifo_queue.py:95-107` `_ghost_job_sweep_loop` | Template the daemon scaffold (threading.Event, daemon=True, all-exception catch with backoff); replace inner scan with file-rotation logic |
| F4 | 5 MCP tools (`commons_post`, `commons_read`, `commons_who`, `commons_ask_sync`, `commons_ask_async`) | reuse-as-is | `src/lupin_mcp/cosa_voice_mcp.py:620-1050` (5 existing tools using `@mcp.tool` + JSON schemas + project logging conventions); `notify_user_sync.py` / `notify_user_async.py` naming precedent | Follow `@mcp.tool` decorator pattern exactly. **Cross-repo follow-up filed at `<planning-is-prompting>/TODO.md`**: audit + update consumer-facing documentation in every repo that references the cosa-voice MCP tool catalog after Phase 1 lands. |
| F5 | Reserved-topic frontmatter (`reserved: true`, `schema_version: 1`) | reuse-as-is | `src/cosa/training/peft_trainer.py:269-285` (YAML frontmatter); `src/lupin_cli/notifications/notification_models.py` (schema versioning) | Use `yaml.safe_load`/`yaml.safe_dump` for individual blocks; custom multi-block splitter on top (~10 LOC) for the multi-entry topic file shape |
| F6 | POSIX `fcntl.flock()` for append safety | genuinely-new (with justification) | None — first fcntl use in project. Cross-ref: `src/lupin_cli/claude_code/hooks/lib/session_bridge.py:1022-1026` documents `no fcntl, no tmpfile+rename` for THAT module's read-modify-write JSON pattern (idempotent updates → lost writes recoverable). | **Adopt fcntl.flock for commons** because writes are append-only with non-idempotent content (each post is unique data; loss = data loss). Document divergence from session_bridge in plan §9 risk table with explicit citation to `session_bridge.py:1022-1026`. |
| F7 | Bridge-file presence enumeration (`commons_who`) | reuse-as-is | `src/lupin_cli/claude_code/hooks/lib/session_bridge.py:1156-1213` `find_active_voice_persona_sessions`; `:653-732` `find_active_conversation_sessions` | Call existing helpers; extract `(session_id, persona_name, persona_icon, persona_color, last_seen)` tuple. May need to pass staleness threshold parameter or post-filter for the 24h Q4 window |
| F8 | Test fixtures + 2-session smoke roundtrip | reuse-as-is | `src/tests/unit/test_proxy_decision_embeddings.py`, `test_swe_team_delegation.py` (10+ existing tests use `tempfile.TemporaryDirectory()`); subprocess.Popen patterns common throughout `src/tests/` | Standard `tempfile.TemporaryDirectory()` for storage isolation; `subprocess.Popen` for 2-session simulation. Test-internal helper (~30 LOC) coordinates start/ready/teardown |
| F9 | 5 INI keys + paired splainer entries | reuse-as-is | `src/conf/lupin-app.ini:6-100` + paired `src/conf/lupin-app-splainer.ini` (200+ keys follow this pattern); voice-persona keys (`cc session voice persona ...`) for multi-token naming style | Lowercase, spaces, equals-aligned per project convention; every new key gets a paired splainer entry |
| F10 | Question/answer threading via `metadata.in_reply_to == question_id` | extend-existing | `src/cosa/rest/notification_fifo_queue.py:50-51` `str(uuid.uuid4())` UUID-correlation; `:9-108` NotificationItem ID model | `question_id = str(uuid.uuid4())` at ask-time; replies set `metadata['in_reply_to'] = question_id`. Edge cases for code-write: should ask_sync match by sender-session too? should ask_async collect multiple replies or first-only? |
| F11 | UUID v4 for `question_id` and `broadcast_id` | reuse-as-is | `src/cosa/rest/notification_fifo_queue.py:50` `str(uuid.uuid4())`; `deep_research`, `podcast_generator`, `decision_proxy` all use `uuid.uuid4().hex[:8]` for short job-IDs | `str(uuid.uuid4())` for storage; `uuid.uuid4().hex[:8]` if short display form needed |
| F12 | `<system-reminder>` injection mechanism (Phase 3 wiring target, deferred per §10) | reuse-as-is | `src/cosa/rest/routers/conversation_mode.py:195-219` (displace branch); `:252-278` (self-exit branch); `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (action routing → tmux send-keys) | Confirms §10 of this plan correctly identifies the Phase 3 reuse target. Phase 3 plan must enumerate new action types (`action:commons_answer_notify`, `action:broadcast_received`). |

### Layer-3 Design Concerns (REUSE pass)

**None.** All 15 ratified Q-decisions from Phase 0 §13 remain sound in light of REUSE findings:
- Q8 (persona matching) reinforced by F2 (voice_persona_helpers `display_name_for` reuse)
- Q4 (24h rotation) reinforced by F3 (canonical daemon pattern)
- Q6b (sync/async naming) reinforced by F4 (`notify_user_sync`/`async` precedent)
- Phase 0 §10 deviation D1 (`commons_ask_async` polling-mode) reinforced by F12 (Phase 3 injection target confirmed)

### Plan revisions triggered by REUSE

These flow into §4 (file touchpoints), §6 (sequencing), and §9 (risks) at code-write time, not pre-emptively here:

- **§4**: NEW-files LOC estimates can shrink: `commons_store.py` ~150 → ~110 (frontmatter + append helpers reused); `commons_persona_matcher.py` ~80 → ~30 + import; `commons_archival.py` ~100 → ~50 (daemon scaffold templated)
- **§9 risk table**: Add explicit fcntl-divergence note citing `session_bridge.py:1022-1026`
- **§6**: No sequencing change needed — REUSE doesn't move steps around

These will be folded in via the Pass 1 / Pass 2 application loops, not now (per Gate 1: don't pre-emptively apply structural changes outside the §11 table).

---

## 12. Pass 1 Fitness — to be filled by review pipeline

[Empty — populated by Pass 1 walk]

## 13. Pass 2 Adversarial — to be filled by review pipeline

[Empty — populated by Pass 2 walk]

---

## 14. Cross-references

- **Phase 0 design + ratification**: `01-design.md` (this directory)
- **Per-session voice personas** (matcher dependency): `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md`
- **Conv-mode listener-injection pattern** (the Phase 3 wiring target): `src/rnd/v0.1.7/2026.05.05-conv-mode-self-exit-signal-gap/`
- **Notification API reference**: `src/docs/notification-api.md`
- **Path management mandate** (`cu.get_project_root()`): `~/.claude/CLAUDE.md` § PATH MANAGEMENT
- **Test ownership mandate** (Claude owns testing pyramid): `~/.claude/CLAUDE.md` § TESTING & INCREMENTAL DEVELOPMENT
- **Testing venues** (`:7999` vs `:8000` rubric): `CLAUDE.md` § TESTING VENUES
- **Plan review skill**: `~/.claude/skills/plan-review/SKILL.md` — the canonical 3-step pipeline (REUSE → Pass 1 Fitness → Pass 2 Adversarial)

---

## 15. Status and next step

This is a Phase 1 code-execution plan in **DRAFT** status. **Per documentation-stops-at-doc protocol, no code is written before plan-review completes.**

### Next steps (user-directed)

1. User reviews this draft.
2. User invokes the `/plan-review` skill (or asks Tiberius to invoke it) — REUSE pass first.
3. REUSE findings ratified → applied to §11 above → user gate passed → proceed to Pass 1.
4. Pass 1 Fitness findings ratified → applied to §12 + plan revisions → user gate passed → proceed to Pass 2.
5. Pass 2 Adversarial findings ratified → applied to §13 + plan revisions → user gate passed → plan is **APPROVED for code-writing**.
6. Implementation proceeds per §5 sequencing.

**Pre-exit self-audit** (per memory `feedback_plan_self_audit_against_memory.md`):
- ✅ No CoSA git operations from this plan (Phase 1 is parent-Lupin only per §4 file touchpoints)
- ✅ Tests parameterize via `LUPIN_API_URL` env var pattern (not applicable — Phase 1 has no HTTP tests)
- ✅ `cu.get_project_root()` used for all path operations (§7 storage path is RELATIVE; combine at runtime)
- ✅ No defensive `getattr()` chains (matcher uses explicit attribute access)
- ✅ No backward-compat migration code (drop+recreate for any local-store evolution)
- ✅ No GPU usage anywhere in Phase 1
- ✅ No Flask anywhere
- ✅ Test scope routed per §TESTING VENUES (all Phase 1 tests are `:7999` AI-discretionary; explained in §6)
- ✅ Naming follows project convention (sync/async suffix per Q6b ratification)
- ✅ Q1b reserved-set seeding (broadcast-acks + presence + system-events) reflected in AC2
- ✅ Documentation-stops-at-doc honored (this doc is the deliverable; no code yet)
- ✅ Phase 0 deviations called out explicitly in §10 (only D1 deviation: ask_async polling-mode in Phase 1)
