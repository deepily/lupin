"""
`idle_waiter`'s abort and degrade paths — row `e2099400`.

WHY THESE. Lines 75-76, 168, 173, 177-178, 231-232, 258-259, 284-285 and 335-337
were dark. They are the paths the waiter takes when something is already wrong:
an unwritable log, a bridge that vanished mid-sleep, a qualifier injection that
failed, a malformed test-mode override.

WHY A WAITER'S ABORT PATHS ARE WORTH MORE THAN ITS HAPPY PATH. This process
sleeps for minutes and then speaks to the user unprompted. Every one of these
branches exists to make it exit QUIETLY instead — and the cost of getting one
wrong is a phantom voice prompt in a session that has already moved on, or a
waiter chain that dies silently and never asks again. Neither shows up anywhere
but the log this same module writes.

WHAT IS PINNED:

· **The bridge is re-checked AT WAKE, not just at spawn.** The waiter slept for
  minutes; the session may have ended in that time. Firing an ask into a dead
  session is the failure this second check exists to prevent, and a version that
  checked only at the start would look correct at every other test.

· **A missing `waiter_started_at` aborts rather than proceeding.** It is what
  `_was_reset_during_sleep` compares against; without it the reset check silently
  can never fire, and the waiter would prompt through a live conversation.

· **A failed qualifier injection is logged and the waiter carries on.** The
  successor scheduling matters more than the injection — losing the chain
  because tmux was unavailable would end the idle prompting entirely.

· **An unwritable log directory does not stop the waiter**, and a log file it
  cannot open degrades the SUCCESSOR to DEVNULL rather than aborting the spawn.

· **A non-numeric `LUPIN_IDLE_WAITER_TEST_SLEEP_SECS` is ignored, not fatal.**
  It is a test-mode convenience; a typo in it must not take the waiter down in
  a real session.

· **The `--sleep-secs` override is propagated to the successor.** Dropped, a
  test-mode chain silently reverts to the real backoff schedule and the next
  link sleeps for minutes instead of seconds.

⚠️ No real sleeping and no real subprocess anywhere — `time.sleep` and
`subprocess.Popen` are both patched.

See: row e2099400
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks.lib import idle_waiter as iw


MODULE = "lupin_cli.claude_code.hooks.lib.idle_waiter"
SID    = "abc12345-0000-1111-2222-333333333333"


@pytest.fixture( autouse=True )
def log_dir( tmp_path, monkeypatch ):
    """_LOG_DIR is resolved at import time; the constant is the only seam."""
    monkeypatch.setattr( iw, "_LOG_DIR", tmp_path )
    return tmp_path


class TestTheLogIsBestEffort:

    def test_a_line_reaches_both_the_session_log_and_the_central_one( self, log_dir ):
        iw._log( SID, "hello" )
        assert "hello" in ( log_dir / "cc-idle-waiter-abc12345.log" ).read_text()
        assert "hello" in ( log_dir / "cc-idle-waiters.log" ).read_text()

    def test_an_unwritable_log_does_not_raise( self ):
        """This runs on every branch of the waiter, including the ones whose
        whole job is to exit cleanly."""
        with patch( "builtins.open", side_effect=OSError( "read-only" ) ):
            iw._log( SID, "hello" )

    def test_an_empty_session_id_still_logs_somewhere( self, log_dir ):
        iw._log( "", "orphan line" )
        assert ( log_dir / "cc-idle-waiter-unknown.log" ).exists()


class TestSpawningTheSuccessor:

    def _spawn( self, popen_kwargs=None, **kwargs ):
        popen = MagicMock( return_value=MagicMock( pid=4242 ), **( popen_kwargs or {} ) )
        with patch( f"{MODULE}.subprocess.Popen", popen ):
            pid = iw._spawn_successor( SID, 999, 2, **kwargs )
        return pid, popen

    def test_it_returns_the_successor_pid( self ):
        pid, _ = self._spawn()
        assert pid == 4242

    def test_the_successor_is_detached( self ):
        """Otherwise it dies with the parent it was spawned to replace."""
        _, popen = self._spawn()
        assert popen.call_args.kwargs[ "start_new_session" ] is True

    def test_the_backoff_index_is_passed_on( self ):
        _, popen = self._spawn()
        cmd = popen.call_args.args[ 0 ]
        assert cmd[ cmd.index( "--backoff-index" ) + 1 ] == "2"

    def test_a_sleep_override_is_propagated( self ):
        """Dropped, a test-mode chain silently reverts to the real schedule and
        the next link sleeps for minutes instead of seconds."""
        _, popen = self._spawn( sleep_secs_override=5 )
        cmd = popen.call_args.args[ 0 ]
        assert cmd[ cmd.index( "--sleep-secs" ) + 1 ] == "5"

    def test_no_override_omits_the_flag_entirely( self ):
        _, popen = self._spawn()
        assert "--sleep-secs" not in popen.call_args.args[ 0 ]

    def test_an_unopenable_log_degrades_to_devnull_rather_than_aborting( self ):
        """Losing the successor's log is a nuisance; losing the successor ends
        idle prompting for the session."""
        popen = MagicMock( return_value=MagicMock( pid=4242 ) )
        with patch( "builtins.open", side_effect=OSError( "read-only" ) ), \
             patch( f"{MODULE}.subprocess.Popen", popen ):
            assert iw._spawn_successor( SID, 999, 1 ) == 4242
        assert popen.call_args.kwargs[ "stdout" ] is subprocess.DEVNULL
        assert popen.call_args.kwargs[ "stderr" ] is subprocess.DEVNULL

    def test_the_source_path_is_put_on_the_child_pythonpath( self ):
        """The successor is `python -m lupin_cli…`; without it the child dies on
        an ImportError that nobody would see."""
        _, popen = self._spawn()
        assert iw._src_path in popen.call_args.kwargs[ "env" ][ "PYTHONPATH" ]


class _Run:
    """The mocks a run_waiter drive needs to be asserted against.

    ⚠️ THEY MUST COME FROM HERE, not from a second `patch` wrapped around the
    call. An outer patch of the same name is SHADOWED by this helper's inner
    one, so `outer.assert_not_called()` passes no matter what run_waiter did.
    Four tests in the first draft of this file were vacuous for exactly that
    reason, and the mutation that deleted the at-wake bridge check stayed green
    against all four."""
    def __init__( self, popen, inject, ask, claim ):
        self.popen  = popen
        self.inject = inject
        self.ask    = ask
        self.claim  = claim


def _run_waiter( bridge_at_start=True, bridge_at_wake=True, state=None,
                 speakerphone=False, reset=False, ask=None, inject_raises=False ):
    """Drive run_waiter with every collaborator stubbed. Returns a _Run carrying
    the mocks — assert against those, never against an outer patch."""
    if state is None:
        state = { "waiter_started_at": "2026-08-26T12:00:00-04:00", "last_task_gist": "gist" }
    if ask is None:
        ask = MagicMock( answer="no", qualifier=None, error=None )

    paths = [ "/bridge" if bridge_at_start else None,
              "/bridge" if bridge_at_wake  else None ]
    popen = MagicMock( return_value=MagicMock( pid=4242 ) )

    inject = MagicMock( side_effect=RuntimeError( "no tmux" ) if inject_raises else None )

    with patch( f"{MODULE}.load_idle_settings", return_value={ "backoff_minutes": [ 1, 2, 4 ] } ), \
         patch( f"{MODULE}.find_session_path_by_id", side_effect=paths ), \
         patch( f"{MODULE}.get_idle_detection", return_value=state ), \
         patch( f"{MODULE}.set_idle_detection_field" ) as claim, \
         patch( f"{MODULE}._is_pid_alive", return_value=True ), \
         patch( f"{MODULE}._was_reset_during_sleep", return_value=reset ), \
         patch( f"{MODULE}.get_speakerphone", return_value=speakerphone ), \
         patch( f"{MODULE}.fire_anything_else_ask", return_value=ask ) as fire, \
         patch( f"{MODULE}.time.sleep" ), \
         patch( f"{MODULE}.subprocess.Popen", popen ), \
         patch( "lupin_cli.claude_code.hooks.lib.hook_common.inject_qualifier_via_tmux", inject ):
        iw.run_waiter( SID, 999, 0, sleep_secs_override=1 )
    return _Run( popen, inject, fire, claim )


class TestTheWaiterExitsQuietly:

    def test_a_missing_waiter_started_at_aborts_before_sleeping( self ):
        """It is what the reset check compares against. Without it that check
        can never fire, and the waiter would prompt through a live
        conversation."""
        run = _run_waiter( state={ "last_task_gist": "gist" } )
        run.popen.assert_not_called()
        run.ask.assert_not_called()

    def test_a_bridge_gone_at_WAKE_aborts_before_asking( self ):
        """The waiter slept for minutes; the session may have ended in that
        time. A version checking only at spawn would look correct everywhere
        else."""
        assert _run_waiter( bridge_at_wake=False ).ask.call_count == 0

    def test_a_bridge_gone_at_START_never_claims_the_slot( self ):
        run = _run_waiter( bridge_at_start=False )
        run.claim.assert_not_called()
        run.ask.assert_not_called()

    def test_a_reset_during_sleep_aborts_before_asking( self ):
        assert _run_waiter( reset=True ).ask.call_count == 0

    def test_conversation_mode_aborts_before_asking( self ):
        assert _run_waiter( speakerphone=True ).ask.call_count == 0

    def test_a_transport_error_schedules_no_successor( self ):
        """No retry storm — the next user activity respawns the chain."""
        _run_waiter( ask=MagicMock( answer="error", qualifier=None, error="boom" ) ).popen.assert_not_called()

    def test_a_yes_schedules_no_successor( self ):
        """The user is about to type; UserPromptSubmit resets the chain."""
        _run_waiter( ask=MagicMock( answer="yes", qualifier=None, error=None ) ).popen.assert_not_called()

    def test_a_no_schedules_a_successor( self ):
        """THE CONTROL for the four aborts above — a waiter that never spawned
        would satisfy every one of them."""
        _run_waiter( ask=MagicMock( answer="no", qualifier=None, error=None ) ).popen.assert_called_once()


class TestQualifierInjection:

    def test_a_qualifier_is_injected( self ):
        run = _run_waiter( ask=MagicMock( answer="no", qualifier="hold on", error=None ) )
        assert run.inject.call_args.args[ 1 ] == "hold on"

    def test_no_qualifier_means_no_injection( self ):
        _run_waiter( ask=MagicMock( answer="no", qualifier=None, error=None ) ).inject.assert_not_called()

    def test_a_failed_injection_does_not_stop_the_successor( self ):
        """Losing the chain because tmux was unavailable would end idle
        prompting for the session; losing one qualifier would not."""
        _run_waiter( ask=MagicMock( answer="no", qualifier="hold on", error=None ),
                     inject_raises=True ).popen.assert_called_once()

    def test_a_qualifier_is_injected_even_on_a_yes( self ):
        """The user said continue AND typed something — dropping the something
        would silently discard what they said."""
        _run_waiter( ask=MagicMock( answer="yes", qualifier="do X", error=None ) ).inject.assert_called_once()


class TestTheTestModeSleepOverride:

    def _main( self, argv, env ):
        with patch( f"{MODULE}.sys.argv", [ "idle_waiter" ] + argv ), \
             patch( f"{MODULE}.os.environ", env ), \
             patch( f"{MODULE}.signal.signal" ), \
             patch( f"{MODULE}._log" ), \
             patch( f"{MODULE}.run_waiter" ) as run:
            iw.main()
        return run

    _ARGV = [ "--session-id", SID, "--cc-pid", "999", "--backoff-index", "0" ]

    def test_the_env_override_is_read_when_the_flag_is_absent( self ):
        run = self._main( self._ARGV, { "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS": "7" } )
        assert run.call_args.kwargs[ "sleep_secs_override" ] == 7

    def test_the_flag_wins_over_the_env( self ):
        run = self._main( self._ARGV + [ "--sleep-secs", "3" ],
                          { "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS": "7" } )
        assert run.call_args.kwargs[ "sleep_secs_override" ] == 3

    def test_a_non_numeric_env_override_is_ignored_rather_than_fatal( self ):
        """A typo in a test-mode convenience must not take down a real
        session's waiter."""
        run = self._main( self._ARGV, { "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS": "soon" } )
        assert run.call_args.kwargs[ "sleep_secs_override" ] is None

    def test_no_override_anywhere_leaves_the_real_schedule_in_charge( self ):
        run = self._main( self._ARGV, {} )
        assert run.call_args.kwargs[ "sleep_secs_override" ] is None
