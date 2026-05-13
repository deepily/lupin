# Resume Prompt — Speakerphone Solo/Chorus, Phases 6-8 (post-context-clear)

**Format**: This file is BOTH (1) a serialized resume doc for project history, and (2) the literal text Rick pastes into a fresh Claude session to pick up where the prior session left off. Last updated: 2026-05-12 PM EDT (Rio session 83ba1e51, after Phase 5 completion).

## Stop-point snapshot (where this session ended)

- ✅ Phase 1 — INI key + helper (commit `c82ee04`)
- ✅ Phase 2 + Phase 3 — bridge rename + server router (commit `8a8c31c`)
- ✅ Phase 4 — MCP tool rename + `_notify_impl` mode-conditional (commit `9ba4db5`)
- ✅ Phase 5 — hook layer renames (latest commit at session-end)
- ⏸️ **Phase 5b** — 4-variant rider content matrix (function gating done in 5; PROSE content in `_system_reminder_body` still says legacy "conversation mode" text — quality-of-output refinement, non-blocking)
- ⏸️ **Phase 6** — Global `~/.claude/CLAUDE.md` + skills rename/retire (user home directory; awaiting authorization)
- ⏸️ **Phase 7** — Multiplexer UI + 100% c8 coverage (biggest phase, ~90-180 min)
- ⏸️ **Phase 8** — Chorus UX color/glyph (deferred per canonical plan, post-merge)

---

## 📋 COPY-PASTE PROMPT (give this to fresh Claude after `/clear`)

> Resume the speakerphone solo/chorus refactor — phases 4 through 7. The full plan + per-phase design docs live at `src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/`. Read `00-index.md` for orientation, then this file (`99-resume-here-phases-4-7.md`) for exact stop-point state.
>
> Quick state check:
>
> ```bash
> git log --oneline -10 | grep -i "speakerphone\|phase"
> ```
>
> The most recent `[LUPIN] Phases ...` commit tells you what's already landed. Phases that have NOT been committed need implementing. The remaining phases are 4 (MCP tool rename + `_notify_impl` mode-conditional), 5 (hook rider 4-variant matrix), 6 (CLAUDE.md + skills), and 7 (multiplexer UI + 100% c8 coverage).
>
> Crush through the remaining phases. Same protocol as the previous session:
> - **Audit at execute time** per `feedback_audit_plans_at_execute_time` — check actual code against design docs before implementing
> - **Phases 2-7 ship as ONE LOGICAL PR** but I've already broken the design-doc's single-commit rule (Phases 2+3 landed as commit `8a8c31c`). Each subsequent phase can be its own commit since the half-state is already on disk.
> - **CoSA submodule**: edit files freely (per `feedback_cosa_edit_vs_manage_git`) but **never commit CoSA from parent context** (per `feedback_lupin_only_never_cosa`). The Phase 3 speakerphone.py, commons.py, voice_persona.py, notifications.py CoSA-side edits remain uncommitted from parent.
> - **High-priority `notify()` at every phase boundary**. cosa-voice MCP server is at `:7999`. If notify fails ("Cannot reach server"), continue without it and try again at next boundary.
> - **No auto-commit** per `feedback_never_auto_commit_push` — wait for explicit "commit" before each git commit.
> - **`feedback_fix_all_failing_tests`** — never classify failures as "pre-existing" or "out of scope"; fix in same session.
> - **`feedback_skip_rnd_doc_for_trivial_fixes`** — but per-phase execution logs (`92-phase2-execution-log.md`, `93-phase3-execution-log.md`, etc.) per the BFE pattern are required for non-trivial phases.
>
> Server boot: `:7999` was UNBLOCKED by the Phases 2+3 commit. The MCP server (cosa_voice_mcp.py) and Claude Code hooks (stop.py, idle_waiter) WILL STILL FAIL until Phases 4+5 land — they import the old `get_conversation_mode` / `set_conversation_mode` names. If a Claude Code session lifecycle event fires, it'll crash until Phase 5.
>
> Test-server (`:8000`) is monopolize-mode — never inject. Phase 7 will land mode-parameterized E2E UI tests; those go via `/api/test-suite/submit` with a user-confirmed `scheduled_at`.
>
> Start by reading: `00-index.md`, then this file's "Where we stopped" section below, then the next un-implemented phase's design doc.

---

## Where we stopped

To determine the EXACT stop point on resume:

```bash
git log --oneline -20 | head -10
```

| If the most recent speakerphone commit is... | Then start at... |
|---|---|
| `c82ee04` (Phase 1) | **Phase 2** — `11-phase2-bridge-rename-design.md` |
| `8a8c31c` (Phases 2+3) | **Phase 4** — `13-phase4-mcp-tool-rename-design.md` |
| `9ba4db5` (Phase 4) | **Phase 5** — `14-phase5-hook-rider-design.md` |
| Phase 5 commit (most recent at end of 2026-05-12 PM session) | **Phase 5b** (content matrix) OR **Phase 6** (CLAUDE.md + skills) OR **Phase 7** (multiplexer UI — biggest) |
| A commit landing Phase 6 work | **Phase 7** — `16-phase7-multiplexer-ui-design.md` |
| A commit landing Phase 7 work | All core phases done; consider Phase 8 (`17-phase8-color-glyph-uxs-design.md`) — DEFERRED post-merge per canonical plan |

**Always grep for un-committed work first**:

```bash
git status --short
# If session_bridge.py / cosa_voice_mcp.py / stop.py / hook_common.py /
# multiplexer files show modifications, those edits are mid-flight and need
# to be folded into the next commit.
```

---

## Cumulative state so far (as of 2026-05-12 PM EDT)

### ✅ Committed in parent Lupin

- `c82ee04` — Phase 1: INI key + `get_tts_interaction_mode()` helper + AM Rio design subdir (15 docs)
- `5ebccab` — Pre-existing commons subprocess test fix (`parents[2]` → `parents[3]`)
- `8a8c31c` — Phases 2+3: bridge field rename + speakerphone.py router + mode-conditional displacement

### ⏳ Uncommitted in CoSA submodule (Rick handles separately)

- `src/cosa/utils/util.py` — `get_tts_interaction_mode()` helper added (Phase 1)
- `src/cosa/rest/routers/speakerphone.py` (NEW) + `conversation_mode.py` (DELETED) (Phase 3)
- `src/cosa/rest/routers/commons.py` — response field renamed (Phase 3)
- `src/cosa/rest/routers/voice_persona.py` — docstring update (Phase 3)
- `src/cosa/rest/routers/notifications.py` — `valid_types` allowlist (Phase 3)
- `src/cosa/rest/commons_rate_limiter.py` — comment update (Phase 3)
- `src/cosa/rest/notification_fifo_queue.py` — comment update (Phase 3)

**Important**: parent's submodule pointer references the OLD CoSA commit (without these edits). Fresh checkouts will not have the CoSA edits until you (Rick) commit them in a CoSA-context session and bump parent's submodule pointer.

### 🟡 Still broken (until Phase 4+5)

- **MCP server** `src/lupin_mcp/cosa_voice_mcp.py` — imports the old `get_conversation_mode` / `set_conversation_mode` names from session_bridge. Will fail on spawn. **Phase 4 fixes this.**
- **Claude Code hooks** `src/lupin_cli/claude_code/hooks/stop.py` line 38 + 671 — imports `get_conversation_mode`. Will fail when stop hook fires. **Phase 5 fixes this.**
- **Test test_idle_waiter.py** line 81 — patches `get_conversation_mode`. **Phase 5 fixes this.**

### ✅ FastAPI server boots

Verified via `python -c "import fastapi_app.main"` against the Phases 2+3 commit.

---

## Phase scope quick-reference

### Phase 4 — MCP tool rename + `_notify_impl` mode-conditional (~60-90 min)

**File**: `src/lupin_mcp/cosa_voice_mcp.py` (parent Lupin, ~1500 LOC). Design doc: `13-phase4-mcp-tool-rename-design.md` (380 LOC after Q4 fold-in).

Key changes:
- Rename MCP tools `enter_conversation_mode` / `exit_conversation_mode` → `enable_speakerphone` / `disable_speakerphone`
- Rename `_flip_conversation_mode` → `_flip_speakerphone`; point HTTP at `/api/cosa-voice/speakerphone/{sid}`
- `get_session_info()` response: rename `conversation_mode_active` → `speakerphone_on`, add `tts_interaction_mode`
- `_notify_impl()` cross-talk leak cue mode-conditional:
  - Solo: keep today's inversion (force `suppress_ding=True` when `speakerphone_on=False` for CC senders)
  - Chorus: passthrough — no inversion
- MCP `instructions=` block + `enable_speakerphone` tool docstring: mode-aware language per Q4 audit finding (`04-mode-coupling-audit.md` §New Finding)

Also: `src/tests/unit/test_cosa_voice_mcp_conversation_mode.py` → rename to `test_cosa_voice_mcp_speakerphone.py` + mass rename + parameterize over modes.

### Phase 5 — Hook rider 4-variant matrix + helper renames (~60-120 min)

**Files**: `src/lupin_cli/claude_code/hooks/lib/hook_common.py` + `user_prompt_submit.py` + `stop.py` + `cc_notification_listener.py`. Design doc: `14-phase5-hook-rider-design.md` (350 LOC).

Key changes:
- Rename `conv_mode_wrap` / `conv_mode_reminder_block` / `conv_mode_exit_reminder` → `speakerphone_wrap` / `speakerphone_reminder_block` / `speakerphone_exit_reminder`
- `_system_reminder_body` split into 4-variant matrix (solo+speaker / solo+phone / chorus+speaker / chorus+phone)
- Migrate CLAUDE.md brevity rules into the speakerphone-on rider variant
- Update `stop.py:38,671` to use `get_speakerphone`
- Update `cc_notification_listener._handle_action` to route `action:disable_speakerphone` → `_inject_disable_speakerphone_reminder` (renamed from `_inject_exit_conversation_reminder`)

### Phase 6 — CLAUDE.md migration + skill rename/retire (~30-60 min)

**Files**: `~/.claude/CLAUDE.md` (global) + `~/.claude/skills/conversation-mode-{on,off,guardrails}/`. Design doc: `15-phase6-claude-md-skills-design.md` (215 LOC).

Key changes:
- Remove `INTERACTIVE TOOL ROUTING` + `CRITICAL: The User Is NOT Watching the Terminal` + `CONVERSATION MODE & TTS RESPONSE BREVITY MANDATE` sections from global CLAUDE.md (content now in Phase 5 rider)
- Add pointer paragraph
- Rename skills `conversation-mode-{on,off}` → `speakerphone-{on,off}`
- Retire `conversation-mode-guardrails` skill (USER-ONLY initiation rule moves into MCP tool docstrings + per-turn rider)

### Phase 7 — Multiplexer UI + 100% c8 coverage (~90-180 min, BIGGEST)

**Files**: `src/fastapi_app/static/js/multiplexer/` + `src/tests/unit/multiplexer/`. Design doc: `16-phase7-multiplexer-ui-design.md` (285 LOC).

Key changes:
- Event listener rename: `conversation_mode_changed` → `speakerphone_changed`
- Mode-aware toggle: solo → bell↔phone (today's UI preserved), chorus → phone↔speaker
- Mode-aware affordances: green mic-monopoly pin in solo only
- 100% c8 coverage hard gate per `feedback_100pct_coverage_multiplexer` (lines AND branches AND functions; `c8 --100` flag)
- Mode-parameterized UI tests

### Phase 8 — DEFERRED per canonical plan

Chorus-mode UX color/glyph follow-up — happens AFTER the Phases 1-7 PR merges. Don't pursue in the same arc. Design doc `17-phase8-color-glyph-uxs-design.md` sketches three options; user gates this separately.

---

## Standing rules (consult before every phase)

| Memory | Rule |
|---|---|
| `feedback_audit_plans_at_execute_time` | Re-audit design doc against actual code BEFORE writing |
| `feedback_lupin_only_never_cosa` | Never run git in `src/cosa/` from parent context |
| `feedback_cosa_edit_vs_manage_git` | But editing CoSA files is fine |
| `feedback_fix_all_failing_tests` | Never defer pre-existing test failures |
| `feedback_no_migration_code` | No backward-compat aliases; hard cuts on naming |
| `feedback_no_defensive_programming` | No `getattr` chains, no `or ""` defaults |
| `feedback_never_auto_commit_push` | Wait for explicit "commit" before every git commit |
| `feedback_sweep_for_pattern_offenders` | When fixing pattern bugs, grep across parent + CoSA + lupin_mcp |
| `feedback_always_include_pros_cons_recommendation` | Multi-option asks need pros/cons/recommendation/flip-condition |
| `feedback_100pct_coverage_multiplexer` | Multiplexer TS hard-gated at 100% c8 (Phase 7) |
| `feedback_test_server_monopolize_mode` | `:8000` tests go via `/api/test-suite/submit` only |
| `feedback_tests_parameterize_base_url` | Tests use `LUPIN_API_URL` env var, never hardcode `:7999` |
| `feedback_skip_rnd_doc_for_trivial_fixes` | But per-phase execution logs are required for non-trivial phases |

## Test posture

```bash
# Phase 1+2+3 test count baseline
env -u PYTHONPATH ./src/cosa/.venv/bin/python -m pytest \
  src/tests/unit/test_tts_interaction_mode_helper.py \
  src/tests/unit/test_session_bridge_speakerphone.py \
  src/tests/unit/test_session_bridge_lookup.py \
  src/tests/unit/test_speakerphone_router.py \
  -v
# Expect: 9 + 14 + 59 + 16 = 98 tests passing
```

Full unit regression will have failures until Phase 5 closes (MCP + hooks consumers). Track them in the execution log; don't classify as out-of-scope.

## Commit pattern

Per-phase commits in parent Lupin (the single-PR design-doc rule has already been broken; per-phase commits are now fine because the half-state is already on disk). For each phase, commit message format:

```
[LUPIN] Phase N: <short description>

<bullet point what changed>
<test results>
<deviations from design doc>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

NEVER commit CoSA from parent context. Mention in commit body what CoSA-side edits are pending.

## When you finish all phases

1. Run full unit regression — expect 0 failures
2. Run WebSocket smoke (`./src/scripts/run-websocket-smoke-tests.sh`) — `:7999`
3. Schedule E2E UI tests via `POST /api/test-suite/submit` (`test_types=e2e`, `pytest_args="-k speakerphone"`, user-confirmed `scheduled_at`)
4. Schedule integration suite via same endpoint (final gate per CLAUDE.md PR MERGE REQUIREMENTS)
5. Notify Rick with the full landing summary
6. Prompt for CoSA submodule batch commit guidance (he handles separately)
7. Phase 8 stays deferred unless he explicitly opens that work
