# Resume Pointer — Phase 3 Pass 1 Fitness, F2-fit picker (2026-05-12)

> ⚪ **SUPERSEDED 2026-05-12** — this resume doc served its purpose. Pass 1 Fitness CLOSED with all 13 findings ratified + Rick's AC15 amendment + apply phase complete. **For the current Phase 3 state, see** [`04-phase3-push-mode-and-llm-fallback-design.md`](04-phase3-push-mode-and-llm-fallback-design.md) **(Pass 2 Adversarial is the next user gate).** Kept below for audit trail.
>
> ---
>
> **You are here**: Pass 1 Fitness walk of Phase 3 (push-mode `ask_async` + LLM fallback for persona matcher). F1-fit ratified; F2-fit picker was open when the session paused. After context clear, this doc is the single self-contained entry point.

---

## TL;DR — immediate next action

1. Read this doc fully — it's self-contained.
2. Confirm MCP startup (Phase A + B per `~/.claude/CLAUDE.md`).
3. **Re-fire the F2-fit `ask_multiple_choice` picker** with the exact framing in §4 below.
4. After F2-fit ratifies, walk **F3-fit → F13-fit one at a time** per Rick's standing directive (highest severity first, then descending; one finding per turn).

**Standing directive from Rick (2026-05-12)**: Every multi-option `ask_multiple_choice` / substantive `ask_yes_no` MUST carry per-option pros AND cons AND a "My recommendation: X because Y" block in BOTH the spoken `question` and the `abstract`, plus a "becomes correct if..." flip-condition. See memory `feedback_always_include_pros_cons_recommendation.md`.

---

## 1. Where the design doc stands

**Primary doc**: `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md`

### Pass 0 ratifications (8/8 ✅ — fully applied to §2)

| Q | Decision |
|---|---|
| Q1 | **Hybrid base class** — refactor `CommonsAckWatcher` → `CommonsTopicWatcher` base + `Ack` / `Question` subclasses. Refactor lands as Phase 3 step 1; all 26 ack-watcher tests must re-verify GREEN unchanged before new functionality. |
| Q2 | **Only-outstanding dynamic registration** — `ask_async()` registers `(topic, question_id)` with the watcher; unregister on answer-arrived or TTL. |
| Q3 | **`COMMONS PEER REPLY` framing** — `<system-reminder>` body: `"COMMONS PEER REPLY (question_id X, from @PersonaName):\n\n[body]"`. Honors INTRA-AI principle. |
| Q4 | **1-hour default TTL + per-call override** — INI `commons question tracker ttl seconds = 3600`; MCP override `ask_async(..., ttl_seconds=N)`. |
| Q5 | **Local PHI-4 first → STUBBED Haiku fallback** — primary path: PHI-4 via `LlmClientFactory` + `BaseXMLModel`. Haiku 4.5 wired but stubbed (`NotImplementedError`). |
| Q6 | **No cache** — YAGNI; pure additive change later if telemetry justifies. |
| Q7 | **Configurable timeout, 5s default** — INI `commons llm disambiguator timeout seconds = 5`. |
| Q8 | **In-memory tracker, lost on reload** — matches Phase 2 `CommonsAckWatcher._in_flight` pattern. |

### REUSE pass (✅ — applied to §3 + §4)

- 8 F-mappings confirmed with file:line citations (F1-F8)
- 4 new F-findings (F9-F12) surfaced and added
- 3 corrections (C1-C3) applied:
  - **C1**: F4 pivot — `LlmClientFactory` (not stale `Llm` class) at `cosa/agents/llm_client_factory.py:17`. Canonical call template: `runtime_argument_expeditor/expeditor.py:82, 167-168`.
  - **C2**: NEW INI key required: `llm spec key for commons persona disambiguator = Deepily/kaitchup/Phi-4-AutoRound-GPTQ-4bit`.
  - **C3**: Q2 sub-question RESOLVED — HTTP register endpoint wins. New endpoint `POST /api/commons/register-question` + `DELETE /api/commons/register-question/{question_id}`.

### File touchpoints after REUSE (§4)

- **9 NEW files**: `commons_topic_watcher.py` (base), `commons_question_watcher.py`, `commons_llm_disambiguator.py`, `commons_xml_models.py`, 4 unit tests, 1 smoke test
- **8 MODIFIED files**: existing `commons_ack_watcher.py` (refactor), `commons_persona_matcher.py` (wire LLM), `cc_notification_listener.py` (4th elif), `commons_ask.py` (push-mode), `routers/commons.py` (+2 endpoints), `main.py` (extend lifespan), `lupin-app.ini` + splainer (4 new keys), `notifications.py` (valid_types extension)
- **Estimated**: ~1,160 LOC new + ~120 LOC modified

---

## 2. Pass 1 Fitness — derived ACs

13 ACs derived from Pass 0 + REUSE. **Currently NOT YET applied to design doc §6 — Pass 1 apply phase pending all 13 findings ratifying.**

| AC | One-liner |
|---|---|
| AC1 | `POST /api/commons/register-question` validates body, same-user-scopes, rate-limits, atomic register-or-409 |
| AC2 | `DELETE /api/commons/register-question/{question_id}` — 204 / 404 / same-user-scoped |
| AC3 | `CommonsQuestionWatcher.tick()` polls registered topics, dispatches `commons_answer_received` push per `in_reply_to` correlation |
| AC4 | Listener `_handle_action("commons_answer_received", notif)` injects `<system-reminder>` via `_inject_via_tmux(wrap=False)` with `COMMONS PEER REPLY` body |
| AC5 | `commons_ask.ask_async()` fires HTTP register when push-mode INI enabled; backwards-compat polling-mode preserved |
| AC6 | `commons_llm_disambiguator.disambiguate(...)` builds XML prompt, invokes PHI-4 via `LlmClientFactory`, parses via `BaseXMLModel`, returns canonical persona or None |
| AC7 | Haiku 4.5 fallback function exists + routed-to on PHI-4 failure; raises `NotImplementedError` (stubbed) |
| AC8 | Hybrid refactor — `CommonsTopicWatcher` base + 2 subclasses; 26 existing ack-watcher tests re-verify GREEN unchanged |
| AC9 | New INI keys + paired splainer entries (count TBD by F1-fit + F2-fit ratifications — currently 5-7) |
| AC10 | `routers/notifications.py` `valid_types` extended with `"commons_answer_received"` |
| AC11 | `py_compile` clean + import-chain check |
| AC12 | **100% line + branch + function coverage** on 4 NEW pure-logic modules + router helpers |
| AC13 | 2-session E2E smoke (`test_ask_async_push_e2e.py`) — A asks, B answers, watcher dispatches, A's mock `inject_fn` records the system-reminder text |
| AC14 | Router registration smoke for new endpoint pair |

---

## 3. F1-fit ✅ RATIFIED (default True + try-except + warning log)

**Finding**: Missing push-mode toggle INI key.

**Decision**: Add `commons ask async push mode enabled = True` to `lupin-app.ini` + paired splainer. When push-mode is enabled, `ask_async` attempts HTTP register; on any failure (404 / connection error / timeout), logs a warning and silently falls back to polling-mode for that call.

**Why**: Phase 3's whole point is push-mode; defaulting off undersells. Try-except handles phased-deploy windows + transient FastAPI hiccups. Warning log keeps silent case grep-able. Matches Phase 2 `failed_recipients` best-effort isolation pattern.

**To apply (deferred until all 13 findings ratify)**: add the INI key to §4 MODIFIED-files list; clarify AC5 wording to specify try-except + warning log on register failure.

---

## 4. F2-fit ⏸ PAUSED — re-fire this picker on resume

### Finding (verbatim)

**🔴 Blocker**: The MCP-side `ask_async` needs to know the FastAPI base URL for the HTTP register call. Hardcoding `http://localhost:7999` couples MCP to single-host deploys and breaks if FastAPI moves to a different host/port.

### Project precedent already on record

- **Memory `feedback_tests_parameterize_base_url`**: tests must read env var `LUPIN_API_URL` (default `http://localhost:7999`); never hardcode `:7999` or `:8000`.
- **Production config**: `lupin-app.ini` via `ConfigurationManager`, with automatic env-var override per key.
- The MCP server already loads from `lupin-app.ini` via `_load_commons_config()` (added in Phase 1).

### Exact picker framing to re-fire

When resuming, call `mcp__cosa-voice__ask_multiple_choice` with these EXACT options. Use `title="Pass 1 Fitness — F2-fit (resumed)"`, `priority="high"`, `timeout_seconds=600`.

**`question`** (spoken — strip code/file paths):

> F2-fit blocker resumed — hardcoded localhost dependency. The MCP-side ask_async needs the FastAPI base URL for the HTTP register call. Three options: INI key with ConfigurationManager env-var override inherited, hardcode plus TODO comment, or direct env-var read skipping INI. My recommendation: Option A, INI key. ConfigurationManager already supports env-var overrides for any INI key; all eight existing commons keys live in INI so a ninth is consistent; production multi-host deploys override per host via INI swap while testing uses env-var; the test-pattern convention from memory is preserved through ConfigurationManager. Option B becomes correct only if deploys are guaranteed single-host forever. Option C is inconsistent because production also needs this, not just tests.

**`options`** (3 entries):

1. **A — INI key + ConfigurationManager env-var override ★ recommended**
   - Description: "INI: commons api base url = http://localhost:7999. Read via config_mgr in MCP-side _load_commons_config(). ConfigurationManager auto-handles LUPIN_CONFIG_MGR_CLI_ARGS env-var overrides. Pros: consistent with 8 existing Phase 1/2 commons keys; production deploys override per-host without code change; env-var override path inherited automatically; test-pattern convention honored via ConfigurationManager. Cons: one more INI key (Phase 3 total: 7 keys); one more splainer entry."

2. **B — Hardcode + TODO comment**
   - Description: "BASE_URL = http://localhost:7999 with a TODO comment for future multi-host. Pros: simplest implementation; zero INI surface change. Cons: locks coupling in code; TODO debt; violates project's own test-pattern memory; future debugging burden on non-default deploys."

3. **C — Direct env-var read (no INI)**
   - Description: "BASE_URL = os.environ.get('LUPIN_API_URL', 'http://localhost:7999'). Skip INI layer entirely. Pros: follows test-pattern convention exactly; one fewer INI key. Cons: inconsistent with production-config patterns elsewhere (all commons config is INI); production deploys can't tune without env-var; splits commons config across INI + env-var which is confusing."

**`abstract`** (markdown for the rich UI side — use the full pros/cons table from above plus "My recommendation" + "Becomes correct if..." block).

### My recommendation (carry into the resume)

**Option A** — INI key, env-var override inherited. ConfigurationManager already supports env-var overrides for any INI key — picking INI gets the test-pattern convention for free. All 8 existing commons keys live in INI; consistency wins.

---

## 5. Remaining 11 findings (F3-fit → F13-fit)

Walk one at a time, highest severity first.

### 🟠 High-severity (3 remaining)

| # | AC | Finding (short form) | Recommended fix |
|---|---|---|---|
| **F3-fit** | AC3 | **Cursor strategy ambiguous** — per-topic cursor (one `_last_seen_ts` per registered topic) vs single global cursor. Phase 2 works with one cursor because there's ONE topic. Phase 3 tails N registered topics. | Lock in **per-topic cursor** in AC3 wording. `_InFlightQuestion` carries its own `last_seen_ts` field. Per-topic wins on efficiency + correctness; global wins on simplicity. |
| **F4-fit** | AC1, AC2 | **Same-user scoping missing** — register/unregister endpoints must scope to `authenticated_user_id` (mirror Phase 2 T7). Otherwise session A's user could register/unregister session B's user's questions = cross-user data leak. | Add explicit same-user check in AC1/AC2. |
| **F5-fit** | AC6 | **PHI-4 prompt envelope undesigned** — code-write needs the actual XML prompt shape before implementation. | Add §8 "Prompt envelope" section. Propose: request `<commons_persona_disambiguation>` with `<active_personas>` list + `<ambiguous_reference>` + optional `<context>`. Response `<persona_disambiguation_response>` with `<matched_persona>` + `<confidence>`. |

### 🟡 Medium-severity (6)

| # | AC | Finding (short form) | Recommended fix |
|---|---|---|---|
| **F6-fit** | AC1 | TTL bounds validation missing — must reject negative / zero / unreasonably-large values | `0 < ttl_seconds ≤ 604800` (7 days); 400 with clear message |
| **F7-fit** | AC1 | Topic regex validation — must match `[A-Za-z0-9_-]+` (per `commons_store.py:39-41` `_HEADER_RE`) or watcher silently fails to read | Add explicit topic regex validation; 400 on invalid |
| **F8-fit** | AC1 | Concurrent register collision — two MCP clients calling `ask_async` with caller-supplied `question_id` racing the watcher | Mirror Phase 2's atomic register pattern (T9); 409 on collision |
| **F9-fit** | AC4 | Persona attribution source ambiguity — `from @PersonaName` in the system-reminder body sourced from where (live lookup vs stamped on answer entry)? | Lock in "read from answer entry's `persona_name` field, NOT live lookup" (per Phase 1's "persona immutable after post" decision) |
| **F10-fit** | AC5 | `commons_ask_sync` push-mode interaction — sync mode blocks the asker; push doesn't help | Document explicitly: push-mode does NOT affect `ask_sync` — sync stays polling-only |
| **F11-fit** | AC13 | E2E smoke must exercise the HTTP endpoint, not just direct `execute_*()` call | Update AC13 wording to specify endpoint hit via `TestClient` OR `requests.post` |

### 🟢 Low-severity (2)

| # | AC | Finding (short form) | Recommended fix |
|---|---|---|---|
| **F12-fit** | AC11 | Import-chain check should include new modules explicitly | Add 4 module names to AC11's import-chain assertion |
| **F13-fit** | AC8 | Refactor naming — `register_broadcast()` / `unregister_broadcast()` are domain-specific; base should NOT have them | Add explicit "what stays in base vs subclass" subsection to AC8 |

---

## 6. After all 13 findings ratify

**Apply phase** — mechanical doc edits to:
- §4 INI keys count (likely 6-7 depending on F1-fit + F2-fit + others)
- §6 AC table (currently empty placeholder — write 13 ACs in full with `EXECUTOR: AI` tags per Phase 2 convention)
- §8 NEW section "PHI-4 prompt envelope" (F5-fit deliverable)
- §3 F11 listener verb if Pass 1 renames it
- §4 ADD `commons_ask.py` modification entry if not already there

**Then**: flip status to `Pass 1 CLOSED`, propose Pass 2 Adversarial (with user gate per `feedback_pip_plan_review_is_sequential`).

---

## 7. Process reminders for fresh-context me

- **Conversation mode is ACTIVE** at the time of pause — receipt-ack notify BEFORE every tool call; closing-turn notify after. Re-shape spoken `message` to conversational prose (~80-120 words for substantive turns). Rich detail in `abstract`.
- **Standing directive (mandatory)**: pros/cons + recommendation on every multi-option `ask_multiple_choice`. See memory `feedback_always_include_pros_cons_recommendation`.
- **Sequential plan-review rule** (memory `feedback_pip_plan_review_is_sequential`): REUSE → user gate → apply → Pass 1 → user gate → apply → Pass 2 → user gate → apply. Pass 1's gate is "apply findings to design doc"; Rick wants per-finding ratification rather than bulk approval.
- **Lupin only** — never manage git in `src/cosa/`; editing CoSA Python is fine, git ops are forbidden.
- **No auto-commit** — wait for explicit "commit"/"push" per change. Rick said `Let's go ahead and document and checkpoint your work` which IS authorization for THIS checkpoint commit; subsequent edits need fresh authorization.

---

## 8. File locations cheatsheet

| Purpose | Path |
|---|---|
| Phase 3 design doc | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/04-phase3-push-mode-and-llm-fallback-design.md` |
| Phase 3 doc-set index | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` |
| Phase 2 closure (for context) | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/92-phase2-closure.md` |
| Phase 2 execution log | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-phase2-execution-log.md` |
| Phase 1 closure | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/92-phase1-closure.md` |
| THIS RESUME DOC | `src/rnd/v0.1.7/2026.05.09-inter-session-commons/91-resume-here-phase3-pass1-f2-fit.md` |

### Code references cited during Pass 0 / REUSE / Pass 1 walks

| Subject | Location |
|---|---|
| `CommonsAckWatcher` (Q1 refactor target) | `src/cosa/rest/commons_ack_watcher.py:42-221` |
| `_InFlightEntry` struct (F3 mirror template) | `src/cosa/rest/commons_ack_watcher.py:42-53` |
| Listener `_handle_action()` dispatcher | `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py:281-302` |
| `LlmClientFactory` (C1 corrected primitive) | `src/cosa/agents/llm_client_factory.py:17` |
| Canonical LLM-call template | `src/cosa/agents/runtime_argument_expeditor/expeditor.py:82, 167-168` |
| `BaseXMLModel` canonical pattern | `src/cosa/agents/io_models/utils/util_xml_pydantic.py:81` |
| Canonical XML model examples | `src/cosa/agents/runtime_argument_expeditor/xml_models.py:17, 219` |
| LLM-script-matcher template (F10) | `src/cosa/agents/notification_proxy/strategies/llm_script_matcher.py` |
| `commons_store.py` `_HEADER_RE` (F7 regex) | `src/lupin_mcp/commons_store.py:39-41` |
| Phase 2 broadcast router (HTTP template) | `src/cosa/rest/routers/conversation_mode.py:116-` |
| Phase 2 commons singletons block | `src/fastapi_app/main.py:527+` |

---

## 9. MCP / cosa-voice tool reminders

- **`mcp__cosa-voice__get_session_info`** — call at Phase A to verify connectivity + grab persona
- **`mcp__cosa-voice__set_session_topic`** — set as soon as session focus is knowable (use `"Phase 3 Pass 1 Fitness — F2-fit resume"`)
- **`mcp__cosa-voice__notify`** — receipt acks + closing turns. `priority="high"`, `suppress_ding=True` for conversation mode
- **`mcp__cosa-voice__ask_multiple_choice`** — for finding ratifications. `priority="high"`, `timeout_seconds=600`
- **`mcp__cosa-voice__ask_yes_no`** — for binary apply/don't-apply gates

---

## 10. Idempotency marker

`paused-at: 2026-05-12 ~mid-Pass-1-Fitness. F1-fit ratified; F2-fit picker in flight; 11 findings remain. Resume = re-fire F2-fit picker per §4 of this doc.`
