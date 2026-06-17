#!/usr/bin/env python3
"""
PostToolUse hook: smart TTS announcements + voice buffer drain.

Fires after every tool call. Applies smart filtering:
- Silent (no TTS): Read, Grep, Glob, TaskCreate, TaskUpdate, TaskGet, TaskList
- Announce (with detail): Bash, Write, Edit
- Default (name only): MCP/unknown tools

After TTS, drains the voice buffer and acknowledges any buffered messages.

Install in ~/.claude/settings.json:
    "hooks": {
        "PostToolUse": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/post_tool_use.py\""
        }]
    }
"""
import os
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:                 # pragma: no cover - bootstrap-exception (PATH MANAGEMENT mandate): sets sys.path BEFORE the lupin_cli package is importable, so it is genuinely unreachable under pytest (src already on sys.path) — not a coverable branch
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts, build_progress_group_id,
    format_tool_summary, drain_and_acknowledge, format_voice_context,
    build_additional_context, enrich_voice_context,
    TOOLS_SILENT, TOOLS_ANNOUNCE
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, resolve_stable_session_id,
    kill_idle_waiter, set_idle_detection_field, touch_bridge_mtime,
)

# Fleet PROGRESS beacon trigger set (arbiter signs-of-life Fix 2, 2026-06-16): a
# task-store WRITE in ANY of these forms is unambiguous coordination work-
# advancement. BOTH creation doors count — the harness TaskCreate/TaskUpdate
# (self-owned stubs, auto-mirrored) AND the MCP task_create/task_transition
# (typed / cross-persona items, status moves). A write of any of these emits one
# kind="task_transition" fleet event so the arbiter reads an actively-
# coordinating session as PROGRESSING (see heartbeat_events.emit_task_transition).
TASK_STORE_WRITE_TOOLS = (
    "TaskCreate", "TaskUpdate",
    "mcp__cosa-voice__task_create", "mcp__cosa-voice__task_transition",
)


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # v2.1 direct-state liveness (arbiter design 03 §10.1; redlines C1/C3/C4):
    # bump THIS session's bridge mtime on EVERY tool call so a heads-down worker
    # — one that's actively churning and never hits a Stop — still reports live.
    # This is the SINGLE PostToolUse stamp (C3): a BARE metadata-only os.utime on
    # the ONE host-side clock (C4 — shared touch_bridge_mtime, no parallel store),
    # with NO content write (bridge-JSON corruption gate — C1), NO transcript
    # read, NO server POST, NO heavy logic. The hook fires dozens of times per
    # turn × every session, so the stamp must stay this cheap. touch_bridge_mtime
    # is no-throw by contract (unit-proven), so no guard is added — a redundant
    # try/except here would only be a dead, uncoverable branch.
    touch_bridge_mtime()

    # Extract tool information
    tool_name  = payload.get( "tool_name", "unknown" )
    tool_input = payload.get( "tool_input", {} )

    # Log full payload for empirical analysis
    log_payload( "post_tool_use", payload )

    # No MCP voice bypass — drain fires after every tool call (including voice tools)
    # to catch any messages that arrived during tool execution

    # Resolve session_id: payload first (future-proof), then session bridge fallback
    session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()
    pg_id      = build_progress_group_id( "pu", session_id )

    # Idle-aware Stop hook: when Claude calls a cosa-voice notify/ask tool
    # mid-turn, kill any pending idle waiter and bump last_interaction_at.
    # Claude is actively talking — a phantom waiter waking up now would
    # interrupt. Don't respawn here; the next Stop hook will respawn at
    # turn-end. See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
    if tool_name.startswith( "mcp__cosa-voice__" ):
        import datetime as _dt
        kill_idle_waiter( session_id )
        set_idle_detection_field(
            session_id,
            last_interaction_at = _dt.datetime.now().astimezone().isoformat( timespec="seconds" ),
        )

    # Task-store mirror — DEPRECATED (Step-5 stage-1, 2026-06-17): now a LOGGED
    # NO-OP. The store-canonical cutover is live, so the harness→store auto-
    # mirror is obsolete; instead of writing, mirror_task_tool_event emits one
    # fire-log line per native TaskCreate/TaskUpdate (greppable phase=
    # task_store_mirror_deprecated_noop) so we can see, fleet-wide, which
    # sessions still use native Task* for owed work. Stage-2 (DELETE this call +
    # drop the dead TASK_STORE_WRITE_TOOLS entries below) is evidence-gated on
    # that fire-log going quiet. The mirror's MIRROR_WRITES_DEPRECATED guard
    # keeps the old write path reversible. never-raises by contract; lazy import
    # keeps the every-tool-call hot path untouched for the ~all non-Task* events.
    if tool_name in ( "TaskCreate", "TaskUpdate" ):
        from lupin_cli.claude_code.hooks.lib.task_store_mirror import mirror_task_tool_event
        mirror_task_tool_event( payload, session_id )

    # Fleet PROGRESS beacon (arbiter signs-of-life Fix 2, 2026-06-16): emit one
    # kind="task_transition" fleet event on every task-store WRITE — harness OR
    # MCP (TASK_STORE_WRITE_TOOLS). The arbiter folds a per-session
    # last_task_transition_ts into _fleet_progress_signature so a session
    # actively creating/moving task items registers as PROGRESS, fixing the
    # false whole-fleet-stall on an actively-coordinating fleet. A task write
    # can never be idle chatter, so it is a SAFE progress source (does NOT
    # re-open the chatty-but-stuck blind spot). Lazy import keeps the
    # every-tool-call hot path untouched for the ~all non-task tool events.
    # emit_task_transition is no-throw by contract, so no guard is added — a
    # redundant try/except here would only be a dead, uncoverable branch.
    if tool_name in TASK_STORE_WRITE_TOOLS:
        from lupin_cli.claude_code.hooks.lib.heartbeat_events import emit_task_transition
        emit_task_transition( session_id )

    # Smart TTS filtering (respects HOOK_TTS_ENABLED)
    if tool_name in TOOLS_SILENT:
        pass  # No TTS for high-frequency read-only tools
    elif tool_name in TOOLS_ANNOUNCE:
        send_tts( f"Done: {format_tool_summary( tool_name, tool_input )}", progress_group_id=pg_id )
    else:
        send_tts( f"Done: {tool_name}", progress_group_id=pg_id )

    # Drain voice buffer, acknowledge, and inject as additionalContext
    messages  = drain_and_acknowledge( session_id )
    voice_ctx = format_voice_context( messages )
    emit_json( build_additional_context( enrich_voice_context( voice_ctx, messages ), "PostToolUse" ) )
    # enrich returns "" when empty → build_additional_context returns {} → passthrough


if __name__ == "__main__":
    main()
