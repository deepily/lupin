"""
Phase 2 of the session watcher, started DELIBERATELY and asserted on.

Row `87ae7234`. `_session_watcher_thread` used to do two separable jobs in one
`while True:` started at module import. Phase 1 — the one-shot resolve that sets
`_session_ready` in a `finally` — is load-bearing: suppressing it takes a suite from
`333 passed` to a silent `EXIT=1`, because `_wait_for_sender_id` blocks on that event.
Phase 2 — the forever 2-second poll — is not load-bearing, nothing waits on it, and
it was the source of every line the daemon credited to no test.

It is now `_watch_bridge_for_changes( stop_event, poll_interval, max_iterations )`.
These tests drive it directly and assert what it DID, which is the shape this repo has
already accepted as earned coverage (CommonsArchiver, CommonsAckWatcher).

⚠️ IT MUTATES MODULE GLOBALS. `SESSION_ID` and `SENDER_ID` are module-level and the
watcher rewrites them. Every test here restores both, or it leaks into the 41 other
files that import this module.
"""
import os
import sys
import threading
from unittest.mock import patch

import pytest

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" ) )

import lupin_mcp.cosa_voice_mcp as m


@pytest.fixture
def restore_globals():
    """Snapshot and restore the two globals the watcher rewrites."""
    session, sender = m.SESSION_ID, m.SENDER_ID
    yield
    m.SESSION_ID, m.SENDER_ID = session, sender


class _Bridge:
    """A stand-in for the resolved bridge path — only `.stat().st_mtime` is used."""

    def __init__( self, mtime ):
        self.mtime = mtime

    def stat( self ):
        outer = self
        class _S:
            st_mtime = outer.mtime
        return _S()


def _run_watcher( iterations=1, **patches ):
    """Run the loop for a bounded number of polls with zero wait."""
    defaults = { "clear_cached_session_id": lambda: None }
    defaults.update( patches )
    with patch.multiple( m, **{ k: v for k, v in defaults.items() } ):
        m._watch_bridge_for_changes( poll_interval=0, max_iterations=iterations )


class TestItStops:

    def test_max_iterations_bounds_the_loop( self, restore_globals ):
        """Without a bound this is `while True:` — the tests could not exist."""
        calls = []
        _run_watcher( iterations=3,
                      clear_cached_session_id=lambda: calls.append( 1 ),
                      _find_session_file=lambda: None )

        assert len( calls ) == 3, f"expected exactly 3 polls, got {len( calls )}"

    def test_a_set_stop_event_returns_before_polling_at_all( self, restore_globals ):
        """
        The loop's own guard, not the iteration bound. An already-set event must mean
        zero work — otherwise `stop()` cannot be trusted to have stopped anything.
        """
        calls    = []
        stopper  = threading.Event()
        stopper.set()

        with patch.multiple( m, clear_cached_session_id=lambda: calls.append( 1 ),
                                _find_session_file=lambda: None ):
            m._watch_bridge_for_changes( stop_event=stopper, poll_interval=0 )

        assert calls == [], "a set stop_event must stop the loop before it polls"

    def test_a_stop_event_that_never_fires_still_polls( self, restore_globals ):
        """
        The wait's FALSE arm — it timed out, nobody stopped us, so keep working.
        Every other test here has the event set, so this is the only path that
        proves a stop_event does not itself suppress the watch. Found by branch
        coverage: arc 502->507 was the one uncovered branch in the new function.
        """
        calls   = []
        stopper = threading.Event()          # deliberately never set

        with patch.multiple( m, clear_cached_session_id=lambda: calls.append( 1 ),
                                _find_session_file=lambda: None ):
            m._watch_bridge_for_changes( stop_event=stopper, poll_interval=0,
                                         max_iterations=2 )

        assert len( calls ) == 2, (
            f"a stop_event that never fires must not stop the watch; polled {len( calls )}x"
        )

    def test_an_event_set_during_the_wait_ends_the_loop( self, restore_globals ):
        """
        The interruptible-wait arm. `stop_event.wait()` returning True is a DIFFERENT
        exit than the `while` guard, and only this reaches it.
        """
        stopper = threading.Event()
        calls   = []

        def _find():
            calls.append( 1 )
            return None

        stopper.set()
        with patch.multiple( m, clear_cached_session_id=lambda: None, _find_session_file=_find ):
            # while-guard sees it set first, so force the wait arm by clearing then
            # setting from the wait itself.
            stopper.clear()
            t = threading.Timer( 0.01, stopper.set )
            t.start()
            m._watch_bridge_for_changes( stop_event=stopper, poll_interval=0.05 )
            t.cancel()

        assert calls == [], "the wait returning True must return before doing any work"


class TestItSkipsWhatItShould:

    def test_no_bridge_file_is_skipped( self, restore_globals ):
        before = m.SESSION_ID
        _run_watcher( _find_session_file=lambda: None )

        assert m.SESSION_ID == before, "no bridge file must leave the session id alone"

    def test_a_stat_that_raises_oserror_is_skipped( self, restore_globals ):
        class _Boom:
            def stat( self ): raise OSError( "gone" )

        before = m.SESSION_ID
        _run_watcher( _find_session_file=lambda: ( _Boom(), "src" ) )

        assert m.SESSION_ID == before, "an unstattable bridge must not change anything"

    def test_an_unchanged_mtime_is_skipped( self, restore_globals ):
        """last_mtime starts at 0.0, so an mtime of 0.0 is 'not newer'."""
        reads  = []
        before = m.SESSION_ID
        _run_watcher( _find_session_file=lambda: ( _Bridge( 0.0 ), "src" ),
                      _read_session_file=lambda p: reads.append( p ) )

        assert reads == [], "an unchanged mtime must not re-read the file"
        assert m.SESSION_ID == before

    def test_an_empty_session_file_is_skipped( self, restore_globals ):
        before = m.SESSION_ID
        _run_watcher( _find_session_file=lambda: ( _Bridge( 99.0 ), "src" ),
                      _read_session_file=lambda p: "" )

        assert m.SESSION_ID == before, "an empty read must not blank the session id"

    def test_the_same_session_id_is_not_reported_as_a_change( self, restore_globals ):
        """
        NEGATIVE CONTROL for the update arm below. A fresh mtime with the SAME id is
        the common case — a bridge file rewritten with unchanged content — and it must
        not announce a context clear that did not happen.
        """
        senders = []
        m.SESSION_ID = "aaaaaaaa"
        _run_watcher( _find_session_file=lambda: ( _Bridge( 99.0 ), "src" ),
                      _read_session_file=lambda p: "aaaaaaaa-rest-of-uuid",
                      _get_sender_id=lambda proj, sid: senders.append( sid ) )

        assert senders == [], "an unchanged id must not rebuild the sender id"
        assert m.SESSION_ID == "aaaaaaaa"


class TestItUpdatesWhenItShould:

    def test_a_changed_session_id_rewrites_both_globals( self, restore_globals ):
        """THE POINT OF THE LOOP. Everything above is a path that declines to do this."""
        m.SESSION_ID = "aaaaaaaa"
        m.SENDER_ID  = "old-sender"

        _run_watcher( _find_session_file=lambda: ( _Bridge( 99.0 ), "src" ),
                      _read_session_file=lambda p: "bbbbbbbb-rest-of-uuid",
                      _get_sender_id=lambda proj, sid: f"sender-{sid}" )

        assert m.SESSION_ID == "bbbbbbbb", "the new session id was not picked up"
        assert m.SENDER_ID  == "sender-bbbbbbbb", "the sender id was not rebuilt from it"

    def test_it_only_updates_once_for_one_change( self, restore_globals ):
        """
        `last_mtime` must advance, or a single change is re-applied on every poll and
        the log fills with context clears that never happened.
        """
        builds = []
        m.SESSION_ID = "aaaaaaaa"
        _run_watcher( iterations=4,
                      _find_session_file=lambda: ( _Bridge( 99.0 ), "src" ),
                      _read_session_file=lambda p: "bbbbbbbb-rest",
                      _get_sender_id=lambda proj, sid: builds.append( sid ) or "s" )

        assert len( builds ) == 1, f"one change must update once, updated {len( builds )}x"


class TestItSurvivesAFailedPoll:

    def test_an_exception_in_one_poll_does_not_end_the_watch( self, restore_globals ):
        """
        A watch that dies on the first bad poll is a watch that silently stops
        watching. The positive control is that later polls still run.
        """
        seen = []

        def _find():
            seen.append( 1 )
            if len( seen ) == 1: raise RuntimeError( "transient" )
            return None

        _run_watcher( iterations=3, _find_session_file=_find )

        assert len( seen ) == 3, (
            f"the loop stopped after an exception - saw {len( seen )} polls, expected 3"
        )


class TestTheEntryPointActuallySetsTheFlag:
    """
    THE ONE LINE NO IMPORT CAN REACH, and the most important line in the change.

    `_IS_MCP_SERVER = True` lives inside `if __name__ == "__main__":`, so importing
    the module never executes it and no ordinary test can observe it. Deleting that
    line leaves every test in this repo green while a real MCP server silently reads
    False — a genuine session-id failure would then raise instead of exiting, leaving
    a server up that cannot serve. Caught by mutation: removing the assignment passed
    351 tests.

    So this reads the entry-point block STRUCTURALLY, via the AST. Not elegant; it is
    the only way to hold a line that exists outside every import.
    """

    @staticmethod
    def _main_block():
        import ast
        src  = open( m.__file__ ).read()
        tree = ast.parse( src )
        for node in tree.body:
            if not isinstance( node, ast.If ): continue
            t = node.test
            if ( isinstance( t, ast.Compare ) and isinstance( t.left, ast.Name )
                 and t.left.id == "__name__" ): return node.body
        return None

    def test_the_main_block_exists_at_all( self ):
        assert self._main_block() is not None, (
            "no `if __name__ == '__main__':` block found - the entry point moved, and "
            "the server flag moved with it"
        )

    def test_the_main_block_sets_the_server_flag_to_true( self ):
        import ast
        body    = self._main_block()
        assigns = [ n for n in body if isinstance( n, ast.Assign ) ]
        names   = [ ( t.id, getattr( n.value, "value", None ) )
                    for n in assigns for t in n.targets if isinstance( t, ast.Name ) ]

        assert ( "_IS_MCP_SERVER", True ) in names, (
            "the entry point does not set _IS_MCP_SERVER = True. A real MCP server "
            f"would read False and raise instead of exiting. Assignments found: {names}"
        )

    def test_the_flag_is_set_before_mcp_run( self ):
        """
        Order matters: a failure DURING startup must still hard-exit the server as it
        always has. Setting the flag after `mcp.run()` would be setting it never.
        """
        import ast
        body = self._main_block()

        flag_at = run_at = None
        for i, n in enumerate( body ):
            if isinstance( n, ast.Assign ) and any(
                isinstance( t, ast.Name ) and t.id == "_IS_MCP_SERVER" for t in n.targets ):
                flag_at = i
            if ( isinstance( n, ast.Expr ) and isinstance( n.value, ast.Call )
                 and isinstance( n.value.func, ast.Attribute )
                 and n.value.func.attr == "run" ): run_at = i

        assert flag_at is not None and run_at is not None, ( flag_at, run_at )
        assert flag_at < run_at, "the flag must be set BEFORE mcp.run(), not after"


class TestTheMtimeGuardDoesItsOwnWork:
    """
    `last_mtime = current_mtime` is what stops one change being re-processed on every
    poll. Caught by mutation: deleting it passed every test, because after the first
    update `last_session_id` also matches and the id-comparison hides the rework. The
    id guard was covering for the mtime guard.
    """

    def test_an_unchanged_file_is_read_once_not_once_per_poll( self, restore_globals ):
        reads = []
        m.SESSION_ID = "aaaaaaaa"
        _run_watcher( iterations=4,
                      _find_session_file=lambda: ( _Bridge( 99.0 ), "src" ),
                      _read_session_file=lambda p: reads.append( p ) or "bbbbbbbb-rest",
                      _get_sender_id=lambda proj, sid: "s" )

        assert len( reads ) == 1, (
            f"the bridge file was re-read {len( reads )}x across 4 polls with one "
            "mtime - last_mtime is not advancing, so every poll redoes the work"
        )


# ── A MUTANT THAT SURVIVED, AND WHY THAT IS THE HONEST ANSWER ────────────────
#
# Replacing `while stop_event is None or not stop_event.is_set():` with a bare
# `while True:` passes every test in this file, and I could not write one that
# catches it. That is not a coverage gap — the two are EQUIVALENT:
# `stop_event.wait()` on an already-set event returns True immediately, so every
# path that the guard would short-circuit is short-circuited one line later by the
# wait, with no extra interval paid. I first wrote a latency test claiming to catch
# it; the test passed on the mutant, so it was asserting something it could not see.
# It is deleted rather than kept as decoration.
#
# The guard stays because it says the loop's exit condition out loud at the top,
# where a reader looks for it. It is redundancy for legibility, not a control — and
# recording that is better than leaving a future reader to re-derive it, or to
# "strengthen" a test that was never testing anything.
