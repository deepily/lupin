"""
What every bridge reader in `session_bridge.py` does when the file on disk is unreadable.
Row `e2099400` §3d, target 3.

🔴 THE FINDING THIS FILE EXISTS FOR — IT IS ONE SHAPE, WRITTEN NINETEEN TIMES, AND NONE OF THEM
HAD A TEST. `session_bridge.py` had 44 missing statements when this was written, measured at sha
6b7533eb on the unit tier with an isolated coverage data file. Mapping each missing line to its
enclosing function turns that scatter into a single pattern:

    except ( json.JSONDecodeError, OSError ):
        return <fallback>          # or `continue`, in the scanners

Nineteen functions. Eighteen of them are that guard. Fifteen are the same two lines. They were
not uncovered in nineteen unrelated ways — the whole FAMILY was untested, because nothing in
this suite ever handed any of them a broken bridge file.

WHY THAT IS WORSE THAN 44 UNCOVERED STATEMENTS SOUNDS. These are the guards that stand between
one corrupt JSON file and the fleet's liveness path. A bridge file is written by one process and
read by every other one, and it can be caught mid-write, truncated by a full disk, or left
unreadable by a permission change. If ANY of these nineteen caught the wrong exception or
returned the wrong fallback, the failure would not be a wrong answer — it would be a traceback
out of a SessionStart or Stop hook, and no coverage number would ever have pointed at it. The
copies are near-identical, so a defect in one is invisible next to eighteen correct siblings.

⇒ THE TESTS BELOW ARE TABLE-DRIVEN ON PURPOSE. Reading the family as a table is the only way to
see that the fallbacks are not uniform — the getters answer None, the setters answer False, the
scanners skip the file and keep going — and a table makes an odd one out obvious in a way
nineteen hand-written cases never would.

THE TWO WAYS A BRIDGE GOES BAD, and both are exercised for every accessor: the file parses as
nothing (`json.JSONDecodeError`) and the file cannot be opened at all (`OSError`). A guard that
caught only one of them would pass a test that only tried the other.

Venue: :7999-eligible — in-process, no server, no network. Files are written under pytest's own
tmp_path; nothing touches a real `~/.claude/sessions`.
"""

import json
import os
import unittest

from pathlib import Path
from unittest import mock

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


# ── the accessor family: session_id in, one answer out ───────────────────────
#
# ( function name, positional args after session_id, the documented fallback )
#
# The fallbacks are NOT all the same, and that is the point of listing them here rather than
# asserting "falsy": a getter returning False instead of None, or a setter returning None
# instead of False, is a real change in meaning for the caller.
ACCESSORS = [
    ( "get_speakerphone",              ( ),                False ),
    ( "set_speakerphone",              ( True, ),          False ),
    ( "get_last_autonarrated_turn_id", ( ),                None  ),
    ( "set_last_autonarrated_turn_id", ( "turn-9", ),      False ),
    ( "get_voice_persona",             ( ),                None  ),
    ( "set_voice_persona",             ( { "name": "john" }, ), False ),
    ( "clear_idle_waiter_pid",         ( ),                None  ),
]


def _bridge( tmp, pid, payload ):
    r"""
    Write one bridge file into `tmp` under the name the code actually looks for.

    ⚠️ THE FILENAME IS ``cc-<pid>.json`` AND NOTHING ELSE, which cost me a green test. My first
    version named them ``cc-<a-readable-word>-<pid>.json``, and ``_extract_pid_from_filename``
    matches a bare ``cc-`` plus digits plus ``.json`` — so every liveness filter read them as
    "no pid recorded" and took a different branch than the one under test. `prune_dead_persona_
    bridges` skipped every file outright and its test passed while running none of it.
    """
    path = Path( tmp ) / f"cc-{pid}.json"
    path.write_text( payload if isinstance( payload, str ) else json.dumps( payload ) )
    return path


class AccessorsSurviveACorruptBridgeTest( unittest.TestCase ):
    """
    Every single-session accessor, against a file that is not JSON.

    ⚠️ `set_idle_detection_field` is exercised separately below — it takes keyword arguments
    rather than positionals, so folding it into the table would have meant a special case
    inside the loop, which is exactly the kind of thing that hides a missing entry.
    """

    def setUp( self ):
        self.tmp  = self.enterContext( __import__( "tempfile" ).TemporaryDirectory() )
        self.path = _bridge( self.tmp, os.getpid(), "{ this is not json" )

    def _call( self, name, args ):
        with mock.patch.object( sb, "find_session_path_by_id", return_value=self.path ):
            return getattr( sb, name )( "wise-penguin", *args )

    def test_every_accessor_returns_its_documented_fallback( self ):
        for name, args, expected in ACCESSORS:
            with self.subTest( function=name ):
                self.assertIs( self._call( name, args ), expected,
                               f"{name} must answer {expected!r} on a corrupt bridge, not raise" )

    def test_set_idle_detection_field_answers_false_too( self ):
        with mock.patch.object( sb, "find_session_path_by_id", return_value=self.path ):
            self.assertIs( sb.set_idle_detection_field( "wise-penguin", waiter_pid=4242 ), False )


class AccessorsSurviveAnUnreadableBridgeTest( unittest.TestCase ):
    """
    The same family, against a file that cannot be opened at all.

    THE SECOND HALF OF EACH GUARD. `except ( json.JSONDecodeError, OSError )` catches two
    different worlds — a file full of garbage and a file we are not allowed to read. A guard
    listing only the first would pass every case in the class above and still let a permission
    change take a hook down.
    """

    def setUp( self ):
        self.tmp  = self.enterContext( __import__( "tempfile" ).TemporaryDirectory() )
        self.path = _bridge( self.tmp, os.getpid(), { "session_id": "clever-dolphin" } )

    def _call( self, name, args ):
        with mock.patch.object( sb, "find_session_path_by_id", return_value=self.path ), \
             mock.patch( "builtins.open", side_effect=PermissionError( "not yours" ) ):
            return getattr( sb, name )( "clever-dolphin", *args )

    def test_every_accessor_returns_its_documented_fallback( self ):
        for name, args, expected in ACCESSORS:
            with self.subTest( function=name ):
                self.assertIs( self._call( name, args ), expected )

    def test_set_idle_detection_field_answers_false_too( self ):
        with mock.patch.object( sb, "find_session_path_by_id", return_value=self.path ), \
             mock.patch( "builtins.open", side_effect=PermissionError( "not yours" ) ):
            self.assertIs( sb.set_idle_detection_field( "clever-dolphin", waiter_pid=4242 ), False )


class FakeSessionDir:
    """
    A stand-in for `SESSION_DIR` that yields its files in an ORDER THE TEST CHOOSES.

    ⚠️ THIS CLASS EXISTS BECAUSE THE FIRST VERSION OF THESE TESTS DID NOT GUARD ANYTHING, AND
    THE MUTATION CHECK IS WHAT SAID SO. The original wrote a corrupt bridge and then a good one
    into a real directory and asserted the good one was still found — on the stated reasoning
    that "the good bridge is written second, so a scanner that gave up on the first bad file
    would find nothing". File CREATION order is not `Path.glob` order; glob follows the
    directory's own iteration order, which nothing in the test controlled. Breaking one
    scanner's `continue` into a `return None` left the suite GREEN, because that scanner
    happened to reach the good file first.

    The functions under test use exactly two things from SESSION_DIR — `.exists()` and
    `.glob(pattern)` — so handing them a list in a fixed order is enough, and it makes
    "the bad file comes first" a fact rather than a hope.
    """

    def __init__( self, *paths, exists=True ):
        self._paths  = list( paths )
        self._exists = exists

    def exists( self ):
        return self._exists

    def glob( self, _pattern ):
        return iter( self._paths )


class ScannersSkipTheBadFileAndKeepGoingTest( unittest.TestCase ):
    """
    The other half of the family: functions that WALK the bridge directory.

    Their guard says `continue`, not `return` — one unreadable file must cost that file and
    nothing else. The corrupt bridge is yielded FIRST, guaranteed (see FakeSessionDir), so a
    scanner that gave up on it would find nothing and every assertion here would fail.
    """

    GOOD_ID = "wise-penguin-0000-1111-2222-333344445555"

    def setUp( self ):
        self.tmp    = Path( self.enterContext( __import__( "tempfile" ).TemporaryDirectory() ) )
        self.broken = _bridge( self.tmp, 111111, "{{{ not json at all" )
        self.good   = _bridge( self.tmp, 222222, {
            "session_id"      : self.GOOD_ID,
            "speakerphone_on" : True,
            "tmux_session"    : "cc-author-john-1",
            "cwd"             : str( self.tmp ),
        } )
        # BOTH pids must read as ALIVE. Every scanner drops dead-pid files BEFORE opening them,
        # so a corrupt bridge whose owner looks dead is skipped for the wrong reason and its
        # guard never runs — a test that would pass against a deleted guard.
        for patcher in (
            mock.patch.object( sb, "SESSION_DIR", FakeSessionDir( self.broken, self.good ) ),
            mock.patch.object( sb, "_can_trust_host_pids", return_value=True ),
            mock.patch.object( sb, "_is_pid_alive", return_value=True ),
        ):
            patcher.start(); self.addCleanup( patcher.stop )

    def test_find_session_by_id_still_finds_the_good_one( self ):
        self.assertIsNotNone( sb.find_session_by_id( self.GOOD_ID ) )

    def test_find_session_path_by_id_still_finds_the_good_one( self ):
        self.assertEqual( sb.find_session_path_by_id( self.GOOD_ID ), self.good )

    def test_find_session_by_tmux_still_finds_the_good_one( self ):
        self.assertIsNotNone( sb.find_session_by_tmux( "cc-author-john-1" ) )

    def test_find_active_speakerphone_sessions_still_reports_the_good_one( self ):
        sessions = sb.find_active_speakerphone_sessions()
        self.assertTrue( sessions, "the readable speakerphone bridge must survive its broken neighbour" )


class PruneDeadPersonaBridgesTest( unittest.TestCase ):
    """
    `prune_dead_persona_bridges` — the SessionStart scrub that frees personas held by seats
    that are gone.

    ⚠️ REACHING ITS CORRUPT-FILE ARM NEEDS TWO PRECONDITIONS, AND THE MUTATION CHECK IS WHAT
    FOUND THEM. Folded into the scanner class above, this function never touched a file at all:
    it returns 0 outright when `_can_trust_host_pids()` is False, and it SKIPS every file whose
    pid is still ALIVE — the exact opposite of the other scanners, because its job is to clean
    up after the dead. Breaking its `continue` into a `raise` left the suite green, which is
    the honest signal that the test was not running the code it named.
    """

    def setUp( self ):
        self.tmp = Path( self.enterContext( __import__( "tempfile" ).TemporaryDirectory() ) )
        # A pid nothing can be running under — the prune only looks at files whose owner is gone.
        self.broken = _bridge( self.tmp, 999_999, "{{{ not json" )
        self.dead   = _bridge( self.tmp, 999_998, {
            "session_id"   : "gone-0000",
            "voice_persona": { "name": "sam" },
        } )
        for patcher in (
            mock.patch.object( sb, "SESSION_DIR", FakeSessionDir( self.broken, self.dead ) ),
            mock.patch.object( sb, "_can_trust_host_pids", return_value=True ),
            mock.patch.object( sb, "_is_pid_alive", return_value=False ),
        ):
            patcher.start(); self.addCleanup( patcher.stop )

    def test_a_dead_seat_s_persona_is_released_past_a_corrupt_neighbour( self ):
        """
        The corrupt file is yielded first. A raise there would take SessionStart down before it
        ever reached the bridge it was called to clean, and the persona would stay held.
        """
        self.assertEqual( sb.prune_dead_persona_bridges(), 1 )
        self.assertIsNone( json.loads( self.dead.read_text() )[ "voice_persona" ] )

    def test_it_does_nothing_at_all_when_host_pids_cannot_be_trusted( self ):
        """
        Inside a container the pids in those filenames belong to another namespace, so "dead"
        cannot be established. Pruning on that reading would strip personas from LIVE seats.
        """
        with mock.patch.object( sb, "_can_trust_host_pids", return_value=False ):
            self.assertEqual( sb.prune_dead_persona_bridges(), 0 )

    def test_a_bridge_whose_owner_is_still_alive_is_left_alone( self ):
        with mock.patch.object( sb, "_is_pid_alive", return_value=True ):
            self.assertEqual( sb.prune_dead_persona_bridges(), 0 )
        self.assertIsNotNone( json.loads( self.dead.read_text() )[ "voice_persona" ] )


class ProjectResolutionSurvivesACorruptBridgeTest( unittest.TestCase ):
    """
    `_resolve_project_from_bridge_cwd` — reads the launch directory recorded at SessionStart.

    Its guard is WIDER than the family's (it also catches ValueError and ImportError) because it
    imports from cosa and does path work after the read. That difference is deliberate, and it
    is only visible when the family is read as a table.
    """

    def test_a_corrupt_bridge_resolves_to_no_project_rather_than_raising( self ):
        tmp  = self.enterContext( __import__( "tempfile" ).TemporaryDirectory() )
        path = _bridge( tmp, os.getpid(), "not json" )
        with mock.patch.object( sb, "_find_session_file", return_value=( path, "test" ) ):
            self.assertIsNone( sb._resolve_project_from_bridge_cwd() )

    def test_a_bridge_with_no_cwd_field_resolves_to_no_project( self ):
        tmp  = self.enterContext( __import__( "tempfile" ).TemporaryDirectory() )
        path = _bridge( tmp, os.getpid(), { "session_id": "wise-penguin" } )
        with mock.patch.object( sb, "_find_session_file", return_value=( path, "test" ) ):
            self.assertIsNone( sb._resolve_project_from_bridge_cwd() )

    def test_no_bridge_at_all_resolves_to_no_project( self ):
        with mock.patch.object( sb, "_find_session_file", return_value=None ):
            self.assertIsNone( sb._resolve_project_from_bridge_cwd() )


class ReadSessionFileTest( unittest.TestCase ):
    """`_read_session_file` — the lowest read in the module; everything above it depends on this."""

    def test_a_corrupt_file_reads_as_no_session_id( self ):
        tmp  = self.enterContext( __import__( "tempfile" ).TemporaryDirectory() )
        self.assertIsNone( sb._read_session_file( _bridge( tmp, os.getpid(), "}{" ) ) )

    def test_a_file_that_is_not_there_reads_as_no_session_id( self ):
        self.assertIsNone( sb._read_session_file( Path( "/nonexistent/cc-nope.json" ) ) )


class DefaultSpeakerphoneTest( unittest.TestCase ):
    """
    `_get_default_speakerphone` — what a bridge with no explicit field means.

    ⚠️ ITS GUARD IS THE ONLY BARE `except Exception` IN THE FAMILY, and that is correct here:
    it defers an import of `cosa.utils.util` to dodge a circular import, so the thing that can
    go wrong is not a file read at all. Solo mode is the safe answer — a session wrongly told
    it is in chorus mode starts speaking out loud.
    """

    def test_chorus_mode_means_speakerphone_on_by_default( self ):
        with mock.patch( "cosa.utils.util.get_tts_interaction_mode", return_value="chorus" ):
            self.assertIs( sb._get_default_speakerphone(), True )

    def test_solo_mode_means_off( self ):
        with mock.patch( "cosa.utils.util.get_tts_interaction_mode", return_value="solo" ):
            self.assertIs( sb._get_default_speakerphone(), False )

    def test_anything_going_wrong_falls_back_to_off_rather_than_on( self ):
        with mock.patch( "cosa.utils.util.get_tts_interaction_mode",
                         side_effect=RuntimeError( "config is unreadable" ) ):
            self.assertIs( sb._get_default_speakerphone(), False )


class KillIdleWaiterTest( unittest.TestCase ):
    """
    `kill_idle_waiter` — claims the waiter's PID, then signals it.

    Its guard catches process errors rather than file errors, and the PID it is about to signal
    was read from a file a moment earlier. Between the read and the kill the process can exit
    and its number be reused, which is why liveness is checked first and why the signal itself
    is still wrapped.
    """

    def test_no_recorded_waiter_means_nothing_to_kill( self ):
        with mock.patch.object( sb, "clear_idle_waiter_pid", return_value=None ):
            self.assertIs( sb.kill_idle_waiter( "wise-penguin" ), False )

    def test_a_recorded_but_dead_pid_is_not_signalled( self ):
        """Signalling a dead PID's number risks hitting whatever process inherited it."""
        with mock.patch.object( sb, "clear_idle_waiter_pid", return_value=4242 ), \
             mock.patch.object( sb, "_is_pid_alive", return_value=False ), \
             mock.patch.object( sb.os, "kill" ) as killed:
            self.assertIs( sb.kill_idle_waiter( "wise-penguin" ), False )
        killed.assert_not_called()

    def test_a_live_waiter_is_signalled_and_reported_as_killed( self ):
        with mock.patch.object( sb, "clear_idle_waiter_pid", return_value=4242 ), \
             mock.patch.object( sb, "_is_pid_alive", return_value=True ), \
             mock.patch.object( sb.os, "kill" ) as killed:
            self.assertIs( sb.kill_idle_waiter( "wise-penguin" ), True )
        self.assertEqual( killed.call_args.args[ 0 ], 4242 )

    def test_a_waiter_that_dies_between_the_check_and_the_signal_is_not_an_error( self ):
        """The race the liveness check cannot close: it exits in the microseconds after we look."""
        with mock.patch.object( sb, "clear_idle_waiter_pid", return_value=4242 ), \
             mock.patch.object( sb, "_is_pid_alive", return_value=True ), \
             mock.patch.object( sb.os, "kill", side_effect=ProcessLookupError ):
            self.assertIs( sb.kill_idle_waiter( "wise-penguin" ), False )

    def test_a_waiter_we_may_not_signal_is_reported_as_not_killed( self ):
        with mock.patch.object( sb, "clear_idle_waiter_pid", return_value=4242 ), \
             mock.patch.object( sb, "_is_pid_alive", return_value=True ), \
             mock.patch.object( sb.os, "kill", side_effect=PermissionError ):
            self.assertIs( sb.kill_idle_waiter( "wise-penguin" ), False )


class ClearIdleWaiterPidTest( unittest.TestCase ):
    """
    `clear_idle_waiter_pid` — reads the recorded waiter PID and blanks it in one step.

    The claim has to be atomic: two hooks clearing at once must not both come away believing
    they own the PID and both send a signal.
    """

    def setUp( self ):
        self.tmp = self.enterContext( __import__( "tempfile" ).TemporaryDirectory() )

    def _run( self, payload ):
        path = _bridge( self.tmp, os.getpid(), payload )
        with mock.patch.object( sb, "find_session_path_by_id", return_value=path ):
            return sb.clear_idle_waiter_pid( "wise-penguin" ), path

    def test_a_recorded_pid_is_returned_and_blanked_in_the_file( self ):
        got, path = self._run( { "idle_detection": { "waiter_pid": 4242 } } )
        self.assertEqual( got, 4242 )
        self.assertIsNone( json.loads( path.read_text() )[ "idle_detection" ][ "waiter_pid" ] )

    def test_a_bridge_with_no_idle_block_has_nothing_to_claim( self ):
        got, _ = self._run( { "session_id": "wise-penguin" } )
        self.assertIsNone( got )

    def test_an_idle_block_with_no_waiter_has_nothing_to_claim( self ):
        got, _ = self._run( { "idle_detection": { } } )
        self.assertIsNone( got )

    def test_a_failed_write_claims_nothing( self ):
        """
        THE ATOMICITY POINT. If the blanking write fails, the PID is STILL RECORDED — so
        returning it would hand the caller a waiter it has not actually claimed, and the next
        hook to look would claim the same one.
        """
        path = _bridge( self.tmp, os.getpid(), { "idle_detection": { "waiter_pid": 4242 } } )
        with mock.patch.object( sb, "find_session_path_by_id", return_value=path ), \
             mock.patch.object( sb, "atomic_write_json", return_value=False ):
            self.assertIsNone( sb.clear_idle_waiter_pid( "wise-penguin" ) )
