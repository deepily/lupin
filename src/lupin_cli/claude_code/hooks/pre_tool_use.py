#!/usr/bin/env python3
"""
PreToolUse hook: voice buffer drain before tool execution.

Fires before every tool call. Does NOT announce tools via TTS (PostToolUse
handles that). Only drains the voice buffer and acknowledges buffered messages.

Install in ~/.claude/settings.json:
    "hooks": {
        "PreToolUse": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/pre_tool_use.py\""
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
    read_hook_input, log_payload, emit_json, drain_and_acknowledge,
    format_voice_context, build_voice_deny_response
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, resolve_stable_session_id, touch_bridge_mtime,
)


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # v2.1 direct-state liveness (arbiter signs-of-life Fix 1, 2026-06-16): bump
    # THIS session's bridge mtime at the START of a tool call too — mirroring the
    # PostToolUse stamp (post_tool_use.py). PostToolUse alone only refreshed
    # liveness on tool COMPLETION, so a long-running in-flight tool (a slow Bash,
    # a big Edit) left the bridge mtime aging until it returned — a heads-down
    # worker could read as stale mid-tool. Stamping on PreToolUse closes that gap
    # (pre AND post both emit life). Same cheap contract as the PostToolUse stamp:
    # a BARE metadata-only os.utime on the ONE host-side clock (shared
    # touch_bridge_mtime), NO content write, NO server POST. touch_bridge_mtime
    # is no-throw by contract (unit-proven), so no guard is added — a redundant
    # try/except here would only be a dead, uncoverable branch.
    touch_bridge_mtime()

    # Log full payload for empirical analysis
    log_payload( "pre_tool_use", payload )

    # No MCP voice bypass — if user sent a voice message before Claude
    # calls a voice tool, the buffered message takes precedence

    # Resolve session_id: payload first (future-proof), then session bridge fallback
    session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()

    # Subagent governance (manager-autonomy §2.2): a CREW-MANAGER session (one
    # with a non-empty spawn manifest) may not use the Agent/Task subagent tool —
    # it must staff via spawn_sessions (in-process subagents are invisible/
    # ungovernable). DEFAULT-OFF (LUPIN_SUBAGENT_GOVERNANCE) + FAIL-OPEN (the lib
    # returns None on any error), so this is inert + safe on the hot path.
    from lupin_cli.claude_code.hooks.lib.subagent_governance import (
        subagent_deny_reason, build_subagent_deny_response,
    )
    gov_reason = subagent_deny_reason( payload.get( "tool_name", "" ), session_id )
    if gov_reason:
        emit_json( build_subagent_deny_response( gov_reason ) )
        sys.exit( 0 )

    # Stash guard (bug 1ebc9be3): `git stash` writes to a SINGLE repo-global
    # stack shared by every worktree and every live session, so a pop can apply
    # another session's held work into your tree and — when the changesets do
    # not overlap — do it silently, leaving you to commit their files under your
    # name. Read-only `git stash list` / `show` stay allowed. DEFAULT-ON with a
    # LUPIN_ALLOW_GIT_STASH escape hatch, and FAIL-OPEN by contract (the lib
    # returns None on any error), so it cannot break a tool call.
    from lupin_cli.claude_code.hooks.lib.stash_guard import (
        stash_deny_reason, build_stash_deny_response,
    )
    stash_reason = stash_deny_reason( payload.get( "tool_name", "" ), payload.get( "tool_input", {} ) )
    if stash_reason:
        emit_json( build_stash_deny_response( stash_reason ) )
        sys.exit( 0 )

    # Kill guard (row cd332d2b): a seat's argv carries its whole spawn brief, so a
    # fleet-wide `ps`/`pgrep` sweep grepping for a test path matches LIVE SESSIONS,
    # not just tests. On 2026-08-21 one such sweep killed three seats in 612 ms —
    # ten seconds after the CLI's own `pkill` shim had refused the same pattern by
    # name, which the hand-rolled `ps | grep | kill` form walks straight past.
    # Own-children sweeps (`pkill -P $$`) and kill-free listings stay allowed.
    # DEFAULT-ON with a LUPIN_ALLOW_UNSCOPED_KILL escape hatch, and FAIL-OPEN by
    # contract (the lib returns None on any error), so it cannot break a tool call.
    from lupin_cli.claude_code.hooks.lib.kill_guard import (
        kill_deny_reason, build_kill_deny_response,
    )
    kill_reason = kill_deny_reason( payload.get( "tool_name", "" ), payload.get( "tool_input", {} ) )
    if kill_reason:
        emit_json( build_kill_deny_response( kill_reason ) )
        sys.exit( 0 )

    # Commit scope guard (2026-08-25): `git commit` writes the WHOLE INDEX, not
    # the files you staged. `git add <paths>` does not clear what is already
    # there, so on a shared tree a peer's staged work commits under your name —
    # measured that day, five files staged by name and four peer files committed.
    # The check that failed was a PATH-SCOPED `git status`, which structurally
    # cannot show the contamination it exists to catch. This denies ONCE and puts
    # the complete staged set in front of the committer; re-run with
    # LUPIN_COMMIT_SCOPE_ACK=1 to proceed. It never judges whose files they are —
    # there is no reliable ownership oracle, and a guard that cries wolf gets
    # switched off. FAIL-OPEN by contract (the lib returns None on any error,
    # including an unreadable index), so it cannot break a tool call.
    from lupin_cli.claude_code.hooks.lib.commit_scope_guard import (
        commit_scope_deny_reason, build_commit_scope_deny_response,
    )
    commit_reason = commit_scope_deny_reason( payload.get( "tool_name", "" ), payload.get( "tool_input", {} ) )
    if commit_reason:
        emit_json( build_commit_scope_deny_response( commit_reason ) )
        sys.exit( 0 )

    # Drain voice buffer, acknowledge, and inject as additionalContext
    # No tool TTS — PostToolUse handles announcements
    messages  = drain_and_acknowledge( session_id )
    voice_ctx = format_voice_context( messages )

    if voice_ctx:
        emit_json( build_voice_deny_response( voice_ctx, messages ) )
    else:
        emit_json( {} )


if __name__ == "__main__":
    main()
