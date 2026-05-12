# Lupin Project History

> **Archives**: See [history/README.md](history/README.md) for the full chronological index. Most recent: [2026-05-03 to 05-06](history/2026-05-03-to-06-history.md).

### 2026.05.11 late PM - Session df880556 (María) | Multiplexer Phase 6b Phase 1 — store API prereqs + Phase 5 ownership-flag guard

**Persona**: María 🌸 (warm inquisitive female, #F06292)

#### Checkpoint | 2026.05.11 23:00 EDT | Phase 6b Phase 1 — store API prereqs landed; ready for Phase 2

**Accomplishments**:

- **Phase 6b code-execution pre-flight** — Re-audited feedback memories since 2026-05-11 plan author time (only `feedback_skip_arnold_yes_no_neither_ux` newer; not relevant); captured **`B6a = 31484` bytes** baseline from `boot.65c779ac946b.js` (Phase 6a closure artifact, built 2026-05-07T01:40:36Z, unchanged by HEAD 243267b which only touched TODO.md); recorded `B6a` + **AC7 ceiling = 39676 bytes** in both `2026.05.11-phase6b-code-execution-plan.md` and `90-execution-log.md`; verified all Pass 2 file:line citations still accurate (ActionRequiredStore.respond at L182, tick at L291, expires_at at L266; AudioStore state/queueLength/pause/resume/skip at L201-218; NotificationsListRenderer.renderActionRequiredSection at L228; actionRequiredReadOnly.ts:49 sets `data-id-hash` — confirmed no contract drift); confirmed `AudioStore.stop()` public method MISSING (Phase 1.3 must add).

- **Phase 1.1 — `ActionRequiredStore.respondAndAwait()`** (Pass 2 A1, Phase 0 prereq #8) — new non-optimistic public method: validates entry exists (throws on unknown id), validates state is `pending`/`failed` (throws otherwise — terminal states reject re-submission), flips state `pending → submitting`, stops countdown interval, emits `responded-pending` change kind with response payload, awaits POST, on success emits `responded` + transitions XState actor; on rejection emits `failed` + re-throws so caller can render inline error stripe and re-enable widget for retry. 6 new unit tests cover success path, rejection path, unknown idHash, retry-after-failure, terminal-state rejection, structured POST shape verification.

- **Phase 1.2 — Widen `respond()` + `respondAndAwait()` signature** (Pass 2 A2, Phase 0 prereq #9) — both methods now accept `string | ReadonlyArray<string> | Record<string, string>`. Added new `ActionRequiredResponse` discriminated union type to `shared/types.ts`. Widened `ActionRequiredItem.response?` to match. Server-side reconnaissance: `/api/notify/response` handler at `cosa/rest/routers/notifications.py:929-1040` treats `response_value` as `Dict[str, Any]` — accepts widened shape without changes (no CoSA-context task needed). 5 new unit tests cover array (multiSelect), Record (open_ended_batch), back-compat string for both `respond()` and `respondAndAwait()`.

- **Phase 1.3 — `AudioStore.stop()`** (Pass 2 A6, Phase 0 prereq #10) — extended XState machine with new `STOP_REQUESTED` event; added transitions `playing | paused | ended | error → idle`. Public `stop(): void` no-ops from idle/decoding; otherwise sends `STOP_REQUESTED` + clears `chunksInBurst = 0`. Semantically distinct from `skip()` (which terminates at `ended`) — design contract: idle + cleared queue + no auto-resume. 6 new unit tests cover all 4 entry states (playing/paused/ended/error), idle no-op, and the stop-vs-skip semantic contrast.

- **Phase 1.4 — `NotificationsListRenderer` ownership-flag early-return guard** (Pass 2 A3 Path A) — added single-line guard at `NotificationsListRenderer.ts:228` in `renderActionRequiredSection()`: `if (this.actionRequiredMount.dataset.phase6bOwner === "true") return;`. When the Phase 6b `ActionRequiredRenderer.mount()` claims ownership of the section, this read-only path short-circuits so the interactive widget DOM survives non-tick `store_action_required_changed` events from sibling widgets. 2 new unit tests cover both branches (flag set → short-circuit preserves Phase 6b marker DOM; flag absent → Phase 5 read-only path runs normally).

- **Phase 6b types extension** — `shared/types.ts`: `ActionRequiredState` gained `submitting` + `failed` (re-tryable, NOT terminal); `ActionRequiredChangeKind` gained `responded-pending` + `failed`; `StoreActionRequiredChangedPayload` gained optional `response?: ActionRequiredResponse` + `error?: unknown` for the new change kinds. Forward-compatible: existing Phase 4/5 consumers continue to read `id_hash` + `countdownMs` without changes.

- **Phase 1 verification (all GREEN, all on `:7999`-equivalent unit harness)** — `npx tsc --noEmit` exit 0; `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; **`c8 --100`** on the 3 edited TS files (ActionRequiredStore + AudioStore + NotificationsListRenderer) = 100% lines/branches/functions/statements; full multiplexer unit sweep **489/489 PASS** (was ~467 pre-edit; **22 new tests** added: 14 ActionRequiredStore + 6 AudioStore + 2 NotificationsListRenderer).

**Files modified** (parent Lupin only — CoSA untouched per `feedback_lupin_only_never_cosa`):

- `src/fastapi_app/static/js/multiplexer/shared/types.ts` — extended `ActionRequiredState` + `ActionRequiredChangeKind` + `StoreActionRequiredChangedPayload`; new `ActionRequiredResponse` union
- `src/fastapi_app/static/js/multiplexer/stores/ActionRequiredStore.ts` — `respondAndAwait()` + widened `respond()` + `emitWithDetails()` helper
- `src/fastapi_app/static/js/multiplexer/stores/AudioStore.ts` — `stop()` public + `STOP_REQUESTED` machine event + transitions from playing/paused/ended/error → idle
- `src/fastapi_app/static/js/multiplexer/render/NotificationsListRenderer.ts` — `phase6bOwner` ownership-flag guard at L228
- `src/tests/unit/multiplexer/action_required_store.test.ts` — +14 tests (32 → 46)
- `src/tests/unit/multiplexer/audio_store.test.ts` — +6 tests (23 → 29)
- `src/tests/unit/multiplexer/render/notifications_list_renderer.test.ts` — +2 tests (25 → 27)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/2026.05.11-phase6b-code-execution-plan.md` — Phase 0 plan serialization (B6a + AC7 ceiling recorded)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` — Phase 1 closure row, AC1/AC2 ✅, AC6 partial, B6a captured marker checked
- `TODO.md` — Phase 1 resume action checkboxes marked complete; new Phase 2 entry added
- `history.md` (this entry)
- `.claude-session.md` — register df880556 María + per-Edit touched-file records

**Status**:

- ✅ Phase 6b Phase 1 (store API prereqs + Phase 5 ownership-flag guard) — CLOSED; all sub-steps 1.1-1.5 GREEN
- ⏳ Phase 2 (interactive widget templates: `actionRequiredInteractive.ts` + `ttsChrome.ts`) — gated on user go-ahead
- ⏳ Phases 3-8 (renderers + delete-button wiring + CSS port + smoke + scheduled `:8000` E2E) — sequence per `2026.05.11-phase6b-code-execution-plan.md`
- ⏳ Mr. Radio session 77e1bb27 Phase 5b batch-2 results (`ts-476c971a`/`ts-99f2fa02`/`ts-8461cdd4`) — separate concern, owned by 77e1bb27 / future session

**Commits**: `b697c4c` (this checkpoint — parent Lupin only; CoSA untouched)

#### Checkpoint | 2026.05.11 23:45 EDT | Phase 6b Phase 2 — interactive widget templates landed

**Accomplishments**:

- **Phase 2.1 — `actionRequiredInteractive.ts`** (NEW, 228 LOC) — pure DOM template producer with switch over 5 response_type variants (yes_no / multiple_choice+radio / multiple_choice+checkbox / open_ended / open_ended_batch) plus a default-throws schema-drift defense. Each sub-builder (`buildYesNo`, `buildRadio`, `buildCheckbox`, `buildOpenEnded`, `buildOpenEndedBatch`) builds its own DOM via `html\`\`` tagged template + queries the resulting elements + attaches `addEventListener` handlers (mirrors Phase 6a `jobBucket.ts:126` precedent for self-contained interactive widgets). Submit semantics: yes_no buttons fire on direct click; radio fires `onSubmit(string)` on Submit click after at least one selection; checkbox fires `onSubmit(string[])` on Submit click (empty array if nothing checked); open_ended supports both Enter-key and Submit-click; open_ended_batch builds a `Record<header, value>` from per-row inputs. AC2e safe-write invariant header documents the no-`.innerHTML`/`rawHTML(`/`.outerHTML` rule; verified by grep-ban test (strips comments first so doc-mentions don't trigger).

- **Phase 2.2 — `ttsChrome.ts`** (NEW, 147 LOC) — TTS pane chrome with 3 controls (Pause/Resume single toggle, Stop, Skip) driven by an explicit state→enable matrix table:

| state    | toggle           | stop  | skip  |
|----------|------------------|-------|-------|
| idle     | disabled         | ✗     | ✗     |
| decoding | disabled         | ✗     | ✗     |
| playing  | enabled "Pause"  | ✓     | ✓     |
| paused   | enabled "Resume" | ✓     | ✓     |
| ended    | disabled         | ✓     | ✗     |
| error    | disabled         | ✓     | ✗     |

  Plus `currentTrackName` line (rendered only when present + non-empty), `queueLength` indicator, `.is-playing-current` / `.is-paused-current` classes per Q-B8 (ported from legacy `notifications.css:4692-4712, 4718-4725`). `data-state` + `data-testid` always set for E2E observability. AC2e safe-write invariant + grep-ban test mirror the interactive template's contract.

- **Type extension — `ActionRequiredItem.multiSelect?: boolean`** — added to `shared/types.ts` to support the Pass 2 A2 dispatch contract (`multiple_choice + multiSelect:true → checkbox`, default `false`/undefined → radio). Wire-side population still gated on Phase 0 prereq #2 verification (server payload schema field name).

- **Test coverage** — 22 tests in `templates_action_required_interactive.test.ts` (≥15 floor) covering 5 happy-path renders + 5 click-dispatch scenarios + unknown-response_type throws + multi-instance independence + prompt-rendering parametric across all response_types + multiSelect-undefined defaults to radio + empty-options batch + AC2e grep ban. 18 tests in `templates_tts_chrome.test.ts` (≥15 floor) covering 6 state-driven renders + 4 click-dispatch + currentTrackName present/absent/empty + queueLength + class invariants + multi-instance independence + disabled-controls non-interactive + data-testid/data-state observability + AC2e grep ban.

- **c8 100% gate** — both new template files hit 100% lines / branches / functions / statements after applying the canonical `/* c8 ignore next N */` annotation pattern from Phase 6a `jobCard.ts:251` (tagged-template literal phantom-branch artifact: c8 reports phantom branches on `${...}` interpolations that are straight-line at runtime; pattern documented inline with reason citation). Full multiplexer unit sweep stayed clean — **528/528 PASS** (was 489/489 pre-Phase-2; 39 new tests added: 22 + 18 templates − 1 nominal duplicate).

- **Verification matrix (all GREEN, all on `:7999`-equivalent unit harness)**: `npx tsc --noEmit` exit 0; `npx eslint src/fastapi_app/static/js/multiplexer/` exit 0; `c8 --100` on both new templates exit 0; full multiplexer unit sweep 528/528 PASS.

**Files modified** (parent Lupin only — CoSA untouched):

- `src/fastapi_app/static/js/multiplexer/shared/types.ts` — added `multiSelect?: boolean` to `ActionRequiredItem`
- `src/fastapi_app/static/js/multiplexer/render/templates/actionRequiredInteractive.ts` — NEW (228 LOC)
- `src/fastapi_app/static/js/multiplexer/render/templates/ttsChrome.ts` — NEW (147 LOC)
- `src/tests/unit/multiplexer/render/templates_action_required_interactive.test.ts` — NEW (22 tests)
- `src/tests/unit/multiplexer/render/templates_tts_chrome.test.ts` — NEW (18 tests)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/90-execution-log.md` — Phase 2 closure row + AC3/AC4/AC2e/AC6 status updates
- `TODO.md` — Phase 2 sub-step checkboxes marked done; Phase 3 entry added
- `history.md` (this entry)
- `.claude-session.md` — per-Edit touched-file records appended

**Status**:

- ✅ Phase 6b Phase 2 (interactive widget templates) — CLOSED; both new files at c8 100%; 40 new tests landed
- ⏳ Phase 3 (`ActionRequiredRenderer.ts` — consumes Phase 2 template + Phase 1 `respondAndAwait`) — gated on user go-ahead
- ⏳ Phases 4-8 — sequence per `2026.05.11-phase6b-code-execution-plan.md`

**Commits**: `ad2f479` (this checkpoint — parent Lupin only; CoSA untouched)

---

### 2026.05.11 PM - Session 77e1bb27 (Mr. Radio) | Voice Persona Rename Domi→Rio implementation + Phase 5b :8000 scheduling (2 batches)

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

#### Checkpoint | 2026.05.11 18:00 EDT | Domi→Rio rename landed; Phase 5b batches 1+2 in flight

**Accomplishments**:

- **Voice Persona Rename "Domi" → "Rio"** — name-only label rotation per user directive. Inherited Phase 0 plan doc from prior session 68edb64b (`src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md`, which was orphaned uncommitted at 68edb64b session-end). User answers to the 4 open questions: icon ⚡ KEEP, color `#880E4F` KEEP, profile text "Young & energetic female" KEEP, this-session reallocation N/A (Mr. Radio active). Implementation: 4 files edited (5 hits in `lupin-app.ini` pool list + 4 key block; 6 surgical edits in `lupin-app-splainer.ini` sparing line 175's ElevenLabs catalog reference; 7 replace_all hits in `test_voice_persona_helpers.py`; 2 replace_all hits in `test_voice_persona_allocation.py`). Audit-trail rename history added to splainer line 297 (pool list) and line 319 (Rio voice id splainer), mirroring existing Nora→maria + Quentin→mr radio + Adam→Tiberius precedent. Verification: py_compile clean; unit 34/34 pass (0.08s); smoke 7/7 pass (0.39s); live `:7999` `GET /api/cosa-voice/voice-persona/pool` returns `Rio` with all preserved attributes intact. **No `:7999` bounce required** — pool query re-reads INI per request (pleasant surprise vs the plan's "out-of-scope" assumption).

- **CC Card Normalization Phase 5b — Batch 1 scheduled + post-mortem** — user explicitly authorized `lupin-rest-test` (`:8000`) bounce; refresh-test-server.sh ran clean (24s to healthy). 3 sequential submissions via `/api/test-suite/submit` at 17:13:48 EDT, scheduled for 17:16:48 / 17:31:48 / 17:46:48. Results: **5.8 GREEN** (30/30 passed, 106.6s, AC11 met; new `test_cc_card_renders_in_sibling_shape` runs clean); **5.9 baseline regen completed** (16 passed, 0 failed, 15 errors, 0 skipped — the 15 "errors" are `pytest_playwright_visual_snapshot` standard `--update-snapshots` teardown signals "Snapshots updated. Please review images.", NOT failures; 15 baselines regenerated at `io/test-suite/visual-baselines/` covering 3 CC-normalization-adjacent + 5 auth/account + 5 admin + 2 dev/infra paths); **5.10 SKIPPED** (0/0/0/2 — subscription tests gated out, user later noted 401-cred-system issues at the time as likely cause).

- **CC Card Normalization Phase 5b — Batch 2 resubmitted** — at 17:59:16 EDT user reported the credential-processing 401 issues were restored. Resubmitted same triplet structure but with 5.9 as a TRUE regression (no `--update-snapshots`) to close AC11 via self-consistency check against batch-1's regenerated baselines: **5.8 retry** `ts-476c971a` @ 18:01:16, **5.9-regression** `ts-99f2fa02` @ 18:13:16, **5.10 retry** `ts-8461cdd4` @ 18:25:16. Results expected ~18:35 EDT; next session-checkpoint or session-end revisits the done bucket.

**Files modified** (parent Lupin scope only):

- `src/conf/lupin-app.ini` — Domi→Rio rename (5 lines: pool list + 4 key block); `=` column alignment preserved. **Note**: file also carries parallel session 9a4a601d (Rachel)'s commons INI keys at lines 518-530 (cleanly separate hunk; co-committed by interleaved-file-state pragmatism with attribution in commit message).
- `src/conf/lupin-app-splainer.ini` — Domi→Rio rename (6 surgical edits: pool list + maria color disambig + 4 Rio key splainers + Arnold color disambig); line 175 ElevenLabs catalog reference deliberately preserved. **Note**: also carries Rachel's commons splainer block at lines 691-705 (cleanly separate).
- `src/tests/unit/test_voice_persona_helpers.py` — replace_all Domi→Rio (7 hits).
- `src/tests/smoke/test_voice_persona_allocation.py` — replace_all Domi→Rio (2 hits).
- `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md` — plan doc orphaned by 68edb64b session-end; folded into this commit for clean audit trail.
- `TODO.md` — Phase 5b 3-job batch closure rewritten to reflect batch-1 results + batch-2 in-flight scheduling; new "✅ DONE — Voice Persona Rename Domi → Rio" section appended.
- `history.md` (this entry).
- `.claude-session.md` — register session 77e1bb27 Mr. Radio + per-Edit touched-file records.

**Status**:

- ✅ Domi → Rio rename CLOSED (4 files edited, 34/34 unit + 7/7 smoke green, live `:7999` verified)
- ✅ Phase 5b batch 1 fired + post-mortem written (5.8 GREEN; 5.9 baselines regenerated; 5.10 skipped pending credential restoration)
- ⏳ Phase 5b batch 2 fired (results @ ~18:35 EDT); revisit at next checkpoint
- ⏳ CC card normalization Phase 6.8 parent commit (separate concern, gated on Phase 5b full closure)
- ⏳ Mobile sub-repo TODO seed for "Domi" → "Rio" in cheat-sheets — deferred to mobile-context session per plan-handoff convention

**Commits**: `54f66a6` (this checkpoint commit — parent Lupin only)

#### Post-checkpoint addendum | 2026.05.11 20:00-20:15 EDT | 5.10 deep dive → test RETIRED

**Triggered by**: user request to investigate why the 5.10 subscription test was skipping in batch 1 / 2.

**Findings** (chained):

1. **Gate #1 — `_container_running()` skip**: test was authored as a host-side "deployment probe" calling `docker ps`, but `/api/test-suite/submit` schedules pytest INSIDE the container where the `docker` CLI doesn't exist → `FileNotFoundError` → fixture skipped the whole test. Fixed via `/.dockerenv` short-circuit (new `_running_inside_container()` helper).

2. **Gate #2 — `_server_reachable()` skip**: `TEST_SERVER_BASE = "http://localhost:8000"` hardcoded — but inside the container `:8000` is unreachable (container listens on `:7999` internally). Fixed via `os.environ.get("LUPIN_API_URL", "http://localhost:8000")` — aligns with `feedback_tests_parameterize_base_url.md`.

3. **Gate #3 — stale credentials (Docker bind-mount inode capture)**: `~/.claude/.credentials.json` bind-mounted as a single file → bound to host inode at container-start time. User refreshed creds at 17:52 EDT (atomic write-then-rename → new inode), but container kept seeing the pre-refresh content (hash `4cfccc...` vs host `734012...`). Fixed via test-server bounce (re-bound to current host inode). Long-term mitigation: mount the parent `~/.claude/` directory instead of just the file — directory bind mounts DO follow inode changes inside them.

4. **Gate #4 — schema-drift in `_extract_cost_usd()`**: helper looked for `cost_summary` inside `artifacts` key at top of job record, but the job-history persistence layer stores it inside `metadata_json`. Fixed two-file: (a) `src/cosa/agents/claude_code/job.py` Bounded path now puts `cost_summary` in `self.artifacts` (parity with the dry-run path); (b) `_extract_cost_usd()` now also reads `metadata_json.cost_summary.total_cost_usd`.

5. **THE PREMISE — AC10's `cost_usd == 0.0` is unsalvageable**: with all 4 gates above unblocked, the test finally executed end-to-end and the underlying CC CLI behavior surfaced: `claude -p` non-interactive mode reports `total_cost_usd > 0` on every call (~$0.05 in container, ~$0.32 on host) **even with no `ANTHROPIC_API_KEY` and valid Max OAuth credentials**. User insight (the breakthrough): the cost field is COUNTERFACTUAL API pricing reported as metadata, NOT actual billing. With no API key for the CLI to bill against, Max OAuth is paying the flat rate; the CLI just always reports "what this would cost via API" in its result envelope regardless of auth path. **The test as authored cannot pass on any valid CC CLI invocation.**

**Decision**: 5.10 RETIRED. Module-level `pytestmark = pytest.mark.skip(reason=...)` added to `src/tests/smoke/test_claude_code_max_subscription.py` with full forensic trail in module docstring. The 4 architecture fixes are preserved as patterns for future CC-related smoke tests that need to work both on host and inside the test container.

**Files modified (post-checkpoint, uncommitted)**:
- `src/tests/smoke/test_claude_code_max_subscription.py` — 5 surgical edits + module-level skip marker + forensic-trail docstring
- `src/cosa/agents/claude_code/job.py` — Bounded path artifacts dict now includes `cost_summary` (CoSA edit, separate commit context per `feedback_lupin_only_never_cosa`)
- `TODO.md` — 5.10 rows marked retired; AC10 closed; new TFE-to-CC design-doc amendment item filed
- `history.md` (this addendum)

**:8000 test server bounces this session**: 2 total (17:13 EDT for batch-2 setup, 19:55 EDT after credential refresh + CoSA cost_summary fix; queues confirmed empty before each per server-lifecycle courtesy).

**Phase 5b NET STATUS after retirement**:
- 5.8 ✅ functional regression GREEN both batches
- 5.9 ✅ visual baselines regenerated + self-consistency confirmed
- 5.10 ✅ RETIRED (premise invalid)
- Phase 6.8 parent commit functionally unblocked on CC card normalization scope.

**Caveats / Notes**:

- **Parallel session co-commit (lupin-app.ini + splainer)**: parallel session `9a4a601d` (Rachel, persona Rachel) was mid-Phase-1 implementation of inter-session-commons MCP and had already added 12 commons INI keys + 9 splainer entries to those 2 files when I started editing. Hunks are physically separate (Rachel's at lines 518+ / 691+; mine at 794-826 / 297-326). Pragmatic decision: commit both sets together with explicit attribution in commit message. Rachel's Python code (`commons_ask.py`, `commons_archival.py`, `commons` MCP shims in `cosa_voice_mcp.py`, etc.) is NOT in this commit — it remains in her manifest section for her own commit.
- **Plan doc adoption**: `2026.05.11-rename-persona-domi-to-rio.md` was authored by session 68edb64b (Domi, evening) and intended to be committed in that session-end per the entry below this one. The 68edb64b session-end commit never landed (no `Session-end 68edb64b` in `git log`), leaving the plan doc orphaned uncommitted. Adopted into this commit for clean audit trail; cross-references in the plan doc itself remain valid.
- **`:7999` server-lifecycle**: did NOT bounce — pool query re-reads INI per request, so the rename was live immediately on `GET /api/cosa-voice/voice-persona/pool` without restart. Pleasant deviation from the plan's "Out of Scope" expectation. Per server-lifecycle Rule 1 (never volunteer a `:7999` bounce), no advisory issued.

---

### 2026.05.11 EVE - Session 68edb64b | Voice Persona Rename — brainstormed alternatives to "Domi", user picked "Rio", plan doc serialized + delivered as viewer link

**Persona**: Domi ⚡ (Young & energetic female, #880E4F) — *the very persona being renamed in the plan this session produced*

**Accomplishments**:

- **Brainstormed ~30 alternative persona names** across 5 vibe-clusters (punchy/spark-coded, energy-vitality semantics, modern-bright, playful/pixie, distinctive) for the "Young & energetic female" voice slot occupied by "Domi". User selected **Rio**.
- **Plan doc serialized** at `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md` per `feedback_phase0_serialization_prominence.md` and the plan-serialization mandate. Doc covers: scope (label-only — voice_id unchanged → no TTS audio change), proposed preserved attributes (icon ⚡ / color #880E4F / profile text), file inventory (5 files: lupin-app.ini + splainer + 2 test files), full sweep check (all 13 grep hits classified CHANGE / KEEP / HANDOFF), cross-project handoff plan for mobile sub-repo (zero runtime impact — just doc references), test impact per layer, 4 open questions, execution sequence, explicit out-of-scope list.
- **Document-viewer-link notification delivered** per `feedback_documentation_step_stops_at_doc.md` — closing turn was `notify()` with the markdown viewer link in the abstract; deliberately did NOT auto-progress to ExitPlanMode, batched decision questions, or implementation. Plan is parked awaiting user "go" + answers to the 4 open questions (icon rotation? color rotation? profile rephrase? this-session reallocation on next /clear?).
- **Session-topic discipline**: `set_session_topic("Voice Persona Rename — alternatives to 'Domi'")` set after MCP Phase A and before any substantive tool work, per the session-topic mandate.

**Files modified** (parent Lupin scope only):

- `src/rnd/v0.1.7/2026.05.11-rename-persona-domi-to-rio.md` (NEW — plan doc, ~200 lines)
- `history.md` (this entry)
- `TODO.md` (added pending entry for Rio rename implementation — see TODO.md "Pending" section)
- `.claude-session.md` (session-start manifest registration was skipped this session; entry will be appended in this commit's session-end pass if applicable)

**Status**:

- ✅ Brainstorm delivered + name selected
- ✅ Plan doc serialized + delivered via viewer link
- ⏳ User review + answers to 4 open questions before any code edits land
- ⏳ Implementation (5-file rename + test fixture updates) parked pending approval

**Commits**: this session-end commit (parent Lupin only — `no backup, no push` per user)

**Caveats / Notes**:

- Many other files are showing modified in `git status` — these are from parallel sessions today (658ea35d, 6d544991, 6e8a6a03, 017dc1cc, f9608a41) and are **out of scope** for this session's commit. Per the parallel-session-safety v2.0 mandate, this session's commit stages ONLY: the new plan doc, `history.md`, `TODO.md`.
- Session-start manifest registration was skipped this session (no `## Session: 68edb64b` block in `.claude-session.md` at session-end time). Pre-commit verification falls under the "missing manifest" path; the explicit selective-staging list above takes the place of the manifest's section.

---

### 2026.05.11 PM/EVE - Session 658ea35d | CC Card Normalization — Phases 1-5a CLOSED end-to-end; Phase 5b awaiting `:8000` user slot; commits HELD for authorization

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **All 6 implementation phases of CC card normalization landed in one session** (Phase 0 + plan-review closure inherited from Rachel @ 6e8a6a03 earlier this morning):
  - **Phase 1 (HTML normalization)** — 8 sub-steps applied to `notifications.html` + `notifications.css`. Header rename (`Dispatcher` → `Submit Claude Code Task`); INTERACTIVE comment promoted to disabled `<option>` with tooltip; deleted 5 dead UI blocks (cc-execution-mode select div, cc-response retirement-notice `<pre>`, cc-option-b-controls + 4 disabled inject/interrupt/end inputs, cc-session-info hidden row, .cc-retired-banner CSS class + section-comment header — 29 CSS lines, NOT 2 as REUSE-pre-pass hinted); inserted sibling-pattern `#cc-submit-status` div. AC1, AC1.5, AC2, AC3, AC4 all GREEN via grep.
  - **Phase 2 (JS handler normalization)** — Rewrote `submitClaudeCode()` + `submitClaudeCodeToQueue()` in `notifications.js` to mirror research handler at L2865-2949. Collapsed from 7-arg to 4-arg signature; statusDiv with 3 canonical colors (#666 neutral, #28a745 success, #dc3545 error); dropped all writes to deleted IDs (responseEl, cc-task-id, cc-status, cc-cost, cc-session-info); fetch URL switched to canonical `/api/claude-code/submit`; refreshed L40-42 + L3812 comment blocks to describe post-normalization shape. AC5, AC6 GREEN.
  - **Phase 3 (E2E test cleanup)** — Deleted 2 obsolete `test_cc_card_has_execution_mode_select` + `test_cc_card_has_session_controls` from `test_job_dispatch.py`; added `test_cc_card_renders_in_sibling_shape` asserting header text + sibling-shape DOM + INTERACTIVE-disabled invariant (Q2 FROZEN visible-breadcrumb). py_compile clean.
  - **Phase 4 (URL rename + alias)** — **Q8 VERDICT: PRIMARY** — FastAPI 0.115.12 accepted stacked-`@router.post(...)` decorators on a single handler. CoSA `claude_code_queue.py` now registers BOTH `/api/claude-code/submit` (canonical) AND `/api/claude-code/queue/submit` (deprecated alias with `deprecated=True` in OpenAPI schema, per-request deprecation log via injected `Request` parameter). Module docstring + `quick_smoke_test()` updated to assert both routes. 2 parent-side smoke-test SUBMIT_ENDPOINT constants updated. CoSA edits made from parent context (file-edits only per `feedback_cosa_edit_vs_manage_git`; CoSA git ops are a separate-context concern per `feedback_lupin_only_never_cosa`).
  - **Phase 4.5 (handoff doc finalize)** — `02-handoff-summary.md` Q8 verdict populated as `PRIMARY`; migration timeline filled with the dates/events that have landed; placeholder-vs-literal paragraph replaced with the resolved verdict announcement.
  - **Phase 5a (`:7999` AI-discretionary verification)** — 5.1-5.6 + 5.11 all GREEN: py_compile, import-chain, router smoke (Q8 verdict gate, 5/5 internal tests), live POST to canonical URL with real JWT (HTTP 200 + `cc-41cea588`), live POST to deprecated alias with real JWT (HTTP 200 + `cc-42d86fdd`), 6-scenario dry-run smoke (6/6), TFE + BFE smoke (2/2 in 31.6s). 5.7 headless UI probe folded naturally into 5.8 :8000 functional run (new sibling-shape test is the same Playwright-driven probe). AC7, AC9, AC12 GREEN.

- **`feedback_skip_arnold_yes_no_neither_ux.md` filed** at session start (with index-pointer in `MEMORY.md`) — Arnold (session 6d544991, parallel) owns the `ask_yes_no()` "neither/discuss-further" button work; that item is skipped from future unprompted top-N TODO summaries. Arnold's own end-of-day entry above is the relevant audit trail for the actual work landed there.

- **Session-topic discipline**: topic updated mid-session from session-start summary ("Session start — top 5 TODO summary") to phase-execution ("CC Card Normalization — Phases 2-6 implementation") per the auto-memory mandate "set when topic is knowable, update at task switches."

- **Notifications**: high-priority `notify()` with rich markdown abstract surfaced at top-5 summary delivery time and Phase 1 closure; conversation mode was OFF for the whole session.

**Files modified** (parent Lupin scope only — no CoSA git ops despite CoSA file edits):

- `src/fastapi_app/static/html/notifications.html` (Phase 1.1-1.7)
- `src/fastapi_app/static/css/notifications.css` (Phase 1.8)
- `src/fastapi_app/static/js/notifications.js` (Phase 2.2-2.4 + L40-42 comment refresh)
- `src/tests/e2e_ui/test_job_dispatch.py` (Phase 3.1-3.4)
- `src/cosa/rest/routers/claude_code_queue.py` (Phase 4.1-4.5 — CoSA file edit, NOT committed in CoSA submodule)
- `src/tests/smoke/test_claude_code_dry_run_smoke.py` (Phase 4.6 — SUBMIT_ENDPOINT)
- `src/tests/smoke/test_claude_code_max_subscription.py` (Phase 4.7 — SUBMIT_ENDPOINT)
- `TODO.md` (Phase 6.1 — closed manual UI probe + finalized mobile dispatch entry with canonical URL; Phase 6.2 — added Multiplexer follow-ups section)
- `src/lupin-mobile/TODO.md` (Phase 6.3 — `[LUPIN-CC-SUBMIT-RENAME]` entry seeded under the existing 2026-05-11 CC sync section; mobile session owns the actual commit)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/00-synthesis-and-roadmap.md` (Phase 6.4 — added §9 "Open follow-ups (cross-cutting)" with pointer back to handoff doc)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/00-index.md` (phase status table flipped; all 6 implementation phases marked DONE / 5b AWAITING USER / 6 PARTIAL)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` (untouched this session — design was final pre-implementation)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md` (Phase 4.5 — Q8 verdict populated, migration timeline filled)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` (Phase 2/3/4/4.5/5a per-sub-step evidence + AC verifications + spec-drift documentation)
- `history.md` (this entry)
- `.claude-session.md` (registered session 658ea35d + per-Edit touched-file records)
- (outside repo) `~/.claude/projects/.../memory/feedback_skip_arnold_yes_no_neither_ux.md` (NEW)
- (outside repo) `~/.claude/projects/.../memory/MEMORY.md` (index updated)

**Status**:

- ✅ All AI-discretionary work CLOSED (Phases 1-5a + Phase 6 doc/tracking updates)
- ⏳ Phase 5b awaiting user slot confirmation for 3 `:8000` scheduled submissions (5.8 e2e `-k test_job_dispatch`, 5.9 e2e `-k visual` for baseline regen, 5.10 smoke `-k test_claude_code_max_subscription`)
- ⏳ Phase 6.8 parent-Lupin commit HELD for explicit user authorization per `feedback_never_auto_commit_push`
- ⏳ Phase 6.9 CoSA commit HELD — separate context per `feedback_lupin_only_never_cosa`; AI file edits at `src/cosa/rest/routers/claude_code_queue.py` are on disk awaiting a CoSA-session user-run commit
- ⏳ Phase 6.5 — `bug-fix-queue.md` checked; zero entries reference CC card normalization (no closure needed)

**Commits**:

- None this session. All work held pending user authorization (parent + CoSA in their respective contexts).

**Cycle state for the CC card normalization R&D folder**:

- Phase 0 ✅ • REUSE ✅ • Pass 1 ✅ • Pass 2 ✅ • Phase 1 ✅ • Phase 2 ✅ • Phase 3 ✅ • Phase 4 ✅ • Phase 4.5 ✅ • Phase 5a ✅ • Phase 5b ⏳ user slot • Phase 6 ⏳ partial (docs done; commits pending)

**Caveats / Notes**:

- Phase 1 → Phase 2 sequencing constraint: between the HTML deletion (Phase 1) and the JS rewrite (Phase 2) the CC submit handler would have thrown `TypeError` at `getElementById('cc-session-info').style.display` (the deleted DOM ID). Both phases landed in the same session within ~10 minutes; no `:7999` testing happened between them. Documented in the execution log "Spec drifts" subsection.
- Phase 2.1 (audit cc-inject/cc-interrupt/cc-end/cc-execution-mode event-binding lookups) became a no-op — the 2026-05-05 retirement work already replaced those bindings with a single comment block; nothing to remove. Closure recorded in execution log.
- Phase 1.8 CSS delete was 29 lines, not 2 as REUSE pre-pass implied — the parenthetical "(2 lines)" counted only `.cc-retired-banner` class-declaration lines without the section-comment header + sibling `code` rule. All within design's stated scope ("DELETE the class definition"); REUSE confirmed orphan-safe.
- 5.4 + 5.5 created 2 real CJ Flow jobs (`cc-41cea588` + `cc-42d86fdd`) with `dry_run=true`; both will complete-fast with no LLM cost. Visible in the dev `:7999` server queues.
- Parallel sessions on 2026-05-11: Rachel @ 6e8a6a03 (Phase 0 + plan-review for this CC card normalization work; committed `27f0da6` earlier this morning), Mr. Radio @ 017dc1cc (multiplexer Phase 6b Pass 1; committed `27f0da6` bundle), Tiberius @ f9608a41 (inter-session commons; uncommitted — separate scope), Arnold @ 6d544991 (cosa-voice neither/discuss; parent commit pending — see entry below), this session 658ea35d (implementation of the Rachel-authored CC card normalization plan; commits pending).

---

### 2026.05.11 PM - Session 6d544991 | `ask_yes_no()` "Neither" affordance — landed end-to-end (parent Lupin scope); CoSA commit pending separate context

**Persona**: Arnold 🪨 (gravelly male, #FFD600)

**Accomplishments**:

- **`ask_yes_no()` MCP tool gains a third "Neither" answer button** alongside Yes/No, wired end-to-end across CoSA helper + Lupin MCP + Lupin frontend + project docs. Return value `"neither"` (or `"neither [comment: ...]"`) is distinct from `"yes"`/`"no"` so Claude can branch on it explicitly. Comment field is **load-bearing** when Neither is selected — `format_qualified_response` has a dedicated branch with explicit Claude-directive: "treat as instruction to re-frame the question, not as a soft yes or no. Read the comment, then ask a clearer follow-up." Closes the open TODO filed 2026-05-07 by session 6825e6af.

- **7-phase plan executed end-to-end** (single approved sequence, no mid-impl gates): Phase 0 R&D docs → Phase 1 CoSA backend → Phase 2 MCP docstring → Phase 3 frontend HTML+CSS → Phase 4 unit tests → Phase 5 project docs → Phase 6 TODO+history+commit. Phase 7 (MCP restart for end-to-end E2E verification) is EXECUTOR: HUMAN, parked for next session.

- **Q-decisions ratified** (7): Q1 label=Neither (user-ratified via cosa-voice `ask_multiple_choice`), Q2 keyboard shortcut=none (mouse/touch only, user-ratified), Q3 return value=`"neither"` lowercase, Q4 schema=extend YES_NO response_value vocabulary (NO new ResponseType — minimum blast radius), Q5 default-on-timeout unchanged (yes/no only), Q6 comment qualifier works for all 3 buttons, Q7 visual=neutral gray (#6c757d, no green per `feedback_no_green_in_persona_pool`).

- **R&D doc set landed** at `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/` (4 files, ~13KB total): `00-index.md` (master nav, Q-table, REUSE table), `01-design.md` (full design with §2a comment-parsing-for-Neither guarantee + §3a Pass 1 Fitness/Viability self-review + §3b Pass 2 Adversarial self-review — all findings ratified inline, 0 Block / 0 Major / 2 Minor across both passes), `02-handoff-summary.md` (CoSA-context-session pointer for the working-tree commit), `90-execution-log.md` (per-phase status with verification evidence).

- **R1 (`format_qualified_response` wording) promoted from "deferred" to "applied"** during Pass 1 self-review after user voice-feedback confirmed the comment-parsing-for-Neither is load-bearing, not optional. The `if answer == "neither":` branch with re-framed copy now lives in `notification_utils.py`.

- **Cross-sub-project handoff**: One CoSA file edited (`src/cosa/utils/notification_utils.py` — regex + format branch + smoke test). Per `feedback_lupin_only_never_cosa`, the parent Lupin commit does NOT stage this file; it stays in the CoSA working tree for the next CoSA-context session to commit. The 02-handoff-summary.md doc seeds the CoSA-context TODO.

- **Tests**: 12/12 `TestExtractQualifierComment` unit tests passing (4 new `test_neither_*` methods + 8 pre-existing yes/no tests confirming additive regex). Full `test_stop_hook.py` suite: 50/50 passing. `quick_smoke_test()` in `notification_utils.py` extended with 3 neither parse cases + 1 neither format case, all green. `py_compile` clean on both `notification_utils.py` and `cosa_voice_mcp.py`.

- **MCP server restart caveat documented**: The cosa-voice MCP runs as a stdio subprocess of Claude Code (`Type: stdio`); the Python process loaded `cosa_voice_mcp.py` once at startup and does not re-read the file. Current session (6d544991) will NOT see the docstring change — fresh CC session required for end-to-end E2E verification. Phase 7 captures this as EXECUTOR: HUMAN.

**Files** (parent-Lupin scope only — CoSA file edited but NOT staged):

- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/00-index.md` (NEW — 65 LoC)
- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/01-design.md` (NEW — ~250 LoC post Pass 1 + Pass 2 additions)
- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/02-handoff-summary.md` (NEW — 70 LoC)
- `src/rnd/v0.1.7/2026.05.11-ask-yes-no-neither-button/90-execution-log.md` (NEW — phase status)
- `src/lupin_mcp/cosa_voice_mcp.py` (docstring updated for `ask_yes_no` — 3-way return value contract)
- `src/fastapi_app/static/js/notifications.js` (3rd `<button class="response-button neither">` added to yes_no render at line 13796)
- `src/fastapi_app/static/css/notifications.css` (new `.response-button.neither` neutral-gray rule)
- `src/tests/unit/test_stop_hook.py` (4 new `test_neither_*` methods in `TestExtractQualifierComment`)
- `src/docs/notification-api.md` (3 rows updated: `yes_no` table row at line 895, `ask_yes_no()` tools row at line 1646, example block return-value comment at line 1672)
- `TODO.md` (marked MCP-Neither task ✅ DONE with details; added ☀️ FIRST THING NEXT SESSION for CoSA-context commit + fresh-session E2E verify; refreshed Last-updated)
- `history.md` (this entry)
- `.claude-session.md` (registered session 6d544991 + touched files)
- (outside repo, edited) `~/.claude/CLAUDE.md` (one row updated in Available MCP Tools table at line 322; routing-table label denied by auto-classifier — acceptable, tool-description row is the load-bearing entry)
- (outside repo, plan source) `~/.claude/plans/swirling-watching-hinton.md`

**Files edited in CoSA submodule but NOT committed** (per cross-sub-project handoff):
- `src/cosa/utils/notification_utils.py` — regex extension `(yes|no)` → `(yes|no|neither)`; `format_qualified_response` "neither" branch; `quick_smoke_test` 3 neither parse + 1 neither format cases. Stays in CoSA working tree for next CoSA-context session to commit.

**Status**: Parent Lupin scope ✅ DONE. CoSA scope ⏳ pending CoSA-context-session commit. Fresh CC session ⏳ pending for end-to-end MCP-driven E2E verification.

---

### 2026.05.11 - Session 6e8a6a03 | CC notifications-card normalization — Phase 0 docs + plan-review (all 3 passes) CLOSED; Phase 1 implementation parked READY TO BEGIN

**Persona**: Rachel 🕊️ (calm & clear female, #7B1FA2)

**Accomplishments**:

- **New R&D milestone serialized** at `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/` (4 docs, 665 lines total, all Phase 0 deliverables landed before any code edits per documentation-first protocol):
  - `00-index.md` (141 LOC) — master nav, 9 Q-N FROZEN decisions table, REUSE-table with verification spot-checks, doc-conventions status, idempotency marker stamped
  - `01-design.md` (256 LOC pre-review, ~290 LOC post-review fixes) — full design: context, Q1-Q9 FROZEN, 8 phases (Phase 0/1/2/3/4/4.5/5/6) with EXECUTOR: AI/HUMAN tags, 19 ACs, risks, out-of-scope, REUSE pre-pass anchor
  - `02-handoff-summary.md` (110 LOC) — cross-sub-project handoff for Lupin mobile + multiplexer R&D teams (TL;DR / what changed / why / per-sub-project action / migration timeline / where to ask + 3-tier contact ladder)
  - `90-execution-log.md` (158 LOC pre-review, ~280 LOC post-review evidence) — phase status table, per-phase scaffolds, REUSE + Pass 1 + Pass 2 closure sections

- **`/plan-review` gate fully CLOSED 2026-05-11** — all 3 passes sequential per Q7, zero parallel dispatch:
  - **REUSE pre-pass**: 8 findings (4 reuse-as-is + 1 extend-existing + 3 genuinely-new). 3 fixes applied: elevated `.cc-retired-banner` CSS orphan cleanup to explicit Phase 1.8 + AC1.5; updated 00-index REUSE table with verbatim file:line spot-checks (notifications.js:2870-2949 research handler shape confirmed; notifications.html:272/319/381/441 sibling status divs confirmed; JobStore.ts:215 agent-agnostic confirmed; FastAPI 0.115.12 stacked-decorator support confirmed); added Risk row for `deprecated=True` repo novelty.
  - **Pass 1 Fitness**: 11 findings (0 Block / 4 Major / 7 Minor / 0 L3). 8/11 applied: M1 (Q8 verdict gate pinned to Phase 5.3) + all 7 Minors (function-name fossil note, literal mobile TODO entry shape, "one release cycle" tightened to v0.1.8+ trigger, WHO-to-contact 3-tier ladder, mobile TODO tag `[LUPIN-CC-SUBMIT-RENAME]` + section, backend coverage scope clarification, dropped `include_in_schema=False` so alias appears in OpenAPI as `deprecated: true`). M2/M3/M4 user-skipped.
  - **Pass 2 Adversarial**: 7 findings + 1 swept pattern offender (0 Block / 5 Major / 2 Minor / 0 L3). All 8 applied: A1 (AC11 visual baseline criteria falsifiable with pytest count + diff allow-list), A2 (AC5 "manual submit" → programmatic), A3 (Two-phase E2E gate `EXECUTOR: HUMAN` tag with same-line justification), A4 (Phase 6.8 `EXECUTOR: AI` + explicit 13-file allow-list), A5 (Phase 6.9 `EXECUTOR: HUMAN` for CoSA commit with nested-repo-boundary justification), a1 (mobile TODO placeholder vs literal clarification), a2 ("manual" metadata in Phase 6.1 + AC13 explained as legacy-item-name), plus swept the same "manual" pattern at Risks row 216 per `feedback_sweep_for_pattern_offenders`.

- **Idempotency marker stamped** in `00-index.md`: `last-reviewed-at: 2026-05-11 (commit c1cec74 — pre-implementation HEAD)`.

- **Zero Layer-3 Design Concerns** across all 3 passes. All 9 Q-N FROZEN decisions stand unchanged.

- **Plan file authored + serialized**: `~/.claude/plans/ok-so-far-so-swirling-pearl.md` (drafted in plan-mode 2026-05-09/10, approved via ExitPlanMode 2026-05-10, serialized into this R&D folder).

- **New auto-memory filed**: `feedback_cross_project_handoff_doc.md` — when a change touches multiple sub-projects (mobile, multiplexer, plugin, CoSA, in-flight R&D), plan must include (1) one concise ~150-line handoff doc and (2) seed TODO entries in each affected sub-project. User-ratified 2026-05-10 during plan-mode walk.

- **Channel switch mid-pass to cosa-voice high-priority action-required UI**: at user request mid-Pass-1, all subsequent gates routed through `mcp__cosa-voice__ask_multiple_choice` with `priority="high"` instead of built-in `AskUserQuestion`, so each plan-review decision surfaces as action-required notification in the UI (user not switching between terminal and browser).

**Files**:
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/02-handoff-summary.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-cc-card-normalization/90-execution-log.md` (NEW)
- `TODO.md` (modified — new "FIRST THING NEXT SESSION — CC Card Normalization Phase 1" section above Mr. Radio's parallel-session Phase 6b section; Last-updated line refreshed)
- `history.md` (this entry)
- 2 NEW auto-memory files (outside repo): `feedback_cross_project_handoff_doc.md`, MEMORY.md index updated
- 1 NEW plan file (outside repo): `~/.claude/plans/ok-so-far-so-swirling-pearl.md`

**Status**: Phase 1 implementation BLOCKED on next-session user go-ahead. Origin plan + R&D folder are self-contained — fresh-context session can pick up by reading the 4 R&D docs in order.

---

### 2026.05.11 - Session 017dc1cc | Multiplexer Phase 6b Pass 1 Fitness CLOSED — 14/14 ratified via action-required UI

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **Pass 1 Fitness ratification walk completed end-to-end** — 14/14 findings ratified across 9 turns (1 Minors batch covering F-8/F-9/F-10/F-11/F-12/F-14 + 8 individual Major walks: F-1, F-2, F-3, F-4, F-5, F-6, F-7, F-13). All firings returned `yes`. Per-decision routing via cosa-voice `ask_yes_no` action-required UI per user directive ("push every decision point into the action-required UI" — much easier to parse than terminal-text gates).

- **All 14 resolutions applied** to `09-phase6b-interactive-widgets-design.md`. Net ~+220 LOC across 8 distinct edit clusters: Boot wiring (mount() is sync addendum, F-12); Inertness-lift contract rewritten as single-write template swap (F-7); new Q-B1 dispatch contract subsection (F-3); Q-B3 state machine extended with `expired_visual` + `responded_default` vertices + Q-B5 ratified text rewritten with local RAF timer + clock-skew handling (F-4); AC table row updates (AC2c MutationObserver assertion, AC2d unit-test contract, AC5/AC5b enumerations, AC7 post-6a baseline, AC10b ceiling 500→700, AC10e command fix); two new AC enumeration sub-tables totalling 34 enumerated cases (AC5 subtotal 21, AC5b subtotal 13); R7 risk row for state-change storm (F-13); Phase 0 prerequisites updated (#3 reword for target API shape, #6 reword for sub-step 4A/4B DOD, NEW #7 for `countdown_expires_at` payload field); new § "Phase 4 sub-step DOD" subsection with explicit DOD tables (8 rows for 4A, 11 rows for 4B) + `JobStore.delete` signature returning `{ restoreState: () => void }` closure.

- **Pass 1 closed subsection** appended to `95-phase6b-review-findings.md` (+~70 LOC): full 9-row ratification record table cross-referencing each finding ID to the resolution applied; doc-state delta summary; convergence re-grep note; updated cycle-state diagram.

- **Pass 2 Adversarial dispatch gated on user go-ahead** per user direction. No auto-progression. The `93-resume-here-phase6b-pass1-ratification.md` file is now historical (left in place as audit trail; can be removed in a future cleanup).

**Files** (parent-Lupin scope only):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (status header + 14 finding resolutions applied)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` (NEW "Pass 1 Fitness — closed 2026-05-11" subsection)
- `TODO.md` (FIRST THING IN THE MORNING entry replaced with DONE entry + resolution checklist + historical pointer)
- `history.md` (this entry)
- `.claude-session.md` (registered session 017dc1cc + touched files)

**Phase 6b cycle state**:
- Q-decisions ✅ CLOSED 12/12 (2026-05-07)
- REUSE pre-pass ✅ CLOSED 28 RE + 5 L3 (2026-05-07)
- Pass 1 Fitness ✅ CLOSED 14/14 (2026-05-11)
- Pass 2 Adversarial ⏳ gated on user go-ahead
- Code-execution plan ⏳
- Implementation ⏳

**Commits**:
- session checkpoint pending (this commit)

**Caveats / Notes**:
- `history.md` still at CRITICAL token threshold from 2026-05-07 — archival deferred again to avoid interleaving with active parallel session activity (session `f9608a41` last touched 2026-05-11 working inter-session-commons docs). Will revisit when parallel session pipeline is idle.
- Two task-tool reminders fired during the apply-edits phase; both ignored per harness instructions (tasks #1-#9 already correctly tracked the ratification turns; task #10 in_progress through the entire apply phase).
- Parallel session `f9608a41` (inter-session-commons R&D, separate scope) has its own ongoing work — files cleanly isolated from this session's commit per `.claude-session.md` v2.0 selective staging.

---

### 2026.05.09–11 - Session f9608a41 | NEW INITIATIVE: Inter-Session Commons + User-Broadcast — Phase 0 + 1 (steps 3a+3b) landed

**Persona**: Tiberius 🌑 (Deep male, #3F51B5)

**Multi-day session spanning 2026.05.09 → 2026.05.10 → 2026.05.11.**

**Accomplishments**:

- **NEW initiative launched: Inter-Session Commons + User-Broadcast Channel**. AI-to-AI blackboard for Claude Code sessions + user→all broadcast surface with persona-aware directive parsing (e.g., "all sessions: /plan-session-end; @Mr. Radio: also push; @Maria: skip commit"). Reuses existing per-session voice-persona system + conv-mode listener-injection pattern + WebSocket fanout infra. Doc-set at `src/rnd/v0.1.7/2026.05.09-inter-session-commons/`.

- **Phase 0 CLOSED — 15 Q-decisions ratified** (Q1 free-form + reserved topic registry; Q1b full reserved set: broadcast-acks + presence + system-events; Q2 silent unless priority=high; Q3 defer file-locks to Phase 5; Q4 24h active + indefinite archive; Q5 free-text + `@PersonaName:` syntax; Q6 non-blocking + live aggregate; Q6b both sync + async with naming alignment to project's `_sync`/`_async` convention; Q7 manifest orthogonal; Q8 case-insensitive + punctuation-tolerant matcher + LLM-fallback stub; Q9 follow @all only when persona missing; Q10 confirm dialog; Q11 1/30s rate limit; Q12 JWT-only; Q13 reject empty body; Q14 200 with no-active-sessions status; Q15 markdown from day one). Three architectural principles captured: commons is INTRA-AI; user-as-witness not middleman; sync/async naming consistency.

- **Full plan-review pipeline (REUSE → Pass 1 Fitness → Pass 2 Adversarial) CLOSED**. REUSE: 12 findings (8 reuse-as-is, 3 extend-existing, 1 genuinely-new fcntl with documented justification — `session_bridge.py:1022-1026` no-fcntl is a NUANCED choice for idempotent read-modify-write JSON, NOT a project-wide policy; commons appropriately diverges for append-only non-idempotent posts). Pass 1: 20 fitness findings across all 8 deficiency types ratified + applied. Pass 2: 13 ownership-language findings + 5 design concerns (2 auto-resolved by Cluster A's AI-spawn-subprocess insight) ratified + applied. Plan APPROVED for code-write 2026-05-11.

- **Path correction during walks: storage at `<project_root>/io/commons/`** (was `commons/` at root; user caught it). `io/` already gitignored at `.gitignore:68` — no separate exclusion needed.

- **100% coverage mandate** ratified for commons (commons-only scope per C3; multiplexer-only memory unchanged). Coverage tooling: pytest-cov 7.1.0 + coverage 7.14.0 installed in cosa venv + added to `pyproject.toml` dev deps + `uv.lock` regenerated cleanly (only 2 deps added, 55 lines, torch/flash-attn lock UNTOUCHED) + Docker candidate image `lupin:1.0.0-pytest-cov` built (6ff1643d8796, 31.7GB) but **NOT promoted** per the no-auto-promote-tags feedback memory.

- **Phase 1 implementation steps 3a + 3b CLOSED with 100% coverage**:
  - `src/lupin_mcp/commons_persona_matcher.py` (91 LOC) + 12 unit tests + 100% coverage. Case-insensitive + punctuation/space-tolerant mechanical matcher with stable LLM-fallback hook (Phase 3 wires the actual call).
  - `src/lupin_mcp/commons_store.py` (332 LOC) + 36 unit tests + 100% coverage. CommonsStore class with `post()` / `read()` / `who()`, YAML frontmatter, inline JSON metadata, POSIX `fcntl.flock` for multi-writer safety.
  - **AC10b real-fcntl stress test PASSED**: 5 child processes × 100 posts each = exactly 500 entries in the topic file, zero corruption, all sessions represented. Empirically validates the F6 fcntl ratification.

- **Cross-repo follow-up filed** at `planning-is-prompting/TODO.md`: after Lupin lands the 5 commons MCP tools, audit + update consumer-facing documentation in every repo that references the cosa-voice MCP tool catalog (Lupin CLAUDE.md, src/docs/, planning-is-prompting workflow docs, cosa-voice-notifications skill, etc.).

- **Phase 1 step 3 is a natural session boundary.** Steps 4-8 remain: archival daemon (step 4), 5 MCP tool registrations (step 5), INI keys (step 6), 2-session smoke (step 7), AC12+AC14 subprocess verifications (step 8). Resume pointer at `91-resume-here-phase1-step4.md`.

**Files** (parent-Lupin scope only; no CoSA edits per Phase 1 §4):

- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/01-design.md` (NEW + Phase 0 ratifications + §4.1.1 ask threading + §4.2 empty-match)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/02-phase1-file-commons-design.md` (NEW + REUSE §11 + Pass 1 + Pass 2 applied)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/90-execution-log.md` (NEW)
- `src/rnd/v0.1.7/2026.05.09-inter-session-commons/91-resume-here-phase1-step4.md` (NEW)
- `src/lupin_mcp/commons_persona_matcher.py` (NEW)
- `src/lupin_mcp/commons_store.py` (NEW)
- `src/tests/unit/commons/__init__.py` (NEW)
- `src/tests/unit/commons/test_commons_persona_matcher.py` (NEW)
- `src/tests/unit/commons/test_commons_store.py` (NEW)
- `pyproject.toml` (pytest-cov added to dev deps)
- `uv.lock` (regenerated)
- (Outside repo, planning-is-prompting) `TODO.md` (cross-repo follow-up filed)

**Commits**: none yet — held for explicit user authorization per the `feedback_never_auto_commit_push` memory.

**Docker**: `lupin:1.0.0-pytest-cov` candidate built; `lupin:1.0.0` working tag UNTOUCHED. User decides when/if to promote.

**Caveats / Notes**:
- Phase 1 plan is the deliverable from the plan-review pipeline; code-write is partial (steps 3a + 3b only).
- No `:8000` Phase 1 tests scheduled (none needed — AC10/AC10b/AC11 are all `:7999` AI-discretionary).
- Voice persona color confirmed as immutable per-allocation by user (parallel to Sam-voice fallback for missing voice data) — design coherence with the per-session-voice-personas immutability invariant.

---

### 2026.05.07 - Session e8228026 | Multiplexer Phase 6a final closure on :8000 + Phase 6b planning launched (Q-decisions + REUSE done; Pass 1 paused)

**Persona**: Mr. Radio 🦉 (authoritative warm male, #FFA000)

**Accomplishments**:

- **Phase 6a fully CLOSED on both `:7999` and `:8000`** — AC11a baseline captured (job `ts-b786315c`, 13:59 EDT, PNG at `io/test-suite/visual-baselines/test_multiplexer_phase6a_visual/`) + AC11b regression GREEN (job `ts-bd34af9b`, 1 passed in 5.6s, 14:48 EDT, `-k` filter honored: 398 deselected / 1 selected). Discovery: visual baselines are gitignored under `io/` (`.gitignore:68`), so the baseline lives host-only and bind-mounts into the test container; no commit needed for the PNG.

- **Two `/api/test-suite/submit` silent-drop traps caught + documented as durable memories**:
  - `test_types="e2e_ui"` → silently dropped to 0/0/0/0 (no HTTP error). Use `"e2e"`. Memory `feedback_test_types_e2e_not_e2e_ui.md`.
  - Pydantic field is `pytest_args` (NOT `args`). v2 silently ignores unknown fields → submit body's `"args"` was dropped → full 23-min sweep ran instead of `-k` filtered. Memory `feedback_test_suite_submit_field_pytest_args.md`. Both `TODO.md` AC11a/AC11b entries fixed at source so the next session doesn't re-hit either trap.

- **Phase 6b planning launched** — design doc `09-phase6b-interactive-widgets-design.md` (NEW, 289 LOC) at canonical R&D path. 12 Q-B decisions across 4 clusters (submit semantics, TTS chrome, delete-button, boot/CSS/scope) ratified via cosa-voice walkthrough. Q-B6 corrected mid-walk: per-notification corner buttons belong in 6b not 6c per slicing manifest line 46.

- **REUSE pre-pass closed** — 28 RE-rows (16 reuse-as-is / 9 extend-existing / 3 genuinely-new) + 5 Layer-3 concerns ratified via 4-batch cadence. **C-4 confirmed empirically**: `JobStore.delete(idHash)` does NOT exist (only `indexById.delete(id)` internal Map call at `JobStore.ts:292`). Phase 6b Phase 4 must split into sub-step 4A (extend JobStore + 100% c8 tests) + 4B (wire delete-button click handler). AC table grew: AC2d (JobStore.delete grep + tsc guard), AC5c (delete-button extension tests ≥6 cases), AC10e (cross-phase count-cascade regression).

- **Pass 1 Fitness dispatched** — clean-context Explore agent, 14 findings (0 Block / 9 Major / 5 Minor / 0 Layer 3). Ratification PAUSED at user break point. F-1 caught a real bug in my own doc work — AC10b said `tts-chrome.css ≤500` but Q-B12 ratified `≤700`. Resume via `93-resume-here-phase6b-pass1-ratification.md` (NEW, 109 LOC).

- **Phase 6b cycle state**: Q-decisions ✅ → REUSE ✅ → Pass 1 ⏸️ paused → Pass 2 ⏳ → code-execution plan ⏳ → implementation ⏳.

**Files** (parent-Lupin scope only):
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/09-phase6b-interactive-widgets-design.md` (NEW, 289 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/95-phase6b-review-findings.md` (NEW, 156 LOC)
- `src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/93-resume-here-phase6b-pass1-ratification.md` (NEW, 109 LOC)
- `TODO.md` (AC11a/AC11b field-name fixes + 2026.05.08 morning section)
- `history.md` (this entry)
- 2 NEW auto-memory files (outside repo): `feedback_test_types_e2e_not_e2e_ui.md`, `feedback_test_suite_submit_field_pytest_args.md`

**Commits**:
- `243267b` — Phase 6a AC11a/AC11b CLOSED: TODO.md test-suite submit field-name fixes
- `d70be64` — Phase 6b planning checkpoint: Q-decisions + REUSE closed; Pass 1 paused at break point
- session-end commit pending (this entry)

**Caveats / Notes**:
- `history.md` remains at CRITICAL token threshold (~22.4k). Archival deferred per user direction earlier this session because parallel session 6825e6af (María) had uncommitted edits at that time. Carried forward to 2026.05.08 morning section in `TODO.md`.
- Phase 0 prerequisites for Phase 6b implementation (verified at code-execution plan time): `DELETE /api/queue/<bucket>/<id>` exists ✅; `multiSelect` payload, `AudioStore.currentNotificationIdHash`, action-required mount surface, CoSA `multiplexer_config.py` commit, `JobStore.delete(idHash)` — all pending verification.
- Parallel session 6825e6af (María 🌸) committed her own work (`4d2579f`) mid-session; her files cleanly isolated from my commits per parallel-session-safety v2.0.

---

### 2026.05.07 - Session 6825e6af | Bug Fix Mode — Notification 503 cascade reconciliation

**Persona**: María 🌸 (warm, inquisitive female)

**Context**: User opened a bug-fix session and asked to claim "Notification 503 cascade for offline users in expediter flow" (currently In Progress with stale owner 45e6bf84 — that session closed 2026-05-05T23:25). User flagged: "I thought that we had fixed it already." First task is reconciling the bug-queue entry against actual prior fixes before deciding scope.

### Fixes

#### Reconciliation — "thought we fixed it already"

User's recollection was substantially right: session 45e6bf84 on 2026-05-05 (commit `24e4731` + checkpoint `621be65`) completed Phases 0-4a of a real root-cause fix. The May-1 bug-queue framing ("client doesn't set `response_default`, 4 fix options") was disproved on May-5 — quote from `01-design.md`: "The fix is in the test harness, not the expediter or the server." Real root cause was **silent proxy startup failure**; May-5 made `_start_proxy` raising-on-failure + made all 7 callers abort on failure. Phase 4b on `:8000` was prepared but never ran — a NEW bug surfaced ("`pytest --auto-proxy` is a no-op — `pre_run_hook` never fires under pytest discovery") and was filed Queued. The In Progress entry stayed open because the new bug blocked Phase 4b's pytest path.

User chose **Path B**: fix the new pytest bug FIRST, then run Phase 4b through the canonical pytest path. Both bug-queue entries close together on AC11.

#### Phase 5 — pytest fixture wiring (CODE + :7999 VERIFY DONE)

- **R&D doc**: appended Phase 5 section to `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` + `90-execution-log.md`. Documents why module-scoped (not session-scoped — different test files have different `PROXY_PROFILE`) and why we did NOT take the alternative of wiring through pytest entry points.
- **Code (parent repo only — no CoSA edits)**:
  - `src/tests/smoke/conftest.py` — new module-scoped autouse fixture `_auto_proxy_for_module` + registered `--proxy-debug` CLI option. Fixture introspects test module for `EmbeddedProxyMixin` subclass DEFINED in the module (filter `obj.__module__ == module.__name__` to skip imported parents like `InteractiveSmokeTest`), instantiates it, calls `_start_proxy(...)` with env-var creds, and `pytest.fail(..., pytrace=False)` on `RuntimeError` to prevent cascade. Cleanup via `_stop_proxy()` at module teardown.
  - `src/tests/smoke/test_auto_proxy_fixture.py` (NEW) — regression test for the fixture; asserts `"auto proxy"` session is registered in `/api/debug/websocket-state` with a non-empty user mapping. Marker class `AutoProxyFixtureProbe(EmbeddedProxyMixin)` drives the fixture (profile=`deep_research`).
- **Class introspection sanity** across all 6 affected test modules picked the right concrete subclass: `ProxyIntegrationTest`/`proxy_integration_test`, `ExpeditorSmokeTest`/`expeditor_smoke`, `SweTeamProxySmokeTest`/`swe_team`, `PresentationLiveSmokeTest`/`presentation_gates`, `ResearchToPresentationLiveSmokeTest`/`research_to_presentation_gates`, `PresentationRenderOnlySmokeTest`/`presentation_gates`.
- **AC9 happy-path on `:7999`**: `pytest src/tests/smoke/test_auto_proxy_fixture.py --auto-proxy -v -s` → **1 passed in 2.19s**. Proxy registered as UUID `50c73ba7-36dd-4eaf-a7e2-63256252c84f` (matches the test-user UUID quoted in May-5 design doc).
- **AC10 sad-path on `:7999`**: same command with `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD=wrong-password` → **1 error in 32.33s**, `ERROR at setup of test_fixture_started_proxy`. Test body never executed (cascade prevention contract honored). pytest reported as setup ERROR not assertion FAILED — correct distinction.

#### Phase 3 — `:8000` Phase 4b scheduling (DONE)

User authorized immediate slot. First submission `ts-f04eed7f` failed at startup (exit=4) because `pytest_args = "-k 'expr1 or expr2 or expr3'"` got `.split()` on whitespace — pytest received `'expr1`, `or`, `expr2'`, etc. as positional args and crashed with `ERROR: file or directory not found: or`. Resubmitted as `ts-e6bb533b` using 55 `--ignore=src/tests/smoke/<file>.py` tokens to narrow the smoke run to 4 keepers (`test_proxy_integration`, `test_expeditor_mock_job_smoke`, `test_swe_team_proxy`, `test_auto_proxy_fixture`). `--auto-proxy --cost-cap-usd 5.00` auto-injected via INI key (Cluster B from 2026-04-30 post-mortem) — confirmed in the running pytest argv.

Pre-flight: `preflight-test-container.sh` PASSED (all probes green). Direct container inspection confirmed bind-mount visibility: container saw the new fixture (`grep _auto_proxy_for_module conftest.py = 3 matches`) and the new test file (`test_auto_proxy_fixture.py` with today's mtime). No bounce required. `:8000` pool clean before submit (0 inflight, 0 pending).

#### Phase 4b — :8000 cascade-elimination (DONE — AC11 GREEN)

- **Job**: `ts-e6bb533b::50c73ba7-...`
- **Started**: 2026-05-07T15:23:40 EDT
- **Completed**: 2026-05-07T16:11:10 EDT
- **Duration**: 47:27 (2847.86s)

| Test | Result | Duration | Notes |
|------|--------|----------|-------|
| `test_auto_proxy_fixture::test_fixture_started_proxy` | ✅ PASS | <1s | Fixture regression test green |
| `test_expeditor_mock_job_smoke::test_expeditor_mock_job_smoke` | ✅ PASS | 1620.93s (27 min) | All scenarios green |
| `test_swe_team_proxy::test_swe_team_proxy` | ✅ PASS | 383.92s (6.4 min) | All scenarios green |
| `test_proxy_integration::test_proxy_integration` | ❌ FAIL | ~13 min | 14/15 scenarios pass; **scenario 15 EXP_RTPRES_MISSING failed for an UNRELATED REASON** — voice-routing classifier mis-routes "research something and present it" → `deep_research` instead of `research_to_presentation` |

**AC11 verification — zero `http_error_503`**:

| Source | Count |
|--------|-------|
| Run log `/tmp/smoke-20260507-201109.log` | grep `http_error_503` / `HTTP 503` / `User cancelled` / `503 Service` → **0 hits** |
| `lupin-rest-test` container logs (last 50 min) | grep `503` → 5 false positives, ALL source-port substrings (`127.0.0.1:45030`, `:45032`, etc.); zero actual HTTP 503 responses |
| Proxy subprocess stats (final) | `Notifications Received=90, Responses Sent=19, Script Matcher Used=17, LLM Used=2, Skipped=71, Errors=0` |

**Cascade is eliminated.** Both bug-queue entries close.

**Per-module fixture evidence** captured mid-run:
```
python3 -m pytest src/tests/smoke/ -v --ignore=... --auto-proxy --cost-cap-usd 5.00
└── python3 -m cosa.agents.notification_proxy --profile expeditor_smoke ...
```
The `--profile expeditor_smoke` matches `ExpeditorSmokeTest.PROXY_PROFILE` for that module — proof that `_auto_proxy_for_module` correctly introspects the test class and starts the right proxy per module.

#### Bug-queue updates

- ✅ "Notification 503 cascade for offline users in expediter flow" → **CLOSED** (resolved 2026-05-07 by 6825e6af; annotated In Progress entry with full closure evidence + folded into details)
- ✅ "`pytest --auto-proxy` is a no-op — `pre_run_hook` never fires under pytest discovery" → **CLOSED** (resolved 2026-05-07 by 6825e6af; annotated Queued entry with closure evidence)
- 🆕 **NEW Queued entry filed** (per TEST OWNERSHIP MANDATE): "Voice-routing classifier mis-routes 'research something and present it' → deep_research instead of research_to_presentation" — surfaced during Phase 4b run, NOT a regression of the cascade fix.

### Session Summary

**Outcome**: Two bug-queue entries closed in one session, one new bug filed.

- **Notification 503 cascade for offline users in expediter flow** — RESOLVED. May-5 (45e6bf84) landed Phases 0-4a (test-harness raise-on-failure + 7-caller abort). May-7 (6825e6af) landed Phase 5 (module-scoped pytest fixture closing the pre_run_hook gap). Phase 4b on `:8000` (job `ts-e6bb533b`, 47:27 runtime) verified zero `http_error_503` / 0 proxy errors / 90 notifications received / 19 responses sent.
- **`pytest --auto-proxy` is a no-op** — RESOLVED in same closure. Module-scoped autouse fixture in `src/tests/smoke/conftest.py` introspects test module for the concrete `EmbeddedProxyMixin` subclass (filter `obj.__module__ == module.__name__` to skip imported parents), instantiates it, calls `_start_proxy(...)` with env-var creds, `pytest.fail(..., pytrace=False)` on `RuntimeError`. Cleanup via `_stop_proxy()` at module teardown.
- **Voice-routing classifier mis-route** (NEW) — Queued for future session; pre-existing classifier issue surfaced only because the new pytest-path coverage now exercises Scenario 15 properly.

**Files modified (parent Lupin repo only — no CoSA edits)**:
- `bug-fix-queue.md` — Active Sessions row added; "503 cascade" In Progress entry closed; "pytest --auto-proxy no-op" Queued entry closed; new "voice-routing classifier" Queued entry filed
- `history.md` — this entry
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` — Phase 5 section appended
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/90-execution-log.md` — Phase 5 status + Phase 4b evidence
- `src/tests/smoke/conftest.py` — fixture + `--proxy-debug` option
- `src/tests/smoke/test_auto_proxy_fixture.py` (NEW) — fixture regression test

**Status**: All work complete. Awaiting user `commit` authorization. No commits made automatically.

#### Checkpoint | 2026.05.07 20:15 | 503 cascade fix (Phase 5) + Phase 4b verification + bug-queue closures

**Files** (6 in Lupin parent + manifest):
- `src/tests/smoke/conftest.py` (modified — fixture)
- `src/tests/smoke/test_auto_proxy_fixture.py` (NEW)
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md` (Phase 5 section)
- `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/90-execution-log.md` (Phase 5 + Phase 4b evidence)
- `bug-fix-queue.md` (closures + new Queued entry)
- `history.md` (session entry — this file)
- `.claude-session.md` (manifest section for 6825e6af)

**Commit**: 4d2579f

#### Checkpoint | 2026.05.07 23:00 | Bounded ClaudeCodeJob redesign — plan approved + serialized + REUSE closed + Pass 1 partial (4/11)

**Topic shift mid-session**: After bug-fix work landed at `4d2579f`, user pivoted to a proactive redesign of the BOUNDED `ClaudeCodeJob` to bring it to canonical agentic-job shape. Sequence:

1. **Investigation** — surveyed retired `/api/claude-code/dispatch` cluster (closed 2026-05-05 by `73bee1b`); audited current `src/cosa/agents/claude_code/` (4 of 8 canonical files; missing `config.py`/`state.py`/`orchestrator.py`/`__main__.py`); gold-reference is `src/cosa/agents/deep_research/`.
2. **Plan mode** — drafted at `~/.claude/plans/so-it-looks-like-silly-map.md`; user revised twice (rejected facade-wrap in favor of relocation of `cosa/orchestration/claude_code/` → `cosa/agents/claude_code/`; added cross-agent regression contract after flagging TFE/BFE possible dependency, which Explore agents verified is zero-deps today). Approved via ExitPlanMode.
3. **Serialization** — Phase 0 docs landed at `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/{01-design.md,90-execution-log.md}`.
4. **Plan-review install** — `/plan-install-wizard` (mode=install) added `/plan-review` slash command to `.claude/commands/plan-review.md` with Lupin-specific customization (project=Lupin, prefix=[LUPIN], `:7999`/`:8000` venue notes, CoSA git boundary callout, auto-memory feedback-loop callout).
5. **Convention amendment** (pre-flight to plan-review): created `00-index.md` (master nav + idempotency marker home + Prior art referenced section + Open follow-ups) and `00-working-contract.md` (Layer 2 anchor — test-layer enumeration, user-involvement gate, cannot-execute rule, phase-complete definition). Reformatted `01-design.md` decisions as `Q1`/`Q2`/`Q3 FROZEN 2026-05-07` with Question/✅ Decision/Rationale/Implication structure. Added 42 `EXECUTOR: AI / HUMAN <reason>` tags throughout Phase 6 + Phase 7 + Verification section. All 5 conventions satisfied (Convention 5 false-positive Manual hits skip-logged in `00-index.md`).
6. **REUSE pre-pass (§4)** — single Explore agent grep against `src/cosa/` + `src/fastapi_app/` + `src/tests/`. 18 findings; 4 user decisions via `AskUserQuestion`: F#3 reframe `ClaudeCodeRunResult` as rename-from-`TaskResult`, F#8 INI namespace `claude code bounded job *` (anticipates future `claude code interactive job *`), F#18 `Task`/`TaskType` to `state.py`, applied F#4 + SDK_AVAILABLE re-export + #16 deferral. Convergence ✓.
7. **Pass 1 Fitness (§5)** — single Explore agent. 11 findings + zero TBDs + zero Layer-3 Design Concerns. **STRUCTURAL batch (4/4) closed via single-finding `ask_yes_no` ratification** with conversation-mode voice gates: F1 atomic-rename approach (no shim — user surfaced the overengineering), F4 canonical "all args on `__init__` + parameterless run methods + job-level routing" matching Podcast `do_all_async`/`do_review_only_async`/`do_audio_only_async` pattern (user's qualifier "how does this affect bounded vs interactive dispatch?" surfaced the cleanest answer), F8 `stream_thoughts_to_voice` removed (vestigial copy-paste), F10 baseline timing re-targeted "BEFORE Phase 1" (Phase 2a relocation could leak into siblings).
8. **Pass 1 SUSPENDED at 7 remaining findings** (4 implementation-completeness + 3 operational). Resume with `/plan-review --from=fitness`. Detail in `90-execution-log.md` § "Pass 1 — Fitness — ⏸️ PARTIALLY CLOSED 2026-05-07; SUSPENDED at 4/11 findings applied".
9. **Filed**: TODO entry for `cosa-voice ask_yes_no()` to grow a "Neither" / "Discuss further" button — surfaced because the user wanted to qualify a yes mid-flight ("yes BUT how does this differ from existing patterns?") and the only tool today is comment-text on the chosen answer.

**Files** (this checkpoint, all Lupin parent — no CoSA edits):
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-index.md` (NEW)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/00-working-contract.md` (NEW)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/01-design.md` (NEW; serialized + heavily restructured during plan-review amendments + REUSE/Pass-1 fixes)
- `src/rnd/v0.1.7/2026.05.07-claude-code-bounded-redesign/90-execution-log.md` (NEW; phase status table + REUSE closure + Pass 1 partial breadcrumbs)
- `.claude/commands/plan-review.md` (NEW; installed via `/plan-install-wizard`)
- `TODO.md` (modified — neither-button feature request appended to Pending section)
- `.claude-session.md` (manifest section — touched-files entries added)
- `history.md` (this file — this checkpoint)

**Commit**: c1cec74

---

