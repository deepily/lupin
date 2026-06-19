"""
Unit tests for idle_waiter.run_waiter() — the deferred-ask state machine.

Covers the core branching logic with mocked time/REST/process primitives:
  - Backoff progression on "no" response
  - Cap behavior at last schedule index
  - Reset semantics (last_interaction_at advanced during sleep)
  - Conversation-mode gate at wake-time
  - Dead-CC-PID guard (the CC process died during sleep)
  - "yes" with/without qualifier
  - "no" with qualifier (tmux-inject + spawn successor)
  - Network/transport error path (no successor, exits silently)

Per `feedback_tests_parameterize_base_url` and the project testing-patterns
SKILL: any helper that hits Lupin REST reads BASE_URL from `LUPIN_API_URL`
env. The waiter itself goes through `notify_user_sync()` which honors that
env via the existing config_loader path; in these tests we mock the
`fire_anything_else_ask` helper directly so we don't actually touch HTTP.

Design: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from lupin_cli.claude_code.hooks.lib import idle_waiter
from lupin_cli.claude_code.hooks.lib import session_bridge as sb
from lupin_cli.claude_code.hooks.lib.anything_else_ask import AnythingElseResult


@pytest.fixture
def fake_bridge( tmp_path, monkeypatch ):
    """Create a fake bridge file + monkeypatch path resolution to it."""
    bridge_path = tmp_path / "cc-99999.json"
    bridge_path.write_text( json.dumps( {
        "session_id"        : "test-sid",
        "stable_session_id" : "test-sid",
        "cc_pid"            : 99999,
        "idle_detection"    : {
            "last_interaction_at" : "2026-04-29T10:00:00-04:00",
            "backoff_index"       : 0,
            "waiter_pid"          : None,
        },
    } ) )

    def _fake_find( session_id ):
        return bridge_path if session_id == "test-sid" else None

    monkeypatch.setattr( sb,           "find_session_path_by_id", _fake_find )
    monkeypatch.setattr( idle_waiter,  "find_session_path_by_id", _fake_find )
    return bridge_path


@pytest.fixture( autouse=True )
def _no_real_sleep( monkeypatch ):
    """Replace time.sleep with a no-op so tests run instantly."""
    monkeypatch.setattr( idle_waiter.time, "sleep", lambda _secs: None )


@pytest.fixture
def settings_5_10_20( monkeypatch ):
    """Force a known backoff schedule for deterministic tests."""
    monkeypatch.setattr(
        idle_waiter, "load_idle_settings",
        lambda: { "enabled": True, "backoff_minutes": [ 5, 10, 20 ] }
    )


@pytest.fixture
def alive_cc_pid( monkeypatch ):
    """All CC-PID alive checks return True unless overridden."""
    monkeypatch.setattr( idle_waiter, "_is_pid_alive", lambda _pid: True )


@pytest.fixture
def speakerphone_off( monkeypatch ):
    """Conversation mode reads return False unless overridden."""
    monkeypatch.setattr( idle_waiter, "get_speakerphone", lambda _sid: False )


# ─────────────────────────────────────────────────────────────────────────────
# Happy path — fire and exit on "yes"
# ─────────────────────────────────────────────────────────────────────────────

class TestYesPath:

    def test_yes_no_qualifier_exits_no_successor(
        self, fake_bridge, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch
    ):
        result = AnythingElseResult( answer="yes", qualifier=None, raw_value="yes", error=None )
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: result )

        spawn_calls = [ ]
        monkeypatch.setattr(
            idle_waiter, "_spawn_successor",
            lambda *a, **kw: spawn_calls.append( ( a, kw ) ) or 12345
        )

        # Tmux inject should not be called when no qualifier
        injects = [ ]
        try:
            from lupin_cli.claude_code.hooks.lib import hook_common
            monkeypatch.setattr(
                hook_common, "inject_qualifier_via_tmux",
                lambda sid, q: injects.append( ( sid, q ) )
            )
        except ImportError:
            pass

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert spawn_calls == [ ], "should not spawn successor on yes"
        assert injects     == [ ], "should not inject when no qualifier"

    def test_yes_with_qualifier_injects_then_exits(
        self, fake_bridge, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch
    ):
        result = AnythingElseResult( answer="yes", qualifier="run the tests", raw_value="yes", error=None )
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: result )

        spawn_calls = [ ]
        monkeypatch.setattr(
            idle_waiter, "_spawn_successor",
            lambda *a, **kw: spawn_calls.append( ( a, kw ) ) or 12345
        )

        injects = [ ]
        from lupin_cli.claude_code.hooks.lib import hook_common
        monkeypatch.setattr(
            hook_common, "inject_qualifier_via_tmux",
            lambda sid, q: injects.append( ( sid, q ) )
        )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert spawn_calls == [ ],                                    "no successor on yes"
        assert injects     == [ ( "test-sid", "run the tests" ) ],   "qualifier injected"


# ─────────────────────────────────────────────────────────────────────────────
# Backoff progression — "no" / "timeout" → spawn next
# ─────────────────────────────────────────────────────────────────────────────

class TestBackoffProgression:

    def test_no_response_spawns_successor_at_next_index(
        self, fake_bridge, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch
    ):
        result = AnythingElseResult( answer="no", qualifier=None, raw_value="no", error=None )
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: result )

        captured = { }
        def _fake_spawn( session_id, cc_pid, backoff_index, sleep_secs_override=None ):
            captured[ "session_id" ]    = session_id
            captured[ "cc_pid" ]        = cc_pid
            captured[ "backoff_index" ] = backoff_index
            return 12345
        monkeypatch.setattr( idle_waiter, "_spawn_successor", _fake_spawn )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert captured[ "backoff_index" ] == 1, "next index after 0 should be 1"

        # Bridge backoff_index also bumped
        block = sb.get_idle_detection( "test-sid" )
        assert block[ "backoff_index" ] == 1

    def test_timeout_treated_as_no(
        self, fake_bridge, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch
    ):
        result = AnythingElseResult( answer="timeout", qualifier=None, raw_value="", error=None )
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: result )

        spawned = [ ]
        monkeypatch.setattr(
            idle_waiter, "_spawn_successor",
            lambda sid, cc_pid, idx, sleep_secs_override=None: spawned.append( idx ) or 1
        )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=1, sleep_secs_override=1 )
        assert spawned == [ 2 ]

    def test_caps_at_last_schedule_index(
        self, fake_bridge, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch
    ):
        # Schedule has 3 entries (indices 0-2). At index 2, "no" should keep spawning at 2.
        result = AnythingElseResult( answer="no", qualifier=None, raw_value="no", error=None )
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: result )

        spawned = [ ]
        monkeypatch.setattr(
            idle_waiter, "_spawn_successor",
            lambda sid, cc_pid, idx, sleep_secs_override=None: spawned.append( idx ) or 1
        )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=2, sleep_secs_override=1 )
        assert spawned == [ 2 ], "cap at last index, not index 3"

    def test_no_with_qualifier_injects_and_spawns(
        self, fake_bridge, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch
    ):
        result = AnythingElseResult(
            answer="no", qualifier="check the logs", raw_value="no [comment: check the logs]", error=None
        )
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: result )

        spawned = [ ]
        monkeypatch.setattr(
            idle_waiter, "_spawn_successor",
            lambda sid, cc_pid, idx, sleep_secs_override=None: spawned.append( idx ) or 1
        )

        injects = [ ]
        from lupin_cli.claude_code.hooks.lib import hook_common
        monkeypatch.setattr(
            hook_common, "inject_qualifier_via_tmux",
            lambda sid, q: injects.append( ( sid, q ) )
        )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert injects == [ ( "test-sid", "check the logs" ) ]
        assert spawned == [ 1 ]


# ─────────────────────────────────────────────────────────────────────────────
# Wake-time gates — exit silently
# ─────────────────────────────────────────────────────────────────────────────

class TestWakeTimeGates:

    def test_reset_during_sleep_exits_silently( self, fake_bridge, settings_5_10_20, alive_cc_pid, monkeypatch ):
        # Stage: claim slot writes waiter_started_at. After "sleep", we'll bump
        # last_interaction_at to AFTER waiter_started_at — simulating a reset.
        original_set = sb.set_idle_detection_field
        sleep_phase  = [ "before_sleep" ]

        def _set_with_reset_during_sleep( session_id, **fields ):
            res = original_set( session_id, **fields )
            # When the waiter records its start, bump last_interaction_at past it
            if sleep_phase[ 0 ] == "before_sleep" and "waiter_started_at" in fields:
                # Advance last_interaction to a strictly-later wall-clock value
                bumped = "2099-01-01T00:00:00-04:00"
                original_set( session_id, last_interaction_at=bumped )
                sleep_phase[ 0 ] = "after_reset"
            return res

        monkeypatch.setattr( sb,          "set_idle_detection_field", _set_with_reset_during_sleep )
        monkeypatch.setattr( idle_waiter, "set_idle_detection_field", _set_with_reset_during_sleep )

        fired = [ ]
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: fired.append( kw ) or None )
        spawned = [ ]
        monkeypatch.setattr(
            idle_waiter, "_spawn_successor",
            lambda *a, **kw: spawned.append( ( a, kw ) ) or 1
        )
        monkeypatch.setattr( idle_waiter, "get_speakerphone", lambda _sid: False )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert fired   == [ ], "reset detected → no ask fired"
        assert spawned == [ ], "reset → no successor"

    def test_speakerphone_on_exits_silently(
        self, fake_bridge, settings_5_10_20, alive_cc_pid, monkeypatch
    ):
        monkeypatch.setattr( idle_waiter, "get_speakerphone", lambda _sid: True )

        fired = [ ]
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: fired.append( kw ) or None )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert fired == [ ], "speakerphone on at wake → no ask"

    def test_dead_cc_pid_exits_silently_during_sleep( self, fake_bridge, settings_5_10_20, speakerphone_off, monkeypatch ):
        monkeypatch.setattr( idle_waiter, "_is_pid_alive", lambda _p: False )

        fired = [ ]
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: fired.append( kw ) or None )

        # sleep_secs_override > chunk so the sleep loop iterates and triggers the CC-PID check
        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=60 )

        assert fired == [ ], "dead CC-PID → exit before fire"

    def test_bridge_gone_at_wake_exits_silently( self, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch ):
        # No fake_bridge fixture — find_session_path returns None unconditionally
        monkeypatch.setattr( sb,          "find_session_path_by_id", lambda _sid: None )
        monkeypatch.setattr( idle_waiter, "find_session_path_by_id", lambda _sid: None )

        fired = [ ]
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: fired.append( kw ) or None )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert fired == [ ]


# ─────────────────────────────────────────────────────────────────────────────
# Error path — transport failure
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorPath:

    def test_error_response_no_successor( self, fake_bridge, settings_5_10_20, alive_cc_pid, speakerphone_off, monkeypatch ):
        result = AnythingElseResult( answer="error", qualifier=None, raw_value="", error="server down" )
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: result )

        spawned = [ ]
        monkeypatch.setattr(
            idle_waiter, "_spawn_successor",
            lambda *a, **kw: spawned.append( ( a, kw ) ) or 1
        )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert spawned == [ ], "transport error → no retry storm"


# ─────────────────────────────────────────────────────────────────────────────
# Slot management
# ─────────────────────────────────────────────────────────────────────────────

class TestSlotManagement:

    def test_aborts_when_live_waiter_already_holds_slot(
        self, fake_bridge, settings_5_10_20, speakerphone_off, monkeypatch
    ):
        # Pre-claim the slot with a "live" PID
        sb.set_idle_detection_field( "test-sid", waiter_pid=11111 )
        monkeypatch.setattr( idle_waiter, "_is_pid_alive", lambda pid: pid == 11111 )

        fired = [ ]
        monkeypatch.setattr( idle_waiter, "fire_anything_else_ask", lambda **kw: fired.append( kw ) or None )

        idle_waiter.run_waiter( "test-sid", cc_pid=99999, backoff_index=0, sleep_secs_override=1 )

        assert fired == [ ], "lost the slot race → exit silently, no fire"
        # Slot still held by the incumbent
        block = sb.get_idle_detection( "test-sid" )
        assert block[ "waiter_pid" ] == 11111
