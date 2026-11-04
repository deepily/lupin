"""
The `register_session.main()` arms and helpers no earlier unit test reached.

`$HOME` and the bridge seam point into `tmp_path`, so the real bridge directory is never touched.
The cc pid, tmux lookup, persona allocation, listener spawn, TTS and HTTP calls are stand-ins.
The sibling witness file is serial-gated, so it does not count toward the unit tier.
"""

import builtins
import importlib
import json
import os
import subprocess
import sys
import time
import types
import urllib.request

import pytest

HOOK = "lupin_cli.claude_code.hooks.register_session"
BRIDGE_MOD = "lupin_cli.claude_code.hooks.lib.session_bridge"
CC_PID = 424242

# The real helpers, captured at import so the `rs` fixture's stand-ins cannot shadow them.
_REAL = types.SimpleNamespace(
    find_tmux       = importlib.import_module( HOOK )._find_tmux_session,
    cleanup         = importlib.import_module( HOOK )._cleanup_old_listener,
    status          = importlib.import_module( HOOK )._check_cosa_voice_status,
    repo_root_owning = importlib.import_module( HOOK )._repo_root_owning,
)


@pytest.fixture
def rs( monkeypatch, tmp_path ):
    module = importlib.import_module( HOOK )
    home   = tmp_path / "home"
    seam   = tmp_path / "seam"
    ( home / ".claude" ).mkdir( parents=True )
    seam.mkdir()
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.setenv( "LUPIN_HOOK_SESSIONS_DIR", str( seam ) )
    monkeypatch.delenv( "CLAUDE_ENV_FILE", raising=False )
    monkeypatch.delenv( "COSA_VOICE_SPAWNED_BY", raising=False )
    monkeypatch.delenv( "LUPIN_APP_SERVER_URL", raising=False )

    ns = types.SimpleNamespace( module=module, seam=seam, home=home, emitted=[ ], released=[ ], cleaned=[ ],
                                bridge=seam / f"cc-{CC_PID}.json", lock=seam / f"cc-stable-{CC_PID}.id" )

    monkeypatch.setattr( module, "emit_json", ns.emitted.append )
    monkeypatch.setattr( module, "_resolve_cc_pid", lambda ppid: CC_PID )
    monkeypatch.setattr( module, "_find_tmux_session", lambda pid: None )
    monkeypatch.setattr( module, "_allocate_voice_persona_via_http", lambda *a, **k: ( None, None ) )
    monkeypatch.setattr( module, "_spawn_listener", lambda *a, **k: None )
    monkeypatch.setattr( module, "send_tts", lambda *a, **k: None )
    monkeypatch.setattr( module, "log_payload", lambda *a, **k: None )
    monkeypatch.setattr( module, "emit_context_clear_marker", lambda payload: None )
    monkeypatch.setattr( module, "_check_cosa_voice_status", lambda: "STATUS" )
    monkeypatch.setattr( module, "_build_memento_block", lambda *a, **k: "" )
    monkeypatch.setattr( module, "detect_project", lambda *a, **k: "lupin" )
    monkeypatch.setattr( module, "_cleanup_old_listener", lambda old, new: ns.cleaned.append( ( old, new ) ) )
    monkeypatch.setattr( module, "_release_voice_persona_via_http", lambda *a: ns.released.append( a ) )
    monkeypatch.setattr( f"{BRIDGE_MOD}.prune_dead_persona_bridges", lambda: 0 )
    monkeypatch.setattr( f"{BRIDGE_MOD}.set_manager_figure_implicit", lambda sid, v: True )

    def run( payload, tolerate=False ):
        monkeypatch.setattr( module, "read_hook_input", lambda: payload )
        try:
            module.main()
        except SystemExit as e:
            return e.code
        except Exception:
            if not tolerate: raise
        return None

    ns.run = run
    return ns


def _payload( **kw ):
    return { "session_id": "s1-session", "cwd": "/tmp", "transcript_path": "/x", **kw }


class TestWitnessesAndPayloadShape:

    def test_an_empty_payload_exits_zero_with_an_empty_object_and_says_why( self, rs, capsys ):
        assert rs.run( { } ) == 0
        assert rs.emitted == [ { } ]
        assert "hook payload was empty or unreadable" in capsys.readouterr().err

    def test_a_payload_without_a_session_id_still_names_its_keys_and_writes_no_bridge( self, rs, capsys ):
        rs.run( { "cwd": "/tmp", "transcript_path": "/x" } )
        assert "carried no session_id (keys: ['cwd', 'transcript_path'])" in capsys.readouterr().err
        assert not list( rs.seam.glob( "cc-*.json" ) )

    def test_a_healthy_payload_writes_the_bridge_and_emits_the_session_id_and_status( self, rs ):
        rs.run( _payload() )
        data = json.loads( rs.bridge.read_text() )
        assert ( data[ "session_id" ], data[ "stable_session_id" ], data[ "cc_pid" ] ) == ( "s1-session", "s1-session", CC_PID )
        assert rs.emitted[ 0 ][ "additionalContext" ].startswith( "Session ID: s1-session\n\nSTATUS" )

    def test_an_empty_cwd_leaves_sender_id_off_the_bridge_rather_than_guessing( self, rs ):
        rs.run( _payload( cwd="" ) )
        assert "sender_id" not in json.loads( rs.bridge.read_text() )


class TestLockfileAndDirectoryFailures:

    def test_a_directory_that_refuses_2770_warns_and_still_registers( self, rs, monkeypatch, capsys ):
        monkeypatch.setattr( os, "chmod", lambda p, m: ( _ for _ in () ).throw( OSError( "denied" ) ) )
        rs.run( _payload() )
        assert "could not set 2770" in capsys.readouterr().err
        assert rs.bridge.exists()

    def test_an_unreadable_lockfile_is_reported_and_re_anchored_on_the_new_id( self, rs, monkeypatch, capsys ):
        rs.lock.write_text( "old-stable" )
        real_open = builtins.open
        def fake_open( path, mode="r", *a, **k ):
            if str( path ) == str( rs.lock ) and mode == "r": raise PermissionError( "denied" )
            return real_open( path, mode, *a, **k )
        monkeypatch.setattr( builtins, "open", fake_open )
        rs.run( _payload() )
        monkeypatch.undo()
        assert "failed to read lockfile" in capsys.readouterr().err
        assert rs.lock.read_text() == "s1-session"
        assert json.loads( rs.bridge.read_text() )[ "stable_session_id" ] == "s1-session"

    def test_a_lockfile_that_cannot_be_created_falls_back_to_the_transient_id( self, rs, monkeypatch, capsys ):
        real_open = builtins.open
        def fake_open( path, mode="r", *a, **k ):
            if str( path ) == str( rs.lock ) and mode == "x": raise PermissionError( "no space" )
            return real_open( path, mode, *a, **k )
        monkeypatch.setattr( builtins, "open", fake_open )
        rs.run( _payload() )
        monkeypatch.undo()
        assert "failed to create lockfile" in capsys.readouterr().err
        assert not rs.lock.exists()
        assert json.loads( rs.bridge.read_text() )[ "stable_session_id" ] == "s1-session"


class TestCarryForward:

    def _seed_old( self, rs, **extra ):
        rs.lock.write_text( "stable-1" )
        rs.bridge.write_text( json.dumps( { "session_id": "old-session", "stable_session_id": "stable-1", **extra } ) )

    def test_an_empty_persona_on_the_old_bridge_is_released_over_http_for_the_stable_id( self, rs ):
        self._seed_old( rs, voice_persona={ }, idle_detection={ "backoff_index": 3, "waiter_pid": 99 } )
        rs.run( _payload( session_id="new-session" ) )
        assert len( rs.cleaned ) == 1 and rs.cleaned[ 0 ][ 1 ] == "new-session"
        assert rs.released == [ ( "http://localhost:7999", "lupin", "stable-1" ) ]
        idle = json.loads( rs.bridge.read_text() )[ "idle_detection" ]
        assert ( idle[ "backoff_index" ], idle[ "waiter_pid" ] ) == ( 3, None )

    def test_the_release_falls_back_to_lupin_when_the_project_cannot_be_detected( self, rs, monkeypatch ):
        self._seed_old( rs, voice_persona={ } )
        calls = iter( [ RuntimeError( "no git" ) ] )
        def detect( *a, **k ):
            e = next( calls, "lupin" )
            if isinstance( e, Exception ): raise e
            return e
        monkeypatch.setattr( rs.module, "detect_project", detect )
        rs.run( _payload( session_id="new-session" ) )
        assert rs.released[ 0 ][ 1 ] == "lupin"

    def test_an_old_bridge_that_is_not_a_json_object_is_replaced_not_merged( self, rs ):
        rs.bridge.write_text( "[1, 2]" )          # no lockfile, so it is read only by the merge step
        rs.run( _payload() )
        assert json.loads( rs.bridge.read_text() )[ "session_id" ] == "s1-session"


class TestEnvFileAndPurge:

    def test_session_exports_are_appended_to_the_env_file( self, rs, monkeypatch, tmp_path ):
        env_file = tmp_path / "claude.env"
        monkeypatch.setenv( "CLAUDE_ENV_FILE", str( env_file ) )
        rs.run( _payload() )
        text = env_file.read_text()
        assert "export CLAUDE_SESSION_ID='s1-session'" in text and "export CLAUDE_TRANSCRIPT_PATH='/x'" in text

    def test_an_unwritable_env_file_is_ignored( self, rs, monkeypatch, tmp_path ):
        monkeypatch.setenv( "CLAUDE_ENV_FILE", str( tmp_path / "no" / "such" / "dir" / "env" ) )
        rs.run( _payload() )
        assert rs.bridge.exists()

    def test_stale_files_are_purged_but_a_live_pids_lockfile_and_fresh_files_stay( self, rs, monkeypatch ):
        two_days = time.time() - 2 * 86400
        for name in ( "cc-old.json", "cc-stable-111.id", "cc-stable-222.id" ):
            p = rs.seam / name
            p.write_text( "x" ); os.utime( p, ( two_days, two_days ) )
        ( rs.seam / "cc-fresh.json" ).write_text( "{}" )
        monkeypatch.setattr( rs.module, "_is_live_cc_process", lambda pid: pid == "111" )
        rs.run( _payload() )
        left = sorted( p.name for p in rs.seam.iterdir() )
        assert "cc-old.json" not in left and "cc-stable-222.id" not in left
        assert "cc-stable-111.id" in left and "cc-fresh.json" in left

    def test_a_purge_failure_is_swallowed_and_registration_completes( self, rs, monkeypatch ):
        ( rs.seam / "cc-other.json" ).write_text( "{}" )
        monkeypatch.setattr( os.path, "getmtime", lambda p: ( _ for _ in () ).throw( OSError( "stat failed" ) ) )
        rs.run( _payload() )
        assert rs.emitted[ 0 ][ "additionalContext" ].startswith( "Session ID: s1-session" )


class TestLaterPhasesDegradeSoftly:

    def test_a_prune_count_is_reported( self, rs, monkeypatch, capsys ):
        monkeypatch.setattr( f"{BRIDGE_MOD}.prune_dead_persona_bridges", lambda: 2 )
        rs.run( _payload() )
        assert "Pruned voice_persona on 2 dead-PID bridge(s)" in capsys.readouterr().err

    def test_a_prune_failure_is_reported_not_raised( self, rs, monkeypatch, capsys ):
        def boom(): raise RuntimeError( "bridge dir gone" )
        monkeypatch.setattr( f"{BRIDGE_MOD}.prune_dead_persona_bridges", boom )
        rs.run( _payload() )
        assert "prune phase failed (RuntimeError: bridge dir gone)" in capsys.readouterr().err

    def test_a_manager_figure_failure_is_reported_not_raised( self, rs, monkeypatch, capsys ):
        def boom( *a, **k ): raise RuntimeError( "roster unreadable" )
        monkeypatch.setattr( "lupin_cli.claude_code.hooks.lib.manager_figure.resolve_implicit_manager_figure", boom )
        rs.run( _payload() )
        assert "manager-figure stamp phase failed (RuntimeError: roster unreadable)" in capsys.readouterr().err
        assert rs.emitted

    def test_a_failing_status_block_leaves_it_out_of_the_context( self, rs, monkeypatch ):
        def boom(): raise RuntimeError( "x" )
        monkeypatch.setattr( rs.module, "_check_cosa_voice_status", boom )
        rs.run( _payload() )
        assert rs.emitted[ 0 ][ "additionalContext" ] == "Session ID: s1-session\n\n"

    def test_a_failing_memento_block_is_reported_and_left_out( self, rs, monkeypatch, capsys ):
        def boom( *a, **k ): raise RuntimeError( "no mementos" )
        monkeypatch.setattr( rs.module, "_build_memento_block", boom )
        rs.run( _payload() )
        assert "memento block failed (RuntimeError: no mementos)" in capsys.readouterr().err
        assert rs.emitted[ 0 ][ "additionalContext" ].startswith( "Session ID: s1-session" )

    def test_a_failing_roster_check_is_reported_and_leaves_no_drift_block( self, rs, monkeypatch, capsys ):
        def boom( *a, **k ): raise RuntimeError( "bad roster" )
        monkeypatch.setattr( "lupin_cli.claude_code.hooks.lib.roster_consistency.find_roster_disagreements", boom )
        rs.run( _payload() )
        assert "roster drift check failed (RuntimeError: bad roster)" in capsys.readouterr().err
        assert rs.emitted[ 0 ][ "additionalContext" ] == "Session ID: s1-session\n\nSTATUS"


class TestHelpers:

    def test_a_tmux_line_with_no_pane_pid_is_skipped_and_the_valid_line_still_matches( self, rs, monkeypatch ):
        done = subprocess.CompletedProcess( [ ], 0, stdout="garbage\nmysess 4242\nbad notanumber\n", stderr="" )
        monkeypatch.setattr( subprocess, "run", lambda *a, **k: done )
        assert _REAL.find_tmux( 4242 ) == "mysess"

    def test_a_listener_that_survives_sigterm_and_is_gone_before_sigkill_is_not_an_error( self, rs, monkeypatch ):
        kills = [ ]
        def fake_kill( pid, sig ):
            kills.append( sig )
            if sig == rs.module.signal.SIGKILL: raise ProcessLookupError( pid )
        ticks = iter( [ 0.0, 0.0, 100.0 ] )
        monkeypatch.setattr( rs.module, "time", types.SimpleNamespace(
            monotonic=lambda: next( ticks ), sleep=lambda s: None, time=time.time ) )
        monkeypatch.setattr( rs.module.os, "kill", fake_kill )
        monkeypatch.setattr( rs.module, "process_runs", lambda pid, marker: True )
        monkeypatch.setattr( rs.module, "_log_session_transition", lambda *a: None )
        _REAL.cleanup( { "listener_pid": 777, "session_id": "old-session" }, "new-session" )
        sigs = rs.module.signal
        assert kills == [ 0, sigs.SIGTERM, 0, sigs.SIGKILL ]

    def test_hooks_that_are_not_non_empty_lists_are_not_counted( self, rs, monkeypatch ):
        ( rs.home / ".claude" / "settings.json" ).write_text( json.dumps(
            { "hooks": { "A": [ ], "B": "not-a-list", "C": [ { "matcher": "" } ] } } ) )
        def refused( *a, **k ): raise OSError( "offline" )
        monkeypatch.setattr( urllib.request, "urlopen", refused )
        assert "Hooks   : 1/8 active" in _REAL.status()

    def test_a_missing_lupin_mcp_degrades_to_none( self, monkeypatch ):
        monkeypatch.setitem( sys.modules, "lupin_mcp.memento_repo_root", None )
        assert _REAL.repo_root_owning( "/anywhere" ) is None


class TestIdleCarryForward:

    def test_a_non_integer_backoff_index_on_the_old_bridge_is_not_carried( self, rs ):
        rs.lock.write_text( "stable-1" )
        rs.bridge.write_text( json.dumps( { "session_id": "old-session", "stable_session_id": "stable-1",
                                            "idle_detection": { "backoff_index": "3" } } ) )
        rs.run( _payload( session_id="new-session" ) )
        assert json.loads( rs.bridge.read_text() )[ "idle_detection" ][ "backoff_index" ] == 0
