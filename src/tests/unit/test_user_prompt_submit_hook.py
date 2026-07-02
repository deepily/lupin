#!/usr/bin/env python3
"""
Unit tests for the UserPromptSubmit hook.

Tests voice buffer drain -> format -> inject as additionalContext flow.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_buffer_entry( message, job_id="abc12345" ):
    """Build a JSONL buffer entry dict."""
    return {
        "message"   : message,
        "priority"  : "normal",
        "job_id"    : job_id,
        "sender_id" : "test@example.com",
        "timestamp" : "2026-03-06T10:00:00+00:00",
        "buffered_at" : "2026-03-06T10:00:00+00:00",
    }


def _write_buffer( tmp_dir, session_id, entries ):
    """Write JSONL buffer file and return path."""
    sessions_dir = Path( tmp_dir ) / ".claude" / "sessions"
    sessions_dir.mkdir( parents=True, exist_ok=True )
    hash_part   = session_id[:8]
    buffer_path = sessions_dir / f"cc-buffer-{hash_part}.jsonl"
    with open( buffer_path, "w" ) as f:
        for entry in entries:
            f.write( json.dumps( entry ) + "\n" )
    return buffer_path


def _run_hook_main( payload, tmp_dir, session_id="abc12345-fake-uuid",
                    dm_reconcile_ctx="", dm_capture=None ):
    """
    Run the UserPromptSubmit hook main() with mocked stdin/stdout.

    The store-backed DM inbox reconcile (surface_dm_inbox) is stubbed so the hook
    test stays hermetic (no :7999 network, no HWM file written to the repo root):
    it returns `dm_reconcile_ctx` and, when `dm_capture` is a dict, records the
    call kwargs there.

    Returns the emitted JSON dict.
    """
    import io
    from lupin_cli.claude_code.hooks import user_prompt_submit
    from cosa.config.configuration_manager import ConfigurationManager

    def _fake_surface( session_id, extra_surfaced_ids=() ):
        if dm_capture is not None:
            dm_capture[ "session_id" ]         = session_id
            dm_capture[ "extra_surfaced_ids" ] = list( extra_surfaced_ids )
        return dm_reconcile_ctx

    # Seed the ConfigurationManager singleton BEFORE capturing stdout — at a
    # virgin (hermetic) module boundary the hook's CM instantiation would
    # otherwise print its init banner into the captured stream and corrupt
    # the JSON parse below.
    ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    captured = io.StringIO()

    with patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR",
                Path( tmp_dir ) / ".claude" / "sessions" ), \
         patch( "sys.stdin", io.StringIO( json.dumps( payload ) ) ), \
         patch( "sys.stdout", captured ), \
         patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
         patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id",
                return_value=session_id ), \
         patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id",
                side_effect=lambda x: x ), \
         patch( "lupin_cli.claude_code.hooks.user_prompt_submit.surface_dm_inbox",
                side_effect=_fake_surface ):
        try:
            user_prompt_submit.main()
        except SystemExit:
            pass

    output = captured.getvalue().strip()
    if output:
        return json.loads( output )
    return {}


# ── Tests ────────────────────────────────────────────────────────────────────

class TestUserPromptSubmitHook:
    """Tests for user_prompt_submit.py hook."""

    def test_empty_payload_returns_empty( self ):
        """Empty payload -> {}."""
        import io
        from lupin_cli.claude_code.hooks import user_prompt_submit

        captured = io.StringIO()
        with patch( "sys.stdin", io.StringIO( "{}" ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.get_claude_session_id",
                    return_value="abc12345" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.resolve_stable_session_id",
                    side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.SESSION_DIR",
                    Path( "/nonexistent" ) ):
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

        result = json.loads( captured.getvalue().strip() )
        assert result == {}

    def test_no_buffer_returns_rider_only( self ):
        """No JSONL buffer file -> rider only (always-fire post-Phase-5b)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )
            # Phase 5b: the rider fires on every turn (when session_id
            # resolves), so the hook always emits hookSpecificOutput. With
            # no buffered voice content, the additionalContext is the
            # rider block alone (no [Voice]: prefix lines).
            assert "hookSpecificOutput" in result
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "<system-reminder>" in ctx
            assert "[Voice]" not in ctx

    def test_buffer_with_messages_injects_context( self ):
        """JSONL buffer with messages -> additionalContext."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "list all Python files" ) ]
            _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )

            assert "hookSpecificOutput" in result
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: list all Python files" in ctx

    def test_buffer_consumed_after_drain( self ):
        """Buffer file is deleted after drain."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "hello" ) ]
            buf     = _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            _run_hook_main( payload, tmp_dir )

            assert not buf.exists()

    def test_multiple_messages_combined( self ):
        """Multiple messages are combined into context."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [
                _make_buffer_entry( "first message" ),
                _make_buffer_entry( "second message" ),
            ]
            _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )

            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: first message" in ctx
            assert "[Voice]: second message" in ctx

    def test_empty_buffer_file_returns_rider_only( self ):
        """Empty buffer file -> rider only (always-fire post-Phase-5b)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_buffer( tmp_dir, "abc12345", [] )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )
            # Phase 5b: rider fires on every turn (when session_id
            # resolves). An empty buffer drains to zero voice messages, so
            # additionalContext is the rider block alone.
            assert "hookSpecificOutput" in result
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "<system-reminder>" in ctx
            assert "[Voice]" not in ctx

    def test_session_id_from_payload( self ):
        """session_id from payload is used for buffer lookup."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "payload session", job_id="deadbeef" ) ]
            _write_buffer( tmp_dir, "deadbeef", entries )

            payload = { "session_id": "deadbeef-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir, session_id="deadbeef-fake-uuid" )

            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: payload session" in ctx

    def test_enrich_voice_context_appended( self ):
        """Enriched context includes IMPORTANT reminder."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "do something" ) ]
            _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir )

            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "IMPORTANT:" in ctx
            assert "mcp__cosa-voice__notify()" in ctx

    def test_no_voice_no_reminder_emits_empty( self ):
        """else branch: empty buffer AND empty rider → emit {} (no additionalContext)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = { "session_id": "abc12345-fake-uuid" }
            with patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block",
                        return_value="" ):
                result = _run_hook_main( payload, tmp_dir )
            assert result == {}

    def test_voice_only_no_reminder_branch( self ):
        """elif voice_ctx (voice present, reminder EMPTY) → enriched voice ctx alone.
        The structural §6a decision still attaches the human-voice rider because the
        drained message is human_to_ai (F2 fix passes `messages` to enrich_voice_context)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entries = [ _make_buffer_entry( "do the thing" ) ]
            _write_buffer( tmp_dir, "abc12345", entries )

            payload = { "session_id": "abc12345-fake-uuid" }
            with patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block",
                        return_value="" ):
                result = _run_hook_main( payload, tmp_dir )

            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: do the thing" in ctx
            assert "IMPORTANT:" in ctx          # human-voice rider attached structurally


class TestDmInboxReconcileWiring:
    """Bug 59f355e0: the store-backed DM reconcile is folded into additionalContext."""

    def test_dm_ctx_folded_alone( self ):
        """Reconcile returns a DM block, no voice / no reminder → block is surfaced."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = { "session_id": "abc12345-fake-uuid" }
            with patch( "lupin_cli.claude_code.hooks.user_prompt_submit.speakerphone_reminder_block",
                        return_value="" ):
                result = _run_hook_main( payload, tmp_dir,
                                         dm_reconcile_ctx="<system-reminder>\nPEER DM from sam\n</system-reminder>" )
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "PEER DM from sam" in ctx
            assert "[Voice]" not in ctx

    def test_dm_ctx_folded_after_voice_before_reminder( self ):
        """Order: human voice first, reconciled DMs next, rider last."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            _write_buffer( tmp_dir, "abc12345", [ _make_buffer_entry( "voice line" ) ] )
            payload = { "session_id": "abc12345-fake-uuid" }
            result  = _run_hook_main( payload, tmp_dir,
                                      dm_reconcile_ctx="RECONCILED_DM_BLOCK" )
            ctx = result[ "hookSpecificOutput" ][ "additionalContext" ]
            assert "[Voice]: voice line" in ctx
            assert "RECONCILED_DM_BLOCK" in ctx
            # voice < dm < rider ordering
            assert ctx.index( "[Voice]: voice line" ) < ctx.index( "RECONCILED_DM_BLOCK" )
            assert ctx.index( "RECONCILED_DM_BLOCK" ) < ctx.index( "<system-reminder>" )

    def test_drained_ai_to_ai_ids_passed_as_extra_surfaced( self ):
        """ai_to_ai entries drained THIS turn are threaded to the reconcile as
        extra_surfaced_ids (so a both-paths DM isn't surfaced twice)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            entry = {
                "message"         : "peer dm body",
                "priority"        : "normal",
                "job_id"          : "abc12345",
                "sender_id"       : "s",
                "notification_id" : "nid-123",
                "timestamp"       : "2026-07-02T10:00:00+00:00",
                "buffered_at"     : "2026-07-02T10:00:00+00:00",
                "direction"       : "ai_to_ai",
                "sender_persona"  : "sam",
                "sender_icon"     : "🎙️",
                "thread_id"       : "t1",
            }
            _write_buffer( tmp_dir, "abc12345", [ entry ] )
            capture = {}
            payload = { "session_id": "abc12345-fake-uuid" }
            _run_hook_main( payload, tmp_dir, dm_capture=capture )
            assert capture[ "extra_surfaced_ids" ] == [ "nid-123" ]


class TestHeartbeatPokeReset:
    """Genuine user re-engagement reopens the heartbeat self-poke budget."""

    def test_reset_poke_count_called_on_prompt( self ):
        """UserPromptSubmit resets the per-session heartbeat poke counter."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = { "session_id": "abc12345-fake-uuid" }
            with patch( "lupin_cli.claude_code.hooks.user_prompt_submit.reset_poke_count" ) as mock_reset:
                _run_hook_main( payload, tmp_dir )
            mock_reset.assert_called_once_with( "abc12345-fake-uuid" )

    def test_reset_skipped_on_empty_payload( self ):
        """Empty payload exits before session resolution → no reset attempted."""
        import io
        from lupin_cli.claude_code.hooks import user_prompt_submit

        captured = io.StringIO()
        with patch( "sys.stdin", io.StringIO( "{}" ) ), \
             patch( "sys.stdout", captured ), \
             patch( "lupin_cli.claude_code.hooks.lib.hook_common.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.user_prompt_submit.reset_poke_count" ) as mock_reset:
            try:
                user_prompt_submit.main()
            except SystemExit:
                pass

        mock_reset.assert_not_called()

    # ── c121037b facet 1: the self-poke must NOT reset the cap ──────────────────

    def test_reset_skipped_when_prompt_is_heartbeat_poke( self ):
        """REGRESSION (c121037b): the heartbeat self-poke is re-submitted as a
        prompt via tmux; UserPromptSubmit must NOT reset the poke-cap for it
        (that reset every turn defeated the cap — poke_count stuck at 1 across
        23 pokes). A prompt opening with POKE_PROMPT_SENTINEL → reset SKIPPED."""
        from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import POKE_PROMPT_SENTINEL
        with tempfile.TemporaryDirectory() as tmp_dir:
            poke    = POKE_PROMPT_SENTINEL + " (1 in-progress TODO item(s) you own) and no fresh hold. Resume."
            payload = { "session_id": "abc12345-fake-uuid", "prompt": poke }
            with patch( "lupin_cli.claude_code.hooks.user_prompt_submit.reset_poke_count" ) as mock_reset:
                _run_hook_main( payload, tmp_dir )
            mock_reset.assert_not_called()

    def test_reset_called_on_genuine_user_prompt( self ):
        """A real user prompt (not a self-poke) STILL reopens the poke budget."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = { "session_id": "abc12345-fake-uuid", "prompt": "please fix the failing test" }
            with patch( "lupin_cli.claude_code.hooks.user_prompt_submit.reset_poke_count" ) as mock_reset:
                _run_hook_main( payload, tmp_dir )
            mock_reset.assert_called_once_with( "abc12345-fake-uuid" )


# ── Standalone ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
