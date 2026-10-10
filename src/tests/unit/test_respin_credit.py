#!/usr/bin/env python3
"""
Tests for the one-for-one re-spin credit under skeleton crew.

With skeleton crew on, no spawn is allowed. The operator ruled that a re-spin, one seat
reaped and the same persona coming straight back, is allowed. The credit is how the spawn
path knows a spawn is that case.

Dismissing a seat with its persona named in the re-spin list writes one credit, keyed by the
manager and the persona. The credit lives fifteen minutes. The launcher spends it atomically,
so exactly one spawn uses each credit.

A spawn with no credit, a spent credit, an expired credit or another manager's credit is
refused. With skeleton crew off nothing changes.

Every test writes to tmp_path. The live sessions folder is never touched.
"""
import datetime
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import fleet_cap_admission as fca
from lupin_mcp import fleet_size_cap as fsc
from lupin_mcp import respin_credit as rc
from lupin_mcp import session_spawner as ss
from lupin_mcp import skeleton_crew as sc


NOW         = datetime.datetime( 2026, 10, 10, 17, 0, 0, tzinfo=datetime.timezone.utc )
SPAWN_TEXT  = sc.refusal_text( "spawn" )
LAUNCH_TEXT = sc.refusal_text( "launch" )


@pytest.fixture
def folder( tmp_path, monkeypatch ):
    target = tmp_path / "credits"
    monkeypatch.setenv( rc.CREDIT_DIR_ENV, str( target ) )
    return target


class _Config:
    def __init__( self, on ):
        self._on = on

    def get( self, key, default=None, return_type=None, silent=False ):
        values = { fsc.FLEET_CAP_KEY: 15, fsc.FLEET_CEILING_KEY: 18, sc.SKELETON_CREW_KEY: self._on }
        return values.get( key, default )


# ── the credit itself ────────────────────────────────────────────────────────

def test_mint_writes_one_credit_per_persona_and_names_who_and_when( folder ):
    assert rc.mint( "mgr-1", [ "tiffany", "cheech" ], now=NOW ) == [ "tiffany", "cheech" ]
    record = json.loads( ( folder / "mgr-1.tiffany.json" ).read_text( encoding="utf-8" ) )
    assert record[ "manager_session_id" ] == "mgr-1"
    assert record[ "persona_slug" ]       == "tiffany"
    assert record[ "minted_ts" ]          == NOW.timestamp()
    assert sorted( os.listdir( folder ) ) == [ "mgr-1.cheech.json", "mgr-1.tiffany.json" ]


def test_a_fresh_credit_is_found_for_its_manager_and_persona( folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=NOW )
    assert rc.find( "mgr-1", "tiffany", now=NOW + datetime.timedelta( seconds=60 ) ) is not None


def test_no_credit_is_not_found( folder ):
    assert rc.find( "mgr-1", "tiffany", now=NOW ) is None
    assert rc.spend( "mgr-1", "tiffany", now=NOW ) is False


def test_another_managers_credit_is_not_found_or_spent( folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=NOW )
    assert rc.find( "mgr-2", "tiffany", now=NOW ) is None
    assert rc.spend( "mgr-2", "tiffany", now=NOW ) is False
    assert rc.find( "mgr-1", "tiffany", now=NOW ) is not None


def test_another_personas_credit_is_not_found( folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=NOW )
    assert rc.find( "mgr-1", "cheech", now=NOW ) is None


def test_an_expired_credit_is_not_found_or_spent( folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=NOW )
    late = NOW + datetime.timedelta( seconds=rc.CREDIT_TTL_SECONDS + 1 )
    assert rc.find( "mgr-1", "tiffany", now=late ) is None
    assert rc.spend( "mgr-1", "tiffany", now=late ) is False


def test_the_credit_lives_exactly_fifteen_minutes():
    assert rc.CREDIT_TTL_SECONDS == 900


def test_a_credit_is_spent_once( folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=NOW )
    assert rc.spend( "mgr-1", "tiffany", now=NOW ) is True
    assert rc.spend( "mgr-1", "tiffany", now=NOW ) is False
    assert rc.find( "mgr-1", "tiffany", now=NOW ) is None


def test_two_launches_cannot_share_one_credit( folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=NOW )
    gate    = threading.Barrier( 8 )
    results = []
    def launch():
        gate.wait()
        results.append( rc.spend( "mgr-1", "tiffany", now=NOW ) )
    workers = [ threading.Thread( target=launch ) for _ in range( 8 ) ]
    for worker in workers: worker.start()
    for worker in workers: worker.join( timeout=10 )
    assert results.count( True ) == 1
    assert results.count( False ) == 7


def test_a_garbled_credit_file_is_not_a_credit( folder ):
    folder.mkdir( parents=True )
    ( folder / "mgr-1.tiffany.json" ).write_text( "{not json", encoding="utf-8" )
    assert rc.find( "mgr-1", "tiffany", now=NOW ) is None
    assert rc.spend( "mgr-1", "tiffany", now=NOW ) is False


def test_a_name_that_could_climb_out_of_the_folder_is_refused( folder ):
    assert rc.mint( "../mgr", [ "tiffany" ], now=NOW ) == []
    assert rc.mint( "mgr-1", [ "../x" ], now=NOW ) == []
    assert rc.find( "../mgr", "tiffany", now=NOW ) is None
    assert rc.spend( "mgr-1", "a/b", now=NOW ) is False
    assert not folder.exists() or os.listdir( folder ) == []


def test_the_default_folder_is_beside_the_launch_reservations( monkeypatch ):
    monkeypatch.delenv( rc.CREDIT_DIR_ENV, raising=False )
    assert Path( rc.credit_dir() ).parent == fca.reservation_dir()


# ── what counts as a re-spin ─────────────────────────────────────────────────

@pytest.mark.parametrize( "preference, seed, count, expected", [
    ( "Tiffany",            "/m.md", 1, "tiffany" ),
    ( [ "Tiffany" ],        "/m.md", 1, "tiffany" ),
    ( '["Tiffany"]',        "/m.md", 1, "tiffany" ),
    ( "Mr. Radio",          "/m.md", 1, "mr-radio" ),
    ( "Tiffany",            None,    1, None ),
    ( "Tiffany",            "",      1, None ),
    ( "Tiffany",            "/m.md", 2, None ),
    ( "*",                  "/m.md", 1, None ),
    ( [ "Tiffany", "*" ],   "/m.md", 1, None ),
    ( [ "Tiffany", "Rio" ], "/m.md", 1, None ),
    ( None,                 "/m.md", 1, None ),
    ( "   ",                "/m.md", 1, None ),
] )
def test_only_one_named_persona_with_a_memento_and_one_child_is_a_re_spin( preference, seed, count, expected ):
    assert rc.respin_slug( preference, seed, count ) == expected


def test_the_launcher_value_round_trips():
    value = rc.env_value( "mgr-1", "tiffany" )
    assert rc.parse_env_value( value ) == ( "mgr-1", "tiffany" )


@pytest.mark.parametrize( "garbage", [ None, "", "no-colon", ":x", "x:", "a:b:c" ] )
def test_a_malformed_launcher_value_is_nothing( garbage ):
    assert rc.parse_env_value( garbage ) is None


# ── the early gate ───────────────────────────────────────────────────────────

def test_the_early_gate_lets_a_credited_re_spin_through_with_the_switch_on():
    refusal = ss.default_fleet_gate( 1, config_fn=lambda: _Config( True ), census_fn=lambda: [],
                                     respin_credit_fn=lambda: True )
    assert refusal is None


def test_the_early_gate_refuses_without_a_credit_with_the_switch_on():
    refusal = ss.default_fleet_gate( 1, config_fn=lambda: _Config( True ), census_fn=lambda: [],
                                     respin_credit_fn=lambda: False )
    assert refusal == SPAWN_TEXT


def test_the_credit_still_meets_the_cap():
    sessions = [ ( f"/tmp/b{i}.json", f"s{i}", f"p{i}" ) for i in range( 15 ) ]
    refusal  = ss.default_fleet_gate( 1, config_fn=lambda: _Config( True ), census_fn=lambda: sessions,
                                      respin_credit_fn=lambda: True )
    assert refusal is not None and "FLEET CAP REFUSED" in refusal


def test_with_the_switch_off_the_credit_is_not_asked_for():
    asked = []
    refusal = ss.default_fleet_gate( 1, config_fn=lambda: _Config( False ), census_fn=lambda: [],
                                     respin_credit_fn=lambda: asked.append( 1 ) or True )
    assert refusal is None
    assert asked == []


def test_a_credit_check_that_raises_means_no_credit():
    def boom():
        raise OSError( "cannot read" )
    refusal = ss.default_fleet_gate( 1, config_fn=lambda: _Config( True ), census_fn=lambda: [],
                                     respin_credit_fn=boom )
    assert refusal == SPAWN_TEXT


# ── the spawn tool end to end ────────────────────────────────────────────────

def _spawn( tmp_path, *, on, preference="Tiffany", seed="/m.md", count=1, manager="mgr-1" ):
    started = []
    def runner( argv, env=None ):
        started.append( env )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )
    result = ss.spawn_sessions(
        count, "brief", manager, script_path="/nonexistent", runner=runner, session_dir=tmp_path,
        persona_preference=preference, seed_memento=seed, spawn_cap=8,
        fleet_config_fn=lambda: _Config( on ), fleet_census_fn=lambda: [] )
    return result, started


def test_a_credited_re_spin_spawns_and_hands_the_credit_to_the_launcher( tmp_path, folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=datetime.datetime.now( datetime.timezone.utc ) )
    result, started = _spawn( tmp_path, on=True )
    assert len( started ) == 1
    assert started[ 0 ][ rc.CREDIT_ENV ] == "mgr-1:tiffany"


def test_a_re_spin_without_a_credit_is_refused_and_starts_nothing( tmp_path, folder ):
    with pytest.raises( ValueError ) as raised:
        _spawn( tmp_path, on=True )
    assert str( raised.value ) == SPAWN_TEXT


def test_another_managers_credit_does_not_help( tmp_path, folder ):
    rc.mint( "mgr-2", [ "tiffany" ], now=datetime.datetime.now( datetime.timezone.utc ) )
    with pytest.raises( ValueError ):
        _spawn( tmp_path, on=True )


def test_an_expired_credit_does_not_help( tmp_path, folder ):
    old = datetime.datetime.now( datetime.timezone.utc ) - datetime.timedelta( seconds=rc.CREDIT_TTL_SECONDS + 5 )
    rc.mint( "mgr-1", [ "tiffany" ], now=old )
    with pytest.raises( ValueError ):
        _spawn( tmp_path, on=True )


def test_a_spent_credit_does_not_help( tmp_path, folder ):
    now = datetime.datetime.now( datetime.timezone.utc )
    rc.mint( "mgr-1", [ "tiffany" ], now=now )
    assert rc.spend( "mgr-1", "tiffany", now=now ) is True
    with pytest.raises( ValueError ):
        _spawn( tmp_path, on=True )


def test_a_credit_for_one_persona_does_not_cover_a_batch_of_two( tmp_path, folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=datetime.datetime.now( datetime.timezone.utc ) )
    with pytest.raises( ValueError ):
        _spawn( tmp_path, on=True, count=2 )


def test_with_the_switch_off_a_plain_spawn_is_unchanged_and_carries_no_credit( tmp_path, folder ):
    result, started = _spawn( tmp_path, on=False, preference=None, seed=None )
    assert len( started ) == 1
    assert rc.CREDIT_ENV not in started[ 0 ]


def test_a_re_spin_with_the_switch_off_carries_no_credit_and_spends_nothing( tmp_path, folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=datetime.datetime.now( datetime.timezone.utc ) )
    result, started = _spawn( tmp_path, on=False )
    assert len( started ) == 1
    assert rc.find( "mgr-1", "tiffany" ) is not None


# ── the launcher ─────────────────────────────────────────────────────────────

class _Capture:
    def __init__( self ): self.text = ""
    def write( self, chunk ): self.text += chunk


def _main( environ, spend, skeleton=lambda: LAUNCH_TEXT ):
    err   = _Capture()
    calls = []
    code  = fca.main(
        [ "--session-name", "cc-a", "--headless" ],
        admit_fn        = lambda name, **kw: calls.append( name ) or { "admitted": True },
        dir_fn          = lambda: "/tmp",
        stderr          = err,
        skeleton_fn     = skeleton,
        stdin_is_tty_fn = lambda: False,
        environ         = environ,
        credit_spend_fn = spend )
    return code, err.text, calls


def test_the_launcher_spends_the_credit_and_lets_the_re_spin_launch():
    spent = []
    code, err, calls = _main( { rc.CREDIT_ENV: "mgr-1:tiffany" }, lambda m, s: spent.append( ( m, s ) ) or True )
    assert code == fca.EXIT_ADMITTED
    assert spent == [ ( "mgr-1", "tiffany" ) ]
    assert calls == [ "cc-a" ]


def test_the_launcher_refuses_when_the_credit_cannot_be_spent():
    code, err, calls = _main( { rc.CREDIT_ENV: "mgr-1:tiffany" }, lambda m, s: False )
    assert code == fca.EXIT_REFUSED
    assert LAUNCH_TEXT in err
    assert calls == []


def test_the_launcher_refuses_without_a_credit_and_never_tries_to_spend():
    spent = []
    code, err, calls = _main( {}, lambda m, s: spent.append( 1 ) or True )
    assert code == fca.EXIT_REFUSED
    assert spent == []


def test_the_launcher_refuses_a_malformed_credit_value():
    code, err, calls = _main( { rc.CREDIT_ENV: "garbage" }, lambda m, s: True )
    assert code == fca.EXIT_REFUSED


def test_the_launcher_does_not_touch_the_credit_when_the_switch_is_off():
    spent = []
    code, err, calls = _main( { rc.CREDIT_ENV: "mgr-1:tiffany" }, lambda m, s: spent.append( 1 ) or True,
                              skeleton=lambda: None )
    assert code == fca.EXIT_ADMITTED
    assert spent == []


def test_a_credit_spend_that_raises_refuses_the_launch():
    def boom( manager, slug ):
        raise OSError( "folder gone" )
    code, err, calls = _main( { rc.CREDIT_ENV: "mgr-1:tiffany" }, boom )
    assert code == fca.EXIT_REFUSED


def test_the_default_launcher_spend_uses_the_real_credit_folder( folder ):
    rc.mint( "mgr-1", [ "tiffany" ], now=datetime.datetime.now( datetime.timezone.utc ) )
    err  = _Capture()
    code = fca.main( [ "--session-name", "cc-a", "--headless" ],
                     admit_fn=lambda name, **kw: { "admitted": True }, dir_fn=lambda: "/tmp", stderr=err,
                     skeleton_fn=lambda: LAUNCH_TEXT, stdin_is_tty_fn=lambda: False,
                     environ={ rc.CREDIT_ENV: "mgr-1:tiffany" } )
    assert code == fca.EXIT_ADMITTED
    assert rc.find( "mgr-1", "tiffany" ) is None


# ── dismissal writes the credit ──────────────────────────────────────────────

_OK_RUNNER = lambda argv, env=None: SimpleNamespace( returncode=0 )


def _reap( tmp_path, respin ):
    sd  = Path( tmp_path )
    mgr = "mgr-abc12345"
    ss._write_manifest( ss._manifest_path( mgr, sd ), [ { "session_name": "cc-author-x-1", "session_id": "sid-1" } ] )
    ( sd / "cc-99999.json" ).write_text( json.dumps( {
        "tmux_session"      : "cc-author-x-1",
        "stable_session_id" : "abcd1234-aaaa-bbbb",
        "voice_persona"     : { "name": "Tiffany", "icon": "💍", "color": "#FFD600" },
    } ) )
    result = ss.dismiss_sessions(
        mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
        emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
        clear_hold_fn=lambda i: True, respin_personas=respin )
    return mgr, result


def test_dismissing_a_re_spin_persona_writes_its_credit( tmp_path, folder ):
    mgr, result = _reap( tmp_path, [ "Tiffany" ] )
    assert result[ "respin_credits_minted" ] == [ "tiffany" ]
    assert rc.find( mgr, "tiffany" ) is not None


def test_dismissing_without_a_re_spin_list_writes_no_credit( tmp_path, folder ):
    mgr, result = _reap( tmp_path, None )
    assert result[ "respin_credits_minted" ] == []
    assert rc.find( mgr, "tiffany" ) is None


def test_a_name_that_matched_no_reaped_persona_writes_no_credit( tmp_path, folder ):
    mgr, result = _reap( tmp_path, [ "Nobody" ] )
    assert result[ "respin_credits_minted" ] == []


def test_a_credit_folder_that_cannot_be_written_never_breaks_the_reap( tmp_path, monkeypatch ):
    blocker = tmp_path / "file"
    blocker.write_text( "x", encoding="utf-8" )
    monkeypatch.setenv( rc.CREDIT_DIR_ENV, str( blocker / "inside" ) )
    mgr, result = _reap( tmp_path, [ "Tiffany" ] )
    assert result[ "bridges_deleted" ] == 1
    assert result[ "respin_credits_minted" ] == []


# ── a credit with a minted time that cannot be trusted never lives ───────────

def _plant( folder, minted ):
    folder.mkdir( parents=True, exist_ok=True )
    ( folder / "mgr-1.tiffany.json" ).write_text(
        json.dumps( { "manager_session_id": "mgr-1", "persona_slug": "tiffany", "minted_ts": minted } ),
        encoding="utf-8" )


@pytest.mark.parametrize( "minted", [
    "abc", None, True, [ 1 ], { "t": 1 }, float( "nan" ), float( "inf" ), float( "-inf" ),
    NOW.timestamp() + 60, NOW.timestamp() + 10 ** 9,
] )
def test_a_minted_time_that_is_not_a_past_number_is_expired_and_unspendable( folder, minted ):
    _plant( folder, minted )
    assert rc.find( "mgr-1", "tiffany", now=NOW ) is None
    assert rc.spend( "mgr-1", "tiffany", now=NOW ) is False
    assert ( folder / "mgr-1.tiffany.json" ).exists()


def test_a_credit_minted_this_instant_is_still_good( folder ):
    _plant( folder, NOW.timestamp() )
    assert rc.find( "mgr-1", "tiffany", now=NOW ) is not None


# ── a credit is minted only for a seat this dismissal actually killed ────────

def _reap_with( tmp_path, runner, respin ):
    sd  = Path( tmp_path )
    mgr = "mgr-abc12345"
    ss._write_manifest( ss._manifest_path( mgr, sd ), [ { "session_name": "cc-author-x-1", "session_id": "sid-1" } ] )
    ( sd / "cc-99999.json" ).write_text( json.dumps( {
        "tmux_session"      : "cc-author-x-1",
        "stable_session_id" : "abcd1234-aaaa-bbbb",
        "voice_persona"     : { "name": "Tiffany", "icon": "💍", "color": "#FFD600" },
    } ) )
    result = ss.dismiss_sessions(
        mgr, session_names=[ "cc-author-x-1" ], runner=runner, session_dir=sd,
        emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
        clear_hold_fn=lambda i: True, respin_personas=respin )
    return mgr, result


def test_a_seat_that_was_already_gone_earns_no_credit( tmp_path, folder ):
    gone = lambda argv, env=None: SimpleNamespace( returncode=1 )
    mgr, result = _reap_with( tmp_path, gone, [ "Tiffany" ] )
    assert result[ "dismissed" ][ 0 ][ "status" ] == "already_gone"
    assert result[ "respin_credits_minted" ] == []
    assert rc.find( mgr, "tiffany" ) is None


def test_a_seat_this_dismissal_killed_earns_its_credit( tmp_path, folder ):
    killed = lambda argv, env=None: SimpleNamespace( returncode=0 )
    mgr, result = _reap_with( tmp_path, killed, [ "Tiffany" ] )
    assert result[ "dismissed" ][ 0 ][ "status" ] == "killed"
    assert result[ "respin_credits_minted" ] == [ "tiffany" ]
    assert rc.find( mgr, "tiffany" ) is not None


def test_an_already_gone_seat_still_keeps_its_rows_through_a_re_spin( tmp_path, folder ):
    gone = lambda argv, env=None: SimpleNamespace( returncode=1 )
    mgr, result = _reap_with( tmp_path, gone, [ "Tiffany" ] )
    assert result[ "retained_owner_personas" ] == [ "tiffany" ]
