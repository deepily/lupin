"""
Unit tests for the idle_detection helpers in session_bridge.py.

Covers:
    - get_idle_detection: missing bridge, missing field, valid field
    - set_idle_detection_field: create new block, merge into existing,
      preserve other top-level fields, preserve other idle sub-fields
    - clear_idle_waiter_pid: returns prior PID + clears it
    - kill_idle_waiter: dead-PID guard, no-waiter case, real-PID case

Design: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
"""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


@pytest.fixture
def fake_bridge( tmp_path, monkeypatch ):
    """
    Create a fake bridge file at ~/.claude/sessions/cc-99999.json by
    monkeypatching find_session_path_by_id to return our tmp_path file.

    Yields the path; tests can read/write it directly to inspect/control state.
    """
    bridge_path = tmp_path / "cc-99999.json"
    bridge_path.write_text( json.dumps( {
        "session_id"        : "test-sid",
        "stable_session_id" : "test-sid",
        "ppid"              : 99999,
    } ) )

    def _fake_find( session_id ):
        return bridge_path if session_id == "test-sid" else None

    monkeypatch.setattr( sb, "find_session_path_by_id", _fake_find )
    return bridge_path


# ─────────────────────────────────────────────────────────────────────────────
# get_idle_detection
# ─────────────────────────────────────────────────────────────────────────────

class TestGetIdleDetection:

    def test_returns_none_when_bridge_missing( self, monkeypatch ):
        monkeypatch.setattr( sb, "find_session_path_by_id", lambda _sid: None )
        assert sb.get_idle_detection( "nonexistent" ) is None

    def test_returns_none_when_field_missing( self, fake_bridge ):
        # Bridge has no idle_detection key
        assert sb.get_idle_detection( "test-sid" ) is None

    def test_returns_none_when_field_empty_dict( self, fake_bridge ):
        data = json.loads( fake_bridge.read_text() )
        data[ "idle_detection" ] = { }
        fake_bridge.write_text( json.dumps( data ) )
        assert sb.get_idle_detection( "test-sid" ) is None

    def test_returns_dict_when_present( self, fake_bridge ):
        data = json.loads( fake_bridge.read_text() )
        data[ "idle_detection" ] = {
            "last_interaction_at" : "2026-04-29T18:00:00-04:00",
            "backoff_index"       : 2,
            "waiter_pid"          : None,
        }
        fake_bridge.write_text( json.dumps( data ) )
        result = sb.get_idle_detection( "test-sid" )
        assert result == data[ "idle_detection" ]

    def test_returns_none_on_corrupt_json( self, fake_bridge ):
        fake_bridge.write_text( "{not json at all" )
        assert sb.get_idle_detection( "test-sid" ) is None


# ─────────────────────────────────────────────────────────────────────────────
# set_idle_detection_field
# ─────────────────────────────────────────────────────────────────────────────

class TestSetIdleDetectionField:

    def test_creates_block_when_absent( self, fake_bridge ):
        sb.set_idle_detection_field( "test-sid", backoff_index=3 )
        block = sb.get_idle_detection( "test-sid" )
        assert block == { "backoff_index": 3 }

    def test_merges_into_existing_block( self, fake_bridge ):
        sb.set_idle_detection_field(
            "test-sid", backoff_index=0, last_interaction_at="t1"
        )
        sb.set_idle_detection_field( "test-sid", waiter_pid=12345 )
        block = sb.get_idle_detection( "test-sid" )
        assert block == {
            "backoff_index"       : 0,
            "last_interaction_at" : "t1",
            "waiter_pid"          : 12345,
        }

    def test_preserves_other_top_level_fields( self, fake_bridge ):
        sb.set_idle_detection_field( "test-sid", backoff_index=1 )
        data = json.loads( fake_bridge.read_text() )
        assert data[ "session_id" ] == "test-sid"
        assert data[ "ppid" ]       == 99999

    def test_preserves_other_idle_subfields_on_partial_update( self, fake_bridge ):
        sb.set_idle_detection_field(
            "test-sid",
            last_interaction_at = "t1",
            backoff_index       = 0,
            waiter_pid          = 100,
        )
        # Only update backoff_index
        sb.set_idle_detection_field( "test-sid", backoff_index=1 )
        block = sb.get_idle_detection( "test-sid" )
        assert block[ "last_interaction_at" ] == "t1"
        assert block[ "backoff_index" ]       == 1
        assert block[ "waiter_pid" ]          == 100

    def test_returns_true_on_no_op( self, fake_bridge ):
        # Empty kwargs is documented as no-op returning True
        assert sb.set_idle_detection_field( "test-sid" ) is True

    def test_returns_false_when_bridge_missing( self, monkeypatch ):
        monkeypatch.setattr( sb, "find_session_path_by_id", lambda _sid: None )
        assert sb.set_idle_detection_field( "nope", backoff_index=1 ) is False


# ─────────────────────────────────────────────────────────────────────────────
# clear_idle_waiter_pid
# ─────────────────────────────────────────────────────────────────────────────

class TestClearIdleWaiterPid:

    def test_returns_none_when_no_waiter( self, fake_bridge ):
        sb.set_idle_detection_field( "test-sid", backoff_index=0 )
        assert sb.clear_idle_waiter_pid( "test-sid" ) is None

    def test_returns_prior_pid_and_clears( self, fake_bridge ):
        sb.set_idle_detection_field( "test-sid", waiter_pid=42 )
        old = sb.clear_idle_waiter_pid( "test-sid" )
        assert old == 42
        block = sb.get_idle_detection( "test-sid" )
        assert block[ "waiter_pid" ] is None

    def test_returns_none_when_bridge_missing( self, monkeypatch ):
        monkeypatch.setattr( sb, "find_session_path_by_id", lambda _sid: None )
        assert sb.clear_idle_waiter_pid( "nope" ) is None


# ─────────────────────────────────────────────────────────────────────────────
# kill_idle_waiter
# ─────────────────────────────────────────────────────────────────────────────

class TestKillIdleWaiter:

    def test_no_waiter_returns_false( self, fake_bridge ):
        # No waiter_pid set
        assert sb.kill_idle_waiter( "test-sid" ) is False

    def test_dead_pid_returns_false_and_clears( self, fake_bridge, monkeypatch ):
        sb.set_idle_detection_field( "test-sid", waiter_pid=999999 )  # almost certainly dead
        # Force the alive check to return False
        monkeypatch.setattr( sb, "_is_pid_alive", lambda _p: False )
        assert sb.kill_idle_waiter( "test-sid" ) is False
        # Slot still cleared (clear_idle_waiter_pid runs first)
        block = sb.get_idle_detection( "test-sid" )
        assert block[ "waiter_pid" ] is None

    def test_kills_real_short_lived_subprocess( self, fake_bridge ):
        # Spawn a real sleep process; our kill should reach it
        proc = subprocess.Popen( [ sys.executable, "-c", "import time; time.sleep(30)" ] )
        try:
            sb.set_idle_detection_field( "test-sid", waiter_pid=proc.pid )
            killed = sb.kill_idle_waiter( "test-sid" )
            assert killed is True
            # Brief settle for SIGTERM delivery
            for _ in range( 20 ):
                if proc.poll() is not None:
                    break
                time.sleep( 0.1 )
            assert proc.poll() is not None, "subprocess should be dead after SIGTERM"
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            proc.wait( timeout=5 )

    def test_custom_signal_accepted( self, fake_bridge, monkeypatch ):
        sb.set_idle_detection_field( "test-sid", waiter_pid=99 )
        monkeypatch.setattr( sb, "_is_pid_alive", lambda _p: True )

        captured = { }
        def _fake_kill( pid, sig ):
            captured[ "pid" ]    = pid
            captured[ "signal" ] = sig
        monkeypatch.setattr( sb.os, "kill", _fake_kill )

        assert sb.kill_idle_waiter( "test-sid", signal=signal.SIGINT ) is True
        assert captured == { "pid": 99, "signal": signal.SIGINT }
