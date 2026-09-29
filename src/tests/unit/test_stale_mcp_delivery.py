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
    def get( self, key, default=None, return_type=None ):
        return True if key == "arbiter self respin observer enabled" else default


def _rec( pid=4242, start=1000.5, session="cc-worker-mrradio-3", stale=True ):
    return { "pid": pid, "start_epoch": start, "tmux_session": session, "tmux_pane": "%7", "stale": stale }


class _Rig:
    """One loop with every seam faked; `stale` is the list the check returns each tick."""
    def __init__( self, tmp_path, stale, lookup=lambda r: ( "Sam", "Mr. Radio" ), dm_outcome="dispatched", dm=True ):
        self.stale, self.dms, self.advisories, self.logs = stale, [], [], []
        def dm_push( recipient, thread_id, body ):
            self.dms.append( ( recipient, thread_id, body ) )
            return { "channel": "dm_push", "outcome": dm_outcome }
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


def test_a_dm_that_did_not_dispatch_is_retried_next_tick( tmp_path ):
    rig = _Rig( tmp_path, [ _rec() ], dm_outcome="push_unavailable" )
    assert rig.loop.tell_stale_mcp_once() == 0
    assert rig.loop.tell_stale_mcp_once() == 0 and len( rig.dms ) == 2   # tried again, not marked told
    assert rig.advisories == []


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
