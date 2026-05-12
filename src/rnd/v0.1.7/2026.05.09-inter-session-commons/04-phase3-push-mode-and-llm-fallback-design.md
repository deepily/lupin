# Phase 3 — Push-Mode `ask_async` + LLM Fallback for Persona Matcher

| Field | Value |
|---|---|
| **Initiative** | Inter-Session Commons — Phase 3 (out-of-band push for ask_async + LLM-disambiguated persona matching) |
| **Doc-set started** | 2026-05-12 |
| **Branch** | `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe` (or v0.1.8 if Phase 3 slips past cut) |
| **Status** | 🟡 **Pass 1 Fitness IN FLIGHT 2026-05-12** — F1-fit ratified (Option A: default True + try-except + warning log); F2-fit ⏸ paused mid-picker. 11 findings remaining. **Resume pointer**: [`91-resume-here-phase3-pass1-f2-fit.md`](91-resume-here-phase3-pass1-f2-fit.md). REUSE pass closed 2026-05-12; Pass 0 closed 2026-05-12. |
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

**Open question**: which model? Haiku for cost, Sonnet for quality. Decide during Pass 0.

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
| F1 | Push-mode answer dispatcher (Q1 hybrid refactor target) | extend-existing | `cosa/rest/commons_ack_watcher.py:42-221` — full lifecycle scaffolding intact (`start`/`stop`/`_initialize_last_seen_ts`/`_run_loop`/`tick`/`_prune_expired_locked`); becomes `CommonsTopicWatcher` base + `Ack` / `Question` subclasses per Q1 |
| F2 | `<system-reminder>` injection on listener side | reuse-as-is | `lupin_cli/claude_code/hooks/lib/cc_notification_listener.py:281-302` `_handle_action()` dispatcher — current branches: `set_session_topic` / `exit_conversation_mode` / `broadcast_received`. **F11 below** locks in the new verb. |
| F3 | Outstanding-question tracker (in-flight dict) | extend-existing | `cosa/rest/commons_ack_watcher.py:42-53` `_InFlightEntry` — mirror with `_InFlightQuestion` carrying `(asker_session_id, asker_persona, topic, ttl_seconds, expires_at_monotonic)` |
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
| F11 | New listener action verb | extend-existing | Phase 2's `"broadcast_received"` precedent (cc_notification_listener.py:299). Lock in `action == "commons_answer_received"` for the 4th elif slot. **Pass 1 may revise this name.** |
| F12 | `main.py` lifespan() wiring | extend-existing | Phase 2 commons singletons block at `fastapi_app/main.py:527+` already initializes `commons_ack_watcher` + `commons_store` + `commons_rate_limiter`. Phase 3 extends the SAME block — instantiate `CommonsQuestionWatcher` (Q1 subclass) + start it + register the new `POST /api/commons/register-question` endpoint. No new lifespan() section. |

### Corrections (Cn — ratified during REUSE walk, applied above)

| # | Correction | Resolution |
|---|---|---|
| **C1** | **F4 PIVOT** — original mapping to `cosa.agents.llm::Llm` is stale. Actual primitive is `LlmClientFactory`. | Replaced F4 row with F4-REVISED above; original kept struck-through for audit trail. Canonical call template `runtime_argument_expeditor/expeditor.py:82, 167-168` cited. |
| **C2** | **NEW INI key required** — adopt pattern `llm spec key for commons persona disambiguator = Deepily/kaitchup/Phi-4-AutoRound-GPTQ-4bit` mirroring `expeditor.py:79` (`config_mgr.get("llm spec key for runtime argument expeditor")`). Paired splainer required. | Added to §4 MODIFIED files: `lupin-app.ini` +1 key, splainer +1 entry. Total new INI keys for Phase 3: **4** (Q4 ttl + Q7 timeout + C2 spec key + Q5 fallback model name). |
| **C3** | **Q2 sub-question RESOLVED via REUSE** — HTTP register endpoint wins. Shared-file approach would require a NEW primitive (`session_bridge.py:47 SESSION_DIR` is session-focused, not question-tracking-focused). HTTP path has directly-applicable template at `conversation_mode.py:116-`. | New endpoint `POST /api/commons/register-question` (and matching `DELETE /api/commons/register-question/{question_id}`) added to §4 NEW endpoints. MCP-side `ask_async()` fires the register HTTP call when push mode is enabled. |

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
| `src/tests/smoke/test_ask_async_push_e2e.py` | ~200 | 2-session E2E: A posts `ask_async` (registers question with FastAPI), B reads + answers, watcher tick() dispatches push, A receives `<system-reminder>` injection |

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
| `src/conf/lupin-app.ini` + splainer | **4 new keys** (per Q4 + Q5 + Q7 + C2): `commons question tracker ttl seconds = 3600`, `llm spec key for commons persona disambiguator = Deepily/kaitchup/Phi-4-AutoRound-GPTQ-4bit`, `commons llm disambiguator fallback model name = claude-haiku-4-5`, `commons llm disambiguator timeout seconds = 5`. Plus 4 paired splainer entries. | +8 |
| `src/cosa/rest/routers/notifications.py` | Add `"commons_answer_received"` to `valid_types` list at L359-363 (alongside Phase 2's `commons_broadcast_ack`) | +1 |

### Files NOT touched

- UI (`broadcast-panel.js` etc.) — Phase 3 is INTRA-AI per the Phase 0 §13 architectural principle "commons is INTRA-AI". No user-facing surface changes.
- Phase 1 + Phase 2 modules — additive only.

---

## 5. Sequencing (skeleton — to be expanded during Pass 1)

1. Pass 0 — Ratify Q1-Q8 via `ask_multiple_choice` / `ask_yes_no`
2. REUSE pass — walk §3 prior-art map, file corrections + extend-existing tickets
3. Pass 1 Fitness — apply fitness findings (e.g., F-style)
4. Pass 2 Adversarial — threat-walk the push surface (T-style)
5. Code-write start (after plan APPROVED FOR CODE-WRITE)
6. Implementation steps (TBD by Pass 1 — likely 6-9 steps including INI keys, daemon, listener wiring, MCP tool refactor, E2E smoke, docs, closure)

---

## 6. Test contract (per Test Ownership Mandate — placeholder)

| Tier | Files | Venue |
|---|---|---|
| Unit | `test_commons_question_watcher.py`, `test_commons_llm_disambiguator.py` | `:7999` |
| Smoke | `test_ask_async_push_e2e.py` | `:7999` |
| E2E UI | (none — INTRA-AI scope) | — |
| Coverage gate | 100% lines + branches + functions on all NEW pure-logic modules — same gate as Phase 1 + 2 | — |

---

## 7. Out of scope

- Postgres-backed commons — **Phase 4** (architectural decision tracked at `01-design.md` §9).
- Multiplexer Commons tab — **Phase 4 + Phase 6c** prerequisite.
- Cross-user / cross-installation commons — out of scope for v0.1.7 entirely.
- Mobile broadcast surface — post-v0.1.7.

---

## 8. Required next-session actions

1. **Pass 0 — Q-decisions** via `ask_multiple_choice` / `ask_yes_no`. Yields ratifications for Q1-Q8.
2. **REUSE pass** — confirm §3 prior-art mappings, file F-corrections.
3. **Pass 1 Fitness** — walk each AC for completeness, surface F-findings.
4. **Pass 2 Adversarial** — threat-walk push surface (T1: malformed `in_reply_to` correlation; T2: LLM injection via persona-list prompt; T3: outstanding-question DoS via unbounded tracker; T4: stale answer push after server restart).
5. Only after all 4 passes close → flip status to APPROVED FOR CODE-WRITE.

---

## 9. Idempotency marker

`phase-3-skeleton-drafted-at: 2026-05-12 (Tiberius 🌑, session 6a054460). No plan-review gates run. Pass 0 Q-decisions are the next user-facing step.`
