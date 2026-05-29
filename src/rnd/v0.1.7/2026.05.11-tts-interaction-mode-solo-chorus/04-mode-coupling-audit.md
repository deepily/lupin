# Mode-Coupling Audit (Q4 Resolution)

**Date**: 2026.05.12
**Status**: ✅ Audit complete — implementation-blocking concerns resolved
**Owner**: [LUPIN]
**Resolves**: [Q4 in `03-open-questions.md`](03-open-questions.md#q4--other-behaviors-coupled-to-tts-interaction-mode)
**Companion docs**: [`02-background-synthesis.md`](02-background-synthesis.md), [`13-phase4-mcp-tool-rename-design.md`](13-phase4-mcp-tool-rename-design.md)

---

## 1. Purpose

Before Phase 1 implementation begins, enumerate every behavior in the Lupin codebase that today is coupled to conversation-mode semantics. For each, decide whether the May 12 canonical plan already covers it correctly, or whether the plan needs an addendum.

Audit scope:
- Parent Lupin: `src/lupin_mcp/`, `src/lupin_cli/`, `src/fastapi_app/`, `src/conf/`
- CoSA submodule: `src/cosa/rest/`
- Not in scope: `src/lupin-mobile/`, `src/lupin-plugin-firefox/` (separate repos; mobile has its own port plan)

---

## 2. Headline finding

**All implementation-affecting couplings are already covered by Phases 1–7 design docs OR are explicitly out-of-scope per the May 12 plan.**

One **new** finding surfaced that needs a Phase 4 design update (§ 4.1 below) — the MCP `instructions=` block has hard-coded mutual-exclusion language that must become mode-aware. This is a small text-only update; not a new phase, not a blocker.

**Verdict**: Phase 1 implementation can proceed.

---

## 3. Couplings that are mode-independent (no plan change needed)

These behaviors today gate on `get_conversation_mode(session_id)` but the gating semantics work identically in both modes — only the helper rename to `get_speakerphone()` is needed. Phase 5 (hook rider) already covers the renames.

| # | Coupling site | Today's behavior | Solo behavior | Chorus behavior | Phase covering |
|---|---|---|---|---|---|
| C1 | `stop.py:671` — `if get_conversation_mode(session_id):` runs `_try_auto_narrate` + skips "Anything else?" prompt | Skip idle-prompt; run Layer 3 auto-narrate | Same | Same — auto-narrate applies to any speakerphone-on session; idle-prompt would still interrupt voice dialogue in chorus | Phase 5 (rename only) |
| C2 | `idle_waiter.py:251` — `if get_conversation_mode(session_id): exit` | Exit waiter; don't fire prompt | Same | Same — same reason as C1 | Phase 5 (rename only) |
| C3 | `cc_notification_listener.py:443` — `_inject_via_tmux` wraps text via `conv_mode_wrap` when conv mode is on | Wrap inbound | Wrap inbound | Wrap inbound (4-variant rider matrix selects the body) | Phase 5 |
| C4 | `user_prompt_submit.py` — calls `conv_mode_wrap` | Wrap inbound | Wrap | Wrap | Phase 5 |
| C5 | `anything_else_ask.py` — calls `conv_mode_wrap` when fired | Wrap inbound | Wrap | Wrap | Phase 5 |
| C6 | `cosa_voice_mcp.py:723-834` (`_notify_impl`) — bidirectional gate | Force conv-mode params when active; cross-talk cue when CC sender + suppress_ding=True + conv mode off | Same | Cross-talk cue **disabled** (chorus pass-through); on-branch unchanged | Phase 4 (already designed) |
| C7 | `cosa_voice_mcp.py:1283` (`get_session_info`) — returns `conversation_mode_active` | Bool field | Renamed to `speakerphone_on`; same value semantics | Same as solo | Phase 4 |
| C8 | `session_bridge.py:735` (`get_conversation_mode`) — bridge reader | Returns bool | Renamed to `get_speakerphone`; same semantics | Same as solo | Phase 2 |
| C9 | `session_bridge.py:769` (`set_conversation_mode`) — bridge writer | Writes bool | Renamed to `set_speakerphone`; mode-aware default at creation time | Mode-aware default | Phase 2 |
| C10 | `session_bridge.py:655` (`find_active_conversation_sessions`) — scan helper | Returns list of session IDs | Renamed to `find_active_speakerphone_sessions`; **kept** | Helper exists but **chorus path never calls it** | Phases 2 + 3 |
| C11 | `notifications.js` ttsQueue — single global FIFO at the listener's ear | Serializes all TTS items regardless of source session | Same (only one session speakerphone-on, so no contention) | Same — N voices serialize through one queue; persona disambiguates by voice; action-required priority insertion (line 12860) still works | No change needed |
| C12 | `set_session_topic` (`cosa_voice_mcp.py:1224`) — sets bridge `session_topic` field, fires `session_topic` UI push | Per-session topic for "Continue Session?" notifications | Same | Same — topic is per-session and orthogonal to mode | No change needed |
| C13 | Bridge `voice_persona` field — preserved across `/clear` | Allocation persists | Same | Same — per-session persona allocation works identically | No change needed |
| C14 | Bridge `last_autonarrated_turn_id` — dedup token for Stop hook auto-narrate | Mode-independent dedup | Same | Same | No change needed |

---

## 4. New finding requiring a small Phase 4 addendum

### 4.1 MCP `instructions=` block has hard-coded mutual-exclusion language

**Location**: `src/lupin_mcp/cosa_voice_mcp.py:598-603` — the MCP server's `instructions=` parameter (the top-level description that Claude sees at MCP discovery time):

> "**MUTUAL EXCLUSION**: At most one CC session at a time can hold conversation mode across [the user's sessions]... while another session holds it, the other session is automatically displaced — its UI flips, listener gets pushed `action:exit_conversation_mode`, and a `conversation_mode_changed` event fires with `displaced=true, displaced_by=<this session's id>`."

This text is **incorrect under chorus mode** — there is no mutual exclusion, no displacement, no `displaced=true` flag in payloads.

**Tool docstring at line 1436** has similar language ("Mutual exclusion: at most one CC session at a time can hold conversation mode...").

**Required Phase 4 update**:

Option A (simplest) — mode-conditional `instructions=` text:

```python
mode = get_tts_interaction_mode()
if mode == "solo":
    mutex_block = (
        "**MUTUAL EXCLUSION (solo mode active)**: At most one CC session at a time can "
        "hold speakerphone. Activating speakerphone while another session holds it "
        "displaces that session — its UI flips, listener gets pushed "
        "`action:disable_speakerphone`, and a `speakerphone_changed` event fires with "
        "`displaced=true, displaced_by=<this session's id>`."
    )
else:  # chorus
    mutex_block = (
        "**NO MUTUAL EXCLUSION (chorus mode active)**: Multiple CC sessions can be in "
        "speakerphone mode simultaneously. Persona voices disambiguate at the listener's "
        "ear; the TTS queue serializes playback. Activating speakerphone here does NOT "
        "displace any other session."
    )
```

Tool docstring on `enable_speakerphone` gets the same conditional treatment.

Option B — write a single mode-aware paragraph that describes both branches without bifurcation:

```python
mutex_block = (
    "**Behavior depends on global `tts interaction mode`**: "
    "In SOLO mode (default), at most one CC session at a time can hold speakerphone; "
    "activating displaces the prior holder (listener action `disable_speakerphone`, "
    "WS event `speakerphone_changed` with `displaced=true, displaced_by=<this sid>`). "
    "In CHORUS mode, multiple sessions can be in speakerphone mode simultaneously; "
    "persona voices disambiguate at the listener's ear, no displacement occurs."
)
```

**Recommended**: Option B — single paragraph that describes both branches. Cheaper than runtime conditional; reads cleanly; future readers (including Claude) understand both modes from one read.

**Where to apply**:
1. `cosa_voice_mcp.py:598-603` — `instructions=` block.
2. `cosa_voice_mcp.py:1436` — `enable_speakerphone` tool docstring.
3. Any cross-references to `action:exit_conversation_mode` / `conversation_mode_changed` in surrounding text.

**Phase 4 design doc** (`13-phase4-mcp-tool-rename-design.md`) is being updated alongside this audit to include this work in scope.

**Effort**: trivial — ~10–20 lines of text in two places. No new tests beyond the existing rename coverage.

---

## 5. Out-of-scope confirmations

These were enumerated in Q4 as audit candidates; the audit confirms they remain out-of-scope:

### 5.1 Inbound mic-routing semantics

**Question**: In chorus mode with N speakerphone-on sessions, when the user speaks into the microphone, which session(s) hear it?

**Today**: Each CC session has its own listener (`cc-listener-{session_id_hash}`) that filters incoming notifications by `accepted_ids = {session_id_hash}`. The routing decision (which session a voice utterance targets) is made server-side by cosa-voice when it broadcasts the notification. The May 12 plan explicitly parks this:

> **Inbound mic-routing semantics** — parked. Plan does not change who receives voice-recognized input or how the `<voice-message>` envelope's session-target is decided. Separate axis.

**Status under chorus**: unchanged. The plan does not modify routing. If chorus mode introduces routing ambiguity in practice (e.g., user speaks but is unsure which session received the message), a follow-up axis of work can address it. **Not blocking Phase 1.**

### 5.2 Persona pool sizing for N concurrent sessions

**Question**: The persona pool today has 6 entries (`maria, mr radio, Rachel, Tiberius, Rio, Arnold`). In chorus mode, > 6 concurrent CC sessions would exhaust the pool. Does the plan need to handle this?

**Today**: `voice_persona_helpers.py:152` defines `borrowed_persona_for_sid` — a deterministic hash-modulo fallback that picks a persona from the pool by `stable_session_id`. If two sessions share a borrow, they share a voice. Each session's borrowed slot is stable across server restarts.

**Status under chorus**: the borrow fallback handles N > 6 gracefully. UX implication: sessions sharing a voice are slightly less distinguishable, but the cosa-voice queue + UI session-name still disambiguates. **Not blocking.** If Rick later finds 6 voices insufficient for daily chorus use, the INI pool can be expanded — small follow-up not part of this plan.

### 5.3 `:8000` test-server monopolize semantic

**Question**: The grep audit found `monopolize: bool` fields in CJ Flow job routers (mock_job, presentation_generator, swe_team, deep_research, podcast_generator). Are these related to TTS interaction mode?

**Answer**: **No.** This `monopolize` is a different concept — it's the CJ Flow job-scheduling semantic for "run exclusively, block all other jobs until complete" on the test server. Orthogonal to TTS interaction mode. Documenting here so future readers don't conflate the two.

### 5.4 MCP HTTP-fallback bypass (existing Risk #7 from three-layer enforcement)

**Status**: still a known risk — when the FastAPI endpoint is briefly unreachable, the MCP tool falls back to direct bridge write at `cosa_voice_mcp.py:1295`, bypassing the scan-and-displace. Affects **solo only** (chorus has no scan to bypass). Documented in `02-background-synthesis.md §8 Risk #2`. Not patched in this plan; would be a separate follow-up.

---

## 6. Couplings the plan already covers (cross-reference summary)

| Coupling | Covered by |
|---|---|
| Hook rider content (`conv_mode_wrap` + `_system_reminder_body`) | Phase 5 (`14-phase5-hook-rider-design.md`) — 4-variant matrix |
| Server-side displacement (asyncio.Lock + scan) | Phase 3 (`12-phase3-server-router-design.md`) — mode-conditional branch |
| MCP `_notify_impl` cross-talk leak cue | Phase 4 (`13-phase4-mcp-tool-rename-design.md`) — mode-conditional in chorus |
| Multiplexer UI toggle + green pin + displaced handler | Phase 7 (`16-phase7-multiplexer-ui-design.md`) — mode-aware rendering |
| CLAUDE.md TTS-conditional content | Phase 6 (`15-phase6-claude-md-skills-design.md`) — migrate to server rider |
| Skill files (`conversation-mode-{on,off,guardrails}`) | Phase 6 — rename/retire |
| **NEW**: MCP `instructions=` block mutex language | Phase 4 (updated in §4.1 above) |

---

## 7. Sweep audit results (raw)

For traceability, the actual grep commands and their findings:

| Pattern | Files hit (outside R&D + docs) | Action |
|---|---|---|
| `conversation_mode\|conv_mode\|conversationMode` | 12 source files (parent + lupin_mcp + CoSA) | All covered by Phases 1–7 renames |
| `enter_conversation_mode\|exit_conversation_mode` | `cosa_voice_mcp.py`, slash command files | Phase 4 + Phase 6 |
| `Continue Session\|anything_else_ask\|continue_session` | `stop.py`, `anything_else_ask.py`, `idle_waiter.py`, `cosa_voice_mcp.py:1228` | All mode-independent; Phase 5 rename only |
| `voice_persona\|persona_pool` | `voice_persona.py`, `voice_persona_helpers.py`, `session_bridge.py`, `notification_fifo_queue.py`, `broadcast_handler.py` | Mode-independent; pool sizing has borrow fallback |
| `tts_queue\|ttsQueue\|pauseTTS` | `notifications.js` | Mode-independent; single global queue handles chorus N voices |
| `single.*active\|monopol\|displaced` | `cosa_voice_mcp.py` (instructions + tool docstring), `hook_common.py:1125`, `cc_notification_listener.py:356`, `conversation_mode.py:172-195`, CJ Flow `monopolize` fields | Phase 3 + Phase 4 + Phase 5 + Phase 7 cover; **CJ Flow `monopolize` is unrelated** (§5.3) |

---

## 8. Action items added to other docs

| Doc | Change |
|---|---|
| [`03-open-questions.md`](03-open-questions.md) Q4 | Status flipped to ✅ Resolved; pointer to this audit |
| [`13-phase4-mcp-tool-rename-design.md`](13-phase4-mcp-tool-rename-design.md) §2 (Scope) | Add MCP `instructions=` block + tool docstring updates to scope |
| [`13-phase4-mcp-tool-rename-design.md`](13-phase4-mcp-tool-rename-design.md) §3 (Deliverables) | Add new §3.6 with the mode-aware text (Option B from §4.1) |
| [`00-index.md`](00-index.md) | Add this audit to the doc inventory |
| [`90-decisions-log.md`](90-decisions-log.md) | New entry: "2026-05-12 — Q4 mode-coupling audit complete" |

---

## 9. Implementation readiness verdict

**✅ Phase 1 implementation can proceed.**

The audit found no blocking couplings beyond what Phases 1–7 already cover. The one new finding (MCP `instructions=` + tool docstring) is folded into Phase 4 as a small text update.

The deferred items (Q3 small-group semantics, Q5 solo retirement, Q6 predecessor-doc treatment, Q7 stale plan file, Q8 in-flight skill references) remain deferred and don't block any implementation phase.
