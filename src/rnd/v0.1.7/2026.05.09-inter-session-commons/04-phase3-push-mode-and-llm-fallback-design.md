# Phase 3 — Push-Mode `ask_async` + LLM Fallback for Persona Matcher

| Field | Value |
|---|---|
| **Initiative** | Inter-Session Commons — Phase 3 (out-of-band push for ask_async + LLM-disambiguated persona matching) |
| **Doc-set started** | 2026-05-12 |
| **Branch** | `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe` (or v0.1.8 if Phase 3 slips past cut) |
| **Status** | 🟢 **APPROVED FOR CODE-WRITE 2026-05-12** — All 4 plan-review passes CLOSED (Pass 0 + REUSE + Pass 1 Fitness + Pass 2 Adversarial). User-authorized 2026-05-12. Implementation begins per §5's 9-step sequence; AI executes the §6 Testing Ownership Mandate tiers at each step. |
| **Prereq closures** | Phase 1 ✅ (2026-05-11), Phase 2 ✅ (2026-05-12 — see [`92-phase2-closure.md`](92-phase2-closure.md)) |

---

## 1. Scope

Two work items, both already declared as deferred at the close of earlier phases:

### Item A — `commons_ask_async` polling-mode → push-mode upgrade (D1 from Phase 1)

**Current state (Phase 1)**: `lupin_mcp.commons_ask.ask_async(...)` returns immediately with a `{question_id, posted_ts}` dict. Callers detect answers by polling `commons_read(topic, since=...)` and filtering for entries whose `metadata.in_reply_to == question_id`.

**Phase 3 target state**: Answers arrive at the asking session as `<system-reminder>` injections (push) instead of requiring polling. The MCP tool signature stays stable — callers' code does not change; the difference is on the wire.

**Prior-art template** (already mapped in `00-index.md` F12): `cosa/rest/routers/conversation_mode.py:195-278` exit-reminder injection. Same pattern: server-side daemon detects condition, pushes `user_initiated_message` notification with `title="action:..."`, listener `_handle_action()` dispatches.

### Item B — LLM-fallback wiring for `commons_persona_matcher.disambiguate_via_llm()` stub

**Current state (Phase 1)**: `lupin_mcp.commons_persona_matcher.disambiguate_via_llm()` is a stub returning `None`. The mechanical matcher handles case-insensitive + punctuation/space-tolerant exact matching; ambiguous cases (e.g., "@m" matching both Maria and Mr. Radio) fall through to the stub and return no match.

**Phase 3 target state**: Stub calls `Llm(model_name=...)` with a structured prompt and parses the response to pick one persona. Falls back to "no match" if the LLM errors or returns a non-canonical name.

**Open question** ✅ **Resolved Pass 0**: Q5 ratified local PHI-4 first via `LlmClientFactory` + `BaseXMLModel`; Haiku 4.5 fallback wired-but-stubbed (`NotImplementedError`). Zero per-call API cost when PHI-4 succeeds.

---

## 2. Pass 0 ratifications (✅ CLOSED 2026-05-12)

**Summary of 8 ratified Q-decisions**:

| Q | Decision | One-liner |
|---|---|---|
| Q1 | Hybrid base class | Refactor `CommonsAckWatcher` → `CommonsTopicWatcher` base + `Ack` / `Question` subclasses. Refactor lands as Phase 3 step 1; all 26 ack-watcher tests must re-verify GREEN first. |
| Q2 | Only outstanding (dynamic) | `ask_async()` registers `(topic, question_id)` with the watcher; unregister on answer-arrived or TTL. Cross-process registration primitive (HTTP vs shared-file) deferred to REUSE pass. |
| Q3 | `COMMONS PEER REPLY` framing | `<system-reminder>` body: `"COMMONS PEER REPLY (question_id X, from @PersonaName):\n\n[body]"`. Honors INTRA-AI principle. |
| Q4 | 1-hour default TTL + per-call override | INI `commons question tracker ttl seconds = 3600`; MCP override `ask_async(..., ttl_seconds=N)`. |
| Q5 | Local PHI-4 first → STUBBED Haiku fallback | Primary path: PHI-4 via `LlmClientFactory` + `BaseXMLModel` Pydantic XML. Haiku 4.5 wired but stubbed (`NotImplementedError` / `return None`). |
| Q6 | No cache | YAGNI; pure additive change later if telemetry shows >5% hit rate. |
| Q7 | Configurable timeout, 5s default | INI `commons llm disambiguator timeout seconds = 5`. |
| Q8 | In-memory tracker, lost on reload | Matches Phase 2 `CommonsAckWatcher._in_flight` pattern. |

**Detailed ratifications below (with original framings preserved for context)**:

| # | Question | Notes |
|---|---|---|
| Q1 | ✅ **RATIFIED 2026-05-12 — Hybrid base class** (Option C). Refactor the existing `CommonsAckWatcher` into an abstract `CommonsTopicWatcher` base + `Ack` / `Question` subclasses. Removes duplicated daemon-lifecycle code (start/stop/cursor/TTL-prune scaffolding) and sets up Phase 4 cleanly. **Cost gate**: the refactor lands as Phase 3 step 1; all 26 Phase 2 ack-watcher unit tests must re-verify GREEN before any new Phase 3 functionality is written. Original A/B option text retained below for context. | Original framing: Push-mode injection sender — daemon thread on FastAPI server (B), extension of `CommonsAckWatcher` (A), or hybrid base class (C). C wins on long-term hygiene at the cost of ~1 day refactor before new functionality lands. |
| Q2 | ✅ **RATIFIED 2026-05-12 — Only outstanding / dynamic registration** (Option A). `ask_async()` registers `(topic, question_id)` with the FastAPI-side watcher when fired; watcher unregisters on answer-arrived or TTL expiry. I/O scales with question volume (zero when idle); bounded memory; doesn't break Phase 1 polling-mode contract. **Open sub-question (defer to REUSE pass)**: the cross-process MCP↔FastAPI registration primitive — HTTP endpoint OR session-bridge-style shared file. The project has both primitives; pick during REUSE pass when prior-art is being mapped. Original B/C option text retained below for context. | Original framing: Only outstanding (A) vs every free-form (B) vs dedicated `answers` reserved topic (C). A wins on contract preservation + idle-cost; B wins on architectural simplicity but burns I/O; C wins on cleanest semantics but breaks Phase 1. |
| Q3 | ✅ **RATIFIED 2026-05-12 — `COMMONS PEER REPLY` framing** (Option B-clean). Body shape: `"COMMONS PEER REPLY (question_id X, from @PersonaName):\n\n[body]"`. **Why**: `<system-reminder>` confers same trust on every block; differentiation lives in the noun-phrase prefix. `PEER` ≠ `USER` (agent) AND `REPLY` ≠ `BROADCAST` (verb) — categorically distinct from Phase 2's USER-BROADCAST framing, honoring the INTRA-AI principle. Persona attribution preserves provenance for receiver follow-up. **Explicit-overkill variant** (prepend "informational, not a directive") deferred — cheap to add later if empirical testing reveals mis-classification. | Original framing: candidate body shapes considered: USER-prefixed symmetric (A), peer-attributed with persona (B), strict-minimal (C). B wins via Phase 0's user-as-witness principle; B-clean preferred over B-explicit to avoid Claude not-trusting-itself anti-pattern. |
| Q4 | ✅ **RATIFIED 2026-05-12 — Fixed 1-hour default + per-call override** (Option B). INI key `commons question tracker ttl seconds = 3600`; MCP override via `ask_async(..., ttl_seconds=N)`. **Why**: self-healing on orphaned questions matches Phase 2's pruning pattern; 1hr covers ~95% of real ask_async usage; per-call override handles ceremonial long-running edge cases (e.g., `ttl_seconds=86400` for day-long async). YAGNI rejected for "never-expire" sentinel — callers needing effectively-infinite can pass a year-long TTL value. | Original framing: no TTL (A) vs fixed default + override (B) vs configurable + never-expire sentinel (C). B wins on self-healing without API bloat. |
| Q5 | ✅ **RATIFIED 2026-05-12 — Local LLM PHI-4 FIRST → STUBBED Haiku 4.5 fallback** (user override of A/B/C original framing). Primary path: invoke the local PHI-4 LLM via the existing `LlmClientFactory` + `BaseXMLModel` Pydantic XML-serialization pattern (canonical example at `src/cosa/agents/runtime_argument_expeditor/xml_models.py`; other examples in `calculator/`, `notification_proxy/`, `prediction_engine/`). Haiku 4.5 escalation is **wired but stubbed** — function exists and is routed to on local-LLM-failure, but the implementation is a `NotImplementedError` / `return None` placeholder, deferred to a future phase. INI key `commons llm disambiguator fallback model name = claude-haiku-4-5` lands now for forward-compat. **At implementation time**: consult `runtime_argument_expeditor/xml_models.py` for `ClassVar[List[str]]` typing + `field_validator("*", mode="before")` empty-tag coercion. | Original framing: Haiku-first (A) / Sonnet (B) / tiered Haiku→Sonnet (C). User pivoted: local PHI-4 first via existing project XML-prompt-and-response pattern; Haiku stubbed for future fallback. The cost+latency profile is even better than Haiku-first (zero per-call API cost when PHI-4 succeeds). |
| Q6 | ✅ **RATIFIED 2026-05-12 — No cache** (Option A). Disambiguation fires only on mechanical-matcher misses (already rare); cache hits require SAME ambiguous reference twice per session (rarer); PHI-4 is local + fast with no API cost to amortize per Q5. Cache complexity for theoretical savings = textbook YAGNI. **Pure additive change later** if production telemetry shows >5% cache-hit rate. | Original framing: no cache (A) vs LRU (B) vs TTL (C) vs cache-only-on-fallback (D). A wins on YAGNI grounds. Stale-cache risk in B is a real footgun if added without invalidation discipline. |
| Q7 | ✅ **RATIFIED 2026-05-12 — Configurable INI key, 5s default** (Option C). INI: `commons llm disambiguator timeout seconds = 5`. **Why**: PHI-4 local inference reliably <1s for small prompts; 5s = 10× headroom for cold-start / GPU contention; single key now, splittable later when Haiku unstubs. Worst-case 2-line broadcast latency = 10s, recoverable via INI tunable. Aligns with Phase 2's INI-driven-tunable pattern. | Original framing: short fixed 3s (A) vs medium fixed 10s (B) vs configurable INI (C) vs tiered per-tier (D). C wins on tunability without YAGNI risk of D's pre-split-for-Haiku. |
| Q8 | ✅ **RATIFIED 2026-05-12 — In-memory only, lost on reload** (Option A). Matches Phase 2's `CommonsAckWatcher._in_flight` pattern exactly. **Why**: consistency with Phase 2 is load-bearing — hybrid base class (per Q1) makes the choice for free. Hot-reload is `:7999` dev-time concern; production rarely restarts. If Q2's deferred sub-question picks the shared-file registration primitive, the registry persists across reload essentially for free anyway. Worst case = orphaned question's answer expires unread = papercut, not a correctness bug. | Original framing: in-memory (A) vs persist-to-file (B) vs persist-as-reserved-topic (C). A wins via Phase 2 consistency + YAGNI on cross-process visibility. |

---

## 3. Prior-art map (REUSE pass — ✅ CLOSED 2026-05-12)

### Confirmed F-mappings (file:line verified)

| # | Plan component | Verdict | Prior art (file:line) |
|---|---|---|---|
| F1 | Push-mode answer dispatcher (Q1 hybrid refactor target) | extend-existing | `cosa/rest/commons_ack_watcher.py:42-221` — full lifecycle scaffolding intact (`start`/`stop`/`_initialize_last_seen_ts`/`_run_loop`/`tick`/`_prune_expired_locked`); becomes `CommonsTopicWatcher` base + `Ack` / `Question` subclasses per Q1. **Template-method pattern per F13-fit**: base owns protected `_register(record_id, user_id, ttl_seconds)` / `_unregister(record_id)`; subclasses expose domain-named public methods (`register_broadcast` keeps Phase 2 naming for 26-test compat; `register_question` adds `inject_fn`). |
| F2 | `<system-reminder>` injection on listener side | reuse-as-is | `lupin_cli/claude_code/hooks/lib/cc_notification_listener.py:281-302` `_handle_action()` dispatcher — current branches: `set_session_topic` / `exit_conversation_mode` / `broadcast_received`. **F11 below** locks in the new verb. |
| F3 | Outstanding-question tracker (in-flight dict) | extend-existing | `cosa/rest/commons_ack_watcher.py:42-53` `_InFlightEntry` — mirror with `_InFlightQuestion` carrying `(asker_session_id, asker_persona, topic, ttl_seconds, expires_at_monotonic, user_id, last_seen_ts, inject_fn)`. **`user_id`** stamped at register for F4-fit same-user-scoping; **`last_seen_ts`** per-question cursor per F3-fit (scales correctly across N registered topics); **`inject_fn`** is the callback closure for dispatching `<system-reminder>` injections back to the asker. |
| ~~F4 (original)~~ | ~~LLM call via `cosa.agents.llm.py::Llm`~~ | ~~reuse-as-is~~ | **SUPERSEDED by C1 below — see F4-REVISED.** |
| **F4-REVISED** | LLM call via `LlmClientFactory` (per C1 pivot + Q5 ratification) | reuse-as-is | `cosa/agents/llm_client_factory.py:17` — pattern: `factory.get_client(spec_key, debug=..., verbose=...)`. Canonical call template: `runtime_argument_expeditor/expeditor.py:82, 167-168`. Other call sites: `notification_proxy/verification.py:69`, `notification_proxy/strategies/llm_script_matcher.py:112`. |
| F5 | XML-prompt response parser | reuse-as-is | `cosa/agents/io_models/utils/util_xml_pydantic.py:81` `BaseXMLModel`; canonical examples: `runtime_argument_expeditor/xml_models.py:17` `ExpeditorResponse` + `:219` `ArgConfirmationResponse`, both with `@field_validator("*", mode="before")` at lines 49, 240 |
| F6 | INI key + paired splainer | reuse-as-is | Phase 1+2 commons keys (~9 keys total); per CLAUDE.md splainer-pairing mandate |
| F7 | Unit-test fixtures | reuse-as-is | `tempfile.TemporaryDirectory()` + `mp.spawn` patterns from `test_commons_two_session_roundtrip.py` (Phase 1) + `test_broadcast_two_session_e2e.py` (Phase 2 step 9) |
| F8 | E2E smoke template | reuse-as-is | `test_broadcast_two_session_e2e.py` — DI-injected `execute_*()` + mock listener subprocesses via `mp.spawn` |

### New F-findings (surfaced during REUSE walk)

| # | Plan component | Verdict | Prior art (file:line) |
|---|---|---|---|
| F9 | `BaseXMLModel` XML round-trip (`from_xml()` + `to_xml()`) | reuse-as-is | `util_xml_pydantic.py:128` `from_xml()` + `:245` `to_xml()`; XML cleaning via `remove_xml_escapes()` at `:33` |
| F10 | LLM-call-with-XML-response template (structurally closest match) | reuse-as-is | `cosa/agents/notification_proxy/strategies/llm_script_matcher.py` — pattern: build prompt, invoke LlmClient, parse XML response into Pydantic model, return canonical name match. Direct template for `commons_llm_disambiguator.py`. |
| F11 | New listener action verb | extend-existing | Phase 2's `"broadcast_received"` precedent (cc_notification_listener.py:299). **Locked in by Pass 1 (no rename)**: `action == "commons_answer_received"` for the 4th elif slot. |
| F12 | `main.py` lifespan() wiring | extend-existing | Phase 2 commons singletons block at `fastapi_app/main.py:527+` already initializes `commons_ack_watcher` + `commons_store` + `commons_rate_limiter`. Phase 3 extends the SAME block — instantiate `CommonsQuestionWatcher` (Q1 subclass) + start it + register the new `POST /api/commons/register-question` endpoint. No new lifespan() section. |

### Corrections (Cn — ratified during REUSE walk, applied above)

| # | Correction | Resolution |
|---|---|---|
| **C1** | **F4 PIVOT** — original mapping to `cosa.agents.llm::Llm` is stale. Actual primitive is `LlmClientFactory`. | Replaced F4 row with F4-REVISED above; original kept struck-through for audit trail. Canonical call template `runtime_argument_expeditor/expeditor.py:82, 167-168` cited. |
| **C2** | **NEW INI key required** — adopt pattern `llm spec key for commons persona disambiguator = Deepily/kaitchup/Phi-4-AutoRound-GPTQ-4bit` mirroring `expeditor.py:79` (`config_mgr.get("llm spec key for runtime argument expeditor")`). Paired splainer required. | Added to §4 MODIFIED files: `lupin-app.ini` +1 key, splainer +1 entry. Pass 0 + C2 total: **4** keys. **Pass 1 added 3 more** (F1-fit push toggle + F2-fit base URL + F5-fit confidence floor) → **7 new INI keys total** for Phase 3. |
| **C3** | **Q2 sub-question RESOLVED via REUSE** — HTTP register endpoint wins. Shared-file approach would require a NEW primitive (`session_bridge.py:47 SESSION_DIR` is session-focused, not question-tracking-focused). HTTP path has directly-applicable template at `conversation_mode.py:116-`. | New endpoint `POST /api/commons/register-question` (and matching `DELETE /api/commons/register-question/{question_id}`) added to §4 NEW endpoints. MCP-side `ask_async()` fires the register HTTP call when push mode is enabled. |

### Pass 2 Adversarial ratifications (✅ CLOSED 2026-05-12)

| # | Severity | Threat | Decision |
|---|---|---|---|
| **T1** | 🔴 | Malformed `in_reply_to` correlation | Strict `isinstance(str)` + `TOPIC_RE.match` + `len ≤ 64` + dispatch-once idempotency keyed `(question_id, entry_id)` on `_dispatched_set` (defense in depth) |
| **T2** | 🔴 | LLM prompt injection via `ambiguous_reference` | Pydantic `@field_validator(mode="before")` rejects control chars + XML-escapes `<` `>` `&`; output `matched_persona` whitelist (must be in `active_personas`); Pydantic `confidence: Field(ge=0.0, le=1.0)` |
| **T3** | 🔴 | Outstanding-question DoS via unbounded tracker | Per-user cap (`commons question tracker per user max = 50`) + global cap (`commons question tracker global max = 1000`) + reuse existing `commons_rate_limiter`; HTTP 429 on cap-hit |
| **T4** | 🔴 | Stale answer push after server restart | `_InFlightQuestion.last_seen_ts = time.time()` on re-register; pre-restart entries structurally skipped; Phase 1 polling fallback (F1-fit) covers the restart-gap window |
| **T5** | 🟡 | Cross-user enumeration via 404 body or timing | Uniform 404 body `{"detail": "question_id not found or not owned by caller"}` for both not-found AND user-mismatch; single internal code path; no log differentiation |
| **T6** | 🟡 | Register-during-unregister race | Mirror Phase 2 `commons_ack_watcher.py:96-115, 207-216` — register/unregister/prune wrap `with self._lock:`; tick() does lookup under lock, captures domain payload, releases lock, dispatches `inject_fn` OUTSIDE lock |
| **T7** | 🟡 | Confidence-floor bypass via PHI-4 manipulation | Keep F5-fit 0.7 default; add INI-toggleable decision audit log (`commons llm disambiguator log decisions = True`) for empirical floor tuning |
| **T8** | 🟢 | `inject_fn` callback failure modes | Mirror Phase 2 `commons_ack_watcher.py:231-249` — wrap `inject_fn(answer)` in try-except + log + continue tick batch; failed dispatches do not block subsequent dispatches in the same tick |

### Q1 refactor sizing note (informational)

The `CommonsAckWatcher` → `CommonsTopicWatcher` base + `Ack` / `Question` subclasses refactor has clean grep-able boundaries: **~20% rename + 80% extract-method-to-base**. The 26 existing ack-watcher unit tests should re-verify GREEN unchanged because the public API of the `Ack` subclass is identical to today's `CommonsAckWatcher`. Pass 1 will lock in subclass naming.

---

## 4. Anticipated file touchpoints

### NEW files (post-REUSE)

| Path | Approx LOC | Purpose |
|---|---|---|
| `src/cosa/rest/commons_topic_watcher.py` (NEW base) | ~150 | Abstract `CommonsTopicWatcher` base — lifecycle scaffolding extracted from current `commons_ack_watcher.py` per Q1 hybrid refactor |
| `src/cosa/rest/commons_question_watcher.py` | ~120 | `CommonsQuestionWatcher(CommonsTopicWatcher)` subclass — tails registered topics for `in_reply_to` correlations + pushes `commons_answer_received` notifications. `_InFlightQuestion` tracker (mirror of `_InFlightEntry`). |
| `src/lupin_mcp/commons_llm_disambiguator.py` | ~100 | PHI-4 disambiguator using `LlmClientFactory.get_client(spec_key)` + `BaseXMLModel` Pydantic XML round-trip. Templated after `notification_proxy/strategies/llm_script_matcher.py` per F10. |
| `src/lupin_mcp/commons_xml_models.py` | ~50 | `BaseXMLModel` subclasses for disambiguation prompt/response (e.g. `PersonaDisambiguationResponse` with `<persona>NAME</persona>` field). Follows `runtime_argument_expeditor/xml_models.py` template. |
| `src/tests/unit/commons/test_commons_topic_watcher.py` | ~80 | Base class tests (lifecycle + cursor + TTL prune — currently in `test_commons_ack_watcher.py`) |
| `src/tests/unit/commons/test_commons_question_watcher.py` | ~120 | QuestionSubclass tests (registration / unregister / `in_reply_to` dispatch / TTL prune / cross-session correlation) |
| `src/tests/unit/commons/test_commons_llm_disambiguator.py` | ~100 | LLM disambiguator unit tests with mocked `LlmClientFactory` (success / no-match / parse-error / timeout → stubbed Haiku fallback) |
| `src/tests/unit/commons/test_commons_xml_models.py` | ~40 | XML round-trip tests for `PersonaDisambiguationResponse` |
| `src/tests/smoke/test_ask_async_push_e2e.py` | ~200 | **AC13** — 2-session in-process E2E on `:7999` via `TestClient(app)`: hits `POST /api/commons/register-question` (asserts 201/409/400 codes + JSON shape), then A posts `ask_async`, B reads + answers, watcher tick() dispatches push, A receives `<system-reminder>` injection. Per-F11-fit: HTTP-layer coverage via `TestClient` (in-process FastAPI router + auth dep + Pydantic validation). |
| `src/tests/integration/test_commons_ask_async_push_integration.py` | ~250 | **AC15** (Rick F11-fit amendment) — real end-to-end on `:8000` monopolize mode. Two `mp.spawn` mock-CC-listener subprocesses + actual HTTP register call via `requests.post` against live `:8000`; covers full network round-trip including FastAPI lifespan, JWT/API-key auth path, watcher daemon tick, listener `_handle_action` dispatch. Mirrors Phase 2 Step 11 ts-436237f6 pattern but at HTTP layer (no UI scope per §7). Scheduled via `POST /api/test-suite/submit` with user-confirmed `scheduled_at`. |

### MODIFIED files (post-REUSE)

| Path | Change | Approx LOC delta |
|---|---|---|
| `src/cosa/rest/commons_ack_watcher.py` | Refactor: extract lifecycle scaffolding into `CommonsTopicWatcher` base; this file shrinks to just the `CommonsAckWatcher(CommonsTopicWatcher)` subclass | -80 / +40 |
| `src/tests/unit/commons/test_commons_ack_watcher.py` | Re-verify 26 tests GREEN after refactor; possibly split lifecycle tests into `test_commons_topic_watcher.py` | re-verify only |
| `src/lupin_mcp/commons_persona_matcher.py` | Wire `disambiguate_via_llm()` body to `commons_llm_disambiguator.disambiguate()` | +5 |
| `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` | 4th `elif action == "commons_answer_received"` branch + new `_handle_commons_answer_received()` method (per F11 — may rename in Pass 1) | +40 |
| `src/lupin_mcp/commons_ask.py` | Phase 1 `ask_async` adds optional push-mode: when enabled, fires HTTP `POST /api/commons/register-question` to register `(topic, question_id, asker_session_id, ttl_seconds)` with the FastAPI watcher | +30 |
| `src/cosa/rest/routers/commons.py` | Add `POST /api/commons/register-question` + `DELETE /api/commons/register-question/{question_id}` (per C3 Q2 sub-question resolution). Pure-logic helpers in 100% coverage gate per existing AC12 pattern. | +80 |
| `src/fastapi_app/main.py` | Extend Phase 2 commons singletons block at `:527+` — instantiate `CommonsQuestionWatcher` + start it alongside `CommonsAckWatcher`. No new lifespan() section per F12. | +10 |
| `src/conf/lupin-app.ini` + splainer | **10 new keys** (Pass 0 + REUSE + Pass 1 + Pass 2): `commons question tracker ttl seconds = 3600` (Q4), `llm spec key for commons persona disambiguator = Deepily/kaitchup/Phi-4-AutoRound-GPTQ-4bit` (C2), `commons llm disambiguator fallback model name = claude-haiku-4-5` (Q5), `commons llm disambiguator timeout seconds = 5` (Q7), `commons ask async push mode enabled = True` (F1-fit), `commons api base url = http://localhost:7999` (F2-fit), `commons llm disambiguator confidence floor = 0.7` (F5-fit), `commons question tracker per user max = 50` (T3), `commons question tracker global max = 1000` (T3), `commons llm disambiguator log decisions = True` (T7). Plus 10 paired splainer entries. | +20 |
| `src/cosa/rest/routers/notifications.py` | Add `"commons_answer_received"` to `valid_types` list at L359-363 (alongside Phase 2's `commons_broadcast_ack`) | +1 |

### Files NOT touched

- UI (`broadcast-panel.js` etc.) — Phase 3 is INTRA-AI per the Phase 0 §13 architectural principle "commons is INTRA-AI". No user-facing surface changes.
- Phase 1 + Phase 2 modules — additive only.

---

## 5. Sequencing

| Phase | Status | Closure date |
|---|---|---|
| Pass 0 — Ratify Q1-Q8 via `ask_multiple_choice` / `ask_yes_no` | ✅ CLOSED | 2026-05-12 |
| REUSE pass — walk §3 prior-art map, file corrections | ✅ CLOSED | 2026-05-12 |
| Pass 1 Fitness — 13 findings ratified + Rick's AC15 amendment | ✅ CLOSED | 2026-05-12 |
| Pydantic-native validation retrofit (AC1/AC2/AC6) | ✅ CLOSED | 2026-05-12 |
| Pass 2 Adversarial — 8 threats T1-T8 ratified | ✅ CLOSED | 2026-05-12 |
| **AI-executed test pyramid** (`py_compile` → unit → smoke → integration → scheduled `:8000` E2E) per §6 Testing Ownership Mandate | ⏭ **Next gate (AI runs, reports tabular results)** | — |
| Code-write start (status flips to APPROVED FOR CODE-WRITE) | ⏸ Blocked on test pyramid + user authorization | — |

### Implementation steps (post-APPROVED FOR CODE-WRITE)

Locked at 9 steps based on the 9 NEW + 8 MODIFIED file count from §4:

1. **Q1 refactor pre-flight** — extract `CommonsTopicWatcher` base from current `CommonsAckWatcher`; protected `_register` / `_unregister` per F13-fit; re-verify 26 existing ack-watcher tests GREEN unchanged.
2. **INI keys + splainer** — land all 7 new keys + 7 paired splainer entries; verify `ConfigurationManager.get()` resolves each.
3. **`CommonsQuestionWatcher` subclass** — extend base; `register_question(qid, uid, ttl, inject_fn, last_seen_ts=time.time())`; per-topic cursor (F3-fit); user-scoping field (F4-fit); atomic-or-`ValueError` (F8-fit); TTL bounds enforced at base register (F6-fit).
4. **`commons_xml_models.py`** — `PersonaDisambiguationRequest` + `PersonaDisambiguationResponse` BaseXMLModel classes per §8 envelope.
5. **`commons_llm_disambiguator.py`** — PHI-4 via `LlmClientFactory.get_client(spec_key)` + XML round-trip + confidence-floor thresholding; stubbed Haiku fallback raises `NotImplementedError`.
6. **Router endpoints** — `POST/DELETE /api/commons/register-question` in `routers/commons.py` with full validation (TTL bounds + topic regex + same-user-scoping + atomic 409); 404-on-user-mismatch.
7. **MCP-side `commons_ask.py`** — `ask_async()` reads `commons api base url` from INI; fires `POST /api/commons/register-question` when push-mode enabled; try-except + warning log + polling fallback on failure; `ask_sync()` untouched.
8. **Listener wiring** — 4th `elif action == "commons_answer_received"` branch in `cc_notification_listener.py` + `_handle_commons_answer_received()` reading stamped `persona_name` from answer entry (F9-fit); `valid_types` list extension in `routers/notifications.py`.
9. **Tests + lifespan** — unit (4 modules), smoke (AC13 TestClient), integration (AC15 scheduled `:8000`); extend `main.py:527+` lifespan to instantiate + start `CommonsQuestionWatcher`.

---

## 6. Acceptance Criteria (Pass 1 Fitness + Pass 2 Adversarial — derived, ratified, applied)

### Testing Ownership Mandate

**Per CLAUDE.local.md §"THE USER IS NEVER A TESTER" + `feedback_comprehensive_automated_testing`**:

The AI executes every verification tier listed below. The user is the **designer + end-user**, NEVER the tester. No code-write authorization happens until every applicable tier has run AND passed under the AI's execution.

**Tier execution responsibility table**:

| Tier | Executor | Venue | When |
|---|---|---|---|
| `py_compile` on all NEW + MODIFIED `.py` files | AI | local | After every file edit |
| Import-chain check (AC11 explicit list) | AI | local | After step-2 INI key + step-9 lifespan |
| Unit tests (`src/tests/unit/commons/*.py`) — AC8 26-test re-verify + AC11/12 100% coverage + AC16-AC20 Pass 2 tests | AI | `:7999` (in-process, AI-discretionary) | After steps 1, 3, 4, 5, 8 |
| Smoke tests (`src/tests/smoke/test_ask_async_push_e2e.py`) — AC13 TestClient | AI | `:7999` (in-process, AI-discretionary) | After step 9 |
| Router-registration smoke — AC14 | AI | `:7999` (in-process, AI-discretionary) | After step 6 |
| Integration E2E (`src/tests/integration/test_commons_ask_async_push_integration.py`) — AC15 | AI | **`:8000` (scheduled monopolize)** via `POST /api/test-suite/submit` with user-confirmed `scheduled_at` | After all unit + smoke tiers PASS |
| Coverage gate (`c8` / `pytest --cov`) — AC12 100% lines + branches + functions | AI | local | Mid-step-9 + at code-write closure |

**Status flip rule**: `Pass 2 CLOSED` → `APPROVED FOR CODE-WRITE` requires:
1. ALL applicable tiers above have been EXECUTED by the AI (not described, not planned — executed).
2. ALL tier results have been REPORTED in tabular form (pass/fail per tier) to the user.
3. The user has explicitly authorized the flip (this gate cannot be inferred from silence).

Tier-1 (`py_compile` + import-chain + unit tests) and Tier-2 (`:7999` smoke) are AI-discretionary per `feedback_small_ad_hoc_runs_go_to_7999`. Tier-3 (`:8000` integration E2E) requires user slot-confirmation per `feedback_test_server_monopolize_mode` — the user-ask is **slot availability**, NOT budget approval and NOT tester-duty deferral.

If a verification tier genuinely cannot be automated (subjective UX feel, external-service gating), the AI states this **explicitly with the specific reason** — silent deferral to the user is prohibited.

---

### AC table



| # | EXECUTOR | Acceptance Criterion |
|---|---|---|
| **AC1** | AI | `POST /api/commons/register-question` validates body via **Pydantic-native `RegisterQuestionRequest(BaseModel)`** (per `feedback_pydantic_native_validation`): `topic: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")` (F7-fit), `question_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")` (T1), `ttl_seconds: int = Field(default=3600, gt=0, le=604800)` (F6-fit). FastAPI auto-returns **422** on field-validation failure. `authenticated_user_id` from `Annotated[str, Depends(require_api_key_or_jwt)]` (F4-fit). Rate-limits via existing `commons_rate_limiter`. **Cap checks (T3)**: register raises `CapExceededError` if `len(per_user_in_flight) >= commons question tracker per user max` OR `len(_in_flight) >= commons question tracker global max`; router translates to **HTTP 429**. `CommonsQuestionWatcher.register_question()` is **lock-guarded** (`with self._lock:` — T6) atomic insert-or-`ValueError` (F8-fit, T9 mirror); router translates `ValueError` to **HTTP 409** (application-level invariant). Stamps `user_id = authenticated_user_id` + `last_seen_ts = time.time()` (T4) on `_InFlightQuestion`. |
| **AC2** | AI | `DELETE /api/commons/register-question/{question_id}` — `question_id: str = Path(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")` Pydantic-validates path param (422 on malformed). Returns 204 on success; **uniform 404 with body `{"detail": "question_id not found or not owned by caller"}` for both not-found AND `record.user_id != authenticated_user_id` cases (F4-fit + T5)** — single internal code path, no log differentiation, prevents enumeration via body or timing side-channel. Idempotent. **Lock-guarded** (`with self._lock:` — T6) mutation. |
| **AC3** | AI | `CommonsQuestionWatcher.tick()` polls each registered `_InFlightQuestion`'s topic using that question's own `last_seen_ts` cursor (F3-fit per-topic cursor — each question advances independently). For each new entry: **(T1 validation)** verify `isinstance(in_reply_to, str)` + `TOPIC_RE.match(in_reply_to)` + `len(in_reply_to) ≤ 64` (skip + warn on violation); **(T1 idempotency)** check `(question_id, entry_id) not in self._dispatched_set` (skip silently on dup); **(T6 lock-guarded lookup)** acquire `self._lock`, prune expired, lookup `inflight = self._in_flight.get(question_id)`, capture `inject_fn` reference, **release lock**, then call `inject_fn(answer)` **outside lock** (mirrors `commons_ack_watcher.py:207-216`); **(T8 dispatch isolation)** wrap `inject_fn` in try-except + log + continue tick batch (mirrors `commons_ack_watcher.py:231-249`). After successful dispatch: add `(question_id, entry_id)` to `_dispatched_set`. **(T4 re-register cursor)** when a question is re-registered post-restart, `last_seen_ts = time.time()` — pre-registration entries on the topic are structurally skipped (Phase 1 polling fallback covers any restart-gap answers per F1-fit). |
| **AC4** | AI | Listener `_handle_action("commons_answer_received", notif)` reads `entry['persona_name']` from the **stamped answer entry per Phase 1 immutability principle (F9-fit, NOT live lookup)**; builds `<system-reminder>` body as `"COMMONS PEER REPLY (question_id X, from @{entry['persona_name']}):\n\n[body]"` (Q3); injects via `_inject_via_tmux(wrap=False)`. |
| **AC5** | AI | `commons_ask.ask_async()` reads `commons api base url` from `ConfigurationManager` (F2-fit, env-var override inherited); when `commons ask async push mode enabled = True` (F1-fit default), fires `POST /api/commons/register-question`; on register failure (404 / connection error / timeout) logs a warning and silently falls back to polling-mode for that call (F1-fit Option A try-except). **`commons_ask.ask_sync()` is unaffected by push-mode and continues using its existing polling-loop wait mechanism (F10-fit).** |
| **AC6** | AI | `commons_llm_disambiguator.disambiguate(active_personas, ambiguous_reference, context=None)` constructs a **`PersonaDisambiguationRequest` BaseXMLModel** (per `feedback_pydantic_native_validation`) that Pydantic-validates inputs at instantiation: `ambiguous_reference: str = Field(..., min_length=1, max_length=256)`, `context: Optional[str] = Field(default=None, max_length=2048)`, plus `@field_validator("ambiguous_reference", "context", mode="before")` that rejects control chars and XML-escapes `<` `>` `&` (T2 sanitize-at-boundary). Serializes via `to_xml()`, invokes PHI-4 via `LlmClientFactory.get_client(config_mgr.get("llm spec key for commons persona disambiguator"))`, parses `PersonaDisambiguationResponse` via `BaseXMLModel.from_xml()`. **Output validation**: `matched_persona` must be in `active_personas` list (whitelist, T2) else returns None; applies `confidence < config_mgr.get("commons llm disambiguator confidence floor") → return None` rule (F5-fit). **(T7 decision audit log)** when `commons llm disambiguator log decisions = True`, emits a per-decision log record (debug-level `print()`) with: timestamp, sanitized `ambiguous_reference`, active personas count, `matched_persona`, `confidence`, returned value (after whitelist + floor). INI-toggleable for production cost-management. |
| **AC7** | AI | Haiku 4.5 fallback function exists at `commons_llm_disambiguator.py::_fallback_via_haiku()` + routed-to on PHI-4 timeout or parse-error; **raises `NotImplementedError("Haiku fallback stubbed for future phase")`** per Q5 ratification (wired-but-stubbed). |
| **AC8** | AI | **Hybrid refactor (Q1) using template-method pattern (F13-fit)**: `CommonsTopicWatcher` base has protected `_register(record_id, user_id, ttl_seconds)` / `_unregister(record_id)` (generic, **lock-guarded via `with self._lock:` — T6**). Subclass `CommonsAckWatcher.register_broadcast(bid, uid, expected_recipients)` calls `self._register(...)` + stores expected_recipients on `_InFlightEntry` (keeps Phase 2 naming for 26-test compat). Subclass `CommonsQuestionWatcher.register_question(qid, uid, ttl, inject_fn, last_seen_ts)` calls `self._register(...)` + stores inject_fn + last_seen_ts on `_InFlightQuestion`, plus owns the **T1 `_dispatched_set: Set[Tuple[str, str]]`** (cleared on `_unregister`) and **T3 per-user-count + global-count tracking** (`_register` checks caps before atomic insert). **All 26 existing ack-watcher unit tests re-verify GREEN unchanged** before any Phase 3 functionality lands. **tick() dispatch pattern** (T6): lookup under lock, capture domain payload, release lock, dispatch outside lock — mirrors `commons_ack_watcher.py:207-216`. |
| **AC9** | AI | **10 new INI keys** + 10 paired splainer entries (per §4): `commons question tracker ttl seconds`, `llm spec key for commons persona disambiguator`, `commons llm disambiguator fallback model name`, `commons llm disambiguator timeout seconds`, `commons ask async push mode enabled`, `commons api base url`, `commons llm disambiguator confidence floor`, **`commons question tracker per user max` (T3)**, **`commons question tracker global max` (T3)**, **`commons llm disambiguator log decisions` (T7)**. All addressable via `config_mgr.get()` + verified by smoke test. |
| **AC10** | AI | `src/cosa/rest/routers/notifications.py` `valid_types` list (L359-362) extended with `"commons_answer_received"` alongside Phase 2's `commons_broadcast_ack`. |
| **AC11** | AI | `py_compile` clean on all 4 NEW pure-logic modules + 1 NEW E2E test file. **Import-chain check explicitly verifies** `cosa.rest.commons_topic_watcher`, `cosa.rest.commons_question_watcher`, `cosa.rest.commons_llm_disambiguator`, `cosa.rest.commons_xml_models` all import cleanly (F12-fit explicit list). |
| **AC12** | AI | **100% lines + branches + functions** coverage via `c8` / `pytest --cov` on 4 NEW pure-logic modules: `commons_topic_watcher`, `commons_question_watcher`, `commons_llm_disambiguator`, `commons_xml_models`. Router endpoints follow Phase 2 split: pure-logic helpers 100%; endpoint integration coverage via AC13 + AC15. |
| **AC13** | AI | 2-session in-process E2E smoke (`src/tests/smoke/test_ask_async_push_e2e.py`) — **uses `TestClient(app)` to hit `POST /api/commons/register-question`** (asserts 201/409/400 response codes + JSON body shape at HTTP layer per F11-fit); then A posts `ask_async`, B reads + answers, watcher dispatches via A's mock `inject_fn`, the recorded `<system-reminder>` body is asserted to contain `"COMMONS PEER REPLY"` + the answer text + the stamped persona. Runs on `:7999` (in-process, no live server). |
| **AC14** | AI | Router-registration smoke confirms `POST /api/commons/register-question` + `DELETE /api/commons/register-question/{question_id}` appear in `app.routes` with `require_api_key_or_jwt` auth dep wired (analogous to Phase 2 Step 8 AC14). |
| **AC15** | AI | **Rick F11-fit amendment** — `src/tests/integration/test_commons_ask_async_push_integration.py` provides real end-to-end coverage against live `:8000` (monopolize mode). Two `mp.spawn` mock-CC-listener subprocesses; asker calls `ask_async` against live `:8000` via `requests.post`; answerer posts; full HTTP round-trip + FastAPI lifespan + auth + watcher daemon + listener dispatch verified. Scheduled via `POST /api/test-suite/submit` with user-confirmed `scheduled_at` (per `feedback_test_server_monopolize_mode`). Must land before Phase 3 closes. |
| **AC16** | AI | **T1 idempotency unit test** (`test_commons_question_watcher.py::test_dispatched_set_prevents_duplicates`) — register question, post answer, run `tick()` twice; assert `inject_fn` called exactly once even though entry's `ts > last_seen_ts` on both ticks. Also: type-confusion variants (`in_reply_to = 42` / `None` / `["array"]`) are skipped + log-asserted; oversize and control-char variants are skipped. |
| **AC17** | AI | **T3 caps unit + smoke tests** — `test_commons_question_watcher.py::test_per_user_cap` registers 51 questions for the same user, asserts 51st raises `CapExceededError`; `test_global_cap` registers up to global ceiling across multiple users, asserts ceiling+1 raises. `test_ask_async_push_e2e.py::test_register_returns_429_on_cap` hits HTTP endpoint past cap, asserts 429 with expected error body. |
| **AC18** | AI | **T4 re-register cursor unit test** (`test_commons_question_watcher.py::test_re_register_cursor_resets_to_now`) — register question, post answer entry, simulate server-restart by clearing tracker; re-register same question, run `tick()`; assert pre-restart entry is NOT dispatched (cursor = `time.time()` skipped it). |
| **AC19** | AI | **T6 concurrency unit test** (`test_commons_question_watcher.py::test_concurrent_register_unregister_dispatch`) — N threads (e.g., 32) interleave register / unregister / `tick()` calls on the same question_id; assert no exceptions raised, final tracker state is consistent (either present or absent, never partial), no double-dispatch. |
| **AC20** | AI | **T8 inject_fn failure unit test** (`test_commons_question_watcher.py::test_failing_inject_fn_does_not_kill_tick_batch`) — register two questions Y1 (failing inject_fn) and Y2 (succeeding inject_fn) in same topic; post answers to both; assert Y2's inject_fn fires even though Y1's raised; assert Y1's exception is logged at debug level. |

### Test contract (per Test Ownership Mandate)

| Tier | Files | Venue | Gate |
|---|---|---|---|
| Unit | `test_commons_topic_watcher.py`, `test_commons_question_watcher.py`, `test_commons_llm_disambiguator.py`, `test_commons_xml_models.py` + 26 ack-watcher re-verify | `:7999` | AC8, AC11, AC12 |
| Smoke (in-process HTTP) | `test_ask_async_push_e2e.py` via `TestClient` | `:7999` | AC13, AC14 |
| Integration (live HTTP) | `test_commons_ask_async_push_integration.py` against `:8000` | `:8000` (scheduled monopolize) | AC15 |
| E2E UI | (none — INTRA-AI per §7) | — | — |
| Coverage gate | 100% lines + branches + functions on all 4 NEW pure-logic modules — multiplexer parity (`feedback_100pct_coverage_multiplexer` not applicable scope, but Phase 2 set 100% precedent for commons modules) | — | AC12 |

---

## 7. Out of scope

- Postgres-backed commons — **Phase 4** (architectural decision tracked at `01-design.md` §9).
- Multiplexer Commons tab — **Phase 4 + Phase 6c** prerequisite.
- Cross-user / cross-installation commons — out of scope for v0.1.7 entirely.
- Mobile broadcast surface — post-v0.1.7.

---

## 8. PHI-4 Prompt Envelope (F5-fit deliverable)

The `commons_llm_disambiguator` invokes PHI-4 via `LlmClientFactory` with the XML envelope below. Per F5-fit, Option A (match + confidence) was ratified — smallest envelope supporting no-match via confidence-floor thresholding, matches `ExpeditorResponse` canonical pattern, additively extensible later.

### Request envelope (`PersonaDisambiguationRequest`)

```xml
<commons_persona_disambiguation>
  <active_personas>
    <persona><name>Rachel</name><icon>🎸</icon></persona>
    <persona><name>Tiberius</name><icon>🌑</icon></persona>
    <persona><name>Rio</name><icon>⚡</icon></persona>
    <persona><name>Maria</name><icon>🌺</icon></persona>
  </active_personas>
  <ambiguous_reference>the Rachel session</ambiguous_reference>
  <context>(optional — surrounding question text or session topic for additional disambiguation signal)</context>
</commons_persona_disambiguation>
```

**Pydantic model** (`src/lupin_mcp/commons_xml_models.py`) — Pydantic-native validation per `feedback_pydantic_native_validation`. Constraints declared on `Field`; sanitization via `@field_validator(mode="before")` at the substitution boundary per `feedback_sanitize_at_boundary_not_format_strip`:

```python
from typing import ClassVar, List, Optional
from pydantic import Field, field_validator
from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel

class PersonaInfo( BaseXMLModel ):
    """One persona entry in the active_personas list."""
    name : str = Field( ..., min_length=1, max_length=64 )
    icon : str = Field( ..., min_length=1, max_length=8 )

class PersonaDisambiguationRequest( BaseXMLModel ):
    """Outbound request envelope for PHI-4 disambiguation."""
    active_personas     : ClassVar[ List[ PersonaInfo ] ]
    ambiguous_reference : str = Field( ..., min_length=1, max_length=256 )
    context             : Optional[ str ] = Field( default=None, max_length=2048 )

    @field_validator( "ambiguous_reference", "context", mode="before" )
    @classmethod
    def _sanitize_text( cls, v: Optional[ str ] ) -> Optional[ str ]:
        """T2 sanitize-at-boundary: reject control chars; XML-escape <, >, &."""
        if v is None: return None
        if any( ord( c ) < 32 and c not in "\n\t" for c in v ):
            raise ValueError( "control characters not allowed in disambiguator input" )
        return v.replace( "&", "&amp;" ).replace( "<", "&lt;" ).replace( ">", "&gt;" )
```

### Response envelope (`PersonaDisambiguationResponse`)

```xml
<persona_disambiguation_response>
  <matched_persona>Rachel</matched_persona>
  <confidence>0.87</confidence>
</persona_disambiguation_response>
```

**Pydantic model** — `confidence` is `Field`-constrained to `[0.0, 1.0]`; out-of-range values raise ValidationError before reaching the disambiguator's downstream logic:

```python
class PersonaDisambiguationResponse( BaseXMLModel ):
    """Inbound response from PHI-4 disambiguation.

    matched_persona == None signals 'no match' explicitly.
    confidence is 0.0-1.0; disambiguator applies confidence-floor threshold.

    Output `matched_persona` whitelist (must be in active_personas) is
    enforced in the disambiguator body, not on the model — the whitelist
    depends on runtime state the model doesn't see.
    """
    matched_persona : Optional[ str ] = None
    confidence      : float           = Field( ..., ge=0.0, le=1.0 )

    # Per CLAUDE.md xmltodict guidance — empty <matched_persona/> tag → None
    # Standard BaseXMLModel field_validator handles "" → None coercion.
```

### Disambiguator usage

Input validation happens at `PersonaDisambiguationRequest` instantiation (Pydantic ValidationError raised on malformed input). Output validation includes the runtime `active_personas` whitelist check that the model can't enforce:

```python
from pydantic import ValidationError

def disambiguate(
    active_personas     : List[ PersonaInfo ],
    ambiguous_reference : str,
    context             : Optional[ str ] = None
) -> Optional[ str ]:
    """
    Requires:
        - active_personas is a non-empty list of PersonaInfo
        - ambiguous_reference is a non-empty string ≤ 256 chars (Pydantic-enforced)

    Ensures:
        - returns canonical persona name from active_personas, OR None on no-match
        - returns None if matched_persona not in active_personas (T2 whitelist)
        - returns None if confidence < INI threshold floor
        - returns None on parse failure or input ValidationError (logged, NOT raised)

    Raises:
        - None publicly. Internal errors caught and logged.
    """
    try:
        request = PersonaDisambiguationRequest(
            active_personas     = active_personas,
            ambiguous_reference = ambiguous_reference,
            context             = context
        )  # raises ValidationError on malformed input — Pydantic-native
    except ValidationError as e:
        if debug: print( f"[commons_llm_disambiguator] input ValidationError: {e!r} → returning None" )
        return None

    request_xml = request.to_xml()

    spec_key = config_mgr.get( "llm spec key for commons persona disambiguator" )
    timeout  = config_mgr.get( "commons llm disambiguator timeout seconds", default=5 )
    floor    = config_mgr.get( "commons llm disambiguator confidence floor", default=0.7 )

    client   = LlmClientFactory.get_client( spec_key, debug=debug, verbose=verbose )

    try:
        response_xml = client.invoke( request_xml, timeout=timeout )
        response     = PersonaDisambiguationResponse.from_xml( response_xml )
    except ( TimeoutError, ValidationError, ValueError ) as e:
        if debug: print( f"[commons_llm_disambiguator] PHI-4 failed: {e!r} → returning None" )
        return None

    # T2 whitelist: matched_persona must be in active_personas
    if response.matched_persona is not None:
        canonical_names = { p.name for p in active_personas }
        if response.matched_persona not in canonical_names:
            if debug: print( f"[commons_llm_disambiguator] matched_persona {response.matched_persona!r} not in active_personas → returning None" )
            return None

    if response.confidence < floor:
        if debug: print( f"[commons_llm_disambiguator] confidence {response.confidence:.2f} < floor {floor:.2f} → no-match" )
        return None

    return response.matched_persona  # may be None on explicit no-match
```

### System prompt scaffolding (for `client.invoke()`)

The PHI-4 system prompt frames the task; the XML body is the user content. Outline:

> "You are a persona disambiguator. You will receive a `<commons_persona_disambiguation>` XML block listing active personas, an ambiguous reference, and optional context. Return ONLY a `<persona_disambiguation_response>` XML block with `<matched_persona>` (the canonical name from active_personas, or empty for no-match) and `<confidence>` (0.0-1.0). Do not explain your reasoning. Do not return any other text."

Exact wording tuned during Pass 2 Adversarial walk (T-style prompt-injection considerations).

### Additive growth path

`reasoning` field could be added in a future revision without breaking parsing:
- Pydantic's `extra="ignore"` (default for BaseXMLModel) lets older parsers consume newer responses
- A new `reasoning : Optional[ str ] = None` field added to `PersonaDisambiguationResponse` is fully backward-compatible
- Same for multi-candidate `ranked_candidates` shape (would be a sibling field on the response)

---

## 9. Idempotency marker

`phase-3-pass2-closed-at: 2026-05-12 (Tiberius 🌑, session 6a054460). Pass 0 ✅ + REUSE ✅ + Pass 1 Fitness ✅ (13 findings + AC15) + Pydantic-native retrofit ✅ + Pass 2 Adversarial ✅ (8 threats T1-T8); apply phase complete (both passes folded in). Next gate: AI-executed test pyramid per §6 Testing Ownership Mandate; user is never a tester.`
