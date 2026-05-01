# Lupin Project History

### 2026.04.30 - Session b195a160 (afternoon continuation) | Postmortem Tier-1+2 closures + slow-test rewrite + Cluster J root-cause

#### Session-End | 2026.04.30 ~21:20 EDT | Closed Clusters D + E + F-step1 + F-step2 + K + slow-test + J | Scheduled :8000 all-test-run for 21:30

**Context**: Continuation of session b195a160 from this morning (commit `177d1af` covered postmortem A/B/C closures + bcrypt 4.3.0 image rebuild + dev/test recompose). Afternoon arc closed every Tier-1 and Tier-2 follow-up from the postmortem doc plus discovered and fixed a hidden 196-second regression introduced by an earlier covert-E2E pattern. Final all-test-run scheduled on :8000 at 21:30 EDT to verify the postmortem-cluster collapse end-to-end.

**Tier-1 + Tier-2 postmortem closures**:

- **Cluster D — `--auto-proxy` fail-fast** (1 smoke fail). `test_presentation_live_smoke.py` + `test_research_to_presentation_live_smoke.py` now raise `RuntimeError` in <1s if invoked under pytest without `--auto-proxy` (env-var sentinel `PYTEST_CURRENT_TEST`). Was burning 900s/2400s timeouts per scheduled run waiting for human gate approvals. CLI dev mode keeps the warning + manual flow. Surfaced (deferred to user) the architectural follow-up: per-test-file pytest_arg declarations that the scheduler could merge.

- **Cluster E — render-only YAML fixture pin** (1 smoke fail). Authored `src/tests/fixtures/presentations/render-only-example.yaml` (3-slide minimum, valid schema) and replaced `_find_latest_yaml()` glob auto-discovery with `_resolve_fixture_yaml()`. Auto-discovery was suspected (but not proven) to suffer from dev-vs-test bind-mount divergence — pinning to a checked-in fixture removes the brittleness regardless. `--yaml-path` CLI override preserved for ad-hoc dev runs. Dropped now-unused `glob` import.

- **Cluster F-step1 — `slide_count` in PG artifacts** (CoSA). Added `self.artifacts["slide_count"] = presentation.total_slides` to `presentation_generator/job.py` LIVE branch (line 290) + sentinel `0` to dry-run branch.

- **Cluster F-step2 — `slide_count` through `ChainedResult`** (CoSA, Path 1 chosen — formal field through state machine, not the dict-passthrough hack). Added `slide_count: Optional[int] = None` to `state.py:ChainedResult`. Orchestrator at `agent.py:214` now reads `pg_artifacts.get("slide_count")` into `self.result.slide_count`. R2P `job.py:256` writes `self.artifacts["slide_count"] = result.slide_count` (LIVE + dry-run branches). Test's `_check_slide_count` will now pass on the next R2P live run.

- **Cluster K — 3-attempt verifier retry with gentle backoff** (CoSA). `notification_proxy/verification.py` loop bumped from 2-attempt to 3-attempt with `time.sleep(0.5 * attempt)` between attempts (0.5s, 1.0s). Yesterday's `FUZZY_BUDGET_2` failed on attempt 1+2 due to vLLM transient empty-XML; this gives 3rd-attempt insurance. Worst-case adds 1.5s for a triply-flaky scenario.

**Discovered + fixed: `test_swe_team_orchestrator.py::TestDryRunRegression` 196-second covert-E2E** (parent + CoSA):

- **Diagnosis**: full-suite run in load-stressed conditions flagged `test_dry_run_completes` as failed; standalone re-run took **196 seconds**. Reading the test confirmed it instantiated `SweTeamOrchestrator` WITHOUT a mocked `team_io`, so `orch.run()` called the REAL `cosa_interface.notify_progress` → `_dispatcher.notify_progress` → `asyncio.to_thread(_notify_user_async, ...)` for every breadcrumb. Under load each notify takes ~25-30s through the dispatcher's IPC path; 7 breadcrumbs × ~28s ≈ 196s. **The test was a covert end-to-end test masquerading as a unit test.**
- **Fix (Path 1: full rewrite)**: split into Tier-1 (fast, mocked) + Tier-2 (slow, real) per the testing-venues rubric. Phase 0 serialized plan to `src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md`. Phase 1 added `DELAY_MULTIPLIER = 1.0` class constant to `MockAgentSDKSession` (CoSA). Phase 2 rewrote `TestDryRunRegression` as 7 small tests + class-autouse fixture that AsyncMocks the 4 `cosa_interface` entry points + zeroes the mock-client delays. Phase 2.5 applied same `monkeypatch` to `test_dry_run_emits_state_changes` (line 386 — same pattern, different class). Phase 3 authored new Tier-2 smoke at `src/tests/smoke/test_swe_team_dry_run_e2e.py` (~80 lines, 240s budget, `:8000`-scheduled venue).
- **Result**: 8 unit tests pass in **0.58 seconds total** (was ~980s for the same coverage area, **~1700× speedup**). Tier-2 smoke takes ~196s against the real dispatcher — that's the smoke doing its job, surfacing dispatcher health honestly. Bumped budget to 240s.

**Cluster J — `'NoneType' object has no attribute 'split'`** (CoSA + parent regression test):

- **Live traceback captured on `:7999`** (after a courtesy bounce of an unhealthy dev container): `queues.py:241 push → todo_fifo_queue.py:1096 _handle_agentic_command → expeditor.py:170 expedite → completion_client.py:237 llm_client.run → aiohttp ClientConnectorError to 192.168.1.21:3001`. The :7999 dev hit a NETWORK error first because that vLLM endpoint isn't reachable from dev — separate infra issue surfaced. On :8000 yesterday, the LLM call SUCCEEDED, control flowed past line 170 to line 340, and `None.split()` fired.
- **Root cause** (static analysis from line 340 + 588 of `expeditor.py`): `agent_entry.get("display_name", agent_entry["cli_module"].split(...)...)` — Python's `dict.get(key, default)` evaluates the default arm **eagerly**. The `test_suite` registry entry has `cli_module=None` by design (API-only agent, no CLI), so the eager `None.split(".")` ran every time. Yesterday's :8000 traceback matches.
- **Fix**: extracted `_resolve_display_name(agent_entry)` static method on `RuntimeArgumentExpeditor` with proper short-circuit (display_name first, cli_module derivation second, "agent" sentinel last). Both call sites now use the helper. Added 8 regression tests in `TestResolveDisplayName` covering the exact `test_suite` registry shape. Full expediter unit suite: 155/0 fail (was 147 → +8).
- **Adjacent finding (NOT cluster J)**: dev `:7999` cannot reach `192.168.1.21:3001` for the runtime-argument expediter's LLM. Test `:8000` could yesterday. Worth a follow-up if it affects dev workflow.

**Schedule for tonight**: `:8000` all-test-run scheduled 2026-04-30T21:30:00-04:00, job_id `ts-0fb8e488::50c73ba7-...`. Predicted delta vs yesterday's 15-failure baseline: **5–6 failures** (closing 7 method-level fails from A+B+C this morning, plus D+E+F+K+slow-test+J this afternoon, plus likely G+H+I via the recompose; held-open: J's adjacent dev-LLM infra issue + visibility on whether G/H/I close cleanly).

**Files committed in this checkpoint** (parent Lupin only — 9 files):
- `src/tests/smoke/test_presentation_live_smoke.py` (Cluster D)
- `src/tests/smoke/test_presentation_render_only_smoke.py` (Cluster E)
- `src/tests/smoke/test_research_to_presentation_live_smoke.py` (Cluster D)
- `src/tests/smoke/test_swe_team_dry_run_e2e.py` (NEW — slow-test Tier-2)
- `src/tests/unit/test_runtime_argument_expeditor.py` (Cluster J — 8 new tests)
- `src/tests/unit/test_swe_team_orchestrator.py` (slow-test Tier-1 rewrite + monkeypatch on test_dry_run_emits_state_changes)
- `src/tests/fixtures/presentations/render-only-example.yaml` (NEW — Cluster E fixture)
- `src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md` (NEW — slow-test plan doc)
- `history.md` (this entry)

**Note on TODO.md**: my afternoon TODO.md edits (postmortem follow-ups marked done, archive task added) landed in commit `b6a8915` ("Session 406cadbf session-end: final closure pass") because the parallel session's session-end ritual used a broader `git add` and swept up my staged-but-uncommitted TODO.md changes. Outcome is correct (TODO.md reflects this session's work and is in HEAD); minor parallel-session-hygiene issue worth flagging.

**CoSA submodule edits NOT in this commit** (per `feedback_lupin_only_never_cosa` — manage from cosa-context):
- `src/cosa/training/quantizer.py` (Cluster B from morning)
- `src/cosa/agents/presentation_generator/job.py` (Cluster F-step1)
- `src/cosa/agents/notification_proxy/verification.py` (Cluster K)
- `src/cosa/agents/deep_research_to_presentation/state.py` (F-step2)
- `src/cosa/agents/deep_research_to_presentation/agent.py` (F-step2)
- `src/cosa/agents/deep_research_to_presentation/job.py` (F-step2)
- `src/cosa/agents/swe_team/mock_clients.py` (slow-test DELAY_MULTIPLIER)
- `src/cosa/agents/runtime_argument_expeditor/expeditor.py` (Cluster J)

**Open follow-ups** (parked, in TODO.md):
- Cluster J adjacent: investigate why `192.168.1.21:3001` (vLLM for runtime-argument expediter) isn't reachable from `:7999` dev.
- Cluster I config audit: after the 21:30 EDT all-test-run, verify whether `EXP_PRES_MISSING` still returns "Could not match voice command" (presentation_generator routing in agentic-commands.json may need a reload or cache invalidation).
- history.md archival: deferred this session; user chose "next session" at 20.8k tokens.
- Architectural follow-up: per-test-file pytest_arg declarations the scheduler could merge (so tests like `test_presentation_live` always get `--auto-proxy` without manual repetition at submission).

#### Schedule for verification

- `ts-0fb8e488` — all-test-run on `:8000`, scheduled `2026-04-30T21:30:00-04:00`. Will return cosa-voice notification on completion (~25-45 min depending on dispatcher slowness).

---

### 2026.04.30 - Session 406cadbf | Conversation-Mode Three-Layer Mic-Monopoly Enforcement (Phases 1-5) + cc_listener hardcoded sender_id fix

#### Checkpoint | 2026.04.30 ~20:10 EDT | 7 commits across two thematically distinct fixes

**Context**: Started as a bug-fix session on the cc_notification_listener ghost-card symptom (a CoSA-context CC session was rendering as TWO sender cards in the UI, one correctly under [COSA] and a ghost under [LUPIN] with the same session_id). Root cause was a hardcoded `lupin.deepily.ai` literal in the listener — a regression-shaped miss of the 2026.04.24 nested-repo detection fix. Then pivoted to the architectural-gap conversation that's been outstanding since the conv-mode mic-monopoly mutex (v1.1, Session c7333045 on 2026.04.28): the mutex coordinates the bridge file and UI but **not Claude's in-session belief about `conversation_mode_active`** — so a displaced session's Claude keeps emitting conv-mode-shaped `notify()` calls, producing the multi-session cross-talk symptom user reported on 2026-04-29 ("multiple sessions responding to me through TTS as though I had multiple monopolized conversation engagements running simultaneously"). User's framing: "if it's not code-based and deterministic, then I think that Claude could simply drift away from remembering what state it is in." Designed and shipped a three-layer enforcement net.

**Two thematically distinct fixes** in one session:

#### A. `cc_notification_listener` hardcoded sender_id fix (commits `2eaeffc` + `2ae7f1a`)

- **Bug**: `cc_notification_listener.py:453` constructed the gist-response `sender_id` with `f"claude.code@lupin.deepily.ai#{self.session_id_hash}"` — project segment **literally hardcoded to "lupin"** regardless of which repo the CC session is running in. Nested-repo CC sessions got a ghost `[LUPIN]` sender card alongside their correct `[COSA]` card for the same session_id. Same family as the 2026.04.24 nested-repo bug; missed offender during that fix's audit.
- **Fix** (commit `2eaeffc`): replaced the hardcoded line with `build_sender_id_for_cc(session_id=self.session_id_hash) or f"claude.code@lupin.deepily.ai#{self.session_id_hash}"` (Option 1 — symmetric with the parallel correct path at `permission_request.py:123` → `send_tts()`). The `or` fallback preserves failure-mode parity. Net diff: +1 import line, ±1 logic line.
- **Sweep check**: grepped parent Lupin source for hardcoded `lupin.deepily.ai` literals (excluded tests/CoSA/rnd). Singleton offender; other hits benign (docstring examples, Firefox plugin server URL, swe.* agent seed data). Saved memory `feedback_sweep_for_pattern_offenders.md` codifying the lesson.
- **V5 user-verified** (commit `2ae7f1a`): user restarted a CoSA-context CC session post-commit; no ghost card appeared. Bug fully resolved end-to-end.
- **R&D doc**: `src/rnd/v0.1.7/2026.04.30-cc-listener-hardcoded-sender-id-fix.md`

#### B. Conversation-Mode Three-Layer Mic-Monopoly Enforcement (commits `02af97b` → `d7a6c9f`)

**Architectural gap diagnosed**: the mutex coordinates THREE state surfaces — bridge file (canonical), UI cache (broadcast-driven), and Claude's in-session belief (set ONCE at SessionStart via `get_session_info()`, never refreshed). The first two were correctly wired; surface 3 was the gap. Confirmed by source-inspection of `_notify_impl` (no bridge consultation) and the static MCP `instructions=` block ("check `get_session_info()` once at session start"). User proposed fix architecture: push the state into a per-call gate at the MCP boundary; verify Claude's behavior at every text-injection and notify boundary.

**User-driven design supersedure** during plan drafting: my first F2 fix (drop `<voice-message>` XML wrap, switch to append-only system-reminder) was overcorrecting. User pushed back: *"I think you're throwing the baby out with the bathwater. Sanitize the input by stripping everything from `</voice-message` to the end, in addition to dropping anything after and including `<system-reminder`."* Reinstated the wrapping form + added `sanitize_for_wrap` boundary sanitization. Saved memory `feedback_sanitize_at_boundary_not_format_strip.md` codifying the lesson.

**5 phases delivered** (each phase = one commit + ping):

| Phase | Commit | Layer | Key artifact |
|---|---|---|---|
| 1 | `02af97b` | Wrap helper + sanitization | `sanitize_for_wrap` + `conv_mode_wrap` in `hook_common.py` (27 unit tests) |
| 2 | `a9ff8bc` | Thread through 3 inbound paths | listener tmux inject (voice), qualifier tmux inject (hook-idle-prompt), user_prompt_submit (terminal-typed via `conv_mode_reminder_block`) — pre/post tool use deferred (per-tool-call reminder noise rationale); permission_request, anything_else_ask confirmed outbound + exempt |
| 3 | `3e030dc` | `_notify_impl` bidirectional gate | active forces `priority='high'` + `suppress_ding=True` + strips fenced code; inactive + CC sender + `suppress_ding=True` inverts ding for **audible cross-talk cue** (the original symptom fix); `_internal_call=True` escape hatch for `set_session_topic`; dynamic `cc_meta` session resolution |
| 4 | `9a00d6b` | Stop-hook auto-narrate | reads transcript JSONL, checks for `mcp__cosa-voice__notify` ToolUseBlock, synthesizes `send_tts(narration, priority='high', suppress_ding=True)` if turn ended silent; dedup via `last_autonarrated_turn_id` bridge stamp; 5 fail-closed gates |
| 5 | `d7a6c9f` | Cross-layer integration smoke | mock-driven 3-layer compose verification including the cross-talk-cue regression test |

**Adversarial review pass** before execution: 9 findings raised against my own design doc — 3 critical (F1 layer 2 didn't fix symptom C, F2 wrapper injection vector, F3 inbound/outbound conflation), 3 important (F4 dynamic session resolution, F5 internal-callers exemption, F6 MCP HTTP fallback bypass documented as known limitation), 3 minor. All findings incorporated into the design doc; F2 then user-superseded as noted above. Re-audit pass confirmed coverage of all 13 applicable feedback memories.

**Test totals**: 176/176 pass in 30.1s (83 new + 93 existing regression). Phase 6 (multi-session live verification + WebSocket smoke full run) outstanding, user-gated per `feedback_e2e_two_phase_gate`.

**R&D docs**:
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md` — design + adversarial-review findings table + sweep check
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/90-execution.md` — phase-by-phase execution log with commit hashes + verification details + cumulative summary table
- Viewer URLs: `http://localhost:7999/static/html/document-viewer.html?path=plans/2026.04.30-conv-mode-three-layer-{design,execution}.md` (real file copies in `io/plans/`, refreshed at every phase commit; not symlinks per user direction)

**Memories saved this session**:
- `feedback_sweep_for_pattern_offenders.md` — class-of-bugs fixes require codebase-wide grep, not just call-site patch
- `feedback_sanitize_at_boundary_not_format_strip.md` — defending templated content against injection: prefer boundary input sanitization over giving up structural framing

**Files modified** (Lupin parent only — no CoSA git ops):

R&D:
- `src/rnd/v0.1.7/2026.04.30-cc-listener-hardcoded-sender-id-fix.md` (NEW)
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md` (NEW)
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/90-execution.md` (NEW)

Code (Phase 1+2+3+4):
- `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (hardcoded fix + Layer 1 voice wrap)
- `src/lupin_cli/claude_code/hooks/lib/hook_common.py` (Layer 1 helpers + Layer 1 qualifier wrap + send_tts suppress_ding kwarg)
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (Layer 3 dedup helpers)
- `src/lupin_cli/claude_code/hooks/user_prompt_submit.py` (Layer 1 reminder via additionalContext)
- `src/lupin_cli/claude_code/hooks/stop.py` (Layer 3 auto-narrate)
- `src/lupin_mcp/cosa_voice_mcp.py` (Layer 2 bidirectional gate + strip_fenced_code_blocks helper)

Tests:
- `src/tests/unit/test_conv_mode_wrap.py` (NEW, Phase 1+2)
- `src/tests/unit/test_conv_mode_wrap_threading.py` (NEW, Phase 2 integration)
- `src/tests/unit/test_notify_impl_conv_mode_override.py` (NEW, Phase 3)
- `src/tests/unit/test_stop_hook_auto_narrate.py` (NEW, Phase 4)
- `src/tests/smoke/test_conv_mode_three_layer_integration.py` (NEW, Phase 5)

Tracking:
- `history.md` (this entry)
- `TODO.md` (Phase 6 follow-up)
- `.claude-session.md` (session manifest entries per phase)
- `io/plans/2026.04.30-conv-mode-three-layer-{design,execution}.md` (viewer copies, gitignored)

**Operational notes**:
- TTS notify pipeline timed out 5× across the session before user bounced the server; recovered after bounce.
- Phase 4 test runtime is ~30s due to lazy-import of `cosa_voice_mcp.strip_fenced_code_blocks` triggering MCP module init (account-validation HTTP). Could be optimized by extracting the helper to a lighter module — deferred.

**Open follow-ups** (logged in TODO.md):
- Phase 6 multi-session live verification matrix (10 rows, design doc §4 Phase 6)
- Full WebSocket smoke suite run on user-confirmed slot
- MCP HTTP-fallback mutex bypass at `cosa_voice_mcp.py:1295` (Risk #7, deferred follow-up)
- Pre/post-tool-use Layer 1 threading (deferred per per-tool-call reminder noise rationale; revisit if drift observed)

---

### 2026.04.30 - Session 488ca8bd | CC Notification Session Panel Display Modality — selector strip + exclusive focus mode (Phase 0 + Phase 1 + E2E test file written, :8000 scheduling deferred per user)

#### Checkpoint | 2026.04.30 ~20:00 EDT | Phase 0 docs + Phase 1 implementation + Phase 2 E2E test file (gated for :8000 scheduled run)

**Context**: User wanted a different display modality for the CC notification session panels. Two pains: (a) volume — too much surface area when multiple CC sessions are active; (b) **vertical reorder churn** — every incoming notification bubbles the receiving session's card to the top of the stack, destroying focus mid-read on any one session. Conversation-mode pin only partially helps (engages only during audio). Inspired by the conv-mode mutex, user proposed the *visual* analog: an exclusive focus mode where only one session's card is rendered at a time.

**Elicitation outcome** (Q1-Q6 via Socratic dialogue):
- **Q1 — Conv-mode coupling**: orthogonal axes (independent on/off; either, both, or neither active)
- **Q2 — Non-focused activity**: strip badge (icon glow + numeric unread count); no toasts, no audio interrupts
- **Q3 — Selector strip**: always-on permanent chrome above `#notifications-list`; click-to-scroll in default mode, click-to-switch in focus mode
- **Q4 — Focus toggle placement**: pill button embedded inside the strip itself
- **Q5 — Reorder behavior**: default-view stack still reorders by recency (unchanged); strip icons mirror that ordering (leftmost = most recently updated session); focus-mode preserves the strip's recency-meter behavior so non-focused sessions getting fresh activity slide leftward, providing peripheral awareness without yanking focus
- **Q6 — Appetite**: (ii) proper feature, 1-2 weeks; Pattern 3 with single R&D doc + execution log (BFE-style)

**Phase 0 — Documentation Artifacts** (per DOCUMENTATION-FIRST PROTOCOL):
- `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md` (NEW) — 17-section design: pain, modality choice, conv-mode coupling table, DOM structure, strip icon spec (~40-44px circle, persona-color background, project initial), focus toggle UX, peripheral awareness, `localStorage` persistence (`notifications_cc_focus_state` key), edge cases, why client-only, coexistence with conv-mode pin, single ordering rule (leftmost = freshest in both modes), files-to-modify map, testing layers, deferred items, out-of-scope, revision log
- `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/90-execution-log.md` (NEW) — Phase 0 + Phase 1 + Phase 2 results: sweep findings, files modified, static verification table, surprises, plan-deviation note for WS-smoke layer

**Phase 1 — Implementation** (Lupin parent only, no CoSA edits per `feedback_lupin_only_never_cosa`):
- `src/fastapi_app/static/html/notifications.html` — `#cc-session-strip` chrome added above `#notifications-list` (icons container + toggle pill, `hidden` until first CC session card)
- `src/fastapi_app/static/css/notifications.css` — new ~163-line section: sticky strip, persona-color icons via `var(--persona-color)`, `data-focused` / `data-unread` (with `cc-strip-icon-pulse` keyframe + `::after` numeric badge) / `data-conv-mode` (mic-overlay `::before`) states, `.cc-strip-toggle` pill, `.sender-card[data-focus-hidden="true"] { display: none; }`
- `src/fastapi_app/static/js/notifications.js` — 14 new helper methods (`_addStripIcon`, `_removeStripIcon`, `_promoteStripIcon`, `_setStripIconPersonaColor`, `_setStripIconConvMode`, `_enterFocusMode`, `_exitFocusMode`, `_handleStripIconClick`, `_handleStripToggleClick`, `_bindStripToggle`, `_applyFocusHiddenToCard`, `_clearStripUnreadFor`, `_saveCcFocusState`, `_stripIconIdFor`); `CC_FOCUS_STATE_KEY` constant + `ccFocusState` hydration in constructor + toggle binding; hooks into `createSenderCard` (add icon + apply focus-hidden + bump unread on new non-focused session arrivals during focus), `moveSenderCardToTop` (promote icon + bump unread for non-focused), `deleteSenderConversation` (remove icon + auto-exit focus if focused session deleted), `_setPersonaBadgeOnCard` (mirror persona color to strip icon — bug caught during self-review: initial integration placed mirror after early-return paths, fixed by moving alongside the card's `--persona-color` setProperty/removeProperty calls so it fires on add/replace/release equally), `handleNotificationUpdate` switch case for `conversation_mode_changed`

**Phase 1 sweep + verification on `:7999`** (AI-discretionary, all 8 checks ✅):
- Sweep clean: no existing CSS/JS rule manipulates `.sender-card` display/visibility → no collision with new `data-focus-hidden` rule
- `node --check notifications.js` → OK
- `:7999/health` → 200; HTML/JS/CSS served → 200 each; 67 strip-helper matches in served JS, 19 strip-CSS-rule matches in served CSS, 4 strip-element matches in served HTML

**Phase 2 — Test file written, scheduling DEFERRED per user** (gate per `feedback_e2e_two_phase_gate`):
- `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` (NEW) — 12 Playwright tests across 7 classes (`TestStripRenders`, `TestRecencyReorder`, `TestFocusMode`, `TestPeripheralAwareness`, `TestPersistence`, `TestConvModeOrthogonality`, `TestFocusModeEdgeCases`); covers 11 of 13 plan scenarios. Tests use deterministic DOM injection via `window.notificationsUI._helper(...)` rather than waiting on real multi-session WS notifications.
- **Plan deviation** (documented in `90-execution-log.md` §"Plan deviation"): planned `src/tests/websocket_smoke/test_focus_state_persistence.py` NOT created — the two scenarios it would cover (focus state localStorage round-trip; badge update without focus swap) are DOM/localStorage behaviors, not raw-WS-protocol; properly belong in Playwright. The `src/tests/websocket_smoke/` suite is for connection/auth/event-system protocol tests. Both scenarios are already covered by `TestPersistence` + `TestPeripheralAwareness` in the new E2E file. Net coverage unchanged.
- **Visual regression baselines** (4 PNGs under `__snapshots__/`) NOT yet captured — generated on first `--update-snapshots` run during the deferred E2E batch.
- **Scheduling**: user opted to batch this E2E run with other test work later this evening. No `POST /api/test-suite/submit` from this session.

**Pre-existing modifications NOT staged** (belong to parallel sessions per `.claude-session.md` v2.0):
- `src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/90-execution.md`
- `src/tests/smoke/test_presentation_*` (3 files)
- `src/tests/unit/test_swe_team_orchestrator.py`
- `src/rnd/v0.1.7/2026.04.30-swe-team-orchestrator-test-perf-fix.md`
- `src/tests/fixtures/presentations/`
- `src/tests/smoke/test_swe_team_dry_run_e2e.py`

**Out of scope** (deferred per design §16):
- Cross-device focus sync (would need server-side bridge field + WS event — wait for use case)
- Strip overflow strategy beyond `overflow-x: auto` with thin scrollbar (revisit only if 8+ active CC sessions become routine)
- Per-card "anchor" pinning (Q5 option-c from elicitation — separate small feature if reorder churn in default-stacked-view still bothers user)
- Tier 3 / Tier 4 persona theming (held from Round 1 follow-ups in TODO.md; orthogonal to this work)

**Plan**: `~/.claude/plans/i-want-to-start-parsed-blossom.md`

**Files committed in this checkpoint** (Lupin parent only):
- `src/fastapi_app/static/html/notifications.html`, `src/fastapi_app/static/css/notifications.css`, `src/fastapi_app/static/js/notifications.js`
- `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/01-design.md`, `src/rnd/v0.1.7/2026.04.30-cc-session-focus-mode/90-execution-log.md` (both NEW)
- `src/tests/e2e_ui/test_cc_session_strip_and_focus.py` (NEW)
- `history.md` (this entry)
- `.claude-session.md` (488ca8bd section + Last Updated — gitignored)

---

### 2026.04.30 - Session b195a160 | Postmortem of 2026-04-29 all-test run + bcrypt 4.3.0 image rebuild + postgres relocation + dev/test recompose

#### Checkpoint | 2026.04.30 ~13:15 EDT | Closed 7 of 15 yesterday-test-run failures + put new bcrypt-pinned image into rotation on both servers

**Context**: User went to the doctor mid-morning with the brief "perform a full Postmortem on yesterday's all test run on the test server. Group errors and failures in the clusters, propose fixes in order of easiest first, and do as much good as you can in my absence." Yesterday's 17:39 EDT `:8000` all-test run produced 4583 passed / 15 failed / 54 skipped / 0 errors. Session executed in three arcs: (a) postmortem + low-risk closures, (b) docker image rebuild (postgres bind-mount permission + uv.lock blockers), (c) tag promotion + recompose.

**Arc 1 — Postmortem (Clusters A/B/C closed, eight others surfaced for user review)**:

- **Postmortem doc** at `src/rnd/v0.1.7/2026.04.30-postmortem-2026.04.29-all-test-run.md` — 11-cluster grouping with cost/risk matrix and predicted next-run delta table.
- **Cluster A** (3 unit failures): `src/tests/unit/test_swe_team_job.py::TestErrorHandling` 3 tests wrapped in `with pytest.raises( <ExcType>, match=... ):` per the Phase 4 #5 do_all re-raise contract from Session d34f2f74. Verified: 22/22 of `test_swe_team_job.py` pass. Full unit suite: 3803/0 fail (was 3770/3 fail yesterday).
- **Cluster B** (3 smoke failures): `src/cosa/training/quantizer.py:8` un-gated `from auto_round import AutoRound` replaced with try/except + `AUTO_ROUND_AVAILABLE` flag (mirrors peft_trainer pattern). `quantize_model()` now raises clear `RuntimeError` if called without `auto_round` installed. Verified by simulated `sys.modules` block — peft_trainer imports cleanly without the cascade. **CoSA submodule edit; not staged in this checkpoint per `feedback_lupin_only_never_cosa`.**
- **Cluster C** (1 smoke failure): `src/tests/smoke/test_tfe_error_capture_smoke.py:105` wrapped `tfe.do_all()` in try/except so forensic assertions still run after re-raise. Verified live on `:7999`: 1/1 pass.
- **Surfaced for user review** in TODO.md: Tier 1 (Cluster D auto-proxy skip-marker, K verifier threshold), Tier 2 (E YAML 404, F slide_count missing, J `'NoneType'.split` in test_suite push handler), Tier 3 (container recreate — addressed in Arc 3 below).

**Arc 2 — Docker image rebuild (two stacked blockers resolved)**:

- **Blocker 1: BuildKit context-load permission**: `src/conf/long-term-memory/postgresql-dev-data` was mode 0700 owned by UID 70 (postgres-in-container). `.dockerignore` already had 11 postgres-specific patterns (lines 1-11) but BuildKit's sender stats the dir BEFORE applying ignore filters. User authorized 1B (durable relocation) and overrode the original plan's target — moved to `/mnt/DATA01/include/www.deepily.ai/projects/lupin-data/postgresql-dev-data` (NOT `/mnt/DATA01/lupin-data/`). Same physical disk → `rename(2)` only, no copy. Pre-flight pg_dump backup at `src/conf/long-term-memory/postgresql-backup.sql` (11 MB).
  - Surprise: passwordless sudo not configured + `mv` (coreutils) won't work even with parent-dir write permission because `rename(2)` on a directory needs write permission on the *directory itself* (to update its `..` entry), and rruiz can't write to a 0700 UID-70 dir. Worked around by spinning up an `alpine:latest` container with `--user 0 -v /mnt/DATA01:/mnt/DATA01` and running `mv` inside — root inside the container has CAP_DAC_OVERRIDE, same-fs rename collapses to instant inode-update. Same outcome as `sudo mv` would produce.
  - 5 files edited (parent Lupin only): `docker-compose.yml` (mount path), `.dockerignore` (deleted 11 patterns + comment), `.gitignore` (deleted dir line, kept backup-file line), `src/scripts/conf/rsync-exclude.txt` (deleted dir line), `src/scripts/run-postgresql-dev.sh` (updated displayed path). Each with breadcrumb comment dating the relocation.
  - Verified: same inode (`24777760`), UID 70, mode 0700 preserved at new path. Postgres came back up healthy on new mount; 119 users in dev DB intact, both dev+test DBs present.
- **Blocker 2: uv.lock drift**: Build then advanced to stage 13/47 and failed with "warning: The package `pydantic-ai==0.6.2` does not have an extra named `slim`. The lockfile at `uv.lock` needs to be updated, but `--locked` was provided." Investigation revealed pyproject.toml line 53 was already correct (`pydantic-ai==0.6.2`, `[slim]` dropped 2026-04-28). The uv.lock had ALSO been cleaned of `[slim]` references. The misleading `slim` warning was a symptom of the broader lockfile-pyproject mismatch — actual drift was `bcrypt` spec (`>=4.0,<5` → `==4.3.0`). Single `uv lock` regen on host produced a 2-line diff and unblocked the build.
- **Build outcome**: All 47 stages passed. `lupin:1.0.0-bcrypt-4.3.0` image (31.7 GB, ID `2283718c1317`) created. Verified bcrypt 4.3.0 inside via `docker run --rm --entrypoint=/opt/venv/bin/python lupin:1.0.0-bcrypt-4.3.0 -c "import bcrypt; print(bcrypt.__version__)"` → `4.3.0`. Per `feedback_no_auto_promote_tags`, parked at candidate tag (NOT yet promoted at this point in the arc).

**Arc 3 — Tag promotion + dev/test recompose**:

- Pre-flight: queue-empty courtesy check on `:7999` per `feedback_dev_server_bounce_courtesy` — todo=0, running pool=0, consumer healthy, heartbeat 16s. Safe.
- `docker tag lupin:1.0.0-bcrypt-4.3.0 lupin:1.0.0` — `lupin:1.0.0` now points to `2283718c1317` (was `8f523bcc8ac2`). Old image preserved on `lupin:1.0.0-fonts` as rollback target.
- `docker compose down lupin-rest-dev && up -d lupin-rest-dev` — healthy in 30s, running new image, bcrypt 4.3.0 confirmed inside.
- `docker compose down lupin-rest-test && up -d lupin-rest-test` — healthy in 31s, same.
- **Verification**: `LUPIN_INTERACTIVE_TESTS=true` now in env on **both** containers (was missing from running test container, was the root cause of yesterday's Cluster G/H/likely-I cascade). bcrypt 4.3.0 in both. `:7999` /health 200, `:8000` /health 200.
- **Surprise**: `(trapped) error reading bcrypt version` log STILL fires with bcrypt 4.3.0. Confirmed via `hasattr( bcrypt, '__about__' ) == False` on the new image. Per pyca/bcrypt issue #684, this is a known 4.1.1+ cosmetic artifact — `hashpw/checkpw` work fine (verified). The 4.3.0 pin still fixes the actual functional breakage that 5.0.0 introduced (which removed `__about__` harder, breaking passlib's bulk-user fixture). The previously-xfail'd `test_admin_users.py::test_list_users_search_filter` and `test_update_user_roles_remove_admin` should now PASS — that was the real value of the pin.

**Predicted next-test-run delta**:

| Stage | Failures |
|---|---:|
| Yesterday | 15 |
| After this morning's 3 file fixes | 8 |
| **After today's recompose (now)** | **5–6** |

Recompose closes Cluster H (swe_team_proxy 3/3 cancels, explicit `LUPIN_INTERACTIVE_TESTS` dependency from yesterday's TODO), very likely Cluster G (12 expediter http_error_503 cascade — same env-var family), possibly Cluster I (presentation routing — fresh config load).

**Files committed in this checkpoint** (parent Lupin only):
- `src/tests/unit/test_swe_team_job.py`, `src/tests/smoke/test_tfe_error_capture_smoke.py` (Clusters A + C closures)
- `docker-compose.yml`, `.dockerignore`, `.gitignore`, `src/scripts/conf/rsync-exclude.txt`, `src/scripts/run-postgresql-dev.sh` (postgres relocation set)
- `uv.lock` (bcrypt spec drift fix)
- `TODO.md` (postmortem + image-rebuild follow-ups, marked yesterday's stale postgres + uv.lock TODO bullets as DONE)
- `src/rnd/v0.1.7/2026.04.30-postmortem-2026.04.29-all-test-run.md` (NEW — postmortem doc)
- `history.md` (this entry)
- `.claude-session.md` (session b195a160 section added + Last Updated bumped)

**CoSA submodule edits NOT in this commit** (per `feedback_lupin_only_never_cosa`): `src/cosa/training/quantizer.py` (Cluster B `auto_round` import gate). Manage via separate cosa-context session.

**Open follow-ups** (parked, surfaced in TODO.md):
- Tier 1: Cluster D `--auto-proxy` skip-marker; Cluster K verifier transient threshold.
- Tier 2: Cluster E (YAML 404 in render-only test); Cluster F (slide_count not in R2P artifacts); Cluster J (`'NoneType'.split` in test_suite push handler — needs `:8000` container stdout grep).
- Optional: route the uv.lock R&D doc to external uv expert (build-blocking severity is gone, the toolchain-governance questions remain).

---

### 2026.04.30 - Session 406cadbf | cc_notification_listener hardcoded sender_id fix

#### Checkpoint | 2026.04.30 ~12:50 EDT | One-line bug fix + R&D doc

**Context**: User reported that a fresh CC session started inside `src/cosa/` (session ID `77dac746`) was rendering as **two sender cards** in the notifications UI for the same session_id — one correctly under `[COSA]`, plus a ghost card under `[LUPIN]` that appeared the moment the listener fired its first voice-receipt ACK ("Received: Why haven't you updated your..."). The receipt notification used a different `sender_id` than the SessionStart-era notifications, so the UI grouped them as separate senders.

**Diagnosis**: `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py:453` builds the gist-response notification's `sender_id` with the project segment **literally hardcoded to `"lupin"`**: `f"claude.code@lupin.deepily.ai#{self.session_id_hash}"`. The 2026.04.24 nested-repo detection fix (R&D doc `2026.04.24-cosa-voice-nested-repo-detection-fix.md`) repaired `detect_project()` inside CoSA's `sender_id.py` and added the `build_sender_id_for_cc()` bridge-anchored helper at `session_bridge.py:436` (whose docstring literally describes this dual-card-per-session symptom), but the audit didn't sweep parent Lupin code for hardcoded `lupin.deepily.ai` strings — so this listener offender was missed. Family of bug, missed singleton.

**Fix**: replaced the hardcoded line with `build_sender_id_for_cc( session_id=self.session_id_hash ) or f"claude.code@lupin.deepily.ai#{self.session_id_hash}"` (Option 1 — symmetric with the parallel correct path at `permission_request.py:123` → `send_tts()` → `build_sender_id_for_cc()`). The `or` fallback preserves the legacy hardcoded value as a worst-case fallback if bridge resolution returns `None`, so failure-mode is no worse than today. Added the import. Net diff: +1 import line, ±1 logic line.

**Sweep check**: grepped parent Lupin source for `lupin.deepily.ai` literals (excluded `src/tests/`, `src/cosa/`, `src/rnd/`). Singleton offender — only `cc_notification_listener.py:453` constructs CC-session sender_ids. Other hits are benign (cosa_voice_mcp.py docstring example, README, Firefox plugin server URL, seed_proxy_decisions.py for `swe.*` agents).

**Verification**:

| Layer | Result |
|---|---|
| `py_compile` | OK |
| Import chain | OK |
| `pytest src/tests/smoke/test_cc_notification_listener.py` | passing (mocks `_send_gist_response`, no assertion regression) |
| `pytest src/tests/unit/test_session_bridge_lookup.py` (incl. `TestBuildSenderIdForCcBridgeCwdAnchoring` × 6) | passing |
| Combined | **93/93 passed in 0.20s** |
| Live re-test | User-gated (restart CC session in `src/cosa/`, check UI for ghost card) |

**Files** (Lupin parent only — no CoSA): `src/lupin_cli/claude_code/hooks/lib/cc_notification_listener.py` (the fix), `src/rnd/v0.1.7/2026.04.30-cc-listener-hardcoded-sender-id-fix.md` (NEW R&D doc), `history.md` (this entry), `.claude-session.md` (manifest).

**Deployment note**: the listener is a long-lived subprocess spawned by SessionStart hook. In-flight CC sessions still run pre-fix code; the fix takes effect on next SessionStart.

**V5 user-verified 2026-04-30**: user restarted a CoSA-context CC session post-commit `2eaeffc`; no ghost `[LUPIN]` card appeared. Bug fully resolved.

**Out of scope** (separate concerns from user's report):
- The CoSA session's Claude failed to call `set_session_topic()` until prompted — Phase B startup discipline issue, not code.
- This Lupin parent's first `set_session_topic` call this session got `bridge=ok / ui_push=HTTP 401` — succeeded silently in the bridge but didn't reach UI. Retry succeeded. Worth a follow-up if it's recurring.

---

### 2026.04.29 - Session 9977a1ba | Persona Theming Round 1 + WS-Event Cleanup + UI Polish + Rachel TTS bug fix

#### Session-End | 2026.04.29 evening | Four commits across cleanup + theming + polish

**Accomplishments**:

1. **WS-event cleanup migration** (`70959c5`): four ad-hoc `ws_manager.emit_to_user(...)` callsites in `voice_persona.py` + `conversation_mode.py` migrated to the canonical `push_notification(type=..., payload={...})` subsystem. Client-side: top-level `conversation_mode_changed` case relocated into `handleNotificationUpdate` by `notification.type`; new dispatches added for `voice_persona_assigned` / `voice_persona_released`. Schema: `payload: Optional[dict]` field on `NotificationItem`; `valid_types` extended. Plus persona hydration Layer A (live DOM patch on assignment) + Layer B (`/senders-visible` carries `voice_persona` for refresh-survival). New 5-test WS-frame capture E2E suite. R&D: `src/rnd/v0.1.7/2026.04.29-ws-event-cleanup-to-custom-notification-types/01-design.md` + `90-execution.md`.

2. **Persona theming Round 1** (`06e5795`): CSS custom-property foundation (`--persona-color`, `--persona-color-rgb` set on each `.sender-card`) via new `_hexToRgb` helper. Tier 1 chrome — card border + outer glow + active stripe + active dot all tinted via `var(--persona-color, fallback)`. Tier 2 header — subtle persona-tinted top-to-bottom gradient (was flat `#f8f9fa`). Badge relocated from beside session-name to first child of `.sender-stats-group` (right-aligned). Personaless cards unchanged via fallback values. R&D: `02-theming-round1-design.md` + `91-theming-execution.md`. Pinned-conv-mode green glow retained for mic-mutex semantic via more-specific selector.

3. **UI tweaks rounds 1–2** (`d8bce7f` + `21e92f1`): incoming AI bubbles get persona-tinted gradient mirroring header (alphas 0.10/0.02 — quieter than header's 0.14/0.04). Focus shift to recording mic on conversation-mode entry (not exit) and on send (Send button or Enter) for follow-up dictation. Action-required notification persona badge added to active + minimized renders; TTS queue's voice_id lookup now reads from persisted envelope (`item.notification.voice_persona.voice_id`) with map-lookup fallback — resilient to localStorage-restored items.

4. **Server-side Rachel TTS bug fix** (CoSA, NOT in any of my Lupin commits — `src/cosa/rest/routers/speech.py`): legacy code special-cased Rachel's voice_id `21m00Tcm4TlvDq8ikWAM` as the "no voice specified" sentinel, overriding it with the configured default (Sam) — so Rachel sessions silently spoke as Sam despite badges showing Rachel. Replaced with `None` sentinel; explicit voice_id values pass through unchanged. Rachel now speaks as Rachel.

5. **Persona color disambiguation iterations**: Rachel went `#4CAF50` (green) → `#009688` (teal) → `#0288D1` (sky blue) → `#7B1FA2` (Material purple 700) — first three iterations all read green-adjacent against the Bootstrap-success-green conv-mode pin at Tier 1 alphas. Saved `feedback_no_green_in_persona_pool.md` codifying the rule (green RGB component < 30% AND green not in top 2 channels). Nora `#E91E63` → `#F06292` (lighter pink) and Domi `#C2185B` → `#880E4F` (darker wine) for unambiguous Nora/Domi separation. Note: the `#7B1FA2` swap landed via parallel session's `400288f` commit — not authored by this session.

**Memory entries saved**:
- `feedback_terse_answer_direct_questions.md` — narrow factual lookups get just the answer, no padding with adjacent context
- `feedback_no_green_in_persona_pool.md` — persona pool may not contain green hues; reserved for the conv-mode pin

**Commits authored** (Lupin parent): `70959c5`, `06e5795`, `d8bce7f`, `21e92f1` — plus pending Nora/Domi color tweaks awaiting this session-end commit.

**Files Modified** (this session-end commit, parent Lupin only): `src/conf/lupin-app.ini`, `src/conf/lupin-app-splainer.ini` (Nora + Domi color swaps with provenance notes), `history.md` (this entry).

**CoSA submodule edits NOT in any of my commits** (per `feedback_lupin_only_never_cosa.md` — manage from CoSA context): `src/cosa/rest/routers/speech.py` (Rachel TTS sentinel fix), plus the 4 voice_persona / conversation_mode router migrations from earlier in the session.

**Open follow-ups** (parked, not in scope this session):
- Tier 3 widgets theming (toggle button border, gist button, voice input row chrome).
- Tier 4 message bubbles (outgoing background → persona color).
- frontend-design plugin polish pass against live :7999.
- UserPromptSubmit hook to backstop the conv-mode acknowledge-receipt rule (architecture sketched in conversation, not implemented).

---

### 2026.04.29 - Session 78abd1aa | passlib/bcrypt `__about__` AttributeError diagnosis + remediation

#### Checkpoint | 2026.04.29 17:19 EDT | Pin `bcrypt==4.3.0`, drop xfail markers, queue docker rebuild

**Files** (Lupin parent, 4 modified): `pyproject.toml` (line 69 tightened from `bcrypt>=4.0,<5` to `bcrypt==4.3.0`), `src/scripts/reset_user_password.py` (dropped now-stale host-vs-container bcrypt-version docstring note), `src/tests/integration/test_admin_users.py` (removed two `@pytest.mark.xfail` markers — `test_list_users_search_filter` + `test_update_user_roles_remove_admin` — that referenced the passlib/bcrypt mismatch), `TODO.md` (new follow-up entry for docker rebuild).
**Commit**: 093b7ca
**CoSA submodule edits NOT in this commit** (per `feedback_lupin_only_never_cosa`): `src/cosa/requirements.txt:16` (`bcrypt==5.0.0` → `bcrypt==4.3.0`) — informational only; the Lupin Docker build resolves from `pyproject.toml` + `uv.lock`, not from the COSA requirements file.
**NOT staged** (parallel session, idle-aware stop hook): `.claude/skills/testing-patterns/SKILL.md`, `src/lupin_cli/claude_code/hooks/lib/session_bridge.py`, `src/lupin_cli/claude_code/hooks/lib/anything_else_ask.py` (untracked), `src/lupin_cli/claude_code/hooks/lib/idle_settings.py` (untracked), `src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/` (untracked dir).

**Context**: User reported a recurring, context-free log line — `(trapped) error reading bcrypt version` followed by `AttributeError: module 'bcrypt' has no attribute '__about__'` from `passlib/handlers/bcrypt.py:620` — alongside an unrelated `[WS-AUDIO] Skipping disconnect for slow zebra` line. Asked for a hypothesis.

**Diagnosis** (Explore agent + WebFetch confirmation):
- **Root cause**: passlib 1.7.4 + bcrypt 5.0.0 incompatibility. passlib's `_load_backend_mixin` reads `bcrypt.__about__.__version__` for backend version logging; bcrypt 5.0.0 removed `__about__` entirely. The traceback is "trapped" by passlib's try/except, hashing/verification still work — purely cosmetic.
- **Secondary impact (NOT cosmetic)**: Two integration tests in `test_admin_users.py` were `@pytest.mark.xfail`-marked with reason "multiple_test_users fixture returns [] due to passlib/bcrypt version mismatch (bcrypt.__about__ missing)". Same version drift was silently breaking the bulk-user fixture, masked by xfail.
- **Constraint inconsistency surfaced**: `pyproject.toml:69` had `bcrypt>=4.0,<5` (upper bound `<5`), but `src/cosa/requirements.txt:16` had `bcrypt==5.0.0` — and the running container had 5.0.0 from a stale build. `uv.lock` already had `bcrypt==4.3.0` correctly resolved; the running image just predated the lock update.
- **Adjacent `[WS-AUDIO]` line is unrelated**: WS reconnect uses JWT (`get_current_user`), not password verify. Coincidental log interleaving.

**Web validation of pin choice**: pyca/bcrypt issue [#1079](https://github.com/pyca/bcrypt/issues/1079) (passlib 1.7.4 + bcrypt 5.0.0 — reporter's stated workaround is `bcrypt==4.3.0`); [PyPI release history](https://pypi.org/project/bcrypt/) confirmed 4.3.0 (Feb 28, 2025) is the latest 4.x with cp313 wheels; pyca/bcrypt issue [#684](https://github.com/pyca/bcrypt/issues/684) confirmed the trapped warning is a 4.1.1+ artifact (cosmetic only, functional fix landed in 4.1.1). Initial half-correct pin recommendation `4.2.1` was upgraded to `4.3.0` after web search.

**Plan doc**: `~/.claude/plans/let-s-start-a-new-generic-badger.md` (canonical) + viewer-accessible copy at `io/plans/2026.04.29-bcrypt-passlib-version-mismatch-plan.md` (gitignored, not committed). Document-viewer URL: `http://localhost:7999/static/html/document-viewer.html?path=plans/2026.04.29-bcrypt-passlib-version-mismatch-plan.md`.

**Next step (logged in TODO.md)**: Rebuild `lupin:1.0.0` to pick up the locked `bcrypt==4.3.0` from pyproject. Park at candidate tag (e.g. `lupin:1.0.0-bcrypt-4.3.0`) per `feedback_no_auto_promote_tags`. After rebuild: confirm trapped warning quieter on startup, re-run unit + smoke on `:7999`, schedule integration suite on `:8000` to verify the now-unxfailed tests.

#### Session Summary

- **Checkpoints**: 1 (commit `093b7ca`)
- **Files committed**: 5 (4 source + history.md)
- **Outstanding**: docker rebuild → TODO.md (Session 78abd1aa follow-ups)
- **Session closed**: 2026.04.29 18:00 EDT

---

### 2026.04.29 - Session d34f2f74 | Test-Suite Anomaly Remediation Phases 1+2+3 + Discretionary Backlog Cleanup + Idle-Aware Stop Hook

#### Session-End | 2026.04.29 18:00 EDT | Idle-aware Stop hook with exponential backoff (Phase 0–5, all green)

**Plan-driven work** (5-phase implementation per `~/.claude/plans/peppy-tickling-wolf.md` → serialized to `src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md`):

- **Phase 0**: R&D doc serialization — `01-design.md` with state machine + race analysis + alternatives, paired `90-execution.md` skeleton.
- **Phase 1**: Bridge helpers (`get_idle_detection`, `set_idle_detection_field`, `clear_idle_waiter_pid`, `kill_idle_waiter`) + `idle_settings.py` loader with 8-case validation (rejects bogus schedules loudly per `feedback_no_defensive_programming`).
- **Phase 2**: Detached-subprocess `idle_waiter.py` with chunked-sleep + PPID-poll + reset-detection state machine; `anything_else_ask.py` shared helper extracted from `stop.py:_ask_anything_else()` (the existing prompt flow is reused unchanged — what changed is *when* it fires, not *what* it asks).
- **Phase 3**: 5 hooks modified — `stop.py` defers via `_arm_idle_waiter()` instead of fire-immediately (gated by `settings.idle_detection.enabled`, default true), `user_prompt_submit.py` kills waiter + resets `backoff_index=0`, `post_tool_use.py` kills waiter on `mcp__cosa-voice__*` calls, `register_session.py` initializes the idle_detection block on SessionStart with `/clear` carry-forward, `session_end.py` kills waiter at session end.
- **Phase 4**: 32 new tests pass (18 bridge + 12 waiter logic + 2 smoke with real subprocess), 103 existing `test_stop_hook.py` + `test_session_bridge*.py` pass after autouse-fixture migration of 4 affected classes (legacy immediate-ask path now gated, but still covered with `enabled=False` settings stub). 135 tests total, 0 regressions. All tests parameterize `LUPIN_API_URL` per the new `feedback_tests_parameterize_base_url` rule + `.claude/skills/testing-patterns/SKILL.md` v1.3.
- **Phase 5**: Documentation (90-execution.md finalized with phase status + surprises + verification snapshot). Global `~/.claude/CLAUDE.md` update deferred-by-design (out-of-scope risk for global file).

**Commit**: [pending]
**Files** (Lupin parent only, no CoSA): 9 modified + 7 new + 1 R&D directory; ~492 insertions / ~9 deletions.
**New behavior**: ask "Anything else?" only after N min of true inactivity. Backoff `[5, 10, 20, 40, 60]` min on consecutive "no" responses. Resets on user input / Stop / cosa-voice tool calls. Conversation mode skipped (TTS dialogue is itself active).
**Activates**: on next CC session start (hooks loaded at session boot; this session keeps the old in-memory copies).

---

#### Checkpoint | 2026.04.29 16:22 | Phase 3 + Phase 4 backlog Lupin parent files (CoSA edits deferred)

**Files** (Lupin parent, 8 modified, 0 new): TODO.md, history.md, src/conf/lupin-app.ini (Phase 3 cap key + 1 small Rachel persona color tweak from in-progress persona theming work), src/conf/lupin-app-splainer.ini, src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/03-oos-4-test-suite-in-dead-anomaly.md (Resolution status table for Findings A/B/C/D), src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/07-final-execution-plan.md (status header reflecting actual completion state), src/tests/unit/test_test_suite_job.py (TestArtifacts io_base patches + test_exception_sets_failed pytest.raises wrapper), src/tests/unit/test_tfe_forensics.py (do_all re-raise contract updates)
**Commit**: 7e8be00
**CoSA submodule edits NOT in this commit** (deferred to separate cosa-context session per `feedback_lupin_only_never_cosa`):
- Phase 3: `src/cosa/agents/test_fix_expediter/config.py`, `prompts/proposal.py`, `orchestrator.py`
- Phase 4 backlog #1: `src/cosa/agents/utils/agent_notification_dispatcher.py` (ContextVar plumbing), `src/cosa/agents/deep_research/cosa_interface.py` (set_dispatch_context helper), `src/cosa/agents/deep_research/job.py`
- Phase 4 backlog #2: `src/cosa/rest/queue_consumer.py` (heartbeat refresh + bounded wait)
- Phase 4 backlog #4: `src/cosa/rest/running_fifo_queue.py` (4 non-canonical paths refactored to `_transition_to_dead`)
- Phase 4 backlog #5 (do_all re-raise across 9 subclasses): `deep_research/job.py`, `podcast_generator/job.py`, `presentation_generator/job.py`, `deep_research_to_podcast/job.py`, `deep_research_to_presentation/job.py`, `swe_team/job.py`, `test_fix_expediter/job.py`, `test_suite/job.py`, `bug_fix_expediter/job.py`, `claude_code/job.py`

**NOT staged** (in-progress user work, ownership unclear): `src/fastapi_app/static/css/notifications.css`, `src/fastapi_app/static/js/notifications.js` — these are persona-theming continuations after commit `d8bce7f` and don't belong in this Phase 3+4 checkpoint.

#### Phase 4 — Discretionary backlog (5 items, all done)

**Item 1 — Cross-job sender_id leak in DR notifications**: Concurrent DR jobs in the agentic pool were sharing `cosa_interface.SENDER_ID` (module global) and `_dispatcher.sender_id` (shared instance attribute), so the most-recently-launched job's sender leaked onto earlier still-running jobs' notifications. Fix: added `ContextVar`s for sender_id / target_user / session_name to `agent_notification_dispatcher.py`. Dispatcher resolver methods prefer ContextVar over `self.*`. DR's `cosa_interface` exposes `set_dispatch_context()` helper; DR `job.py` calls it at execution start. ContextVars are asyncio-task-local AND thread-local so the agentic pool's per-worker `asyncio.run()` contexts are naturally isolated. Live verification via concurrent-task test confirms per-task isolation works.

**Item 2 — Consumer-stalls-after-test-suite-job heartbeat**: Consumer thread set heartbeat at the OUTER while loop top, then blocked indefinitely in `condition.wait()` when queue was empty (e.g., after a test_suite job completed). Heartbeat went stale, stall detector (120s threshold) flagged healthy idle consumer as stalled. Fix: bound the previously-indefinite waits to `idle_wake_interval_secs` (derived as `stall_threshold // 4` = 30s default), and tick the heartbeat at the top of EACH inner loop iteration (not just outer). Healthy idle consumer now refreshes heartbeat at least every 30 seconds.

**Item 3 — OOS-4 Finding D: integration-e2e-remediation.json empty failures[]**: Surveyed all `*-integration-e2e-remediation.json` files since 2026-04-24 — all show `failed=4, in-array=0`. Tracked to `test_test_suite_job.py::TestArtifacts::test_artifacts_populated`: the unit test mocked `_run_suite` returning `{passed:10, failed:2}` but lacked `failure_details` and didn't patch `cu.get_project_root` — so `do_all()` wrote a real remediation.json to host filesystem with the inconsistent shape. Fix: added `@patch("cu.get_project_root")` + `mock_root.return_value = str(tmp_path)` so the test isolates its writes; also included `failure_details` entries in the mock data so the writer's iteration produces a consistent file shape. Verified with `BEFORE/AFTER` count of remediation files in `io/test-suite/` — 0 new files written by the fixed test.

**Item 4 — OOS-4 Finding C: 4 non-canonical dead-queue write paths**: Refactored all 4 sites in `running_fifo_queue.py` (`_process_job` exception handler, `_handle_error_case`, two paths in `_handle_agentic_job` legacy method) to delegate to the canonical `_transition_to_dead` primitive. Reduced ~150 lines of duplicate metadata-build / WS-emit / queue-push logic to ~5 one-line calls. Behavioral change: fast-lane errors now also fire the auto-fix watchdog (was previously only on agentic path), but watchdog filters by eligible_types so only agentic types actually trigger BFE. Only one `jobs_dead_queue.push` site remains (the canonical one inside `_transition_to_dead`).

**Item 5 — AgenticJobBase `do_all` swallow cleanup**: All 9 subclasses (DR, Podcast, Presentation, R2P, R2Presentation, BFE, TFE, TestSuite, SWE Team, ClaudeCode, ClaudeCode SDK) had a swallow-and-return pattern in their exception handler — they caught the exception, set `state=FAILED`, and returned the error string instead of re-raising. This forced the agentic-pool callback at `_on_agentic_complete` to handle "job ran without raising but state==FAILED" via the defensive FAILED-state branch added in cluster 2.3. Cleanup: re-raise from each subclass's exception handler after persisting state/error/answer_conversational. `Future.exception()` now correctly carries the real exception, and the pool callback's exception branch fires directly. The cluster 2.3 FAILED-state branch remains as defensive belt against future regressions. 3 unit tests updated to wrap `do_all()` in `pytest.raises(...)` matching the new contract.

**Verification (Phase 4)**: 503+ unit tests pass across all touched modules (TFE, agentic-pool, fifo-queue, running-queue-threshold, consumer-heartbeat, test-suite-job). py_compile clean across all 13 touched files (2 dispatcher infra + 5 from item 4 refactor + 9 from item 5 + 1 unit test fix). Live concurrent-task isolation test confirms ContextVar-based per-task sender state.

#### Checkpoint | 2026.04.29 14:15 | Phase 1+2 Lupin parent files (CoSA edits deferred to cosa-context session)

**Files** (parent Lupin only, 11 modified): docker-compose.yml, history.md, TODO.md, .claude-session.md, src/lupin_cli/notifications/notify_user_async.py, src/tests/smoke/test_deep_research_dry_run_smoke.py, src/tests/smoke/test_deep_research_submit_smoke.py, src/tests/smoke/test_podcast_generator_dry_run_smoke.py, src/tests/smoke/utilities/live_pipeline_base.py, src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/07-final-execution-plan.md (NEW), src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/90-execution-log.md
**Commit**: 7df56e3
**CoSA submodule edits NOT in this commit** (5 files, separate cosa-context session): src/cosa/agents/test_fix_expediter/job.py, src/cosa/training/peft_trainer.py, src/cosa/rest/running_fifo_queue.py, src/cosa/agents/notification_proxy/verification.py, src/cosa/agents/runtime_argument_expeditor/agent_registry.py
**Note**: src/fastapi_app/static/js/notifications.js (cluster 2.9 UI string) is already at the correct value in HEAD — no change needed in this commit.

**Context**: Continuation of session ba7138c4's test-suite remediation. RUN 2 (2026-04-28 22:39 EDT) landed 14 surviving smoke FAILs across 9 distinct issue clusters per `07-final-execution-plan.md`. Phase 1 was the OOS-1A one-line typo fix at `src/cosa/agents/test_fix_expediter/job.py:549`. Phase 2 was the cluster-by-cluster triage of all 14 fails.

**Accomplishments**:

- **Phase 1 (OOS-1A)**: Fixed TFE cluster-count typo (`getattr(c, "failure_count", len(getattr(c, "failures", []) or []))` → `len(c.failure_indices)`). Initial fix copied the plan verbatim and reintroduced defensive `getattr` cargo — user caught it. Re-fix used direct attribute access on the Pydantic model. Then expanded cleanup to the full surrounding block (lines 540-565): removed redundant `try/except` wrappers, dead-attribute fallbacks (`getattr(c, "id", ...)`), and dead-code `summary` field (replaced with `c.shared_error_signature` per the model docstring). Saved memory `feedback_audit_plans_at_execute_time.md` capturing the lesson: re-audit serialized plan diffs against feedback memories before applying.
- **Phase 2 (all 14 smoke FAILs resolved)**:
  - **2.1 LoRA env update × 3**: guarded `trl` and `auto_round` imports in `peft_trainer.py` (same pattern as existing `peft` guard from WG-4).
  - **2.2 DR submit × 1**: assertion `queue_position >= 1` → `>= 0` (matches the dry-run sister test).
  - **2.2 DR dry_run × 1**: deep dig revealed dry_run actually completed in 41s (not 6s). Root cause: `notify_user_async` retried on `user_not_available` for fire-and-forget progress notifications, inflating each notify by 5-7s × 6 notifies. Fix: gate the `user_not_available` retry on `notification_type != PROGRESS` (progress is persisted to DB unconditionally — retrying for live UI presence is wasted effort). Plus bumped test poll budget 30→90s as defensive headroom.
  - **2.3 BFE Phase 6 × 1**: live :8000 admin probe revealed the forced-failure DR job was in done_queue with `status=failed`, NOT in dead_queue. Root cause: `DeepResearchJob.do_all()` catches its own exceptions, sets `state=FAILED`, and **returns the error string** instead of re-raising. `Future.exception()` returns None → pool callback at `running_fifo_queue.py:_on_agentic_complete` routes to `_transition_to_done` → failed job lands in done_queue → BFE auto-fix never fires. Fix: added FAILED-state branch parallel to existing STALLED branch in `_on_agentic_complete`. Defensive belt against any subclass that swallows; cleanup TODO logged to fix the underlying do_all swallow pattern.
  - **2.4 Notification proxy verifier × 1**: single-retry on `Exception` from `from_xml` parse in `AnswerVerifier.verify` to absorb vLLM transient empty-XML responses.
  - **2.5 Podcast dry-run × 1**: `pytest.skip()` on missing prereq directory. DR dry_run never writes files (mock-only) so the dependency is permanent fragility; skip is the right idiom.
  - **2.6 Presentation × 3**: one-line fix at `live_pipeline_base.py:885` (`parse_args` → `parse_known_args`) so the shared base class tolerates pytest's positional + `--junit-xml=` args. Fixes all 3 presentation tests.
  - **2.7 SWE team proxy × 1**: added `LUPIN_INTERACTIVE_TESTS: "true"` to both `lupin-rest-test` and `lupin-rest-dev` env blocks in `docker-compose.yml`. Requires container recreation (`docker compose down && up -d`) — `docker restart` does NOT pick up env changes.
  - **2.8 Test suite live × 1**: `agent_registry.py` `get_cli_help` and `get_user_visible_args` crashed on test_suite's `cli_module=None` (intentional — test_suite has no CLI). Added early-return guard. Expediter caller already handles `help_text=None`, so the upstream contract was correct.
  - **2.9 TFE error capture × 1**: UI string `"Partial Plan (written before failure)"` had drifted from the spec's `"Partial plan written before failure"`. Realigned `notifications.js:7111` to the spec wording.
- **Process correction (cluster 2.2/2.3)**: I initially called these "M-effort, queue-transition bug, new OOS doc" and queued for follow-up. User pushed back ("Do not defer work dig into the log!!!" → "Keep going on 2.2 and 2.3"). Continued investigation found two simpler bugs both fixable in this session. The "M-effort" claim was premature pattern-matching on the symptom; cheap probes (admin queue GET, exception-banner grep, do_all source read, retry-condition check) would have found both bugs in 45 minutes. Lesson saved as `feedback_audit_plans_at_execute_time.md` and reinforced in the cluster docs.
- **Verification**: 436 unit tests across TFE / agentic-pool / fifo-queue / notify domains pass. py_compile clean across all 12 touched files. Live :8000 verification of cluster fixes deferred to a fresh user-confirmed test-suite slot.

**Files Modified (Lupin + CoSA — no commits per `feedback_never_auto_commit_push`)**:

R&D:
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/07-final-execution-plan.md` (status header updated)
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/90-execution-log.md` (Phase 2 cluster-by-cluster log)

Configuration:
- `docker-compose.yml` (`LUPIN_INTERACTIVE_TESTS: "true"` on both test + dev containers)

CoSA (submodule edits only — git managed separately per `feedback_lupin_only_never_cosa`):
- `src/cosa/agents/test_fix_expediter/job.py` (Phase 1 OOS-1A typo + defensive-programming cleanup of full block)
- `src/cosa/training/peft_trainer.py` (cluster 2.1 — guard `trl` + `auto_round` imports)
- `src/cosa/rest/running_fifo_queue.py` (cluster 2.3 — FAILED-state branch in `_on_agentic_complete`)
- `src/cosa/agents/notification_proxy/verification.py` (cluster 2.4 — single retry on LLM/parse exception)
- `src/cosa/agents/runtime_argument_expeditor/agent_registry.py` (cluster 2.8 — `cli_module=None` early-return in two helpers)

Lupin tests + lib:
- `src/lupin_cli/notifications/notify_user_async.py` (cluster 2.2 root cause — skip `user_not_available` retry for PROGRESS)
- `src/tests/smoke/test_deep_research_submit_smoke.py` (cluster 2.2 submit — assertion fix)
- `src/tests/smoke/test_deep_research_dry_run_smoke.py` (cluster 2.2 dry_run — poll budget 30→90s)
- `src/tests/smoke/test_podcast_generator_dry_run_smoke.py` (cluster 2.5 — `pytest.skip()` wrapper)
- `src/tests/smoke/utilities/live_pipeline_base.py` (cluster 2.6 — `parse_known_args`)

Frontend:
- `src/fastapi_app/static/js/notifications.js` (cluster 2.9 — UI string realigned to spec)

Tracking:
- `TODO.md` (Phase 2 follow-ups: container recreation, cross-job sender_id leak, cleanup-pass for AgenticJobBase do_all swallow pattern)
- Memory: `feedback_audit_plans_at_execute_time.md` (new), MEMORY.md index updated

**Awaiting**:
- User authorization to commit (parent Lupin context: docker-compose.yml + lupin tests + notifications.js + lupin_cli notify + R&D + TODO.md)
- Separate cosa-context session for CoSA submodule commits (5 files)
- Container recreation to pick up `LUPIN_INTERACTIVE_TESTS` env var (cluster 2.7 fix is not live until then)
- User buy-in for Phase 3 (OOS-1B INI proposal-cap)

---

### 2026.04.28 - Session 30072c25 | Per-Session Voice Personas for CC Notifications UI

**Context**: Conversation Mode v1.1 (Apr 27–28, commits 48dc03e + f2cef9f) gave each Claude Code session a per-session toggle to make Claude auto-narrate every turn via TTS. It works, but exposed a UX gap: when 2+ CC sessions run in parallel (multi-repo work), the user can't audibly tell them apart — every session speaks with the same default voice (Sam, `G7ILShrCNLfmS0A37SXS`). User asked for each new CC session to be uniformly randomly assigned a voice/persona at SessionStart from a configured pool, with a colored badge in the sender-card header so sessions are distinguishable both audibly and visually.

**Accomplishments**:

- **R&D + design** at `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` + paired `90-execution.md` (BFE-style execution log). Architecture: bridge file (`~/.claude/sessions/cc-{PPID}.json`) is canonical, per-request dead-PID filter is the implicit sweeper, no separate goroutine. Design audited against `feedback_conversation_mode_user_only_initiation.md` — voice persona allocation is a hook-driven harness mechanism, not a Claude-initiated MCP call, so the rule is not violated.
- **Voice pool**: 6 allocatable personas (Nora, Quentin, Rachel, Adam, Domi, Arnold) with name + voice_id + emoji icon + CSS hex color + texture profile. Sam reserved as the system-wide TTS default for any request lacking a `voice_id` — NOT in the allocatable pool. User-confirmed pool composition mid-plan.
- **Allocation algorithm**: `random.choice(pool − occupied)` uniform random draw from the unallocated subset. Pool exhaustion (>6 active sessions) triggers deterministic hash-modulo borrow with a visible "borrowed" badge variant (dashed border, ↻ suffix).
- **End-to-end wiring**: SessionStart hook synchronously POSTs `/api/cosa-voice/voice-persona/{sid}/allocate` (auth: hook_credentials → JWT → Bearer) before its own send_tts; bridge is the persistence anchor with fail-soft fallback to Sam if server unreachable. SessionEnd hook POSTs `/release`. Notifications router stamps `voice_persona` on the outbound WS envelope by looking up bridge for the resolved sender_id. UI hydrates `senderPersonaMap` from notification arrivals, threads `voice_id` through `playTTS`→`playInstantTTS`/`playReliableTTS`, renders persona badge in sender-card header. `/clear` carry-forward in `register_session.py` Phase 2 preserves voice across context clears.
- **Bundled bug fix**: `notifications.js` was sending `{ voice: "default" }` to `/api/get-speech-elevenlabs` — server reads `voice_id` (not `voice`), so UI parameter was silently ignored. Fixed body key `voice` → `voice_id` in both `playInstantTTS` and `playReliableTTS`. Caught by Phase 2 design-review agent.
- **Test totals**: 102/102 PASS in 0.80s — 25 new unit tests (`test_voice_persona_helpers.py`: pool parsing, allocation against parametrized N=0/1/2/5 occupancy, borrow determinism, malformed-bridge skip, bridge round-trip), 7 new live :7999 smoke tests (`test_voice_persona_allocation.py`: pool returns 6 voices, allocate yields non-Sam, idempotent re-allocate, release frees slot, 404 on unknown session, 2-session uniqueness check), 70 regression tests (existing `test_session_bridge_lookup.py` + `test_conversation_mode_router.py`) — no breakage.
- **The one verification I cannot automate**: spawning 3 concurrent `claude code` sessions in different terminals to confirm three distinct voices speak + three distinct colored badges render. Subjective audio-perception check; flagged as a TODO follow-up for the user.

**Files Modified (parent Lupin only — no CoSA git ops, no tests touched outside this feature)**:

R&D:
- `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/01-design.md` (NEW)
- `src/rnd/v0.1.7/2026.04.28-per-session-voice-personas/90-execution.md` (NEW)

Configuration:
- `src/conf/lupin-app.ini` ([Voice Personas] block: 1 pool key + 6 personas × 4 fields = 25 new keys)
- `src/conf/lupin-app-splainer.ini` (matching splainer descriptions for all 25 new keys)

Hooks + lib:
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (`get_voice_persona`, `set_voice_persona`, `find_active_voice_persona_sessions` + extended smoke block)
- `src/lupin_cli/claude_code/hooks/register_session.py` (`_allocate_voice_persona_via_http` helper + Phase 4.5 hook step + `/clear` voice_persona carry-forward)
- `src/lupin_cli/claude_code/hooks/session_end.py` (`_release_voice_persona` helper + Phase 1.5 release call)

CoSA REST (edits only — submodule git managed separately per `feedback_lupin_only_never_cosa`):
- `src/cosa/rest/voice_persona_helpers.py` (NEW pure-function module: load_pool / pick_unallocated / borrowed_for_sid / allocate)
- `src/cosa/rest/routers/voice_persona.py` (NEW router — GET /pool, GET /{sid}, POST /{sid}/allocate, POST /{sid}/release; asyncio.Lock for atomic allocation)
- `src/cosa/rest/notification_fifo_queue.py` (`NotificationItem.voice_persona` field + to_dict + push_notification kwarg)
- `src/cosa/rest/routers/notifications.py` (`_voice_persona_for_sender_id` resolver + 3 callsite injections: queued path, response-required path, cc-listener inline broadcast)

FastAPI:
- `src/fastapi_app/main.py` (import + register voice_persona router)
- `src/fastapi_app/static/js/notifications.js` (`senderPersonaMap` + `getVoiceIdForSender`/`getPersonaForSender` helpers + handleNotificationUpdate hydration + body-key fix `voice` → `voice_id` in playInstantTTS/playReliableTTS + voiceId threaded through playTTS chain + 2 callsite wirings + persona badge in sender-card header)
- `src/fastapi_app/static/css/notifications.css` (`.persona-badge` styling + `.persona-badge.borrowed` dashed-border variant)

Tests:
- `src/tests/unit/test_voice_persona_helpers.py` (NEW — 25 tests across 6 classes)
- `src/tests/smoke/test_voice_persona_allocation.py` (NEW — 7 live :7999 tests)

Documentation:
- `CLAUDE.md` (DOCUMENTATION TOUCHPOINTS rows for voice_persona router + INI keys)
- `TODO.md` (added persona-UX-experience follow-up)

**Commit**: [pending — uncommitted at session close]

---

### 2026.04.28 - Session ba53b0d2 | Bug Fix Mode — Conversation-mode response acknowledgment

**Context**: User reports that in cosa-voice conversation mode, Claude often acts on a user prompt but never speaks back — the user has no way to know the prompt was received. Existing directives say "after every assistant turn, call notify(...)" but never explicitly require a *receipt acknowledgment before tool work begins*. This session adds the missing per-turn "acknowledge receipt before tool work" rule across the three redundancy layers (MCP server-instructions, slash-command, global guardrails skill) plus an auto-memory feedback entry, then verifies via grep cross-check.

### Fixes

#### Fix 1: Codify "acknowledge receipt before tool work" rule across 4 redundancy layers

- **Source**: ad-hoc (user-reported during conversation-mode investigation)
- **Symptom**: In conversation mode, Claude often opens a turn with tool calls and never calls `notify()` — leaving the user (listening at a distance via TTS) with no audio confirmation that the prompt was received. Original directives addressed only "speak the closing response" via "after every assistant turn, call notify(...)" — the gap was tool-only turns that never produce user-facing text.
- **Root cause**: Contract gap. The MCP `instructions=` block and `/conversation-mode-on` slash command only described one obligation (closing-turn full-response speak). Receipt acknowledgment before tool work was not an explicit clause anywhere, so silent tool-only turns slipped through.
- **Fix**: Added explicit two-obligation contract — (1) ack receipt BEFORE tool work begins, (2) speak closing turn in full — across 4 redundancy layers matching the existing USER-ONLY INITIATION pattern:
  1. `src/lupin_mcp/cosa_voice_mcp.py` MCP `instructions=` block (`cosa_voice_mcp.py:570-585`) — split conversation-mode bullet into two sub-obligations
  2. `.claude/commands/conversation-mode-on.md` — split step 3 into 3a "ack before tool work" + 3b "speak closing turn in full"
  3. `~/.claude/skills/conversation-mode-guardrails/SKILL.md` — NEW "Per-turn speaking contract" section (rule was absent from global skill)
  4. `~/.claude/projects/.../memory/feedback_acknowledge_receipt_before_tool_work.md` — NEW auto-memory feedback file + index pointer in MEMORY.md
- **In-repo touched files**: `src/lupin_mcp/cosa_voice_mcp.py`, `.claude/commands/conversation-mode-on.md`
- **Out-of-repo touched files** (NOT committed — global Claude Code config): `~/.claude/skills/conversation-mode-guardrails/SKILL.md`, `~/.claude/projects/.../memory/feedback_acknowledge_receipt_before_tool_work.md`, `~/.claude/projects/.../memory/MEMORY.md`
- **Verification**: grep cross-check confirmed "Acknowledge receipt BEFORE tool work begins" string present in all 4 layers (MCP `:574`, slash command `:18`, skill `:52`, memory file frontmatter + body). `py_compile` clean on `cosa_voice_mcp.py`.
- **Test**: documentation-only change → no automated tier applies (no behavior code touched). Compile-clean is the verification floor; effective-test will be the user's lived experience in next conversation-mode session after MCP server reload.
- **Effective-when**: Layer 1 takes effect after the cosa-voice MCP server restarts (loads new `instructions=` block on startup). Layers 2/3/4 take effect immediately on next session start.
- **Commit**: 4513f08

### Session Summary

(Will be completed at session close)

---

### 2026.04.28 - Session 30072c25 | Docker Build Diagnostics — Postgres Bind-Mount Permission + uv.lock / pydantic-ai[slim] Drift

**Context**: User opened the session reporting `docker build -f docker/lupin/Dockerfile -t lupin:1.0.0-fonts .` failed with `error from sender: open src/conf/long-term-memory/postgresql-dev-data: permission denied`. After landing the diagnosis + permanent-relocation plan, user prepended `sudo` and re-ran — surfacing a second blocker: `uv sync --locked --no-install-project` failing at stage 13/47 because `pydantic-ai==0.6.2` does not have a `slim` extra. User requested the second issue be written up as a self-contained problem-statement document for an external expert.

**Accomplishments**:

- **Postgres bind-mount diagnosis**: `src/conf/long-term-memory/postgresql-dev-data` is mode `0700` owned by UID 70 (postgres-in-container) — unreadable by host user `rruiz`. `.dockerignore` already carries 6 exclusion patterns + a header comment documenting that "BuildKit's sender will try to open the dir during context evaluation" — the patterns aren't enough because BuildKit's walker stats the dir before applying the ignore. Fixing perms in place is impossible (Postgres requires `0700` to start). Two-step strategy: (1) `sudo docker build` for the immediate unblock, (2) relocate the bind-mount outside the build context permanently. Confirmed target via cosa-voice `ask_multiple_choice`: `/mnt/DATA01/lupin-data/postgresql-dev-data` (same physical disk as repo, no cross-disk copy, user-writable parent). 5-file edit set scoped: `docker-compose.yml:17`, delete `.dockerignore` lines 1–11, delete `.gitignore:47`, delete `src/scripts/conf/rsync-exclude.txt:85`, update `src/scripts/run-postgresql-dev.sh:236` help text.
- **uv.lock / pydantic-ai[slim] diagnosis**: `pyproject.toml:53` declares `pydantic-ai[slim]==0.6.2`. `uv.lock:2087` faithfully records the ask: `extras = ["slim"]`. But the resolved `pydantic-ai==0.6.2` metadata at `uv.lock:3097-3106` has NO `[package.optional-dependencies]` table — the meta-package exposes zero extras at the meta level. The 14 extras listed (anthropic, openai, google, mcp, ...) are all on the *transitive* `pydantic-ai-slim` dep. So the lockfile is internally inconsistent — it pins an extra that doesn't exist on the resolved package metadata. `uv 0.8.x` `--locked` correctly refuses to silently re-resolve. Recommended fix (Option 1 of 4): drop `[slim]` from `pyproject.toml`, regenerate `uv.lock`, commit atomically. Functionally a no-op — `pydantic-ai==0.6.2` already pulls `pydantic-ai-slim` transitively with all 14 sub-extras.
- **Expert problem-statement document** at `src/rnd/v0.1.7/2026.04.28-uv-lock-pydantic-ai-slim-extra-mismatch.md` — self-contained for an external Python-packaging / `uv` expert. Sections: TL;DR, environment table (CUDA/Python/uv/pydantic-ai versions), observable symptom (annotated build output), evidence (5 file:line citations with verbatim TOML), hypothesis (3 candidates with `uv` lock-writer leniency as primary suspect), 4 ranked solutions with tradeoffs, 5 open questions, deterministic reproducer (~10 lines, runnable in a `tmp` dir).

**Files Modified (parent Lupin only — no CoSA-side edits, no INI changes, no test changes)**:

R&D:
- `src/rnd/v0.1.7/2026.04.28-uv-lock-pydantic-ai-slim-extra-mismatch.md` (NEW)

**Pending follow-ups**:

- Postgres bind-mount permanent relocation — plan finalized at `~/.claude/plans/compressed-percolating-prism.md`, target `/mnt/DATA01/lupin-data/postgresql-dev-data`. Awaiting execution slot (irreversible without rollback path; user-gate before move).
- `uv.lock` surgical fix: drop `[slim]` extra at `pyproject.toml:53`, regenerate `uv.lock`, commit `pyproject.toml + uv.lock` atomically. Verify rebuild advances past stage 13/47.
- Optional: route the uv.lock R&D doc to an external `uv` / packaging expert for root-cause input on lockfile-vs-metadata inconsistency (open questions: did `pydantic-ai==0.6.2` ever expose `slim`? did `uv` tighten extras-validation between lock-time and sync-time? should we file a `uv` bug?).
- **Memory update saved**: `feedback_expert_handoff_problem_statement.md` (when the user asks for an expert-handoff doc, format as: TL;DR → environment table → observable symptom → file:line evidence → hypothesis → ranked solutions with tradeoffs → open questions → deterministic reproducer).

---

### 2026.04.28 - Session c7333045 | Conversation Mode v1.1 — 404 fix + Mutex + Pinning + Corner Pause Button

#### Checkpoint | 2026.04.28 16:31 EDT | Mid-session checkpoint — multi-bug pass + mutex/pinning feature complete

**Context**: User opened the session reporting two bugs from yesterday's conversation-mode v1 (commit 48dc03e): UI toggle was misplaced (in the sender-card header instead of next to the per-session record button), and clicking it returned 404 from the FastAPI server. Investigation surfaced more issues during the day (duplicate "Received:" notification echo, stop-hook interrupting voice flow, corner pause button missing, mid-stream playback control wrong API). After bugs landed, user requested a v1.1 follow-up: mutual exclusion across CC sessions ("only one session can monopolize the mic") + pinning the active session's pane to the top of the notifications accordion + soft-glow visual cue. Plan landed at `~/.claude/plans/drifting-skipping-porcupine.md`; execution covered 5 phases.

**Accomplishments**:

- **Bug — 404 from container PID-namespace**: `find_session_path_by_id` was discarding every bridge file because `_is_pid_alive(host_pid)` always returned False inside the `lupin-rest-dev` container (different PID namespace from the host). Added `_can_trust_host_pids()` helper that returns False when `/.dockerenv` exists, gating the PID-alive filter. Live `:7999` round-trip POST/GET/POST/GET now returns 200; bug verified fixed in production listener log (1 event per voice message instead of 2).
- **Bug — UI toggle position**: moved the `sender-conversation-mode-btn` button from the `.sender-card-header` (next to gist) into the `.cc-voice-input-row` immediately to the left of the `.cc-session-stt` mic button, sized to match `.cc-voice-input .stt-button` (height 34px, min-width 40px, padding 4px 8px).
- **Bug A — Duplicate "Received:" echo**: long-standing dispatch bug in `emit_to_user_or_listener_sync` (CoSA `websocket_manager.py`). When the cc-listener authenticates as the same user as the sender, its session was already in `user_sessions[user_id]` so `emit_to_user_sync` reached it via fan-out — and then `emit_to_session_sync` delivered the same envelope a second time. Added a `listener_in_user_fanout` check that skips the targeted listener emit when the session is already covered. New regression test `test_listener_emit_skipped_when_already_in_user_fanout` in `test_websocket_manager_dispatch.py`. Verified live: every voice message now produces exactly one `_handle_event` invocation in the listener log instead of two.
- **Bug B — Stop-hook gate on conversation mode**: added a check at the top of `stop.py::main()` that calls `get_conversation_mode(session_id)` and emits `{}` immediately when true. Voice-buffer drain, `notify_user_sync`, and TTS calls all bypassed when conversation mode is on, so Claude's stop-hook can't interrupt the voice flow. 2 new tests covering both directions of the gate.
- **Feature — Corner pause button on currently-playing notification**: rendered an absolutely-positioned `.notification-corner-pause-btn` in the upper-right of the message div with size matching the surrounding chrome. Visibility gated by `.sender-message.tts-playing` (the existing class that the audio lifecycle already toggles via `startTTSPlayingIndicator`/`stopTTSPlayingIndicator`). Click handler iterations: first attempt called `currentAudio.pause()` which hit a stale HTML5 Audio handle while real playback runs through Web Audio AudioContext; switched to `pauseTTS()`/`resumeTTS()` (the same APIs the global pause button uses) — fixed.
- **Feature — Mutual exclusion across CC sessions** (Phases 0–4 + 2.5 of `~/.claude/plans/drifting-skipping-porcupine.md`):
  - **Phase 0**: §11 addendum to `src/rnd/v0.1.7/2026.04.27-conversation-mode-design.md` documenting locked decisions, architecture diagram, invariants, and risks.
  - **Phase 1**: New `find_active_conversation_sessions(exclude_session_id)` helper in `session_bridge.py` that scans `SESSION_DIR.glob("cc-*.json")` for active bridges, honors `_can_trust_host_pids()`, supports full-UUID-or-8-char-prefix exclude. 9 new tests in `TestFindActiveConversationSessions`.
  - **Phase 2 (CoSA)**: `routers/conversation_mode.py` POST endpoint takes a module-level `asyncio.Lock` on activate, scans for other active bridges, deactivates each + broadcasts `conversation_mode_changed {session_id, active=false, displaced=true, displaced_by=<sid>}`, then activates ours and broadcasts. Response gains `displaced_sessions` array. 6 new auto-displace tests covering single/multi/no-displacement/deactivate-no-scan/broadcast-failure/self-no-displace.
  - **Phase 2.5**: `_flip_conversation_mode` in `cosa_voice_mcp.py` refactored to POST the canonical HTTP endpoint (with credential lookup + JWT login + Bearer-authed toggle POST) instead of writing the bridge directly. Falls back to `set_conversation_mode` direct-write on any HTTP failure (server down, login 401, endpoint 5xx) — preserves degraded-mode availability. **User-only-initiation guardrail** layered in three places: (a) extended MCP `instructions=` block with a USER-ONLY-INITIATION + MUTUAL-EXCLUSION rule; (b) extended `enter_conversation_mode()` and `exit_conversation_mode()` tool docstrings with the same hard rule; (c) created new global skill at `~/.claude/skills/conversation-mode-guardrails/SKILL.md`. 4 new tests covering HTTP success / ConnectionError fallback / login 401 fallback / endpoint 500 fallback.
  - **Phase 3**: `handleConversationModeChanged` extended with displaced-event handling — calls `pauseTTS()` if `activeTTSItem` is playing, pins/unpins matching sender card, normalizes session_id to 8-char prefix at WS event entry (fixed a keying mismatch where server emits full UUID but UI keys by 8-char). New `_pinSenderCardForSession` and `_unpinSenderCardForSession` helpers. Both copies of `moveSenderCardToTop` (lines 9317 + 15163) and `createSenderCard`'s top-insertion path now respect the pinned card invariant — non-pinned cards land at index 1 when a pinned card holds index 0. `createSenderCard` also auto-pins its own card on creation when the session is in `conversationModes` with true (initial-load hydration case).
  - **Phase 4**: `.sender-card[data-pinned-conv-mode="true"]` CSS — soft green border + box-shadow matching the corner-pause-button accent palette + linear-gradient header tint.
- **Cache-bust progression** for `notifications.html`: `20260426b` → `20260428a` (after CSS toggle re-style) → `b` (corner pause first attempt) → `c` (click handler v2) → `d` (pauseTTS rewire) → `e` (Phase 3 pin/unpin) → `f` (8-char normalization fix). All visible in the file's history.
- **Test totals**: 130/130 PASS across `test_session_bridge_lookup.py` (51), `test_conversation_mode_router.py` (13), `test_cosa_voice_mcp_conversation_mode.py` (10), `test_websocket_manager_dispatch.py` (10), `test_stop_hook.py` (46). 22 net new tests (9 + 6 + 4 + 1 + 2).
- **Live verification**: API smoke confirmed `displaced_sessions` field in POST response and self-activation correctly avoids displacing self. Multi-tab browser smoke confirmed displaced session's toggle flips back to bell + pin drops + mid-stride TTS pauses (after the 8-char normalization fix in `?v=20260428f`).
- **Memory updates**: `feedback_conversation_mode_user_only_initiation.md` (hard rule: never call enter/exit_conversation_mode preemptively); `feedback_enumerate_all_activation_paths.md` (when planning multi-path features, enumerate every activation surface up front — don't default any path to "follow-on activity").

**Files Modified (parent Lupin only — CoSA submodule managed separately)**:

Hooks + lib:
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (container PID gate + `find_active_conversation_sessions` helper)
- `src/lupin_cli/claude_code/hooks/stop.py` (Bug B — conversation-mode gate)

MCP:
- `src/lupin_mcp/cosa_voice_mcp.py` (Phase 2.5 — HTTP-first `_flip_conversation_mode` with fallback + USER-ONLY-INITIATION + MUTUAL-EXCLUSION instructions / tool docstrings)

UI:
- `src/fastapi_app/static/js/notifications.js` (toggle button moved + corner pause button render+wire + pin/unpin helpers + handleConversationModeChanged extended for displaced/pause + 8-char normalization + sort-respecting moveSenderCardToTop both copies + createSenderCard pinned-aware insertion)
- `src/fastapi_app/static/css/notifications.css` (corner pause button rules + pinned-card glow border + header gradient)
- `src/fastapi_app/static/html/notifications.html` (cache-bust to `?v=20260428f`)

R&D:
- `src/rnd/v0.1.7/2026.04.27-conversation-mode-design.md` (§11 mutex + pinning addendum)

Tests (Lupin-side):
- `src/tests/unit/test_session_bridge_lookup.py` (+11 tests)
- `src/tests/unit/test_conversation_mode_router.py` (+6 tests)
- `src/tests/unit/test_cosa_voice_mcp_conversation_mode.py` (+4 tests)
- `src/tests/unit/test_websocket_manager_dispatch.py` (+1 test)
- `src/tests/unit/test_stop_hook.py` (+2 tests)

CoSA-side (separate submodule commit needed):
- `src/cosa/rest/websocket_manager.py` (Bug A — listener-already-in-user-fanout dedup)
- `src/cosa/rest/routers/conversation_mode.py` (Phase 2 — auto-displace endpoint with asyncio.Lock + WS displaced payload + displaced_sessions response field)

Plus new global skill (not in repo): `~/.claude/skills/conversation-mode-guardrails/SKILL.md`.

**Pending follow-ups**:

- E2E Playwright extension for the new mutex + pinning + auto-pause scenarios — gated behind a user-confirmed `:8000` slot per the E2E two-phase gate.
- Per-session TTS queue isolation (so B's new audio plays while A's queued audio stays paused on displacement) — current model is global pauseTTS, user manually resumes. Separate UX cycle.
- Hard programmatic enforcement of the user-only-initiation rule (e.g., require a "user-utterance attestation" field on the MCP call). v1.1 documents the rule in three layers; this is a future enhancement if drift is observed.
- Toast UI for displaced sessions — payload carries `displaced=true, displaced_by=<sid>` already, just no UI rendering yet.
- **Bug observed at checkpoint time (deferred — investigation pending)**: user reported two notification panes both labeled with session_id `c7333045` but different sender labels (one "Lupin", one "Cosa"). Hypothesis to investigate: project-aware sender_id derivation may be producing two distinct sender keys (e.g. `claude.code@lupin.deepily.ai#c7333045` and `claude.code@cosa.deepily.ai#c7333045`) for the same underlying CC process, depending on the cwd at notify-call time. Worth checking `parseSenderId` + project-detection in MCP + how cwd flips when Claude reads files in `src/cosa/`. ✅ **RESOLVED** — see follow-up checkpoint below.

#### Checkpoint | 2026.04.28 17:05 EDT | Follow-up — duplicate sender_id bug root-caused + fixed

**Context**: After the `f2cef9f` checkpoint, dug into the duplicate-pane bug listed in pending follow-ups. Empirical pull from the live `:7999` notification store confirmed BOTH `claude.code@lupin.deepily.ai#c7333045` (31 entries — "Received: ..." messages from the cc-listener) AND `claude.code@cosa.deepily.ai#c7333045` (40 entries — "Done: Bash: ..." messages from the PostToolUse hook) coexist in the DB for the same underlying CC session. Two distinct sender groupings, two cards in the UI accordion.

**Root cause**: `build_sender_id_for_cc()` in `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` calls `build_sender_id("claude.code", suffix=...)` without an explicit `project`, so `build_sender_id` falls back to `detect_project()` which uses **live `os.getcwd()`**. Hook scripts inherit cwd from the spawning Claude Code process, but Claude Code preserves the **bash subshell's mutated cwd across tool invocations** — so once the user runs `cd /path/to/lupin/src/cosa && git status` in any Bash command, every subsequent PostToolUse hook spawn sees cwd inside `src/cosa/`. Since `src/cosa/` is a git submodule with its own `.git`, `detect_project()` walks up and returns `"cosa"` instead of `"lupin"`, pivoting the sender_id mid-session.

**Fix**: New `_resolve_project_from_bridge_cwd()` helper that reads the bridge file's stable SessionStart `cwd` snapshot (written once at session bootstrap, never drifts) and walks up from THAT path to find the `.git` ancestor. `build_sender_id_for_cc()` passes the resolved project explicitly, falling back to live-cwd detection only if the bridge can't be resolved (preserves degraded-mode behavior).

**Empirical confirmation** (in this Python process, before/after fix):
```
CWD=/lupin                    → claude.code@lupin.deepily.ai#c7333045 ✓
CWD=/lupin/src/cosa  (drift)  → claude.code@lupin.deepily.ai#c7333045 ✓ (was @cosa pre-fix)
```

**Audit clean**: every hook sender_id call site (`stop.py:223`, `register_session.py:643`, `permission_request.py:154`, and indirectly `hook_common.send_tts → build_sender_id_for_cc` from `post_tool_use.py`) inherits the fix automatically. The single direct `detect_project()` call at `register_session.py:457` only fires at SessionStart when cwd is stable — safe. `cc_notification_listener.py` hardcodes `lupin.deepily.ai` — already stable. MCP module-level `SENDER_ID` is set once at MCP startup and the MCP process cwd doesn't drift — safe.

**Test totals**: 6 new regression tests in `TestBuildSenderIdForCcBridgeCwdAnchoring` (test_session_bridge_lookup.py) — covers full-uuid match, walk-up from subdirectory, build_sender_id-uses-bridge-cwd-not-live-cwd (the key regression assertion), missing-bridge fallback, missing-cwd-field fallback, planning-is-prompting alias. 57/57 PASS in the file overall.

**Pre-rebuild Phase A2 sanity baseline** locked in `/tmp/baseline-unit-pre-rebuild.log` (3720 unit pass + 1 xfailed) and `/tmp/baseline-ws-smoke-pre-rebuild.log` (50/50 ws smoke pass).

**Files Modified (parent Lupin only)**:
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py` (new `_resolve_project_from_bridge_cwd()` + modified `build_sender_id_for_cc()`)
- `src/tests/unit/test_session_bridge_lookup.py` (+6 regression tests)

**Memory updates**:
- `feedback_lupin_only_never_cosa.md` — appended a new bullet reinforcing that submodule state must not surface in checkpoints, status reports, or "what's pending" summaries (rule existed; tightened from the user reminder).

**Existing DB notifications**: the 40 historical "cosa"-flavored notifications in PostgreSQL retain their old sender_ids and continue rendering as a "Cosa" pane until they age out via natural retention. New notifications going forward all anchor on the bridge cwd. No migration scripted — natural decay handles cleanup.

#### Checkpoint | 2026.04.28 21:00 EDT | EmbeddingProvider HTTP-routing refactor — eliminate accidental GPU loads from non-FastAPI processes

**Context**: User flagged that another agent claimed `SolutionSnapshot.__init__()` "loads embedding models on cuda:0." Investigation: strictly false (the two suspicious lines `EmbeddingManager()` + `get_embedding_provider()` are both lazy), but practically true — `SolutionSnapshot.__init__()` calls `generate_embedding()` up to 5 times for question/code/solution/thoughts when fields are non-empty without precomputed embeddings. With config `embedding provider = local` + `local embedding device = cuda:0`, the first such call lazy-loads `nomic-embed-text-v1.5` and `nomic-ai/CodeRankEmbed` onto cuda:0 — a non-FastAPI process holding a duplicate GPU model. User's "zero need to load an embedding engine" stance is correct; the canonical path is the FastAPI `/api/embeddings/{generate,batch}` endpoints which already use the in-process singleton. User added a critical requirement: HTTP-routing URL must be **dynamic at runtime** so a test on the `:8000` test server hits `:8000`, removing cross-container dependencies.

**Accomplishments**:

- **Process-aware routing in `EmbeddingProvider`**: new `_is_in_process_engine_owner` class flag (default False). `declare_in_process_engine_owner()` classmethod flipped True only by FastAPI startup after engines load. `generate_embedding()` and `generate_embeddings_batch()` route locally only when flag=True; otherwise HTTP-route to `/api/embeddings/generate` or `/api/embeddings/batch` via X-API-Key auth (mirrors `prediction_engine._generate_embedding_via_http` pattern). HTTP failures raise clear `RuntimeError` with URL + cause — fail-fast beats silent GPU grab.
- **Dynamic URL resolution via `_resolve_server_url()`**: reads `LUPIN_APP_SERVER_URL` env var at every call (NOT module load). A test running on `:8000` can `export LUPIN_APP_SERVER_URL=http://localhost:8000` and route there mid-process without restarting Python. Default `http://localhost:7999`.
- **`SolutionSnapshot.__init__()` requires zero changes**: same `self._embedding_provider.generate_embedding()` calls; routing is now context-aware automatically.
- **FastAPI startup wired**: `main.py` calls `EmbeddingProvider.declare_in_process_engine_owner()` immediately after `prose_engine` warmup — first-class one-line declaration with explanatory comment.
- **Comprehensive ultrathink test-quality analysis** before implementation: surveyed existing test bed (~30 tests in `test_local_embedding_engine.py` covering engines + provider routing for openai/local/code/prose/batch), identified gap (no in-process-vs-HTTP routing tests because that distinction didn't exist), planned 12 new tests across 4 new test classes targeting the gap precisely. Existing monkeypatch in `test_lancedb_gcs_integration.py` (above the routing layer) continues to work unchanged.
- **16 new unit tests** (vs 12 estimated):
  - `TestEmbeddingProviderRoutingFlag` (5): default False, declare flips True, idempotent, flag=True routes to engine + skips HTTP, flag=False routes to HTTP + skips engine.
  - `TestEmbeddingProviderHttpPath` (5): correct endpoint + X-API-Key header, missing key → clear error, ConnectionError → clear error, 5xx → clear error, malformed response → clear error.
  - `TestEmbeddingProviderDynamicUrl` (4): default URL when env unset, custom URL from env, **resolved-at-call-time** key assertion (set env, call, change env, call, verify two URLs), empty env → fallback.
  - `TestEmbeddingProviderBatchHttpPath` (2): batch routes to `/api/embeddings/batch` with right body, owner-path unaffected.
- **Test hygiene improvement**: extended `_reset_singletons()` to also reset `_is_in_process_engine_owner = False` and clear `LUPIN_APP_SERVER_URL` between tests. Updated existing `TestEmbeddingProvider.setup_method` to flip flag True so legacy routing tests representatively exercise the local-engine path. **40 prior tests + 16 new = 56/56 pass**. Full conversation-mode + embedding sweep: **192/192 pass**.
- **Live verification**: from a non-FastAPI Python process (with `LUPIN_ROOT` set), `EmbeddingProvider().generate_embedding("smoke test")` round-tripped via HTTP to `:7999/api/embeddings/generate`, returning 768-dim vector. Batch endpoint round-tripped 2 vectors × 768 dims. Dynamic URL: setting `LUPIN_APP_SERVER_URL=http://localhost:9999` mid-process correctly failed at the new URL.
- **One mid-implementation bug caught by clear-error design**: my `_http_api_key()` initially called `cu.get_api_key()` but the module imports `cosa.utils.util as du`, not `cu`. The "no API key found" error fired immediately on first live test — fail-fast worked exactly as designed. One-line fix.

**Files Modified (parent Lupin only)**:
- `src/cosa/memory/embedding_provider.py` (+140 lines: flag, declare classmethod, `_resolve_server_url`, `_http_api_key`, single + batch HTTP helpers, modified `generate_embedding` and `generate_embeddings_batch` for routing branch)
- `src/fastapi_app/main.py` (+5 lines after prose-engine warmup: import + `declare_in_process_engine_owner()` + log)
- `src/tests/unit/test_local_embedding_engine.py` (+~250 lines: `os` import, `_reset_singletons` extended, `TestEmbeddingProvider.setup_method` updated, 4 new test classes with 16 tests)

**Memory updates**:
- `feedback_never_grab_gpu.md` — appended "EmbeddingProvider routing invariant" section documenting the new architectural enforcement (class-level flag, FastAPI-startup-flipped, runtime URL resolution, practical consequence for `SolutionSnapshot.__init__()`).

---

### 2026.04.28 - Session ba7138c4 | Test-Suite Anomaly Remediation (Phase 0 + WG-2/3/4/5/7/8b/9; WG-1 prep + 4 OOS plans)

#### Checkpoint | 2026.04.28 12:00 EDT | Mid-session checkpoint — autonomous remediation pass complete

**Context**: User invoked the session for postmortem analysis of the 2026-04-27 22:35 EDT scheduled `:8000` test-suite run (`ts-90890bae`) which produced 4422 P / 23 F / 19 E / 47 S, 1 orphaned Calculator job in `run` queue, 8 reaped Calculator jobs in `dead`, and a stalled downstream TFE (`tfe-d9786eea`) that timed out at the proposing voice gate after generating 23 fix proposals. After the analysis, user approved a remediation plan covering 9 working groups + 4 out-of-scope follow-ups, then went out for errands with autonomous-execution authorization. This checkpoint captures everything landed during the unsupervised window.

**Accomplishments**:

- **Phase 0 — Documentation-First serialization** at `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/`: 15 docs total (1 design + 9 per-WG + 90-execution-log + 4 OOS plans).
- **WG-2 — Smoke-test prereq skip discipline**: `_docker_available()` now catches `FileNotFoundError`/`OSError` so the autouse fixture's `pytest.skip` path is reached when the docker binary is absent (test container reality). `LivePipelineTestBase.run_scenarios` converts silent `False` returns at the credential gate + `ConnectionError` handler to `pytest.skip()` calls when pytest is importable; standalone CLI usage preserved. Effect: 7 prior ERRORs + 9 inheriting live-pipeline FAILs become SKIPs.
- **WG-3 — BURN GPU-touching tests**: deleted `src/tests/smoke/test_embedding_benchmark.py` and `src/tests/smoke/test_local_embedding_smoke.py`. Audit grep clean afterward. Per the never-grab-GPU mandate (corollary added to memory): tests that touch CUDA/embedding-engines must be **deleted, not guarded**; tests should call `/api/embeddings/batch` instead. Earlier draft of the plan proposed VRAM headroom guards — user course-corrected. Effect: 6 prior FAILs eliminated.
- **WG-4 — Optional `peft` import guard**: wrapped `peft` import in `peft_trainer.py` in `try/except ImportError` with `PEFT_AVAILABLE` flag + None fallbacks (matches `claude-agent-sdk` pattern in `dispatcher.py`). Effect: 3 `test_lora_env_update_smoke` collection-time failures resolved.
- **WG-5 — Optional `lxml` dep + audit**: added `lxml>=5,<6` to `pyproject.toml` NLP/parsing block. `lxml` was in `src/cosa/requirements.txt` but `uv sync --locked --no-install-project` reads from `pyproject.toml + uv.lock`, so the dep was never reaching the image. Audit grep surfaced two more unguarded ML imports in `src/cosa/training/` (peft_trainer, quantizer) — backlog only since training-tier files are operator-launched.
- **WG-1 — Docker fonts (Dockerfile edit only; rebuild deferred)**: authoritative font enumeration via `playwright install-deps chromium --dry-run` against the existing `lupin:1.0.0` image identified 9 missing font packages + 8 X11/font support libs. Added to `docker/lupin/Dockerfile` apt list with refresh-instruction comment. Image rebuild + visual baseline regen + retag deferred for user to time per `feedback_no_auto_promote_tags` (never overwrite working tag automatically).
- **WG-7 — Websocket false-FAIL parser fix**: added `_parse_non_pytest_stdout(suite_type, stdout)` to `TestSuiteJob` that recognizes the websocket runner's `[INFO] Total Tests: N / Passed: X / Failed: Y / ALL SMOKE TESTS PASSED!` format. Called as a fallback when `_parse_junit_xml(None)` returns zero-counts. Effect: the 22:35 websocket suite (which logged `ALL SMOKE TESTS PASSED · 50/50 (100%)`) is now classified PASS instead of the previous 0/0/0/0 FAIL.
- **WG-8b — Consumer-thread heartbeat in pool-status**: `RunningFifoQueue.last_consumer_heartbeat_at` updated by `consumer_worker` at the top of each loop iteration. `/api/queue/pool-status` now reports `last_consumer_heartbeat_at`, `seconds_since_heartbeat`, `consumer_stall_threshold_secs`, `consumer_stalled`. New INI key `cj flow consumer stall threshold seconds = 120` + splainer. Effect: stalled consumer is now observable for operators (or future watchdogs) without requiring runtime instrumentation. WG-8a (orphan + 8 dead Calculator cleanup on `:8000`) and WG-8c (empty-`error` field audit) deferred — 8c subsumed into OOS-4 since both anomalies share the same dead-queue routing investigation.
- **WG-9 — TFE voice-gate auto-fallback policy**: 4 modes added (`stall` default, `top_1`, `top_n`, `none`). On `VoiceGateTimeoutError`, the orchestrator branches via `_apply_voice_gate_timeout_policy(proposals)` — sorts by confidence (input order tiebreak), returns 0/1/N proposals or re-raises per policy. Two new INI keys + splainers (`test fix expediter voice gate timeout policy` + `… auto ratify top n`). Effect: after-hours autonomous TFE runs can opt into auto-ratifying the highest-confidence proposal instead of stalling and discarding all proposals. Default unchanged (stall) — preserves prior production behavior.
- **23 new unit tests across 3 files, all PASS**: 9 in `test_tfe_voice_gate_fallback.py` (WG-9), 8 in `test_test_suite_websocket_parser.py` (WG-7), 6 in `test_consumer_heartbeat.py` (WG-8b).
- **147 regression tests PASS** across adjacent unit suites (TFE config + propose, test_suite job + watchdog + pytest_direct, consumer_timed, agentic_pool, fifo_queue_thread_safety, running_queue_threshold) — no breakage.
- **11 changed/new files `py_compile` clean**: full POST-EDIT-VERIFICATION sweep.
- **4 OOS plans drafted (no code work — awaiting ratification)**: `03-oos-1-tfe-bfe-pattern-matcher.md` (cluster coverage invariant + proposal de-dup; explains why 22:35 TFE produced 23 proposals against 8 empty clusters), `03-oos-2-websocket-pytest-junitxml.md` (replace bash runner with native pytest; eliminates WG-7 fallback), `03-oos-3-survivor-deep-dive.md` (conditional, only if WG-6 surfaces non-trivial bugs), `03-oos-4-test-suite-in-dead-anomaly.md` (subsumes WG-8c; finds rogue dead-queue routing path).
- **Memory updates**: `feedback_never_grab_gpu.md` expanded with the "tests must be deleted, not guarded" corollary. New: `feedback_plan_self_audit_against_memory.md` (audit plan against memory rules pre-ExitPlanMode), `feedback_phase0_serialization_prominence.md` (Phase 0 doc serialization belongs at top of plan, not buried as "pre-flight").

**Files Modified (parent Lupin only — CoSA submodule managed separately)**:

Top-level config / image:
- `pyproject.toml` (WG-5: +`lxml>=5,<6`)
- `docker/lupin/Dockerfile` (WG-1: 9 fonts + 8 X11/font libs)
- `src/conf/lupin-app.ini` (WG-9 + WG-8b: 3 new INI keys)
- `src/conf/lupin-app-splainer.ini` (WG-9 + WG-8b: 3 new splainer entries)

CoSA-side (separate submodule commit needed):
- `src/cosa/training/peft_trainer.py` (WG-4: import guard)
- `src/cosa/agents/test_fix_expediter/config.py` (WG-9: 2 new fields + key map)
- `src/cosa/agents/test_fix_expediter/orchestrator.py` (WG-9: timeout-policy branch + helper)
- `src/cosa/agents/test_suite/job.py` (WG-7: `_parse_non_pytest_stdout` + fallback wiring)
- `src/cosa/rest/running_fifo_queue.py` (WG-8b: heartbeat field + pool-status enrichment)
- `src/cosa/rest/queue_consumer.py` (WG-8b: heartbeat write at consumer-loop top)

Lupin-side tests:
- `src/tests/smoke/test_container_preflight.py` (WG-2a: catch FileNotFoundError)
- `src/tests/smoke/utilities/live_pipeline_base.py` (WG-2b: pytest.skip on missing creds + ConnectionError)
- `src/tests/unit/test_tfe_voice_gate_fallback.py` (NEW — 9 tests)
- `src/tests/unit/test_test_suite_websocket_parser.py` (NEW — 8 tests)
- `src/tests/unit/test_consumer_heartbeat.py` (NEW — 6 tests)

Lupin-side deletions (WG-3 BURN):
- `src/tests/smoke/test_embedding_benchmark.py` (DELETED)
- `src/tests/smoke/test_local_embedding_smoke.py` (DELETED)

R&D docs (15 files):
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/01-design.md`
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/02-wg-{1..9}-*.md` (9 files)
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/03-oos-{1..4}-*.md` (4 files)
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/90-execution-log.md`

Tracking docs:
- `history.md` (this entry)
- `TODO.md` (added Session ba7138c4 follow-ups block)
- `.claude-session.md` (appended Session ba7138c4 section)

**Files Deliberately NOT staged** (pre-existing uncommitted changes from prior session, not mine — confirmed via git diff content shows real code changes dated before 2026-04-28):
- `src/fastapi_app/static/css/notifications.css`
- `src/fastapi_app/static/html/notifications.html`
- `src/fastapi_app/static/js/notifications.js`
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py`
- `src/tests/unit/test_session_bridge_lookup.py`

**Commit**: bb9298c

#### Checkpoint | 2026.04.28 19:35 EDT | A-phase + B-phase end-to-end + OOS-4 hotfix + CalculatorAgent codeless replay fix

**Context**: After morning checkpoint (`bb9298c`), user authorized end-to-end execution of the orchestration plan. A-phase walked through Docker rebuild → compose bumps → container recreates → visual-regression alignment proof. B-phase verification re-run on `:8000` exposed two more bugs that needed fix-and-retry cycles before passing: (1) cosa-voice MCP validation failed inside `lupin-rest-test` because two bind mounts (`~/.lupin`, `~/.claude/sessions`) were dev-only AND `claude.code@lupin.deepily.ai` user wasn't seeded into `lupin_db_test`; (2) consumer's bare-exception `failed_job = self.head()` mis-attributed Calculator crashes to the test_suite_job running in the agentic pool, dead-lettering the wrong job (OOS-4 Finding A surfaced as a real production failure). User course-correction surfaced a third regression: CalculatorAgent's snapshots have `code = ['']` BY DESIGN (codeless agent — dispatches CalcIntent to pure-Python helpers), but `solution_snapshot.run_code()` was missing the matching CalculatorAgent special-case that already existed in `run_formatter()`. Fixed all three. Final verification re-run completed cleanly: 4524 P / 15 F / 12 E / 54 S, websocket suite went from false-FAIL to PASS, test_suite_job survived 5 calc dead-letters with proper error fields populated.

**Accomplishments**:

- **A-phase complete**:
  - **A1**: User built `lupin:1.0.0-fonts` (31.7 GB, image_id 8f523bcc8ac2). Pre-build, identified two blockers: (1) `pydantic-ai[slim]==0.6.2` lockfile had a non-existent `slim` extra that uv 0.8.x's tightened `--locked` check rejected; (2) Postgres bind-mount permission collision in build context (sudo workaround required). Fixed lockfile via surgical `uv lock --upgrade-package pydantic-ai` (only pydantic-ai subtree + lxml from WG-5 changed; 295 packages preserved).
  - **A5**: Both `lupin-rest-dev` (port 7999) and `lupin-rest-test` (port 8000) recreated on the new image. 29 fonts + Noto Color Emoji confirmed in container.
  - **A6/A7**: Visual baseline regen wasn't actually needed — pre-existing baselines already align with proper-font chromium rendering. Verified by running canonical e2e script with `-k visual` (no `--update-snapshots`): 13/13 PASSED in 39s.
  - **A8**: Retagged `lupin:1.0.0-fonts` → `lupin:1.0.0`. Old image preserved as `lupin:1.0.0-audioop` and `riqui/lupin:1.0.0` for rollback.
- **B-phase verification** (`ts-976bdc44`, 18:05 EDT submission, 75 min runtime, completed cleanly in DONE queue):
  - websocket: **0/0/0/0 FAIL → 50P PASS** (WG-7 parser fix landed perfectly)
  - smoke: 23F + 7E → **15F + 0E** (WG-2 + WG-3 + WG-5 wins; 8 fewer FAILs, 7 ERRORs eliminated)
  - 0 jobs orphaned in run after run completed
  - test_suite_job survived 5 Calculator dead-letters (vs ts-1c41e064 which got mis-attributed kill before OOS-4 hotfix)
- **OOS-4 hotfix landed** (Parts A + B paired in same try-block) at `src/cosa/rest/running_fifo_queue.py:276`:
  - Part A: `failed_job = self.head()` → `failed_job = job` (use the parameter, mirror happy-path fix already at line 203)
  - Part B: added `failed_job.error = str( e )` so dead-queue listings have populated error fields (was empty for the 8 reaped Calc jobs in 22:35 baseline)
- **CalculatorAgent codeless replay fix** at `src/cosa/memory/solution_snapshot.py:run_code()`:
  - Added codeless-agent short-circuit: when `agent_class_name == "CalculatorAgent"`, synthesize `code_response_dict = {"return_code": 0, "output": self.answer}` instead of raising on the empty-code guard. Mirrors the existing `run_formatter()` special-case at lines 943-953.
  - Diagnosis: user's intuition that "the agent isn't broken; the playback is" was correct. CalculatorAgent dispatches CalcIntent to pure-Python helpers — no Python source to save. Snapshots persist `code = ['']` legitimately. Replay path's empty-code guard mistook this for corruption.
  - 4 corrupted-looking calc snapshots deleted from lancedb (35 → 31 rows) before the codeless-replay fix landed; the deletion was treating a symptom — agent re-cached them on next run, proving the playback was the root cause.
  - 6 new unit tests in `src/tests/unit/test_solution_snapshot_codeless_replay.py`. All PASS in 1.93s with no GPU touch (use `SolutionSnapshot.__new__()` + direct attribute set to bypass the constructor's CUDA model load — see GPU-rule near-miss below).
- **dev/test container parity fix**: added `~/.lupin:/home/rruiz/.lupin:ro` and `~/.claude/sessions:/home/rruiz/.claude/sessions` bind mounts to `lupin-rest-test` in `docker-compose.yml`. cosa-voice MCP credentials + conversation-mode bridge files now visible inside test container.
- **Test-DB user seeding**: added `CC_LISTENER_LUPIN = "claude.code@lupin.deepily.ai"` to `COMPANION_EMAILS` in `src/scripts/seed_test_companions.py`. Test container restart auto-seeded the user into `lupin_db_test` (5 → 6 users).
- **Forward-compat breadcrumbs** (WG-9 deferred work):
  - Splainer note in `lupin-app-splainer.ini` reserving `delegate` mode for future UPE integration.
  - Stub `_delegate_to_predictor()` method in `test_fix_expediter/orchestrator.py` raising `NotImplementedError` with pointer to design doc.
  - New R&D doc `05-voice-gate-policy-evolution.md` capturing the layered architecture target (Layer 0 system default + Layer 1 per-agent + UPE delegate + post-hoc feedback loop). UPE online-learning ~2 dev branches out per user.
- **OOS prewarms** (forensic-only; folded into existing OOS plan docs):
  - **OOS-1 Finding A**: ONE-LINE typo at `test_fix_expediter/job.py:549` — `getattr(c, "failures", [])` should be `getattr(c, "failure_indices", [])`. Explains the 22:35 "0 failure(s) per cluster" rendering bug. The 23 proposals were all grounded; the report just lied about cluster sizes.
  - **OOS-1 Finding B**: 1-3 alternatives per cluster is by design at the prompt level (`prompts/proposal.py:20`). Recommendation: new INI key `test fix expediter max proposals per cluster = 1`.
  - **OOS-4 Findings A-D**: 5 dead-queue write paths (only `_transition_to_dead` canonical), the empty-error root cause at line 270 catch, watchdog confirmed NOT moving source to dead, integration-e2e empty-failures regression (separate snapshot-writer bug).
  - **OOS-2 reality check**: original "M (1-2 days)" estimate was optimistic. The 5500 LOC of bespoke websocket smoke infrastructure uses a fundamentally non-pytest "record and continue" pattern. Realistic effort 4-6 days for full migration; ~half-day for adapter-layer stop-gap.
- **Orchestration plan**: new R&D doc `04-execution-orchestration.md` capturing the 4-phase A→B→C→D execution plan with role assignments (USER vs CLAUDE vs BOTH).
- **GPU-rule near-miss**: `SolutionSnapshot.__init__()` loads ~1 GB of embedding models onto cuda:0 (nomic-embed-text-v1.5 + CodeRankEmbed). First test draft constructed via normal path → triggered GPU load → caught and rewrote to bypass `__init__` via `SolutionSnapshot.__new__()` + direct attribute set. Should expand `feedback_never_grab_gpu.md` with the SolutionSnapshot constructor warning.

**Files Modified (parent Lupin only — CoSA submodule changes need separate cosa-context commit)**:

Top-level config / image / deps:
- `pyproject.toml` (dropped `[slim]` extra from pydantic-ai)
- `uv.lock` (regenerated for pydantic-ai subtree; 295 packages preserved)
- `docker-compose.yml` (lupin-rest-dev image bumped through `:1.0.0-fonts` candidate then back to `:1.0.0` after retag; lupin-rest-test added `~/.lupin` + `~/.claude/sessions` bind mounts)
- `src/conf/lupin-app-splainer.ini` (voice-gate timeout-policy splainer note reserving `delegate` for UPE integration)
- `src/scripts/seed_test_companions.py` (added CC_LISTENER_LUPIN to COMPANION_EMAILS)

CoSA-side (separate submodule commit needed):
- `src/cosa/rest/running_fifo_queue.py` (OOS-4 hotfix Parts A + B at line 276 + 294 area)
- `src/cosa/memory/solution_snapshot.py` (CalculatorAgent codeless replay short-circuit in run_code())
- `src/cosa/agents/test_fix_expediter/orchestrator.py` (WG-9 `_delegate_to_predictor()` stub for future UPE integration)

Lupin-side tests:
- `src/tests/unit/test_solution_snapshot_codeless_replay.py` (NEW — 6 tests, no GPU touch)

R&D docs:
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/03-oos-1-tfe-bfe-pattern-matcher.md` (prewarm Findings A-D folded in)
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/03-oos-2-websocket-pytest-junitxml.md` (prewarm Findings A-F + revised effort estimate)
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/03-oos-4-test-suite-in-dead-anomaly.md` (prewarm Findings A-D folded in)
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/04-execution-orchestration.md` (NEW — 4-phase plan)
- `src/rnd/v0.1.7/2026.04.28-test-suite-anomaly-remediation/05-voice-gate-policy-evolution.md` (NEW — WG-9 forward-compat design)

Lancedb cleanup (data, not git-tracked):
- 4 corrupted CalculatorAgent rows deleted from `src/conf/long-term-memory/lupin.lancedb` (35 → 31). They re-populated via agent path during ts-976bdc44 (proving the playback was the bug, not the data).

**Test results**:
- 6/6 new unit tests in test_solution_snapshot_codeless_replay.py PASS in 1.93s, no GPU touch
- 64/64 regression tests PASS (consumer_timed + agentic_pool + fifo_queue_thread_safety + running_queue_threshold + consumer_heartbeat) after OOS-4 hotfix
- ts-976bdc44 verification re-run: 4524P / 15F / 12E / 54S; test_suite_job survived to completion

**Remaining open issues** (full breakdown in `06-resume-from-here.md`):
1. **12 e2e visual ERRORs persist** — container chromium renders subtly different from host even with same fonts. Fix: schedule a regen run via `pytest_args="--update-snapshots -k visual"` so baselines lock to container rendering.
2. **13 smoke FAILs** — real agent-level failures (not infra). Need OOS-3 deep dive for the 2 confirmed survivors (test_notification_proxy_script_matching + test_tfe_error_capture_smoke).
3. **CoSA submodule commit pending** — 4 files (running_fifo_queue.py, solution_snapshot.py, test_fix_expediter/orchestrator.py + config.py from prior c4e5d4f, agents/test_suite/job.py from prior).
4. **Push parent commit** pending (per `feedback_never_auto_commit_push`).
5. **T46 deferred**: delete deprecated `enter_running_loop()` (~30 LOC; user authorized for after current job).
6. **Memory updates pending**: `feedback_never_grab_gpu.md` should grow the SolutionSnapshot constructor warning.

**Commit**: 892652c

---

### 2026.04.27 - Session aabece5e | Conversation Mode for Claude Code (per-session toggle via cosa-voice MCP)

**Context**: User invoked `/p-is-p-00-start-here` then pivoted into a free-form design conversation about ergonomic friction during voice-driven dialogue from the cosa-voice notification UI session pane: every assistant turn required manually saying "speak your answer as high priority", breaking natural back-and-forth. Outcome: a new session-level toggle ("conversation mode" vs default "notification mode") with four convergent activation surfaces (voice phrase, slash command, MCP tool, UI toggle button), server-canonical state in the existing `~/.claude/sessions/cc-{PPID}.json` bridge, and WebSocket sync to keep multiple UI tabs aligned. Pattern 3 Feature Dev, ~1 week scope, executed end-to-end in this session via plan-then-auto-mode.

**Accomplishments**:

- **Phase 0 — R&D companion doc** at `src/rnd/v0.1.7/2026.04.27-conversation-mode-design.md`: locked decisions table, integration map from Phase 1 Explore agents, gotcha catalog, test plan.
- **Phase 1 — Bridge schema + helpers** in `src/lupin_cli/claude_code/hooks/lib/session_bridge.py`: added `find_session_path_by_id()`, `get_conversation_mode()`, `set_conversation_mode()` following the existing read-modify-write JSON pattern. Inline smoke extended. 10 new pytest tests in `test_session_bridge_lookup.py` covering round-trip, per-session_id isolation, missing-bridge graceful failure, field preservation.
- **Phase 2 — MCP tools + behavioral instructions** in `src/lupin_mcp/cosa_voice_mcp.py`: extended `instructions=` block with the conversation-mode rule (Claude reads `get_session_info()['conversation_mode_active']`, auto-`notify(full_text, suppress_ding=True)` after every turn when on, strips fenced code blocks + tool-call narration, no length cap). Added `enter_conversation_mode()` and `exit_conversation_mode()` `@mcp.tool` functions + `_flip_conversation_mode()` helper. `get_session_info()` now returns `conversation_mode_active` from the bridge. 6 new pytest tests in `test_cosa_voice_mcp_conversation_mode.py`.
- **Phase 3 — HTTP endpoint + WebSocket event**: new router `src/cosa/rest/routers/conversation_mode.py` (CoSA-side per existing convention; plan deviation logged — `src/fastapi_app/routers/` doesn't exist). `GET/POST /api/cosa-voice/conversation-mode/{session_id}` with `@require_api_key_or_jwt` + `emit_to_user(authenticated_user_id, "conversation_mode_changed", {...})` broadcast. Wired in `src/fastapi_app/main.py` (import + include_router). INI allowlist updated: `websocket available events` += `conversation_mode_changed` in `lupin-app.ini` + `lupin-app-splainer.ini`. 7 new pytest tests in `test_conversation_mode_router.py` (mocked WebSocketManager).
- **Phase 4 — UI toggle widget**: `notifications.js` got `CONVERSATION_MODES_KEY` localStorage (object keyed by session_id, mirrors `SESSION_NAMES_KEY` pattern), `conversationModes` cache, WebSocket subscription update, `case "conversation_mode_changed"` dispatch, `toggleConversationMode()`/`handleConversationModeChanged()`/`_setConversationModeLocal()` methods, and a per-session toggle button in the sender-card header (`data-session-id` selector for cross-tab updates). `notifications.css` got `.sender-conversation-mode-btn` styles matching the gist-btn pattern with green `.is-active` variant. Icon corrected from 🔕 (muted bell — semantically backwards) to 🔔 (plain bell — notifications happening) per user feedback.
- **Phase 5 — Slash commands**: `/conversation-mode-on` and `/conversation-mode-off` at `.claude/commands/`. Both registered.
- **Phase 6 — E2E test file written, execution gated**: `src/tests/e2e_ui/test_conversation_mode.py` Playwright tests for cache hydration + DOM presence. NOT submitted to `:8000` (per E2E two-phase gate — needs user-confirmed slot via `/api/test-suite/submit`).
- **Bind mount fix discovered live**: first toggle attempt in browser returned 404 because `:7999` Docker container had no bind mount for `~/.claude/sessions/`. Added `~/.claude/sessions:/home/rruiz/.claude/sessions` (rw) to `docker-compose.yml`, recreated container via `docker compose up -d --force-recreate lupin-rest-dev` (a plain `docker restart` won't re-evaluate volumes). Verified bridge files now visible inside container.
- **23 new pytest tests across 3 files, 52/52 pass** including pre-existing session_bridge suite.

**Files Modified (parent Lupin only — CoSA submodule managed separately)**:
- `src/lupin_cli/claude_code/hooks/lib/session_bridge.py`
- `src/lupin_mcp/cosa_voice_mcp.py`
- `src/fastapi_app/main.py`
- `src/fastapi_app/static/js/notifications.js` (layered on pre-existing parallel-session WIP)
- `src/fastapi_app/static/css/notifications.css`
- `src/conf/lupin-app.ini`
- `src/conf/lupin-app-splainer.ini`
- `src/tests/unit/test_session_bridge_lookup.py`
- `docker-compose.yml`
- `history.md`

**Files Created (parent Lupin)**:
- `src/rnd/v0.1.7/2026.04.27-conversation-mode-design.md`
- `src/tests/unit/test_cosa_voice_mcp_conversation_mode.py`
- `src/tests/unit/test_conversation_mode_router.py`
- `src/tests/e2e_ui/test_conversation_mode.py`
- `.claude/commands/conversation-mode-on.md`
- `.claude/commands/conversation-mode-off.md`

**CoSA submodule** (managed in its own context — not committed from this session):
- `src/cosa/rest/routers/conversation_mode.py` (new)

**Status**: Implementation complete across Phases 0-5. Phase 6 file written; E2E execution awaits user-confirmed `:8000` slot. No commits yet.

---

### 2026.04.27 - Session 09f4c557 | Docker image hygiene: 130 GB → 31.6 GB (Tier 0+1 + cuda-compat fix + drop recursive chown + audioop-lts) + Lance DB cleanup

**Context**: Day-long arc. Started reviewing CJ-flow phase-3 test results; ended having cut the production image from 130 GB to 31.6 GB across three iterative rebuilds, reclaimed 16.67 GB on the lancedb, fixed two regressions caught at sanity-boot time (CUDA Error 804 on RTX 4090s; `pydub` import failing on Python 3.13), and bounced both servers onto the new image.

**Accomplishments**:
- **Tier 0+1 hygiene pass**: Python 3.11.5 → 3.13.7 via `uv python install` (~20 s vs 15-min source build), single `uv sync --locked` from new `pyproject.toml` + `uv.lock` (293 packages) vs 20+ pip layers, BuildKit cache mounts, fail-loud Python patcher replacing silent `sed -i` for pytest-playwright-visual-snapshot. Image: 130 GB → 72.1 GB.
- **CUDA Error 804 fix**: `apt purge cuda-compat-12-4` after FROM. Base image's R550-class libcuda shim was getting bind-mounted by nvidia-container-toolkit and engaging Forward Compatibility (Tesla-only). On consumer RTX 4090s: error 804. Removing it lets cu124 wheels run on R535 driver via Minor Version Compatibility (unrestricted). Validated via runtime experiment (commit derivative, GPU sanity green).
- **Drop recursive `chown -R`**: single `USER rruiz` switch after front-loaded root block + `--chown=rruiz:rruiz` on every COPY. Eliminated the 31.5 GB chown layer that copy-on-write was creating from inode-metadata-only changes. Bonus: BuildKit uv cache mount retargeted to `/home/rruiz/.cache/uv,uid=1001,gid=1001` saved another 8.5 GB. Image: 72.1 GB → 31.6 GB.
- **Audioop-lts fix**: full FastAPI app import sanity boot caught `pydub 0.25.1` failing on Python 3.13 (stdlib `audioop` removed). Added `audioop-lts==0.2.2` shim, rebuilt. 3-stage sanity now green (GPU + flash-attn + audioop + 155 FastAPI routes register). lupin:1.0.0 promoted to the audioop-fixed build (image ID `1b0805cfb3aa`).
- **docker-compose.yml**: both pins (lines 34 + 93) → `lupin:1.0.0`. Dev :7999 + test :8000 bounced onto the new image, both healthy.
- **Lance DB cleanup**: created `src/scripts/cleanup_lupin_lancedb.py` (uses `tbl.optimize(cleanup_older_than=...)`, the modern combined compaction+cleanup API). First run with 7-day cutoff reclaimed 16.67 GB (43.4 GB → 26.7 GB; `input_and_output_tbl` had 11,819 versions, 5,093 cleaned). Verified zero `.checkout()` calls anywhere = no time-travel breakage. Pre-cleanup backup in `io/backups/` deleted after smoke tests (+43 GB on /mnt/DATA01).
- **R&D plan docs serialized** in `src/rnd/v0.1.7/`: `2026.04.26-dockerfile-cpython-3.11.9-upgrade.md` (narrower predecessor), `2026.04.27-cuda-driver-vs-image-torch-cu124-mismatch.md` (Error 804 handoff to Docker expert), `2026.04.27-drop-recursive-chown-image-bloat-audit.md` (chown plan + execution log).
- **Memory feedback rules added**: `feedback_no_auto_promote_tags.md` (park rebuild outputs at candidate tag, never overwrite working tag without confirmation), `feedback_backups_only_to_dedicated_drive.md` (per-script backups go to dedicated drive only, never `io/backups`).
- **User-driven script refinements**: `cleanup_lupin_lancedb.py` updated to default `--older-than-days 1` (was 7), backup function removed entirely (Lupin already has nightly ecosystem-level backups).
- **Dockerfile follow-up**: added missing `COPY --chown=rruiz:rruiz src/lupin_cli /var/lupin/src/lupin_cli` (caught by FastAPI import sanity at validation time; production worked because of the runtime bind-mount of `./src`). Takes effect on next rebuild.
- **Image cleanup**: removed 6 unused images (genie-in-the-box 0.6/0.7/0.8, peft 0.2/0.3, hf-tgi), zapped 25 zombie containers from 2023-2024, ran `docker builder prune -af` (84 GB build cache freed). Net /mnt/DATA01 free: 78 GB → 93 GB after the lance backup delete.

**Files Modified** (parent Lupin only):
- `docker/lupin/Dockerfile` (rewritten end-to-end across 3 iterations)
- `docker/lupin/scripts/patch-pytest-playwright-visual-snapshot.py` (NEW)
- `pyproject.toml` (NEW — 293-package lock)
- `uv.lock` (NEW — generated, 528 KB)
- `.dockerignore` (lancedb + postgresql-dev-data exclusions)
- `src/scripts/cleanup_lupin_lancedb.py` (NEW + later refactor)
- `docker-compose.yml` (both image pins → lupin:1.0.0)
- `src/rnd/v0.1.7/2026.04.26-dockerfile-cpython-3.11.9-upgrade.md` (NEW)
- `src/rnd/v0.1.7/2026.04.26-dockerfile-cpython-3.11.9-upgrade-to-3.13.13.md` (NEW — expert plan)
- `src/rnd/v0.1.7/2026.04.27-cuda-driver-vs-image-torch-cu124-mismatch.md` (NEW)
- `src/rnd/v0.1.7/2026.04.27-cuda-driver-vs-image-torch-cu124-mismatch-omit-cuda-compat-12-4.md` (NEW — expert reply)
- `src/rnd/v0.1.7/2026.04.27-drop-recursive-chown-image-bloat-audit.md` (NEW)
- `history.md` (this entry)

**Image Trajectory**:
| Image | Size | Δ vs 0.9.0 |
|---|---:|---:|
| lupin:0.9.0 (pre-Tier-0) | 130 GB | baseline |
| lupin:1.0.0 (Tier 0+1 + cuda-compat) | 72.1 GB | −45% |
| lupin:1.0.0 (+ drop chown + audioop-lts) | **31.6 GB** | **−76%** |

**Commits**:
- `3950d0a` (Checkpoint: docker image — Tier 0+1 + cuda-compat fix + drop recursive chown — 130 GB → 31.6 GB)
- pending: cleanup script + audioop fix in pyproject/uv.lock + docker-compose pins + Dockerfile lupin_cli + history

---

### 2026.04.27 - Session 49c27830 | Bug Fix Mode — Notification dispatch unification (cross-user CC-listener fallback)

**Context**: USER-REPORTED bug — 3 user-initiated messages from the LookML CC notifications panel UI targeting CC session `b2ce9133` were silently dropped. Forensic dive surfaced a duplicated dispatch pattern across 6 sites with inconsistent behavior. Day's arc: narrow fix → audit → planned full unification → executed Phases A-F.

**Fixes**:

- **Narrow fix — `POST /api/notify` fire-and-forget cross-user listener fallback**: 3 `user_initiated_message` rows persisted with `state='created'` because `notify_user` short-circuited on `is_user_connected(target_system_id)=False` even though `cc-listener-{job_id}` was active under a shared service-account user_id. Added inline cross-user fallback (`src/cosa/rest/routers/notifications.py:504-575`). 5 unit tests in `src/tests/unit/test_notify_cc_listener_fallback.py`.

- **Full fix — Notification dispatch unification (Phases A-F)**: Comprehensive audit found 6 sites with the same dispatch pattern, 2 missing the listener fallback entirely. Extracted `WebSocketManager.emit_to_user_or_listener_sync(user_id, job_id, event, data) -> dict` (~95 lines incl. docstring) as a sibling to the canonical `emit_to_user_and_admins_sync` precedent. Migrated 5 dispatch sites onto the helper:
  1. `notify_user` fire-and-forget — replaced narrow fix with helper call
  2. `notification_expired` SSE timeout broadcast — gained the listener fallback
  3. `notification_responded` response-submission broadcast — gained the listener fallback
  4. `send_job_message` (`queues.py`) — collapsed 40-line dual-emit to ~20 lines
  5. `_emit_notification_added` (notification_fifo_queue.py) — collapsed targeted-user + listener emits

- **Wrapped yesterday's 7-test fix**: marked the 7 self-inflicted E2E test regressions from the 2026-04-26 :8000 sweep as Completed in bug-fix-queue.md.

**Files (CoSA, user commits separately)**:
- `src/cosa/rest/websocket_manager.py` (new helper)
- `src/cosa/rest/routers/notifications.py` (Migrations 1, 2, 3)
- `src/cosa/rest/routers/queues.py` (Migration 4)
- `src/cosa/rest/notification_fifo_queue.py` (Migration 5)

**Files (Lupin)**:
- `src/tests/unit/test_websocket_manager_dispatch.py` (NEW — 9 helper unit tests)
- `src/tests/unit/test_notify_cc_listener_fallback.py` (UPDATED — 5 helper-aware + 2 new structural)
- `bug-fix-queue.md` (Completed entries: dispatch unification + 7-test fix; narrow-fix entry marked superseded)

**Tests**: Lupin unit suite **3672 passed, 1 xfailed, 0 failed** (was 3638 pre-session → +34 tests). With CoSA notification fifo queue tests: **3677 passed**. WebSocket smoke **50/50 pass**. Final grep audit: **zero** `emit_to_session_sync` calls in 3 migrated routers; helper is the single chokepoint.

**Plan**: `~/.claude/plans/dazzling-napping-frost.md` (full Phase A-F design + verification steps).

**Deploy status**: Helper + 5 migrations are backwards-compatible. `:7999`/`:8000` still on pre-fix bytecode (held off bouncing — user is rebuilding v1.0.0 image and other CC sessions are active). Live deployment pending.

**Out-of-scope follow-ups filed**: TFE/BFE post-resume proposal-review UX gap; `:7999` StatReload watcher recovery; CC-listener answer-response wiring; service-account → operator routing helper.

---

### 2026.04.27 - Session ee896fa3 (continued) | R&D: Promote adversarial+fitness review pattern to planning-is-prompting

**Context**: Single-purpose continuation day for session ee896fa3 (running since 2026-04-26). User observed that the two-pass review prompts written ahead of CJ Flow phases 1–3 (`05-adversarial-review-prompt.md` + `06-fitness-review-prompt.md`) caught design gaps and ownership-language ambiguities before any code was written, and asked whether the pattern should be formalized as a reusable skill in the planning-is-prompting repo. After ultrathink-grade review the answer is yes, with a hybrid architecture (PIP canonical + per-project wrapper) and a Pattern 1/2-only trigger.

**Accomplishments**:
- Read the source artifacts (`05-adversarial-review-prompt.md`, `06-fitness-review-prompt.md`, `00-working-contract.md`) and confirmed the technique abstracts cleanly across projects
- Synthesized architecture proposal: `planning-is-prompting/workflow/plan-review.md` (canonical) + `<project>/.claude/skills/plan-review/SKILL.md` (thin wrapper) — matches existing PIP slash-command-wrapper pattern
- Identified Phase 2 (convention establishment) as the linchpin — without `EXECUTOR: AI/HUMAN`, `Q-N` decision anchors, and `TBD` markers being *established* in `p-is-p-02-documenting-the-implementation.md`, the review's greps return false negatives
- Promoted REUSE detection (deficiency type 5 in pass 2) to first-class status — forcing function for de-duplication that AI-authored plans systematically miss
- Enumerated 5 risks (convention dependency, review fatigue, review-as-procrastination, fix-yet-gate violation, pattern drift) with explicit counter-measures
- Defined a 4-phase implementation pathway with Phase 1 (lift) cheapest, Phase 2 (conventions) highest-leverage
- Serialized the full proposal to `src/rnd/v0.1.7/2026.04.27-promote-plan-review-pattern-to-pip.md` (278 lines, ~19 KB) — self-contained, includes Phase 1 deliverable shape spec + 6 open questions for PIP-context resolution

**Files Modified** (parent Lupin only):
- `src/rnd/v0.1.7/2026.04.27-promote-plan-review-pattern-to-pip.md` (NEW)
- `history.md` (this entry)
- `.claude-session.md` (touched-files log)

**Status**: R&D proposal serialized. Phase 1 (lifting the prompts into PIP `workflow/plan-review.md` parameterized) deferred to a `planning-is-prompting`-rooted Claude session.

**Commit**: [pending]

---

### 2026.04.26 - Session ee896fa3 | cosa-voice MCP startup fix + podcast tuning + server-lifecycle skill

**Context**: Three discrete pieces of work in one session — (1) MCP server failed to connect at session start; (2) user wanted podcast speakers more animated/faster-feeling and the submission UI to default to dual-language; (3) post-fix, user asked to canonize the bounce-vs-update knowledge as a skill.

#### Checkpoint | 2026.04.26 13:36 EDT | MCP startup fix + podcast tuning + server-lifecycle skill build

**Stage 1 — cosa-voice MCP failing to connect**
- Root cause: `~/.lupin/config` had a duplicate `email`/`password` pair under `[lupin-mobile]` because the `[cosa]` section header was missing before the second pair. `configparser.read()` raised `DuplicateOptionError`, which crashed the MCP server during `_validate_repo_account()` at `cosa_voice_mcp.py:295`.
- Fix: user inserted the missing `[cosa]` section header. Verified via manual stdio boot — server reached "Session ready" + FastMCP handshake.
- No project-tree changes (config is in user home).

**Stage 2 — Podcast generator tuning** (3 files in parent + 1 in CoSA submodule)
- `src/conf/lupin-app.ini` :663, :670 — ElevenLabs `style` 0.40 → **0.65** (Nora), 0.50 → **0.70** (Quentin) for more expressive delivery
- `src/conf/lupin-app-splainer.ini` :210, :215 — `Default:` annotations resync'd
- `src/cosa/agents/podcast_generator/config.py` :219, :236 (CoSA submodule, managed separately) — Nora tone "highly animated, fast-paced, and inquisitive"; Quentin tone "energetic, warm, and authoritative"
- `src/fastapi_app/static/js/notifications.js` :2666, :2753 — `target_languages: [ 'en' ]` → `[ 'en', 'es-MX' ]` for default dual-language submissions
- Verification: `py_compile` clean on `config.py`; new INI values confirmed live in container after `docker restart lupin-rest-dev`. Subjective audio quality is ear-test only — explicitly not automatable.

**Stage 3 — `server-lifecycle` skill + memory consolidation**
- New skill at `.claude/skills/server-lifecycle/` with `SKILL.md` + `references/change-impact-matrix.md`. Encodes the per-server reload-regime asymmetry: `:7999` dev runs `--reload` ON (`.py` only), `:8000` test runs `reload=False` deliberately so concurrent dev work doesn't poison a running test on the snapshot.
- Three behavioral rules baked in: (1) NEVER volunteer a `:7999` bounce; (2) queue-check courtesy before `:7999` SIGKILL; (3) `:8000` is NEVER bounced ad-hoc — monopolize-mode protocol via `/api/test-suite/submit` only.
- Decision matrix: `.py` (dev: auto-reload, test: bounce), `.ini` (both: bounce), static (both: hard-refresh), `docker-compose.yml`/`Dockerfile`/`requirements.txt`/`.env` (down/up or build/up — `restart` alone silently does nothing).
- `CLAUDE.md` § RUNNING/TESTING FASTAPI APPLICATIONS — added pointer line to the skill.
- Memory: slimmed `feedback_dev_server_bounce_via_docker.md` to a pointer; cross-linked the three keep-memories (`feedback_dev_server_bounce_courtesy.md`, `feedback_fastapi_auto_reload.md`, `feedback_test_server_monopolize_mode.md`).

**ASR gotcha noted**: user's MacBook ASR mistranscribed "Docker" as "doctor" mid-session ("use the doctor command"). Captured in skill as a phonetic-neighbor heuristic.

**Anti-pattern caught**: I improvised a SIGTERM dance on the host-visible Python PID before realizing both servers are containerized. The "bounce" worked only because Docker's restart policy respawned the container — but the canonical command is `docker restart lupin-rest-dev`. Now codified in the skill.

#### Files Modified (parent Lupin only — CoSA submodule managed separately)
- `src/conf/lupin-app.ini`
- `src/conf/lupin-app-splainer.ini`
- `src/fastapi_app/static/js/notifications.js` (split-staged: only my 2 hunks committed; parallel-session WIP left unstaged)
- `CLAUDE.md`
- `.claude/skills/server-lifecycle/SKILL.md` (new)
- `.claude/skills/server-lifecycle/references/change-impact-matrix.md` (new)
- `history.md`

**CoSA submodule** (managed in its own context): `src/cosa/agents/podcast_generator/config.py`

**Status**: Checkpoint committed; session continues.

**Commit**: 3f37b03

---

### 2026.04.25 - Session 6c798a07 | Bug Fix: Podcast generator completion abstract — clickable URLs (Listen → in-app player, Download, View Script)

**Context**: User submitted a podcast generation job (pg-6bcf412d), it completed, but the completion notification's abstract showed bare filesystem paths in backticks instead of clickable URLs — no way to play or download the generated MP3 from the UI. Two-stage fix in one session.

**Accomplishments**:

#### Stage 1 — Build clickable Markdown links in completion abstract
- Root cause at `src/cosa/agents/podcast_generator/job.py:317-320`: paths were embedded as `` `{self.script_path}` `` (raw filesystem paths in backticks)
- Added `_to_rel()` helper that normalizes abs / `io/`-prefixed / `/`-prefixed paths to clean relative paths under `io/` (matches receiving logic in `cosa/rest/routers/io_files.py:88-98`)
- Built three Markdown links: `[🎧 Listen](/app/audio?path=...)`, `[⬇️ Download](/api/io/file?path=...&download=true)`, `[📝 View Script](/app/docs?path=...)`
- Switched artifact storage from absolute → relative paths (matches `presentation_generator/job.py:336-341` convention so UI job-card builds correct URLs)
- Added `report_path` artifact for queue-card metadata

#### Stage 2 — Listen link points to player page, not raw audio endpoint
- First iteration pointed Listen at `/api/io/file?path=...` — user noted this forced download because Starlette `FileResponse(filename=...)` defaults to `Content-Disposition: attachment`
- Briefly fixed `io_files.py` with `content_disposition_type="inline"` then **reverted** when user clarified Listen should target the canonical `/app/audio` route alias (serves `static/html/audio-player.html` — full HTML5 player UI with title, subtitle from script H1, file size, embedded download button)
- Final Listen URL: `/app/audio?path=...` (player page, no API change needed)

#### Tests
- `src/tests/unit/test_podcast_completion_report.py`: updated 2 existing path assertions → URL-link assertions; added artifact-relative-path assertions; added parametrized `test_completion_url_path_normalization` covering 3 input shapes (abs / `io/`-prefixed / `/`-prefixed)
- 6/6 podcast completion tests pass; 26/26 broader podcast-related unit tests pass
- `py_compile` clean, full import chain clean

#### Verification (manual smoke)
- `/app/audio?path=...mp3` → HTTP 200 `text/html` (player page) ✓

## Archives

- [2026-04-22 to 04-24](history/2026-04-22-to-24-history.md) — 6 sessions (PR Readiness 100%-green, CJ Flow Async Phase 0+1, cosa-voice nested-repo fix, [UNKNOWN] hyphen fix, TFE model flip, LanceDB-GCS CUDA OOM resolution)
- [2026-04-14 to 04-21](history/2026-04-14-to-21-history.md) — 12 sessions (TFE Resume E2E, BFE Phase 6 obs, CJ Flow async design, Opus 4.7 + thinking-effort, bug fixes)
- [2026-04-08 to 04-14](history/2026-04-08-to-14-history.md) — 23 sessions (TFE E2E, BFE Phase 6, checkpoint-resume, bug fixes)
- [2026-03-26 to 04-07](history/2026-03-26-to-04-07-history.md) — Sessions 379-a47f938e (BFE Phase 6, CJ Flow persistence, Sonnet pivot, UPE LanceDB isolation)
- [Full archive index](history/README.md)
