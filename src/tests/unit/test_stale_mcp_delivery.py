"""
Row 97c5bd94 — the stale-MCP check is RUN by the observer tick and its finding is DELIVERED.

Before this row, `src/scripts/stale_mcp_check.py` was a manual instrument: nothing ran it and
nothing read its output, so a seat running old MCP code was discovered by accident. These cases
pin the reader: one message per stale process, to that seat's manager, naming the seat and the
remedy; never repeated for the same process; silent when nothing is stale.

THE CASE THAT FAILS AGAINST TODAY'S SWEEP is
`test_the_observer_sweep_tells_the_manager_of_a_stale_seat`: it drives `sweep_once`, the
existing sweep, with a stale process in the check's own JSON shape and asserts a DM reaches the
manager. Today's sweep never runs the check, so no DM is sent.

Each dedup arm has a paired positive: "not told twice" is only meaningful next to a run where
the first tell DID happen, and "quiet" only next to a run where a stale process DID speak.
"""
import json

import pytest

import cosa.agents.heartbeat_arbiter.self_respin_observer as obs


class _Cfg:
    """Observer flag ON unless overridden; every other key answers the caller's default."""
    def __init__( self, **overrides ):
        self._o = { "arbiter self respin observer enabled": True, **overrides }
    def get( self, key, default=None, return_type=None ):
        return self._o.get( key, default )


def _rec( pid=4242, start=1000.5, session="cc-worker-mrradio-3", stale=True ):
    return { "pid": pid, "start_epoch": start, "tmux_session": session, "tmux_pane": "%7", "stale": stale }


class _Rig:
    """One loop with every seam faked; `stale` is the list the check returns each tick."""
    def __init__( self, tmp_path, stale, lookup=lambda r: ( "Sam", "Mr. Radio" ), dm_outcome="dispatched", dm=True ):
        self.stale, self.dms, self.advisories, self.logs = stale, [], [], []
        def dm_push( recipient, thread_id, body ):
            self.dms.append( ( recipient, thread_id, body ) )
            out = { "channel": "dm_push", "outcome": dm_outcome }
            if dm_outcome != "dispatched": out.update( http_status=422, detail="{'detail': 'sender_project is REQUIRED'}" )
            return out
        self.loop = obs.SelfRespinObserverLoop(
            _Cfg(), fetch_pressure_fn=lambda: { "personas": None }, base_dir=str( tmp_path ),
            advisory_fn=self.advisories.append,
            stale_mcp_fn=lambda: self.stale, dm_push_fn=dm_push if dm else None,
            seat_lookup_fn=lookup )
        self.loop._log_skip = self.logs.append


def test_the_observer_sweep_tells_the_manager_of_a_stale_seat( tmp_path ):
    """Drives the EXISTING sweep_once through the real run_stale_mcp_check parser."""
    report = json.dumps( { "processes": [ _rec(), _rec( pid=9, session="fresh", stale=False ) ], "stale_count": 1 } )
    dms    = []
    loop   = obs.SelfRespinObserverLoop(
        _Cfg(), fetch_pressure_fn=lambda: { "personas": None }, base_dir=str( tmp_path ),
        advisory_fn=lambda m: None,
        stale_mcp_fn=lambda: obs.run_stale_mcp_check( runner=lambda argv, t: ( 1, report ), script_path="/x.py" ),
        dm_push_fn=lambda to, thread, body: dms.append( ( to, thread, body ) ) or { "outcome": "dispatched" },
        seat_lookup_fn=lambda r: ( "Sam", "Mr. Radio" ) )
    summary = loop.sweep_once()
    assert summary[ "stale_mcp_told" ] == 1
    assert len( dms ) == 1                                       # the fresh process was not told
    to, thread, body = dms[ 0 ]
    assert to == "Mr. Radio" and thread == "stale-mcp-4242"
    assert "Sam" in body and "4242" in body
    assert "restart the seat; a /clear doesn't reload the MCP" in body


def test_a_process_is_told_once_and_a_new_process_is_told_again( tmp_path ):
    rig = _Rig( tmp_path, [ _rec() ] )
    assert rig.loop.tell_stale_mcp_once() == 1                   # positive: the first tick DID tell
    assert rig.loop.tell_stale_mcp_once() == 0 and len( rig.dms ) == 1
    rig.stale = [ _rec(), _rec( pid=5555, session="cc-other" ) ]
    assert rig.loop.tell_stale_mcp_once() == 1                   # only the new pid
    assert [ d[ 1 ] for d in rig.dms ] == [ "stale-mcp-4242", "stale-mcp-5555" ]


def test_a_recycled_pid_with_a_new_start_time_is_a_new_process( tmp_path ):
    rig = _Rig( tmp_path, [ _rec( start=1000.5 ) ] )
    rig.loop.tell_stale_mcp_once()
    rig.stale = [ _rec( start=2000.5 ) ]                         # same pid, different process
    assert rig.loop.tell_stale_mcp_once() == 1 and len( rig.dms ) == 2


def test_a_seat_that_was_restarted_is_forgotten_and_told_again_if_stale_again( tmp_path ):
    rig = _Rig( tmp_path, [ _rec() ] )
    rig.loop.tell_stale_mcp_once()
    rig.stale = []                                               # restarted: no longer stale
    assert rig.loop.tell_stale_mcp_once() == 0
    rig.stale = [ _rec() ]
    assert rig.loop.tell_stale_mcp_once() == 1


def test_quiet_when_nothing_is_stale( tmp_path ):
    loud = _Rig( tmp_path, [ _rec() ] )
    assert loud.loop.tell_stale_mcp_once() == 1 and loud.dms     # positive control: the rig can speak
    quiet = _Rig( tmp_path, [] )
    assert quiet.loop.tell_stale_mcp_once() == 0
    assert quiet.dms == [] and quiet.advisories == []


def test_a_dm_that_did_not_dispatch_falls_back_to_the_advisory_once_per_process( tmp_path ):
    """The bug this pins: a refused DM used to be retried silently every tick, forever, and
    nobody was ever told. Now the failure is logged with its status and body, the operator
    advisory carries the tell, and the process is not chased again."""
    rig = _Rig( tmp_path, [ _rec() ], dm_outcome="push_unavailable" )
    assert rig.loop.tell_stale_mcp_once() == 1
    assert len( rig.advisories ) == 1 and "restart the seat" in rig.advisories[ 0 ]
    assert "Mr. Radio" in rig.advisories[ 0 ] and "422" in rig.advisories[ 0 ]          # who it failed to reach, and why
    assert "sender_project is REQUIRED" in rig.advisories[ 0 ]
    assert len( rig.logs ) == 1 and "422" in rig.logs[ 0 ] and "sender_project is REQUIRED" in rig.logs[ 0 ]
    for _ in range( 3 ):                                                                # later ticks: silence
        assert rig.loop.tell_stale_mcp_once() == 0
    assert len( rig.dms ) == 1 and len( rig.advisories ) == 1 and len( rig.logs ) == 1


def test_the_failed_dm_advisory_is_per_process_not_per_batch( tmp_path ):
    rig = _Rig( tmp_path, [ _rec( pid=1 ) ], dm_outcome="push_unavailable" )
    rig.loop.tell_stale_mcp_once()
    rig.stale = [ _rec( pid=1 ), _rec( pid=2 ) ]
    assert rig.loop.tell_stale_mcp_once() == 1                                           # only the new pid
    assert len( rig.advisories ) == 2 and "pid 2" in rig.advisories[ 1 ]


def test_a_push_with_no_status_still_falls_back_and_names_the_detail( tmp_path ):
    rig = _Rig( tmp_path, [ _rec() ] )
    rig.loop._dm_push_fn = lambda r, t, b: { "outcome": "push_unavailable", "detail": "refused" }   # a raised push: no status
    assert rig.loop.tell_stale_mcp_once() == 1
    assert "refused" in rig.advisories[ 0 ] and "None" not in rig.advisories[ 0 ]


@pytest.mark.parametrize( "kwargs", [
    { "lookup": lambda r: ( "Sam", None ) },                     # manager unresolved
    { "dm": False },                                             # no DM hop wired
] )
def test_no_manager_route_goes_to_the_operator_advisory_once( tmp_path, kwargs ):
    rig = _Rig( tmp_path, [ _rec() ], **kwargs )
    assert rig.loop.tell_stale_mcp_once() == 1
    assert rig.loop.tell_stale_mcp_once() == 0
    assert rig.dms == [] and len( rig.advisories ) == 1
    assert "restart the seat" in rig.advisories[ 0 ]


def test_an_unknown_seat_is_named_unknown_not_dropped( tmp_path ):
    rig = _Rig( tmp_path, [ _rec() ], lookup=lambda r: ( None, "Mr. Radio" ) )
    rig.loop.tell_stale_mcp_once()
    assert "seat unknown" in rig.dms[ 0 ][ 2 ]


def test_a_failed_check_is_logged_and_says_nothing( tmp_path ):
    rig = _Rig( tmp_path, [] )
    def boom(): raise RuntimeError( "exit 2" )
    rig.loop._stale_mcp_fn = boom
    assert rig.loop.tell_stale_mcp_once() == 0
    assert rig.dms == [] and rig.advisories == []
    assert len( rig.logs ) == 1 and "stale-MCP check failed" in rig.logs[ 0 ]


def test_a_lookup_that_raises_skips_that_record_and_still_tells_the_others( tmp_path ):
    def lookup( rec ):
        if rec[ "pid" ] == 1: raise OSError( "bridge unreadable" )
        return ( "Sam", "Mr. Radio" )
    rig = _Rig( tmp_path, [ _rec( pid=1 ), _rec( pid=2 ) ], lookup=lookup )
    assert rig.loop.tell_stale_mcp_once() == 1
    assert [ d[ 1 ] for d in rig.dms ] == [ "stale-mcp-2" ]                     # the good record WAS told
    assert len( rig.logs ) == 1 and "record skipped" in rig.logs[ 0 ] and "bridge unreadable" in rig.logs[ 0 ]
    assert rig.loop.tell_stale_mcp_once() == 0 and len( rig.logs ) == 2         # pid 1 retried, pid 2 not re-told


def test_a_dm_that_raises_skips_that_record_and_still_tells_the_others( tmp_path ):
    rig = _Rig( tmp_path, [ _rec( pid=1 ), _rec( pid=2 ) ] )
    calls = []
    def dm( recipient, thread_id, body ):
        calls.append( thread_id )
        if thread_id == "stale-mcp-1": raise ConnectionError( "refused" )
        return { "outcome": "dispatched" }
    rig.loop._dm_push_fn = dm
    assert rig.loop.tell_stale_mcp_once() == 1
    assert calls == [ "stale-mcp-1", "stale-mcp-2" ] and "record skipped" in rig.logs[ 0 ]


def test_a_malformed_record_is_skipped_not_fatal( tmp_path ):
    rig = _Rig( tmp_path, [ { "stale": True }, _rec( pid=2 ) ] )                # the first has no pid
    assert rig.loop.tell_stale_mcp_once() == 1
    assert [ d[ 1 ] for d in rig.dms ] == [ "stale-mcp-2" ] and "record skipped" in rig.logs[ 0 ]


# --- its OWN gate: `stale mcp check delivery enabled`, independent of the observer flag ------------

OBSERVER_KEY = "arbiter self respin observer enabled"
STALE_KEY    = "stale mcp check delivery enabled"


def _gated_loop( tmp_path, cfg, dms ):
    return obs.SelfRespinObserverLoop(
        cfg, fetch_pressure_fn=lambda: { "personas": None }, base_dir=str( tmp_path ),
        advisory_fn=lambda m: dms.append( ( "advisory", m ) ),
        stale_mcp_fn=lambda: [ _rec() ],
        dm_push_fn=lambda to, thread, body: dms.append( ( to, thread, body ) ) or { "outcome": "dispatched" },
        seat_lookup_fn=lambda r: ( "Sam", "Mr. Radio" ) )


def test_it_delivers_with_the_observer_flag_off_and_fires_no_respin_advisory( tmp_path ):
    # a marker that WOULD alarm if the respin half ran (deadline long past, no pressure record)
    ( tmp_path / f"{obs.MARKER_PREFIX}cheech.json" ).write_text( json.dumps( {
        "session_id": "cheech", "persona": "cheech", "tmux_session": "cheech-mgr",
        "fired_at": "2026-08-14T02:20:00+00:00", "expected_return_by": "2026-08-14T02:22:00+00:00",
        "pre_clear_status": "over_budget", "pre_clear_pct": 51.4, "memento_path": "/x", "memento_verified": True,
        "wake_nonce": "n" } ) )
    dms  = []
    loop = _gated_loop( tmp_path, _Cfg( **{ OBSERVER_KEY: False } ), dms )         # STALE_KEY absent -> default True
    summary = loop.sweep_once()
    assert summary == { "enabled": False, "alarms": 0, "advised": 0, "swept": 0, "stale_mcp_told": 1 }
    assert [ d[ 0 ] for d in dms ] == [ "Mr. Radio" ]                              # the DM, and no respin advisory
    # positive control: the same marker DOES alarm once the observer flag is on
    dms2 = []
    assert _gated_loop( tmp_path, _Cfg(), dms2 ).sweep_once()[ "alarms" ] == 1


def test_the_stale_flag_false_stops_delivery_even_with_the_observer_on( tmp_path ):
    dms = []
    summary = _gated_loop( tmp_path, _Cfg( **{ STALE_KEY: False } ), dms ).sweep_once()
    assert "stale_mcp_told" not in summary and dms == []


def test_both_flags_off_is_the_plain_disabled_summary( tmp_path ):
    dms = []
    summary = _gated_loop( tmp_path, _Cfg( **{ OBSERVER_KEY: False, STALE_KEY: False } ), dms ).sweep_once()
    assert summary == { "enabled": False, "alarms": 0, "advised": 0, "swept": 0 } and dms == []


@pytest.mark.parametrize( "overrides, expected", [
    ( { OBSERVER_KEY: False },                   True ),      # only the stale gate is on
    ( { OBSERVER_KEY: True, STALE_KEY: False },  True ),      # only the observer gate is on
    ( { OBSERVER_KEY: False, STALE_KEY: False }, False ),     # both off: the rollout no-op
] )
def test_start_spawns_the_daemon_when_either_gate_is_on( tmp_path, overrides, expected ):
    loop = _gated_loop( tmp_path, _Cfg( **overrides ), [] )
    loop._tick_seconds = lambda: 3600
    try:
        assert loop.start() is expected
    finally:
        loop.stop()


def _assemble( monkeypatch, **flags ):
    import lupin_arbiter_app.app as app_module
    class Cfg:
        def get( self, key, default=None, return_type="string" ):
            if key in ( "arbiter health watch enabled", "arbiter context watch enabled" ): return False
            return flags.get( key, default )
    class GW:
        def post( self, *a, **k ): return None
    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", lambda: "lupin" )
    return app_module.assemble_app( Cfg(), GW(), dm_push_fn=lambda *a: {}, log_fn=lambda *a, **k: None )


def test_the_arbiter_builds_the_loop_when_only_the_stale_flag_is_on( monkeypatch ):
    app = _assemble( monkeypatch, **{ OBSERVER_KEY: False } )                        # STALE_KEY defaults True
    assert app.state.self_respin_observer_loop is not None


def test_the_arbiter_builds_no_loop_when_both_flags_are_off( monkeypatch ):
    app = _assemble( monkeypatch, **{ OBSERVER_KEY: False, STALE_KEY: False } )
    assert app.state.self_respin_observer_loop is None


def test_the_feature_is_off_when_no_check_is_wired( tmp_path ):
    loop = obs.SelfRespinObserverLoop( _Cfg(), fetch_pressure_fn=lambda: { "personas": None }, base_dir=str( tmp_path ),
                                       advisory_fn=lambda m: None )
    assert "stale_mcp_told" not in loop.sweep_once()


# --- run_stale_mcp_check: the parser owns the exit-code contract ---------------------------------

def test_exit_0_and_1_both_carry_a_report():
    body = json.dumps( { "processes": [ _rec( stale=False ), _rec( pid=1 ) ] } )
    assert obs.run_stale_mcp_check( runner=lambda a, t: ( 0, body ), script_path="/x.py" ) == [ _rec( pid=1 ) ]
    assert obs.run_stale_mcp_check( runner=lambda a, t: ( 1, body ), script_path="/x.py" ) == [ _rec( pid=1 ) ]


@pytest.mark.parametrize( "code, out", [ ( 2, "{}" ), ( 7, "{}" ), ( 0, "not json" ), ( 0, "{}" ), ( 0, "null" ) ] )
def test_untrustworthy_output_raises_rather_than_reading_as_nothing_stale( code, out ):
    with pytest.raises( RuntimeError ):
        obs.run_stale_mcp_check( runner=lambda a, t: ( code, out ), script_path="/x.py" )


def test_the_default_script_path_is_the_project_scripts_dir( monkeypatch ):
    seen = []
    monkeypatch.setenv( "LUPIN_ROOT", "/tmp/rootx" )
    obs.run_stale_mcp_check( runner=lambda argv, t: seen.append( argv ) or ( 0, '{"processes": []}' ) )
    assert seen[ 0 ][ 1 ].endswith( "/src/scripts/stale_mcp_check.py" ) and seen[ 0 ][ 2 ] == "--json"


def test_the_default_runner_shells_out_and_returns_code_and_stdout( monkeypatch ):
    import types
    monkeypatch.setattr( obs.subprocess, "run",
                         lambda argv, **kw: types.SimpleNamespace( returncode=1, stdout="out" ) )
    assert obs._run_subprocess( [ "x" ], 5 ) == ( 1, "out" )


# --- the arbiter actually wires it -----------------------------------------------------------------

def test_the_arbiter_wires_the_check_and_the_dm_hop_into_the_observer( monkeypatch ):
    import lupin_arbiter_app.app as app_module
    class Cfg:
        def get( self, key, default=None, return_type="string" ):
            if key in ( "arbiter health watch enabled", "arbiter context watch enabled" ): return False
            if key == "arbiter self respin observer enabled": return True
            return default
    class GW:
        def post( self, *a, **k ): return None
    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", lambda: "lupin" )
    dm = lambda *a: { "outcome": "dispatched" }
    app = app_module.assemble_app( Cfg(), GW(), dm_push_fn=dm, log_fn=lambda *a, **k: None )
    loop = app.state.self_respin_observer_loop
    assert loop._stale_mcp_fn is obs.run_stale_mcp_check and loop._dm_push_fn is dm
