"""
Idle-waiter slot claiming, reset detection, and CLI — row `e2099400`.

WHY THESE FUNCTIONS. `idle_waiter.py` sat at 70% with 49 statements uncovered.
The dark regions were the small guard helpers and `main()` — and the guards are
the part that decides whether the user gets prompted once, twice, or not at all
after a session goes quiet.

THE TWO GUARDS AND WHAT THEY PREVENT:

· `_claim_waiter_slot` is a mutual-exclusion check. If it ever returned True
  while another waiter was live, the user would get **two "Anything else?"
  prompts for one idle session** — the exact double-prompt its docstring says
  it exists to avoid. It must also NOT be so strict that a dead predecessor
  blocks the slot forever, or a session that crashed once is never prompted
  again. Both directions are tested, plus the fact that they differ.

· `_was_reset_during_sleep` is a phantom-prompt check. A hook that fired while
  the waiter slept means the user is back — prompting them now would be asking
  "anything else?" of someone mid-sentence. The comparison is strictly greater
  than, and an equal timestamp must NOT count as a reset, or a waiter whose
  sleep began in the same second as an interaction would exit for nothing.

⚠️ `_is_pid_alive` is tested against its FOUR distinct outcomes rather than two.
`PermissionError` means the process exists but belongs to someone else, and
`OSError` is a different failure again — all three collapse to False here, which
is correct for this use but only *provably* correct if each is exercised. A
guard that crashed on PermissionError would take the waiter down instead of
declining the slot.

See: row e2099400
"""

import os
from unittest.mock import patch

import pytest

from lupin_cli.claude_code.hooks.lib.idle_waiter import (
    _claim_waiter_slot,
    _is_pid_alive,
    _release_waiter_slot,
    _was_reset_during_sleep,
    main,
)


MODULE = "lupin_cli.claude_code.hooks.lib.idle_waiter"


# ---------------------------------------------------------------------------
# _is_pid_alive — four outcomes, not two
# ---------------------------------------------------------------------------

class TestIsPidAlive:

    def test_a_signalable_process_is_alive( self ):
        with patch( f"{MODULE}.os.kill", return_value=None ):
            assert _is_pid_alive( 4242 ) is True

    def test_a_missing_process_is_not_alive( self ):
        with patch( f"{MODULE}.os.kill", side_effect=ProcessLookupError() ):
            assert _is_pid_alive( 4242 ) is False

    def test_a_process_owned_by_somebody_else_is_treated_as_not_alive( self ):
        """It genuinely exists, but we cannot manage it. Reporting False is the
        right call for slot arbitration — and crucially it must not RAISE."""
        with patch( f"{MODULE}.os.kill", side_effect=PermissionError() ):
            assert _is_pid_alive( 4242 ) is False

    def test_a_generic_os_error_is_also_absorbed( self ):
        with patch( f"{MODULE}.os.kill", side_effect=OSError( "weird" ) ):
            assert _is_pid_alive( 4242 ) is False

    @pytest.mark.parametrize( "bad", [ None, 0, -1 ] )
    def test_a_nonsense_pid_is_rejected_before_signalling( self, bad ):
        """os.kill(0, 0) signals the whole process GROUP. The guard must reject
        it rather than pass it through."""
        with patch( f"{MODULE}.os.kill" ) as kill:
            assert _is_pid_alive( bad ) is False
            kill.assert_not_called()


# ---------------------------------------------------------------------------
# _claim_waiter_slot — the double-prompt guard
# ---------------------------------------------------------------------------

def _claim( *, state, alive ):
    with patch( f"{MODULE}.get_idle_detection", return_value=state ), \
         patch( f"{MODULE}.set_idle_detection_field" ) as setter, \
         patch( f"{MODULE}._is_pid_alive", return_value=alive ):
        got = _claim_waiter_slot( "sess-1" )
    return got, setter


class TestClaimWaiterSlot:

    def test_an_empty_slot_is_claimed( self ):
        got, setter = _claim( state={}, alive=False )
        assert got is True
        assert setter.call_count == 1

    def test_a_missing_state_record_is_treated_as_an_empty_slot( self ):
        """get_idle_detection returns None for a session with no record yet;
        the `or {}` must absorb it rather than raising on .get."""
        with patch( f"{MODULE}.get_idle_detection", return_value=None ), \
             patch( f"{MODULE}.set_idle_detection_field" ), \
             patch( f"{MODULE}._is_pid_alive", return_value=False ):
            assert _claim_waiter_slot( "sess-1" ) is True

    def test_a_live_holder_blocks_the_claim( self ):
        """THE GUARD. Returning True here gives the user two 'Anything else?'
        prompts for one idle session."""
        got, setter = _claim( state={ "waiter_pid": 9999 }, alive=True )
        assert got is False
        setter.assert_not_called()

    def test_a_dead_holder_does_not_block_the_claim( self ):
        """THE OTHER DIRECTION, and it matters just as much: if a dead
        predecessor held the slot forever, a session that crashed once would
        never be prompted again."""
        got, setter = _claim( state={ "waiter_pid": 9999 }, alive=False )
        assert got is True
        assert setter.call_count == 1

    def test_live_and_dead_holders_give_different_answers( self ):
        """The control. A claim that always succeeded would satisfy the
        dead-holder test, and one that always failed would satisfy the live."""
        live, _ = _claim( state={ "waiter_pid": 9999 }, alive=True )
        dead, _ = _claim( state={ "waiter_pid": 9999 }, alive=False )
        assert live != dead

    def test_the_claim_records_this_process_and_a_start_time( self ):
        _, setter = _claim( state={}, alive=False )
        kwargs = setter.call_args.kwargs
        assert kwargs[ "waiter_pid" ] == os.getpid()
        assert kwargs[ "waiter_started_at" ]


class TestReleaseWaiterSlot:

    def test_we_clear_the_slot_when_we_still_own_it( self ):
        with patch( f"{MODULE}.get_idle_detection", return_value={ "waiter_pid": os.getpid() } ), \
             patch( f"{MODULE}.set_idle_detection_field" ) as setter:
            _release_waiter_slot( "sess-1" )
        assert setter.call_args.kwargs[ "waiter_pid" ] is None

    def test_we_do_not_clear_a_slot_somebody_else_now_owns( self ):
        """A successor may have claimed it while we were finishing. Clearing it
        would strand the live waiter and let a third one in."""
        with patch( f"{MODULE}.get_idle_detection", return_value={ "waiter_pid": os.getpid() + 1 } ), \
             patch( f"{MODULE}.set_idle_detection_field" ) as setter:
            _release_waiter_slot( "sess-1" )
        setter.assert_not_called()

    def test_a_missing_state_record_is_a_no_op_rather_than_an_error( self ):
        with patch( f"{MODULE}.get_idle_detection", return_value=None ), \
             patch( f"{MODULE}.set_idle_detection_field" ) as setter:
            _release_waiter_slot( "sess-1" )
        setter.assert_not_called()


# ---------------------------------------------------------------------------
# _was_reset_during_sleep — the phantom-prompt guard
# ---------------------------------------------------------------------------

def _reset( last, started ):
    with patch( f"{MODULE}.get_idle_detection", return_value={ "last_interaction_at": last } ):
        return _was_reset_during_sleep( "sess-1", started )


class TestWasResetDuringSleep:

    def test_an_interaction_after_our_sleep_started_counts_as_a_reset( self ):
        """The user came back. Prompting now asks 'anything else?' of somebody
        mid-sentence."""
        assert _reset( "2026-08-25T19:30:00", "2026-08-25T19:00:00" ) is True

    def test_an_interaction_before_our_sleep_started_is_not_a_reset( self ):
        assert _reset( "2026-08-25T18:00:00", "2026-08-25T19:00:00" ) is False

    def test_an_identical_timestamp_is_not_a_reset( self ):
        """Strictly greater than, deliberately. A waiter whose sleep began in
        the same second as an interaction would otherwise exit for nothing."""
        assert _reset( "2026-08-25T19:00:00", "2026-08-25T19:00:00" ) is False

    def test_no_recorded_interaction_is_not_a_reset( self ):
        assert _reset( None, "2026-08-25T19:00:00" ) is False

    def test_an_unparseable_timestamp_is_not_a_reset_and_does_not_raise( self ):
        """Degrading to 'no reset' keeps the prompt firing. Degrading the other
        way would silently disable the feature on one bad write."""
        assert _reset( "not a timestamp", "2026-08-25T19:00:00" ) is False

    def test_a_missing_state_record_is_not_a_reset( self ):
        with patch( f"{MODULE}.get_idle_detection", return_value=None ):
            assert _was_reset_during_sleep( "sess-1", "2026-08-25T19:00:00" ) is False


# ---------------------------------------------------------------------------
# main — the CLI
# ---------------------------------------------------------------------------

BASE_ARGV = [ "idle_waiter", "--session-id", "sess-1", "--cc-pid", "4242", "--backoff-index", "0" ]


def _main( argv=None, env=None, run_side_effect=None ):
    argv = argv or BASE_ARGV
    with patch( f"{MODULE}.sys.argv", argv ), \
         patch( f"{MODULE}.signal.signal" ), \
         patch( f"{MODULE}._log" ), \
         patch.dict( os.environ, env or {}, clear=False ), \
         patch( f"{MODULE}.run_waiter", side_effect=run_side_effect ) as run:
        code = main()
    return code, run


class TestMain:

    def test_a_clean_run_returns_zero( self ):
        code, run = _main()
        assert code == 0
        assert run.call_count == 1

    def test_an_unhandled_exception_returns_one_rather_than_propagating( self ):
        """This is a detached background process. An escaping traceback would
        leave the waiter slot held by a pid that is gone."""
        code, _ = _main( run_side_effect=RuntimeError( "boom" ) )
        assert code == 1

    def test_the_two_outcomes_do_not_share_a_return_code( self ):
        ok, _  = _main()
        bad, _ = _main( run_side_effect=RuntimeError( "boom" ) )
        assert ok != bad

    def test_the_parsed_arguments_reach_run_waiter( self ):
        _, run = _main()
        kwargs = run.call_args.kwargs
        assert kwargs[ "session_id" ]    == "sess-1"
        assert kwargs[ "cc_pid" ]        == 4242
        assert kwargs[ "backoff_index" ] == 0

    def test_an_explicit_sleep_flag_wins( self ):
        _, run = _main( argv=BASE_ARGV + [ "--sleep-secs", "7" ] )
        assert run.call_args.kwargs[ "sleep_secs_override" ] == 7

    def test_the_env_override_is_used_when_the_flag_is_absent( self ):
        _, run = _main( env={ "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS": "11" } )
        assert run.call_args.kwargs[ "sleep_secs_override" ] == 11

    def test_the_flag_beats_the_env_var( self ):
        """Both set. The explicit flag must win, or a stale exported test value
        would silently override a deliberate command line."""
        _, run = _main( argv=BASE_ARGV + [ "--sleep-secs", "7" ],
                        env={ "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS": "11" } )
        assert run.call_args.kwargs[ "sleep_secs_override" ] == 7

    def test_a_non_numeric_env_override_is_ignored_rather_than_crashing( self ):
        _, run = _main( env={ "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS": "soon" } )
        assert run.call_args.kwargs[ "sleep_secs_override" ] is None

    def test_no_override_anywhere_leaves_it_none( self ):
        _, run = _main( env={ "LUPIN_IDLE_WAITER_TEST_SLEEP_SECS": "" } )
        assert run.call_args.kwargs[ "sleep_secs_override" ] is None
