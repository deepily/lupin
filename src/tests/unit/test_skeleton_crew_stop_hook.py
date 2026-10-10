#!/usr/bin/env python3
"""
Tests that a manager's Stop hook says nothing about staffing while skeleton crew is on.

The ordinary poke carries staffing lines. They tell a manager to manage and never build, to
delegate, to spawn when tasks outnumber workers, and to staff up this tick. Those lines are
wrong while skeleton crew is on, because no spawning is allowed.

These tests drive the real settings loader and the real Stop hook adapter. The switch is a
file in tmp_path. A control with the switch off proves the instrument can see the staffing
text. With the switch on, the hook emits only the operator's one line. It must also never
reach the code that builds the staffing text.

Every test writes to tmp_path. The live configuration file is never touched.
"""
import json
import os
import sys
from unittest.mock import patch

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks import stop
from lupin_cli.claude_code.hooks.lib import heartbeat_settings as hs
from lupin_mcp import fleet_cap_ini_io as io
from lupin_mcp import skeleton_crew as sc


STAFFING = [ "must manage", "never build", "delegate", "spawn", "staff up", "workers" ]


def _real_goal_line():
    root = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    path = os.path.join( root, "src", "conf", "lupin-app.ini" )
    return io.read_value_from_disk( path, "heartbeat manager goal line" )


@pytest.fixture
def hook( tmp_path, monkeypatch ):
    home = tmp_path / "home"
    ( home / ".claude" ).mkdir( parents=True )
    ( home / ".claude" / "settings.json" ).write_text( json.dumps( { "heartbeat": {
        "enabled": True, "poke_cap": 3, "owed_source_from_store": False,
        "verification_threshold_seconds": 600 } } ), encoding="utf-8" )
    monkeypatch.setattr( hs.os.path, "expanduser", lambda p: p.replace( "~", str( home ) ) )
    switch = tmp_path / "switch.ini"
    monkeypatch.setenv( sc.INI_OVERRIDE_ENV, str( switch ) )

    def set_switch( value ):
        switch.write_text( f"[Lupin: Baseline]\n{sc.SKELETON_CREW_KEY} = {value}\n", encoding="utf-8" )

    with patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ) as events, \
         patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=None ), \
         patch( "lupin_cli.claude_code.hooks.stop.replay_task_state", return_value={ "t1": "in_progress" } ) as replay, \
         patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" ) as notify, \
         patch( "lupin_cli.claude_code.hooks.stop._gather_outstanding_delegations", return_value=[ ] ), \
         patch( "lupin_cli.claude_code.hooks.stop._gather_unanswered_inbound_questions",
                return_value={ "owed": [ ], "stale": [ ] } ), \
         patch( "lupin_cli.claude_code.hooks.stop.inject_qualifier_via_tmux" ) as inject, \
         patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="claude.code@lupin.deepily.ai#sid" ), \
         patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient", return_value=None ), \
         patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 ), \
         patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" ), \
         patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" ), \
         patch( "lupin_cli.claude_code.hooks.stop.get_session_metadata", return_value={ "role": "manager" } ), \
         patch( "lupin_cli.claude_code.hooks.stop._heartbeat_goal_line", return_value=_real_goal_line() ) as goal:
        events.EVENT_IDLE = "idle"
        events.is_idle_transition.return_value = True
        yield { "switch": set_switch, "replay": replay, "goal": goal, "inject": inject, "notify": notify }


def _emitted_text( result ):
    block, _ = result
    return "" if block is None else block[ "reason" ]


def test_the_control_sees_the_staffing_text_when_the_switch_is_off( hook ):
    hook[ "switch" ]( "false" )
    text = _emitted_text( stop._run_heartbeat( "sid", "/t.jsonl" ) ).lower()
    assert text, "the unmuted poke produced no text, so this control proves nothing"
    assert "must manage" in text and "never build" in text
    assert "spawn" in text


def test_with_the_switch_on_a_manager_gets_only_the_operators_line( hook ):
    hook[ "switch" ]( "true" )
    out = stop._run_heartbeat( "sid", "/t.jsonl" )
    assert _emitted_text( out ) == hs.SKELETON_CREW_POKE_MESSAGE
    found = [ w for w in STAFFING if w in _emitted_text( out ).lower() ]
    assert found == []


def test_with_the_switch_on_the_injected_keystrokes_and_the_card_carry_no_staffing_text( hook ):
    hook[ "switch" ]( "true" )
    stop._run_heartbeat( "sid", "/t.jsonl" )
    hook[ "inject" ].assert_called_once()
    injected = hook[ "inject" ].call_args[ 0 ][ 1 ].lower()
    assert [ w for w in STAFFING if w in injected ] == []
    card = hook[ "notify" ].call_args[ 0 ][ 0 ]
    shown = f"{card.message} {card.abstract}".lower()
    assert [ w for w in STAFFING if w in shown ] == []


def test_with_the_switch_on_the_staffing_text_is_never_even_built( hook ):
    hook[ "switch" ]( "true" )
    stop._run_heartbeat( "sid", "/t.jsonl" )
    hook[ "goal" ].assert_not_called()
    hook[ "replay" ].assert_not_called()


def test_the_garbled_value_also_silences_the_staffing_text( hook ):
    hook[ "switch" ]( "perhaps" )
    out = stop._run_heartbeat( "sid", "/t.jsonl" )
    assert _emitted_text( out ) == hs.SKELETON_CREW_POKE_MESSAGE
