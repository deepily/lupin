# Phase 4 — MCP Tool Rename + `_notify_impl` Mode-Conditional

**Date**: 2026.05.12
**Status**: 📝 Design — not yet implemented
**Owner**: [LUPIN]
**Phase**: 4 of 8
**Prerequisites**: Phases 1, 2, 3 (config helper, bridge renames, server router).
**Companion docs**: [`00-index.md`](00-index.md), [`01` (May 12 canonical plan)](2026.05.12-tts-interaction-mode-solo-chorus.md), [`02-background-synthesis.md`](02-background-synthesis.md)
**Execution log**: [`94-phase4-execution-log.md`](94-phase4-execution-log.md) (TBD)

---

## 1. Goal

Rename the MCP tools, update the `get_session_info()` response shape, and make `_notify_impl`'s cross-talk leak cue mode-conditional. After this phase, the MCP layer speaks the new vocabulary (`enable_speakerphone`, `speakerphone_on`, `tts_interaction_mode`) and correctly suppresses the cross-talk audible cue in chorus mode (where a quiet notify is a legitimate pattern, not a leak symptom).

---

## 2. Scope

### In scope

**`src/lupin_mcp/cosa_voice_mcp.py`** — four categories of change:

1. **Tool renames** (signatures unchanged):
   - `enter_conversation_mode` → `enable_speakerphone`
   - `exit_conversation_mode` → `disable_speakerphone`
2. **Internal helper rename**: `_flip_conversation_mode` → `_flip_speakerphone`. HTTP-first, direct-bridge fallback preserved. Endpoint URL updated to `/api/cosa-voice/speakerphone/{sid}`.
3. **`get_session_info()` shape**:
   - Rename `conversation_mode_active` → `speakerphone_on`.
   - Add new field `tts_interaction_mode: "solo" | "chorus"` (read via `get_tts_interaction_mode()` from Phase 1).
4. **`_notify_impl` mode-conditional cross-talk leak cue**:
   - `speakerphone_on=true` branch: unchanged (force `suppress_ding=True`, force `priority="high"`, strip fenced code blocks).
   - `speakerphone_on=false` branch becomes mode-conditional:
     - Solo: keep cross-talk leak cue (today's `_notify_impl` lines 805–811 behavior — inverts `suppress_ding` when `sender.startswith("claude.code@")` and `suppress_ding=True`).
     - Chorus: passthrough — no inversion.
5. **MCP `instructions=` block + tool docstring mode-aware rewrite** (added 2026-05-12 per [`04-mode-coupling-audit.md`](04-mode-coupling-audit.md) §4.1):
   - `cosa_voice_mcp.py:598-603` — the FastMCP server's `instructions=` parameter currently contains hard-coded mutual-exclusion language ("**MUTUAL EXCLUSION**: At most one CC session at a time..."). This is wrong under chorus mode. Rewrite as a single mode-aware paragraph that describes both branches (Option B from the audit).
   - `cosa_voice_mcp.py:1436` — the `enable_speakerphone` tool docstring has similar language; same rewrite.
   - Cross-references to `action:exit_conversation_mode` / `conversation_mode_changed` in surrounding text get updated to new names.

### Out of scope

- USER-ONLY initiation enforcement at the MCP boundary (today's discipline-based docstring + skill enforcement is preserved; no programmatic enforcement is added in this phase).
- Direct-bridge fallback's monopoly bypass (existing Risk #7 from three-layer enforcement doc — deferred per the predecessor's out-of-scope list).
- HTTP-fallback Lock-acquire (still process-local in solo mode; not solved here).

---

## 3. Deliverables

### 3.1 Tool renames

**Before** (today):
```python
@mcp.tool
async def enter_conversation_mode( ctx: Context ) -> dict:
    """..."""
    return await _flip_conversation_mode( ctx, target_active=True )

@mcp.tool
async def exit_conversation_mode( ctx: Context ) -> dict:
    """..."""
    return await _flip_conversation_mode( ctx, target_active=False )
```

**After**:
```python
@mcp.tool
async def enable_speakerphone( ctx: Context ) -> dict:
    """
    Enable speakerphone mode for this session.

    USER-ONLY INITIATION HARD RULE: NEVER call this tool on your own initiative.
    Only in direct response to a user instruction (voice phrase, typed request,
    slash command).

    Behavior depends on global `tts interaction mode` setting:
    - solo: activating this session displaces any other speakerphone-on session.
    - chorus: this session joins others as a simultaneous speakerphone holder.

    Requires: ...
    Ensures: ...
    """
    return await _flip_speakerphone( ctx, target_on=True )

@mcp.tool
async def disable_speakerphone( ctx: Context ) -> dict:
    """
    Disable speakerphone mode for this session.

    USER-ONLY INITIATION HARD RULE: NEVER call this tool on your own initiative.
    Only in direct response to a user instruction (voice phrase, typed request,
    slash command).

    Behavior is mode-independent: flips this session's speakerphone_on to false,
    broadcasts WS event, pushes listener action.
    """
    return await _flip_speakerphone( ctx, target_on=False )
```

The USER-ONLY initiation rule is documented in three concentric layers per the predecessor design (April 28 §11.3):
- MCP `instructions=` block (the top-level MCP server description) — keep the rule.
- Tool docstrings (above) — keep the rule.
- Skill at `~/.claude/skills/conversation-mode-guardrails/SKILL.md` — Phase 6 retires this skill; the rule survives in the docstrings + per-turn server rider.

### 3.2 `_flip_speakerphone` helper

```python
async def _flip_speakerphone( ctx: Context, target_on: bool ) -> dict:
    """HTTP-first, direct-bridge fallback. Renamed from _flip_conversation_mode."""

    cc_meta = _get_cc_metadata()
    sid = cc_meta.get( "stable_session_id" ) or cc_meta.get( "session_id" ) or SESSION_ID
    server_url = ctx.request_context.lifespan_context.server_url

    # HTTP path (canonical)
    try:
        response = await _http_post(
            f"{server_url}/api/cosa-voice/speakerphone/{sid}",
            json={ "on": target_on },
            headers=_auth_headers(),
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        # Fall through to direct-bridge path
        pass

    # Direct-bridge fallback — known to bypass solo mode mutex (Risk #7).
    # Documented but accepted; emergency degraded path.
    set_speakerphone( sid, target_on )
    return { "on": target_on, "displaced_sessions": [], "fallback_used": True }
```

**Endpoint URL change**: `/api/cosa-voice/conversation-mode/{sid}` → `/api/cosa-voice/speakerphone/{sid}` (Phase 3 ships this server-side).

**JSON body field change**: `active` → `on` (matches new bridge field).

### 3.3 `get_session_info()` response

**Before**:
```python
return {
    "session_id": sid,
    "sender_id": sender_id,
    "version": __version__,
    "conversation_mode_active": get_conversation_mode( sid ),
    # ... other fields
}
```

**After**:
```python
return {
    "session_id": sid,
    "sender_id": sender_id,
    "version": __version__,
    "speakerphone_on": get_speakerphone( sid ),
    "tts_interaction_mode": get_tts_interaction_mode(),
    # ... other fields
}
```

**Why expose `tts_interaction_mode`**: the multiplexer UI needs it to render mode-appropriate toggle (bell↔phone in solo, phone↔speaker in chorus). Phase 7 reads this from `get_session_info()` payload.

### 3.4 `_notify_impl` mode-conditional gate

**Current logic** (cosa_voice_mcp.py:723-834 approximate):

```python
async def _notify_impl( ..., _internal_call=False ) -> dict:
    sid = _resolve_sid()
    active = get_conversation_mode( sid )
    sender = _wait_for_sender_id()

    if _internal_call:
        pass  # pass-through unchanged

    elif active:
        suppress_ding = True
        if priority not in ( "high", "urgent" ):
            priority = "high"
        message = strip_fenced_code_blocks( message )

    elif ( not active ) and sender.startswith( "claude.code@" ) and ( suppress_ding == True ):
        # Cross-talk leak cue: invert suppress_ding so user hears a ding
        suppress_ding = False
        # log INFO: "conv-mode cross-talk cue: suppress_ding inverted for {sender}"

    # else: pass-through unchanged

    # ... build AsyncNotificationRequest, fire, etc.
```

**After Phase 4** (mode-conditional):

```python
async def _notify_impl( ..., _internal_call=False ) -> dict:
    sid = _resolve_sid()
    on = get_speakerphone( sid )
    sender = _wait_for_sender_id()
    mode = get_tts_interaction_mode()

    if _internal_call:
        pass  # pass-through unchanged

    elif on:
        # Speakerphone active — enforce TTS-ready params (mode-independent)
        suppress_ding = True
        if priority not in ( "high", "urgent" ):
            priority = "high"
        message = strip_fenced_code_blocks( message )

    elif ( mode == "solo" ) and sender.startswith( "claude.code@" ) and ( suppress_ding == True ):
        # Solo cross-talk leak cue: invert suppress_ding so user hears a ding
        # Indicates a displaced session is leaking a quiet notify.
        suppress_ding = False
        # log INFO: "solo-mode cross-talk cue: suppress_ding inverted for {sender}"

    # else: pass-through unchanged. Specifically:
    #   - chorus + speakerphone_off + CC sender + suppress_ding=True: PASS-THROUGH.
    #     In chorus, quiet notify is a legitimate pattern (UI card without TTS).
    #   - any non-CC sender: PASS-THROUGH (cross-talk cue only applies to CC senders).
    #   - any non-suppress_ding caller: PASS-THROUGH (no cue needed; default ding fires).

    # ... build AsyncNotificationRequest, fire, etc.
```

**Code-block stripping helper** (`strip_fenced_code_blocks`) is unchanged from three-layer enforcement Phase 3. Already extracted as standalone unit-testable function.

### 3.5 Unit tests

**File**: `src/tests/unit/test_notify_impl_mode_conditional.py` (new; supplements existing three-layer override tests)

Use `pytest.mark.parametrize` over `mode = ["solo", "chorus"]` where applicable.

| Test | Mode | Setup | Assertion |
|---|---|---|---|
| `test_speakerphone_on_forces_params_solo` | solo | bridge `speakerphone_on=true` | `suppress_ding=True`, `priority="high"`, code blocks stripped |
| `test_speakerphone_on_forces_params_chorus` | chorus | bridge `speakerphone_on=true` | Same as solo |
| `test_cross_talk_cue_fires_solo` | solo | bridge `speakerphone_on=false`; CC sender; `suppress_ding=True` from caller | `suppress_ding` inverted to `False` |
| `test_cross_talk_cue_skipped_chorus` | chorus | bridge `speakerphone_on=false`; CC sender; `suppress_ding=True` from caller | `suppress_ding` stays `True` (pass-through) |
| `test_non_cc_sender_pass_through_solo` | solo | bridge `speakerphone_on=false`; non-CC sender; `suppress_ding=True` | `suppress_ding` stays `True` (cue only applies to CC senders) |
| `test_non_cc_sender_pass_through_chorus` | chorus | Same | Same |
| `test_internal_call_bypasses_gate_both_modes` | both | `_internal_call=True`, bridge active | All params unchanged |
| `test_get_session_info_includes_speakerphone_on` | both | Any | Response has `speakerphone_on: bool` |
| `test_get_session_info_includes_tts_interaction_mode` | both | Mock `get_tts_interaction_mode` to return current mode | Response has `tts_interaction_mode: <mode>` |
| `test_get_session_info_no_old_field_name` | both | Any | Response does NOT have `conversation_mode_active` (sweep check) |
| `test_enable_speakerphone_calls_http` | both | Mock HTTP success | `_flip_speakerphone(on=True)` invoked; new endpoint URL used |
| `test_disable_speakerphone_calls_http` | both | Mock HTTP success | `_flip_speakerphone(on=False)` invoked |
| `test_flip_fallback_on_http_failure` | both | Mock HTTP raise | Falls through to direct `set_speakerphone`; response includes `fallback_used=True` |

### 3.6 MCP `instructions=` block mode-aware rewrite

**Location**: `src/lupin_mcp/cosa_voice_mcp.py:598-603` (FastMCP server `instructions=` parameter).

**Today** (excerpt):
```
**MUTUAL EXCLUSION**: At most one CC session at a time can hold conversation mode
across the user's sessions... while another session holds it, the other session
is automatically displaced — its UI flips, listener gets pushed
`action:exit_conversation_mode`, and a `conversation_mode_changed` event fires
with `displaced=true, displaced_by=<this session's id>`.
```

**Replacement** (single paragraph, mode-aware):
```
**Behavior depends on global `tts interaction mode`**:
In SOLO mode (default), at most one CC session at a time can hold speakerphone;
activating displaces the prior holder (listener action `disable_speakerphone`,
WS event `speakerphone_changed` with `displaced=true, displaced_by=<this sid>`).
In CHORUS mode, multiple sessions can be in speakerphone mode simultaneously;
persona voices disambiguate at the listener's ear, no displacement occurs.
```

Apply the same rewrite to:
- **`enable_speakerphone` tool docstring** (`cosa_voice_mcp.py:1436` area) — preserve the USER-ONLY initiation hard rule wording; only rewrite the mutual-exclusion paragraph.
- **`disable_speakerphone` tool docstring** if it has any mutex language (typically it doesn't — deactivate is mode-independent).

**Why static text instead of runtime-conditional**: the `instructions=` block is set once at module load; FastMCP doesn't refresh it per-session. Static description covering both modes is simpler and equally informative. The actual behavior the user sees depends on the runtime mode; the description tells Claude (and Rick) what to expect under each.

**Test**: unit test asserts the new `instructions=` text contains both "SOLO" and "CHORUS" substring markers. Same for the tool docstring (via `inspect.getdoc`).

### 3.7 Smoke tests

**Extend** `src/tests/smoke/test_cosa_voice_mcp_smoke.py` (or add new):

1. Call `enable_speakerphone()` (mocked HTTP).
2. Verify bridge `speakerphone_on=true`.
3. Call `get_session_info()`; verify shape includes both `speakerphone_on` and `tts_interaction_mode`.
4. Call `disable_speakerphone()`.
5. Verify bridge `speakerphone_on=false`.

---

## 4. Implementation order

1. Read `src/lupin_mcp/cosa_voice_mcp.py` end-to-end — especially `_notify_impl`, `_flip_conversation_mode`, `get_session_info`, tool decorators.
2. Apply all renames (file-internal): `enter_conversation_mode` → `enable_speakerphone`, etc.
3. Update `_flip_speakerphone` to hit new endpoint `/api/cosa-voice/speakerphone/{sid}` with `{"on": ...}` body.
4. Add `tts_interaction_mode` to `get_session_info()` response.
5. Add mode branching in `_notify_impl` cross-talk cue.
6. `py_compile` all touched files.
7. Import chain: `from lupin_mcp.cosa_voice_mcp import enable_speakerphone, disable_speakerphone`.
8. Run new unit tests.
9. Run existing three-layer enforcement unit tests for regressions.
10. Run smoke tests.

**Expected breakage at Phase 4 end**: hooks still call `conv_mode_wrap`, etc.; CLAUDE.md still references old names; multiplexer still listens for old event. Phases 5–7 fix these. Single PR for Phases 2–7.

---

## 5. Verification matrix

| Layer | Check | Venue | Pass criteria |
|---|---|---|---|
| `py_compile` | `cosa_voice_mcp.py` | local | Compiles |
| Import chain | MCP module import | local | No error |
| Unit | `test_notify_impl_mode_conditional.py` (~13 tests) | :7999 | 100% pass |
| Unit regression | Existing three-layer enforcement tests | :7999 | All pass with renamed identifiers |
| Smoke | MCP tool flow (mocked HTTP) | :7999 | 5/5 pass |
| Manual | `mcp__cosa-voice__get_session_info()` in a live session | :7999 | Returns new shape; no `conversation_mode_active` field |
| Manual | Toggle `tts interaction mode = chorus` in INI; restart `:7999`; call `notify(suppress_ding=True)` from a CC session with bridge off | :7999 | Ding NOT inverted (chorus pass-through); revert INI after |
| Manual | Toggle back to `solo`; same call | :7999 | Ding inverted (cross-talk cue fires) |

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | The three-layer enforcement code in `_notify_impl` is dense and may have edge cases beyond cross-talk cue | Read predecessor doc §3 Layer 2 carefully; preserve `_internal_call` bypass, priority-floor logic, code-block stripping. Only the cross-talk cue branch changes. |
| 2 | `get_session_info()` shape change breaks consumer code (UI, hooks, tests) | This is by design — the rename ships in one PR. All consumers update in their respective phases. |
| 3 | Tool docstrings affect MCP server's tool-discovery output — Claude sees the new names | Intended: Claude pattern-matches user voice phrases against the new tool names. Voice phrases ("enable speakerphone" / "disable speakerphone") map directly. |
| 4 | The MCP server's `instructions=` block likely references the old conversation-mode rule | Update this in the same phase — search for `conversation_mode`, `enter_conversation_mode`, etc. in the `instructions=` string. |
| 5 | Slash command files (`~/.claude/commands/conversation-mode-on.md`, `conversation-mode-off.md`) call MCP tools by old name | Phase 6 handles slash command renames. Until then, slash commands break — accepted under the single-PR strategy. |
| 6 | HTTP fallback may fail silently if endpoint shape changes (e.g., `active` → `on` in body) | Tests cover both `active` and `on` body shape — fail-loud if regressed. |

---

## 7. Cross-cutting concerns

### Memory check

- [[feedback_no_migration_code]] — no alias for old tool names; hard cut. ✓
- [[feedback_no_defensive_programming]] — no `or False` defaults in bridge reads. ✓
- [[feedback_sweep_for_pattern_offenders]] — implementation order step 1 includes the audit. Grep parent + `src/lupin_mcp/` for `conversation_mode` to enumerate all read sites. ✓
- [[feedback_enumerate_all_activation_paths]] — both `enable_speakerphone` MCP tool AND the HTTP fallback path are mode-aware. ✓
- [[feedback_acknowledge_receipt_before_tool_work]] — speakerphone-on rider in Phase 5 will preserve this; Phase 4 doesn't change rider content. ✓

### Naming

- Tool names match MCP `instructions=` rule and skill names. Slash commands (`/speakerphone-on` / `/speakerphone-off`) ship in Phase 6.
- `_flip_speakerphone` underscore-prefix marks it as internal helper. ✓
- `target_on` parameter name matches `set_speakerphone(sid, on)` convention. ✓

### Documentation touchpoints (per CLAUDE.md table)

- `src/docs/notification-api.md` — update if it references `conversation_mode_active` field name.
- `src/docs/cosa-voice-mcp.md` (if it exists) — tool names.
- MCP `instructions=` block — references and rules.

---

## 8. Implementation timing

Estimated active work: 120–180 minutes including comprehensive tests + careful preservation of the three-layer enforcement contract.

---

## 9. Hand-off to Phase 5

Phase 5 (hook rider content split) will:
- Rename `conv_mode_wrap` / `conv_mode_reminder_block` / `conv_mode_exit_reminder` to `speakerphone_*` equivalents.
- Add mode-aware 4-variant rider matrix.
- Read `get_speakerphone(sid)` AND `get_tts_interaction_mode()` to select rider variant.

Phase 4 must leave `get_speakerphone` and `get_tts_interaction_mode` callable. Phase 5 owns the rider-content logic.
