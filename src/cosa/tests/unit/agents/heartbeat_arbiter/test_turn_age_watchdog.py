"""
Unit tests for the turn-age watchdog (wedge fix f1a21917 lever (ii)).

Covers the pure transcript analysis (find_dangling_tool_use / age_seconds), the
sweep_once detection + flood-guard (one-shot per (session, tool_use) +
intersect-clear), the pane-active suppression, per-session swallow-safety, the
advisory composition, and the daemon lifecycle. All IO is injected — the pragma'd
`_default_*` boundaries are exercised only for their default-wiring branches.

Venue: :7999 bucket — pure in-memory, no server, no real bridges/tmux/clock, <2s.

See: src/rnd/v0.1.9/2026.07.03-notify-turn-hold-fix-design.md §3.
"""

from datetime import datetime, timezone, timedelta

import pytest

from cosa.agents.heartbeat_arbiter.turn_age_watchdog import (
    TurnAgeWatchdog,
    find_dangling_tool_use,
    age_seconds,
    ADVISORY_ACTOR,
)


NOW = datetime( 2026, 7, 3, 3, 0, 0, tzinfo=timezone.utc )


class FakeConfig:
    """Minimal config_mgr: .get( key, default=, return_type= ) over a dict."""
    def __init__( self, values ):
        self._values = values
    def get( self, key, default=None, return_type=None ):
        return self._values.get( key, default )


def _enabled_config( threshold=600, tick=60 ):
    return FakeConfig( {
        "arbiter turn age watchdog enabled"          : True,
        "arbiter turn age watchdog threshold seconds" : threshold,
        "arbiter poll seconds"                        : tick,
    } )


def _tool_use( tid, ts=None ):
    return { "timestamp": ts, "message": { "content": [ { "type": "tool_use", "id": tid } ] } }


def _tool_result( tid, ts=None ):
    return { "timestamp": ts, "message": { "content": [ { "type": "tool_result", "tool_use_id": tid } ] } }


def _session( sid="sess-1", persona="Rio", tmux="cc-author-rio-1", transcript="/t/sess-1.jsonl" ):
    return { "session_id": sid, "persona": persona, "tmux_session": tmux, "transcript_path": transcript }


# ── find_dangling_tool_use ───────────────────────────────────────────────────

class TestFindDanglingToolUse:

    def test_empty_transcript_returns_none( self ):
        assert find_dangling_tool_use( [ ] ) is None

    def test_no_tool_use_returns_none( self ):
        entries = [ { "timestamp": "t", "message": { "content": [ { "type": "text", "text": "hi" } ] } } ]
        assert find_dangling_tool_use( entries ) is None

    def test_last_tool_use_with_result_returns_none( self ):
        entries = [ _tool_use( "toolu_A", "t0" ), _tool_result( "toolu_A", "t1" ) ]
        assert find_dangling_tool_use( entries ) is None

    def test_last_tool_use_without_result_is_dangling( self ):
        entries = [ _tool_use( "toolu_A", "t0" ), _tool_result( "toolu_A", "t1" ),
                    _tool_use( "toolu_B", "t2" ) ]
        assert find_dangling_tool_use( entries ) == ( "toolu_B", "t2" )

    def test_earlier_dangling_but_last_resulted_returns_none( self ):
        # Conservative bias: keying on the FINAL tool_use avoids a false positive
        # when an earlier un-resulted tool_use precedes a later resulted one.
        entries = [ _tool_use( "toolu_A", "t0" ), _tool_use( "toolu_B", "t1" ),
                    _tool_result( "toolu_B", "t2" ) ]
        assert find_dangling_tool_use( entries ) is None

    def test_malformed_entries_are_skipped( self ):
        entries = [ "not-a-dict", 42, None,
                    { "message": "not-a-dict" },
                    { "message": { "content": "not-a-list" } },
                    { "message": { "content": [ "not-a-dict-block", { "type": "tool_use" } ] } },  # block w/o id
                    _tool_use( "toolu_Z", "t9" ) ]
        assert find_dangling_tool_use( entries ) == ( "toolu_Z", "t9" )

    def test_tool_result_without_id_ignored( self ):
        entries = [ _tool_use( "toolu_A", "t0" ),
                    { "timestamp": "t1", "message": { "content": [ { "type": "tool_result" } ] } } ]
        assert find_dangling_tool_use( entries ) == ( "toolu_A", "t0" )

    def test_tool_use_without_id_does_not_become_last( self ):
        entries = [ _tool_use( "toolu_A", "t0" ),
                    { "timestamp": "t1", "message": { "content": [ { "type": "tool_use" } ] } } ]
        # the id-less block must not overwrite the real last tool_use
        assert find_dangling_tool_use( entries ) == ( "toolu_A", "t0" )


# ── age_seconds ──────────────────────────────────────────────────────────────

class TestAgeSeconds:

    def test_z_suffix_parsed( self ):
        assert age_seconds( "2026-07-03T02:59:00Z", NOW ) == 60.0

    def test_explicit_offset_parsed( self ):
        # 02:59:00-00:00 == 02:59:00Z → 60s before NOW
        assert age_seconds( "2026-07-03T02:59:00+00:00", NOW ) == 60.0

    def test_naive_timestamp_coerced_to_utc( self ):
        assert age_seconds( "2026-07-03T02:58:00", NOW ) == 120.0

    def test_none_returns_none( self ):
        assert age_seconds( None, NOW ) is None

    def test_non_string_returns_none( self ):
        assert age_seconds( 12345, NOW ) is None

    def test_empty_string_returns_none( self ):
        assert age_seconds( "", NOW ) is None

    def test_unparseable_returns_none( self ):
        assert age_seconds( "not-a-timestamp", NOW ) is None


# ── sweep_once: disabled ─────────────────────────────────────────────────────

class TestSweepDisabled:

    def test_disabled_is_noop_no_io( self ):
        def _boom_lister():
            raise AssertionError( "must not touch IO when disabled" )
        wd = TurnAgeWatchdog(
            FakeConfig( { "arbiter turn age watchdog enabled": False } ),
            session_lister_fn=_boom_lister,
        )
        assert wd.sweep_once() == { "enabled": False, "advised": 0, "candidates": 0 }


# ── sweep_once: detection + flood-guard ──────────────────────────────────────

class TestSweepDetection:

    def _make( self, entries, *, threshold=600, pane_active=False, sessions=None, now=NOW ):
        advisories = [ ]
        transcripts = { "/t/sess-1.jsonl": entries }
        wd = TurnAgeWatchdog(
            _enabled_config( threshold=threshold ),
            session_lister_fn    = ( lambda: sessions if sessions is not None else [ _session() ] ),
            transcript_reader_fn = ( lambda path: transcripts.get( path, [ ] ) ),
            pane_active_fn       = ( lambda tmux: pane_active ),
            advisory_fn          = advisories.append,
            now_fn               = ( lambda: now ),
        )
        return wd, advisories

    def _aged_dangling( self ):
        # last tool_use 700s before NOW, no result → dangling + aged (> 600 threshold)
        old = ( NOW - timedelta( seconds=700 ) ).isoformat()
        return [ _tool_use( "toolu_HELD", old ) ]

    def test_aged_dangling_pane_idle_advises_once( self ):
        wd, advisories = self._make( self._aged_dangling() )
        summary = wd.sweep_once()
        assert summary == { "enabled": True, "advised": 1, "candidates": 1 }
        assert len( advisories ) == 1
        assert "HELD TURN" in advisories[ 0 ] and "toolu_HELD" in advisories[ 0 ]

    def test_not_aged_is_not_a_candidate( self ):
        recent = ( NOW - timedelta( seconds=120 ) ).isoformat()   # under 600 threshold
        wd, advisories = self._make( [ _tool_use( "toolu_RECENT", recent ) ] )
        assert wd.sweep_once() == { "enabled": True, "advised": 0, "candidates": 0 }
        assert advisories == [ ]

    def test_un_ageable_timestamp_skipped( self ):
        wd, advisories = self._make( [ _tool_use( "toolu_X", None ) ] )
        assert wd.sweep_once() == { "enabled": True, "advised": 0, "candidates": 0 }
        assert advisories == [ ]

    def test_no_dangling_skipped( self ):
        old = ( NOW - timedelta( seconds=700 ) ).isoformat()
        wd, advisories = self._make( [ _tool_use( "toolu_A", old ), _tool_result( "toolu_A", old ) ] )
        assert wd.sweep_once() == { "enabled": True, "advised": 0, "candidates": 0 }

    def test_pane_active_suppresses_advisory_but_holds_marker( self ):
        wd, advisories = self._make( self._aged_dangling(), pane_active=True )
        summary = wd.sweep_once()
        assert summary == { "enabled": True, "advised": 0, "candidates": 0 }
        assert advisories == [ ]
        # marker not set (not advised) but key IS live → persisted for intersect-clear
        assert wd._advised == set()

    def test_pane_active_then_quiet_advises_once( self ):
        old = ( NOW - timedelta( seconds=700 ) ).isoformat()
        entries = [ _tool_use( "toolu_HELD", old ) ]
        advisories = [ ]
        pane_state = { "active": True }
        wd = TurnAgeWatchdog(
            _enabled_config(),
            session_lister_fn    = ( lambda: [ _session() ] ),
            transcript_reader_fn = ( lambda path: entries ),
            pane_active_fn       = ( lambda tmux: pane_state[ "active" ] ),
            advisory_fn          = advisories.append,
            now_fn               = ( lambda: NOW ),
        )
        assert wd.sweep_once()[ "advised" ] == 0          # streaming → suppressed
        pane_state[ "active" ] = False
        assert wd.sweep_once()[ "advised" ] == 1          # stream stopped → advise once
        assert wd.sweep_once()[ "advised" ] == 0          # one-shot thereafter

    def test_one_shot_no_refire_while_dangling( self ):
        wd, advisories = self._make( self._aged_dangling() )
        wd.sweep_once()
        wd.sweep_once()
        wd.sweep_once()
        assert len( advisories ) == 1                     # still dangling → never re-fires

    def test_intersect_clear_allows_new_tool_use_to_advise( self ):
        old = ( NOW - timedelta( seconds=700 ) ).isoformat()
        state = { "entries": [ _tool_use( "toolu_HELD1", old ) ] }
        advisories = [ ]
        wd = TurnAgeWatchdog(
            _enabled_config(),
            session_lister_fn    = ( lambda: [ _session() ] ),
            transcript_reader_fn = ( lambda path: state[ "entries" ] ),
            pane_active_fn       = ( lambda tmux: False ),
            advisory_fn          = advisories.append,
            now_fn               = ( lambda: NOW ),
        )
        assert wd.sweep_once()[ "advised" ] == 1
        assert wd._advised == { ( "sess-1", "toolu_HELD1" ) }
        # wedge #1 resolves → marker must clear on the intersect
        state[ "entries" ] = [ _tool_use( "toolu_HELD1", old ), _tool_result( "toolu_HELD1", old ) ]
        assert wd.sweep_once() == { "enabled": True, "advised": 0, "candidates": 0 }
        assert wd._advised == set()
        # a NEW dangling tool_use later → advises again (not suppressed by a stale marker)
        state[ "entries" ] = [ _tool_use( "toolu_HELD2", old ) ]
        assert wd.sweep_once()[ "advised" ] == 1
        assert wd._advised == { ( "sess-1", "toolu_HELD2" ) }

    def test_session_missing_fields_skipped( self ):
        sessions = [ { "session_id": None, "transcript_path": "/t/x" },
                     { "session_id": "s", "transcript_path": None },
                     _session() ]
        wd, advisories = self._make( self._aged_dangling(), sessions=sessions )
        # only the well-formed session (sess-1) is a candidate
        assert wd.sweep_once() == { "enabled": True, "advised": 1, "candidates": 1 }

    def test_reader_exception_is_swallowed_per_session( self ):
        def _boom_reader( path ):
            raise RuntimeError( "transcript read failed" )
        advisories = [ ]
        wd = TurnAgeWatchdog(
            _enabled_config(),
            session_lister_fn    = ( lambda: [ _session() ] ),
            transcript_reader_fn = _boom_reader,
            pane_active_fn       = ( lambda tmux: False ),
            advisory_fn          = advisories.append,
            now_fn               = ( lambda: NOW ),
        )
        # a reader blow-up on the one session is demoted to a skip; sweep survives
        assert wd.sweep_once() == { "enabled": True, "advised": 0, "candidates": 0 }
        assert advisories == [ ]


# ── advisory composition ─────────────────────────────────────────────────────

class TestAdvisoryComposition:

    def test_advisory_names_persona_or_unknown( self ):
        old = ( NOW - timedelta( seconds=700 ) ).isoformat()
        advisories = [ ]
        wd = TurnAgeWatchdog(
            _enabled_config(),
            session_lister_fn    = ( lambda: [ _session( persona=None ) ] ),
            transcript_reader_fn = ( lambda path: [ _tool_use( "toolu_HELD", old ) ] ),
            pane_active_fn       = ( lambda tmux: False ),
            advisory_fn          = advisories.append,
            now_fn               = ( lambda: NOW ),
        )
        wd.sweep_once()
        assert "persona unknown" in advisories[ 0 ]
        assert "25c7441c" in advisories[ 0 ]              # cites the founding incident

    def test_default_advisory_signal_is_callable( self ):
        # the default sink (not pragma'd) — exercise its banner path
        wd = TurnAgeWatchdog( _enabled_config() )
        wd._default_advisory_signal( "test advisory message" )   # prints a banner, no raise
        assert ADVISORY_ACTOR == "turn-age-watchdog"


# ── default wiring (cover the else-branches without touching pragma'd IO) ─────

class TestDefaultWiring:

    def test_defaults_are_wired_when_seams_omitted( self ):
        wd = TurnAgeWatchdog( _enabled_config() )
        assert wd._session_lister_fn    == wd._default_session_lister
        assert wd._transcript_reader_fn == wd._default_transcript_reader
        assert wd._pane_active_fn       == wd._default_pane_active
        assert wd._advisory_fn          == wd._default_advisory_signal
        assert wd._now_fn() .tzinfo is not None           # default clock is tz-aware


# ── daemon lifecycle ─────────────────────────────────────────────────────────

class TestDaemonLifecycle:

    def test_start_refuses_when_disabled( self ):
        wd = TurnAgeWatchdog( FakeConfig( { "arbiter turn age watchdog enabled": False } ) )
        assert wd.start() is False
        assert wd._thread is None

    def test_start_then_stop( self ):
        wd = TurnAgeWatchdog( _enabled_config( tick=0.05 ), session_lister_fn=( lambda: [ ] ) )
        assert wd.start() is True
        assert wd._thread is not None and wd._thread.is_alive()
        assert wd.start() is False                        # already running → no second thread
        wd.stop()
        assert not wd._thread.is_alive()

    def test_stop_idempotent_without_start( self ):
        wd = TurnAgeWatchdog( _enabled_config() )
        wd.stop()                                         # never started — must not raise
        assert wd._thread is None

    def test_loop_runs_sweep_then_exits_on_stop( self ):
        wd = TurnAgeWatchdog( _enabled_config( tick=0.01 ) )
        calls = [ ]
        def _sweep():
            calls.append( 1 )
            wd._stop_event.set()                          # exit after one pass
            return { "enabled": True, "advised": 0, "candidates": 0 }
        wd.sweep_once = _sweep
        wd._stop_event.clear()
        wd._loop()
        assert calls == [ 1 ]

    def test_loop_swallows_sweep_exception( self ):
        wd = TurnAgeWatchdog( _enabled_config( tick=0.01 ) )
        calls = [ ]
        def _boom():
            calls.append( 1 )
            wd._stop_event.set()
            raise RuntimeError( "sweep blew up" )
        wd.sweep_once = _boom
        wd._stop_event.clear()
        wd._loop()                                        # exception caught, loop exits cleanly
        assert calls == [ 1 ]
