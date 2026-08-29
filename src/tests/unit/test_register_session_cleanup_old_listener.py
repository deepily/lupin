"""
`_cleanup_old_listener` + `_log_session_transition` — row `e2099400`.

WHY THIS BLOCK. Lines 454-541 were the largest single dark region in
`register_session.py` (63 of its 139 missing statements). Nothing reached it
because it only runs on a CONTEXT CLEAR — the moment a seat gets a new session
id on the same pid — which no existing test drove.

WHAT IT DOES, AND WHY GETTING IT WRONG IS QUIET. On a `/clear` the old listener
is still alive and still filtering for the OLD session hash, so anything sent to
that seat lands in a buffer nobody will ever read. This function kills the old
listener and FORWARDS the orphaned buffer to the new hash. Every failure mode
here is silent by construction — the whole body is wrapped in best-effort
exception handling, so a broken forward loses the user's messages and reports
nothing. That is exactly the shape a test has to pin, because production never
will.

WHAT IS PINNED:

· **The kill escalates, and only when it has to.** A listener that dies on
  SIGTERM is never sent SIGKILL; one still alive when the 3-second budget runs
  out is. Both directions, because a version that always escalated and a version
  that never did would each pass a single-sided test.

· **A dead or unsignalable listener is not an error.** `ProcessLookupError` and
  `PermissionError` both mean "there is nothing to kill" — this runs on the boot
  path, and raising here would take the session start down with it.

· **Forwarded entries are re-keyed to the new hash and stamped with the old
  one.** `job_id` is what the new listener filters on; without the rewrite the
  messages are delivered into the new buffer and still ignored. The
  `forwarded_from` stamp is what makes the move auditable afterwards.

· **A malformed buffer line is forwarded VERBATIM rather than dropped.** The
  loop catches `JSONDecodeError` and writes the raw line. Losing a message
  because it could not be parsed would be worse than delivering it unkeyed.

· **The old buffer is removed only after the forward.** A crash between the two
  would duplicate on the next boot; a remove-first would lose everything.

· **Nothing happens when the hash did not change.** Forwarding a buffer onto
  itself would double every message in it.

⚠️ THE 3-SECOND WAIT IS PATCHED, NOT SLEPT. `time.monotonic` is driven from a
fixed list so the timeout branch is reached in microseconds. A test that
actually waited would be three seconds of the unit tier's budget per case, and
the unit tier is the one that must stay fast enough to run constantly.

⚠️ ISOLATION: every test redirects `LUPIN_HOOK_SESSIONS_DIR` to a tmp_path.
That seam exists because this module once wrote fixture data into three live
seats' bridges — see `lib/sessions_dir.py`'s docstring, row `8ccc20ab`.

See: row e2099400
"""

import json
import os
import signal

import pytest

from lupin_cli.claude_code.hooks.register_session import (
    _cleanup_old_listener,
    _log_session_transition,
)
from unittest.mock import patch


MODULE = "lupin_cli.claude_code.hooks.register_session"

OLD_ID = "aaaaaaaa-1111-2222-3333-444444444444"
NEW_ID = "bbbbbbbb-5555-6666-7777-888888888888"
OLD_H  = OLD_ID[:8]
NEW_H  = NEW_ID[:8]


@pytest.fixture( autouse=True )
def isolated_sessions_dir( tmp_path, monkeypatch ):
    """Redirect the bridge directory. Without this the module writes into the
    operator's live `~/.claude/sessions` — the defect row 8ccc20ab exists for."""
    d = tmp_path / "sessions"
    d.mkdir()
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( d ) )
    return d


def _bridge( pid=None, session_id=OLD_ID, stable=None ):
    data = { "session_id": session_id }
    if pid is not None:    data[ "listener_pid" ]      = pid
    if stable is not None: data[ "stable_session_id" ] = stable
    return data


class TestTheKillEscalates:

    def test_a_listener_that_dies_on_sigterm_is_never_force_killed( self ):
        """alive → SIGTERM → gone. SIGKILL here would be gratuitous."""
        sent = []

        def fake_kill( pid, sig ):
            sent.append( sig )
            if len( sent ) >= 3: raise ProcessLookupError()   # gone after the TERM

        with patch( f"{MODULE}.os.kill", side_effect=fake_kill ), \
             patch( f"{MODULE}.time.sleep" ):
            _cleanup_old_listener( _bridge( pid=4242 ), NEW_ID )

        assert signal.SIGTERM in sent
        assert signal.SIGKILL not in sent

    def test_a_listener_still_alive_at_the_deadline_is_force_killed( self ):
        """The budget is 3 seconds; monotonic is driven past it rather than
        waited out."""
        sent = []

        with patch( f"{MODULE}.os.kill", side_effect=lambda pid, sig: sent.append( sig ) ), \
             patch( f"{MODULE}.time.sleep" ), \
             patch( f"{MODULE}.time.monotonic", side_effect=[ 0.0, 1.0, 2.0, 100.0 ] ):
            _cleanup_old_listener( _bridge( pid=4242 ), NEW_ID )

        assert signal.SIGKILL in sent

    def test_the_two_routes_do_not_produce_the_same_signals( self ):
        """The control. A version that always escalated would satisfy the force
        test above, and one that never did would satisfy the graceful test."""
        graceful = []
        def dies( pid, sig ):
            graceful.append( sig )
            if len( graceful ) >= 3: raise ProcessLookupError()
        with patch( f"{MODULE}.os.kill", side_effect=dies ), patch( f"{MODULE}.time.sleep" ):
            _cleanup_old_listener( _bridge( pid=1 ), NEW_ID )

        stubborn = []
        with patch( f"{MODULE}.os.kill", side_effect=lambda p, s: stubborn.append( s ) ), \
             patch( f"{MODULE}.time.sleep" ), \
             patch( f"{MODULE}.time.monotonic", side_effect=[ 0.0, 1.0, 100.0 ] ):
            _cleanup_old_listener( _bridge( pid=1 ), NEW_ID )

        assert set( graceful ) != set( stubborn )

    def test_an_already_dead_listener_is_not_an_error( self ):
        with patch( f"{MODULE}.os.kill", side_effect=ProcessLookupError() ):
            _cleanup_old_listener( _bridge( pid=4242 ), NEW_ID )     # must not raise

    def test_an_unsignalable_listener_is_not_an_error( self ):
        """Someone else's process. Raising here would take the boot down."""
        with patch( f"{MODULE}.os.kill", side_effect=PermissionError() ):
            _cleanup_old_listener( _bridge( pid=4242 ), NEW_ID )

    def test_an_oserror_from_the_signal_is_not_an_error( self ):
        with patch( f"{MODULE}.os.kill", side_effect=OSError( "signal failed" ) ):
            _cleanup_old_listener( _bridge( pid=4242 ), NEW_ID )

    def test_no_recorded_pid_means_no_signal_at_all( self ):
        with patch( f"{MODULE}.os.kill" ) as kill:
            _cleanup_old_listener( _bridge( pid=None ), NEW_ID )
        kill.assert_not_called()


class TestBufferForwarding:

    def _write_buffer( self, d, entries ):
        p = d / f"cc-buffer-{OLD_H}.jsonl"
        p.write_text( "".join( json.dumps( e ) + "\n" for e in entries ) )
        return p

    def test_entries_are_rekeyed_to_the_new_hash( self, isolated_sessions_dir ):
        """job_id is what the new listener filters on. Copied across unchanged,
        the messages arrive and are still ignored."""
        self._write_buffer( isolated_sessions_dir, [ { "job_id": OLD_H, "text": "hello" } ] )

        _cleanup_old_listener( _bridge(), NEW_ID )

        forwarded = json.loads(
            ( isolated_sessions_dir / f"cc-buffer-{NEW_H}.jsonl" ).read_text().strip() )
        assert forwarded[ "job_id" ]         == NEW_H
        assert forwarded[ "forwarded_from" ] == OLD_H
        assert forwarded[ "text" ]           == "hello"

    def test_every_entry_is_forwarded_not_just_the_first( self, isolated_sessions_dir ):
        self._write_buffer( isolated_sessions_dir,
                            [ { "text": "one" }, { "text": "two" }, { "text": "three" } ] )

        _cleanup_old_listener( _bridge(), NEW_ID )

        lines = ( isolated_sessions_dir / f"cc-buffer-{NEW_H}.jsonl" ).read_text().splitlines()
        assert [ json.loads( l )[ "text" ] for l in lines ] == [ "one", "two", "three" ]

    def test_a_malformed_line_is_forwarded_verbatim_rather_than_dropped( self, isolated_sessions_dir ):
        """Delivering an unkeyed message beats losing it."""
        ( isolated_sessions_dir / f"cc-buffer-{OLD_H}.jsonl" ).write_text(
            "not json at all\n" + json.dumps( { "text": "good" } ) + "\n" )

        _cleanup_old_listener( _bridge(), NEW_ID )

        text = ( isolated_sessions_dir / f"cc-buffer-{NEW_H}.jsonl" ).read_text()
        assert "not json at all" in text
        assert "good" in text

    def test_the_old_buffer_is_removed_once_forwarded( self, isolated_sessions_dir ):
        old = self._write_buffer( isolated_sessions_dir, [ { "text": "x" } ] )
        _cleanup_old_listener( _bridge(), NEW_ID )
        assert not old.exists()

    def test_forwarding_appends_rather_than_overwrites( self, isolated_sessions_dir ):
        """The new listener may already have buffered something of its own."""
        ( isolated_sessions_dir / f"cc-buffer-{NEW_H}.jsonl" ).write_text(
            json.dumps( { "text": "already here" } ) + "\n" )
        self._write_buffer( isolated_sessions_dir, [ { "text": "forwarded" } ] )

        _cleanup_old_listener( _bridge(), NEW_ID )

        lines = ( isolated_sessions_dir / f"cc-buffer-{NEW_H}.jsonl" ).read_text().splitlines()
        assert [ json.loads( l )[ "text" ] for l in lines ] == [ "already here", "forwarded" ]

    def test_an_empty_old_buffer_is_still_removed_and_writes_nothing( self, isolated_sessions_dir ):
        old = isolated_sessions_dir / f"cc-buffer-{OLD_H}.jsonl"
        old.write_text( "" )

        _cleanup_old_listener( _bridge(), NEW_ID )

        assert not old.exists()
        assert not ( isolated_sessions_dir / f"cc-buffer-{NEW_H}.jsonl" ).exists()

    def test_an_unchanged_hash_forwards_nothing( self, isolated_sessions_dir ):
        """Forwarding a buffer onto itself would double every message in it."""
        old = self._write_buffer( isolated_sessions_dir, [ { "text": "x" } ] )

        _cleanup_old_listener( _bridge(), OLD_ID )      # same session id back again

        assert old.exists()
        assert old.read_text().count( "\n" ) == 1

    def test_a_missing_old_buffer_is_not_an_error( self, isolated_sessions_dir ):
        _cleanup_old_listener( _bridge(), NEW_ID )      # must not raise
        assert not ( isolated_sessions_dir / f"cc-buffer-{NEW_H}.jsonl" ).exists()

    def test_an_unreadable_buffer_is_swallowed( self, isolated_sessions_dir ):
        """Best-effort by design — this runs on the boot path."""
        self._write_buffer( isolated_sessions_dir, [ { "text": "x" } ] )
        with patch( "builtins.open", side_effect=OSError( "disk gone" ) ):
            _cleanup_old_listener( _bridge(), NEW_ID )   # must not raise

    def test_a_blank_new_session_id_forwards_nothing( self, isolated_sessions_dir ):
        old = self._write_buffer( isolated_sessions_dir, [ { "text": "x" } ] )
        _cleanup_old_listener( _bridge(), "" )
        assert old.exists()


class TestTheTransitionLog:

    def test_a_transition_is_recorded_with_both_hashes( self, isolated_sessions_dir ):
        _cleanup_old_listener( _bridge(), NEW_ID )

        line = ( isolated_sessions_dir / "cc-listeners.log" ).read_text()
        assert "SESSION TRANSITION" in line
        assert f"{OLD_H} -> {NEW_H}" in line

    def test_the_stable_id_is_preferred_over_the_old_one_when_present( self, isolated_sessions_dir ):
        """After a second /clear the OLD id is itself a successor; the stable id
        is what ties the whole chain back to one seat."""
        _cleanup_old_listener( _bridge( stable="cccccccc-9999-0000-1111-222222222222" ), NEW_ID )

        assert "stable: cccccccc" in ( isolated_sessions_dir / "cc-listeners.log" ).read_text()

    def test_it_falls_back_to_the_old_hash_with_no_stable_id( self, isolated_sessions_dir ):
        _cleanup_old_listener( _bridge(), NEW_ID )
        assert f"stable: {OLD_H}" in ( isolated_sessions_dir / "cc-listeners.log" ).read_text()

    def test_a_missing_old_hash_writes_no_transition_line( self, isolated_sessions_dir ):
        """Nothing transitioned from, so there is nothing to record."""
        _cleanup_old_listener( { "session_id": "" }, NEW_ID )
        assert not ( isolated_sessions_dir / "cc-listeners.log" ).exists()

    def test_the_log_appends_rather_than_replaces( self, isolated_sessions_dir ):
        _cleanup_old_listener( _bridge(), NEW_ID )
        _cleanup_old_listener( _bridge(), NEW_ID )
        log = ( isolated_sessions_dir / "cc-listeners.log" ).read_text()
        assert log.count( "SESSION TRANSITION" ) == 2

    def test_an_unwritable_log_is_swallowed( self, isolated_sessions_dir ):
        """Best-effort. A full disk must not stop a session from starting."""
        with patch( "builtins.open", side_effect=OSError( "read-only" ) ):
            _log_session_transition( OLD_H, NEW_H, OLD_H )   # must not raise

    def test_the_line_carries_the_hook_pseudo_hash( self, isolated_sessions_dir ):
        """`[--------]` marks the line as written by the hook rather than by a
        listener — the log is shared and the writers are told apart by it."""
        _log_session_transition( OLD_H, NEW_H, OLD_H )
        assert "[--------]" in ( isolated_sessions_dir / "cc-listeners.log" ).read_text()
