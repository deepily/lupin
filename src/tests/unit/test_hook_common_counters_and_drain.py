"""
Stop-block counters, the turn-start marker, and the voice-buffer drain in
`hook_common` — row `e2099400`.

WHY THESE. Lines 1188-1189, 1213-1214, 1243-1244, 1264-1265, 1290-1291,
1309-1314 and 1386-1406 were dark, and they are all the SAME shape: small
best-effort helpers that swallow their own failures and return a safe value. The
happy path of each was covered incidentally by other tests; not one of the
failure paths was.

WHY THAT SHAPE NEEDS TESTS MORE THAN MOST. These decide whether the stop hook
blocks a session, whether a turn is judged long or short, and whether the
messages waiting for a seat are delivered or thrown away. Every one of them
returns a plausible value on failure — 0, None, an empty list — so a broken one
is indistinguishable at the call site from a working one with nothing to report.

WHAT IS PINNED:

· **The drain is a single-consumer operation.** It renames the buffer before
  reading it, so of two concurrent hooks exactly one gets the messages and the
  other gets an empty list. A drain that read-then-deleted would hand the same
  messages to both, and the user would hear everything twice.

· **The buffer file is gone after a successful drain, and so is the temp file.**
  A drain that left either behind would redeliver on the next turn.

· **A malformed line is skipped and the rest still arrive.** One bad JSON line
  must not swallow the whole buffer.

· **The counters survive a corrupt file.** `get_stop_block_count` reads an
  integer someone else wrote; garbage in that file returns 0, not a crash on the
  stop path.

· **`increment` returns the new count and starts at 1**, and returns 0 rather
  than raising when the write fails — the caller compares it against a
  threshold, so a raise here would take the hook down.

· **`get_turn_elapsed_seconds` returns None, never 0.0, when the marker is
  missing or unreadable.** 0.0 is a legitimate elapsed time and would read as
  "this turn just started" — the gating decision inverts.

· **Both paths truncate the session id to 8 characters** and both fall back to
  `"00000000"` on an empty one, so a caller with a full uuid and one with a
  hash reach the same file.

⚠️ ISOLATION. `_stop_counter_path` hardcodes `/tmp`, so the counter tests patch
that function rather than writing to a real seat's counter file. `TURN_MARKER_DIR`
and `SESSION_DIR` are module constants — `SESSION_DIR` is resolved at IMPORT
time, so redirecting the env var afterwards does nothing and the constant itself
must be patched.

See: row e2099400
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from lupin_cli.claude_code.hooks.lib import hook_common as hc


SID = "abc12345-6789-0000-1111-222222222222"


@pytest.fixture
def counter_file( tmp_path, monkeypatch ):
    """Redirect the counter away from /tmp, where real seats keep theirs."""
    path = tmp_path / "stop-count"
    monkeypatch.setattr( hc, "_stop_counter_path", lambda session_id: path )
    return path


@pytest.fixture
def buffer_dir( tmp_path, monkeypatch ):
    """SESSION_DIR is resolved at import time; the constant is the only seam."""
    monkeypatch.setattr( hc, "SESSION_DIR", tmp_path )
    return tmp_path


class TestTheCounterPath:

    def test_it_is_keyed_on_the_first_eight_characters( self ):
        assert hc._stop_counter_path( SID ).name.endswith( "abc12345" )

    def test_a_full_id_and_its_hash_reach_the_same_file( self ):
        """Callers pass whichever they have; two files would mean two counts."""
        assert hc._stop_counter_path( SID ) == hc._stop_counter_path( "abc12345" )

    def test_an_empty_id_falls_back_to_a_fixed_name_rather_than_crashing( self ):
        assert hc._stop_counter_path( "" ).name.endswith( "00000000" )


class TestTheStopBlockCounter:

    def test_an_absent_file_reads_as_zero( self, counter_file ):
        assert hc.get_stop_block_count( SID ) == 0

    def test_a_written_count_reads_back( self, counter_file ):
        counter_file.write_text( "3" )
        assert hc.get_stop_block_count( SID ) == 3

    def test_surrounding_whitespace_is_tolerated( self, counter_file ):
        counter_file.write_text( "  4\n" )
        assert hc.get_stop_block_count( SID ) == 4

    def test_a_corrupt_file_reads_as_zero_rather_than_raising( self, counter_file ):
        """Someone else wrote this file. A crash here is a crash on the stop
        path, which is the worst place in the hook package to raise."""
        counter_file.write_text( "not a number" )
        assert hc.get_stop_block_count( SID ) == 0

    def test_an_unreadable_file_reads_as_zero( self, counter_file ):
        counter_file.write_text( "3" )
        with patch.object( Path, "read_text", side_effect=OSError( "gone" ) ):
            assert hc.get_stop_block_count( SID ) == 0

    def test_the_first_increment_returns_one( self, counter_file ):
        assert hc.increment_stop_block_count( SID ) == 1

    def test_increments_accumulate_and_persist( self, counter_file ):
        hc.increment_stop_block_count( SID )
        hc.increment_stop_block_count( SID )
        assert hc.increment_stop_block_count( SID ) == 3
        assert counter_file.read_text().strip() == "3"

    def test_a_failed_write_returns_zero_rather_than_raising( self, counter_file ):
        """The caller compares the result to a threshold; a raise would take the
        hook down instead of declining to block."""
        with patch.object( Path, "write_text", side_effect=OSError( "read-only" ) ):
            assert hc.increment_stop_block_count( SID ) == 0

    def test_reset_deletes_the_file( self, counter_file ):
        counter_file.write_text( "5" )
        hc.reset_stop_block_count( SID )
        assert not counter_file.exists()
        assert hc.get_stop_block_count( SID ) == 0

    def test_reset_on_an_absent_file_is_not_an_error( self, counter_file ):
        hc.reset_stop_block_count( SID )        # must not raise

    def test_a_failed_delete_is_swallowed( self, counter_file ):
        counter_file.write_text( "5" )
        with patch.object( Path, "unlink", side_effect=OSError( "busy" ) ):
            hc.reset_stop_block_count( SID )    # must not raise


class TestTheTurnStartMarker:

    @pytest.fixture( autouse=True )
    def marker_dir( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( hc, "TURN_MARKER_DIR", tmp_path )
        return tmp_path

    def test_a_written_marker_yields_a_small_elapsed_time( self ):
        hc.write_turn_start_marker( SID )
        elapsed = hc.get_turn_elapsed_seconds( SID )
        assert elapsed is not None and 0 <= elapsed < 5

    def test_the_marker_is_keyed_on_the_first_eight_characters( self, marker_dir ):
        hc.write_turn_start_marker( SID )
        assert ( marker_dir / "cc-turn-start-abc12345" ).exists()

    def test_a_missing_marker_yields_none_not_zero( self ):
        """0.0 is a legitimate elapsed time and would read as "this turn just
        started" — the gating decision inverts."""
        assert hc.get_turn_elapsed_seconds( SID ) is None

    def test_a_corrupt_marker_yields_none( self, marker_dir ):
        ( marker_dir / "cc-turn-start-abc12345" ).write_text( "not a float" )
        assert hc.get_turn_elapsed_seconds( SID ) is None

    def test_an_unreadable_marker_yields_none( self, marker_dir ):
        hc.write_turn_start_marker( SID )
        with patch.object( Path, "read_text", side_effect=OSError( "gone" ) ):
            assert hc.get_turn_elapsed_seconds( SID ) is None

    def test_a_failed_marker_write_is_swallowed( self ):
        """Non-fatal by design — losing duration gating beats losing the turn."""
        with patch.object( Path, "write_text", side_effect=OSError( "read-only" ) ):
            hc.write_turn_start_marker( SID )   # must not raise

    def test_a_rewrite_moves_the_start_forward( self, marker_dir ):
        marker = marker_dir / "cc-turn-start-abc12345"
        marker.write_text( "1000.0" )
        first = hc.get_turn_elapsed_seconds( SID )
        hc.write_turn_start_marker( SID )
        assert hc.get_turn_elapsed_seconds( SID ) < first


class TestTheBufferPath:

    def test_it_is_keyed_on_the_first_eight_characters( self, buffer_dir ):
        assert hc.get_buffer_path( SID ) == buffer_dir / "cc-buffer-abc12345.jsonl"

    def test_an_empty_id_falls_back_to_a_fixed_name( self, buffer_dir ):
        assert hc.get_buffer_path( "" ).name == "cc-buffer-00000000.jsonl"


class TestTheVoiceBufferDrain:

    def _fill( self, buffer_dir, entries ):
        p = buffer_dir / "cc-buffer-abc12345.jsonl"
        p.write_text( "".join( json.dumps( e ) + "\n" for e in entries ) )
        return p

    def test_an_absent_buffer_drains_to_an_empty_list( self, buffer_dir ):
        assert hc.drain_voice_buffer( SID ) == []

    def test_messages_come_back_in_order( self, buffer_dir ):
        self._fill( buffer_dir, [ { "text": "one" }, { "text": "two" } ] )
        assert [ m[ "text" ] for m in hc.drain_voice_buffer( SID ) ] == [ "one", "two" ]

    def test_the_buffer_is_consumed( self, buffer_dir ):
        path = self._fill( buffer_dir, [ { "text": "one" } ] )
        hc.drain_voice_buffer( SID )
        assert not path.exists()

    def test_a_second_drain_returns_nothing( self, buffer_dir ):
        """Single-consumer. Two hooks draining the same buffer must not both
        deliver it, or the user hears everything twice."""
        self._fill( buffer_dir, [ { "text": "one" } ] )
        assert len( hc.drain_voice_buffer( SID ) ) == 1
        assert hc.drain_voice_buffer( SID ) == []

    def test_a_lost_rename_race_yields_an_empty_list( self, buffer_dir ):
        """The rename is what makes it single-consumer; the loser gets nothing
        rather than a duplicate."""
        self._fill( buffer_dir, [ { "text": "one" } ] )
        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.os.rename",
                    side_effect=FileNotFoundError() ):
            assert hc.drain_voice_buffer( SID ) == []

    def test_a_rename_oserror_yields_an_empty_list( self, buffer_dir ):
        self._fill( buffer_dir, [ { "text": "one" } ] )
        with patch( "lupin_cli.claude_code.hooks.lib.hook_common.os.rename",
                    side_effect=OSError( "cross-device" ) ):
            assert hc.drain_voice_buffer( SID ) == []

    def test_a_malformed_line_is_skipped_and_the_rest_arrive( self, buffer_dir ):
        """One bad line must not swallow the buffer."""
        ( buffer_dir / "cc-buffer-abc12345.jsonl" ).write_text(
            json.dumps( { "text": "good" } ) + "\nnot json\n"
            + json.dumps( { "text": "also good" } ) + "\n" )
        assert [ m[ "text" ] for m in hc.drain_voice_buffer( SID ) ] == \
               [ "good", "also good" ]

    def test_blank_lines_are_ignored( self, buffer_dir ):
        ( buffer_dir / "cc-buffer-abc12345.jsonl" ).write_text(
            "\n" + json.dumps( { "text": "one" } ) + "\n\n" )
        assert len( hc.drain_voice_buffer( SID ) ) == 1

    def test_an_empty_buffer_drains_to_an_empty_list_and_is_removed( self, buffer_dir ):
        path = buffer_dir / "cc-buffer-abc12345.jsonl"
        path.write_text( "" )
        assert hc.drain_voice_buffer( SID ) == []
        assert not path.exists()

    def test_the_temp_drain_file_does_not_survive( self, buffer_dir, tmp_path ):
        """It lives in /tmp; left behind it accumulates, and worse, a later read
        of it would redeliver messages already handed over."""
        self._fill( buffer_dir, [ { "text": "one" } ] )
        before = set( Path( "/tmp" ).glob( "cc-drain-abc12345-*.jsonl" ) )
        hc.drain_voice_buffer( SID )
        after  = set( Path( "/tmp" ).glob( "cc-drain-abc12345-*.jsonl" ) )
        assert after == before

    def test_a_read_failure_returns_what_was_read_rather_than_raising( self, buffer_dir ):
        self._fill( buffer_dir, [ { "text": "one" } ] )
        with patch( "builtins.open", side_effect=OSError( "vanished" ) ):
            assert hc.drain_voice_buffer( SID ) == []


# ── stdin parse failure, log failure, send_tts degradation, stop block ──

class TestReadHookInputAndLogFailures:

    @pytest.mark.parametrize( "stdin_text", [ "", "{ not json", "   " ] )
    def test_unparseable_stdin_reads_as_an_empty_payload( self, monkeypatch, stdin_text ):
        import io
        monkeypatch.setattr( "sys.stdin", io.StringIO( stdin_text ) )
        assert hc.read_hook_input() == { }

    def test_valid_stdin_is_parsed( self, monkeypatch ):
        import io
        monkeypatch.setattr( "sys.stdin", io.StringIO( '{"session_id": "s1"}' ) )
        assert hc.read_hook_input() == { "session_id": "s1" }

    def test_an_unwritable_log_dir_does_not_stop_the_stream_entry( self, monkeypatch ):
        seen = [ ]
        monkeypatch.setattr( hc, "_logs_dir", lambda: ( _ for _ in () ).throw( OSError( "ro" ) ) )
        monkeypatch.setattr( hc, "log_to_stream", lambda name, payload, extra=None: seen.append( ( name, payload ) ) )
        hc.log_payload( "stop", { "k": 1 } )
        assert seen == [ ( "stop", { "k": 1 } ) ]


class TestSendTtsDegradation:

    def _send( self, *, sender_id=None, build_raises=False, notify_raises=False ):
        sent = [ ]
        def fake_notify( request ):
            if notify_raises: raise RuntimeError( "server down" )
            sent.append( request )
        build = ( lambda: ( _ for _ in () ).throw( RuntimeError( "no bridge" ) ) ) if build_raises else ( lambda: "claude.code@lupin.deepily.ai" )
        with patch.object( hc, "is_tts_enabled", return_value=True ), \
             patch.object( hc, "get_target_email", return_value="u@example.com" ), \
             patch( "lupin_cli.claude_code.hooks.lib.session_bridge.build_sender_id_for_cc", build ), \
             patch( "lupin_cli.notifications.notify_user_async.notify_user_async", fake_notify ):
            hc.send_tts( "hello", sender_id=sender_id )
        return sent

    def test_a_missing_sender_is_resolved_from_the_session_bridge( self ):
        sent = self._send()
        assert [ r.sender_id for r in sent ] == [ "claude.code@lupin.deepily.ai" ]

    def test_a_bridge_failure_sends_without_a_sender( self ):
        sent = self._send( build_raises=True )
        assert len( sent ) == 1 and sent[ 0 ].sender_id is None

    def test_an_explicit_sender_is_never_replaced( self ):
        sent = self._send( sender_id="explicit.agent@lupin.deepily.ai" )
        assert sent[ 0 ].sender_id == "explicit.agent@lupin.deepily.ai"

    def test_a_transport_failure_is_swallowed( self ):
        assert self._send( notify_raises=True ) == [ ]


class TestStopBlockWithSystemMessage:

    def test_the_block_carries_the_reason_and_the_full_instruction( self ):
        assert hc.build_stop_block_with_system_message( "why", "do this" ) == \
            { "decision": "block", "reason": "why", "systemMessage": "do this" }


class TestDrainCleanupFailure:

    def test_a_failed_temp_file_unlink_still_returns_the_messages( self, buffer_dir ):
        ( buffer_dir / "cc-buffer-abc12345.jsonl" ).write_text( json.dumps( { "text": "kept" } ) + "\n" )
        with patch.object( Path, "unlink", side_effect=PermissionError( "denied" ) ):
            assert [ m[ "text" ] for m in hc.drain_voice_buffer( SID ) ] == [ "kept" ]


class TestStreamEntryAndProgressGroup:

    def test_a_non_dict_payload_is_logged_without_event_fields( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( hc, "_logs_dir", lambda: tmp_path )
        hc.log_to_stream( "stop", "raw text", extra={ "phase": "x" } )
        entry = json.loads( ( tmp_path / "hook-events.jsonl" ).read_text().splitlines()[ -1 ] )
        assert ( entry[ "hook" ], entry[ "phase" ] ) == ( "stop", "x" )
        assert "event" not in entry and "session_id" not in entry and "tool" not in entry

    def test_a_dict_payload_adds_event_session_and_tool( self, tmp_path, monkeypatch ):
        monkeypatch.setattr( hc, "_logs_dir", lambda: tmp_path )
        hc.log_to_stream( "pre", { "hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "" } )
        entry = json.loads( ( tmp_path / "hook-events.jsonl" ).read_text().splitlines()[ -1 ] )
        assert ( entry[ "event" ], entry[ "tool" ] ) == ( "PreToolUse", "Bash" )

    def test_the_progress_group_id_uses_the_first_eight_characters( self ):
        assert hc.build_progress_group_id( "pt", "6c54ecc2-aaaa-bbbb" ) == "pt-6c54ecc2"

    def test_an_empty_session_id_falls_back_to_zeros( self ):
        assert hc.build_progress_group_id( "pu", "" ) == "pu-00000000"
        assert hc.build_progress_group_id( "pu", None ) == "pu-00000000"
