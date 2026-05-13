"""
Unit tests for the Phase 2 speakerphone-mode bridge helpers.

Covers:
    - Mode-aware default in get_speakerphone (solo → False, chorus → True)
    - format_version stamping on set_speakerphone (upgrade-on-write)
    - v1 bridge handling (no destructive discard; field absent → mode default)
    - Legacy conversation_mode_active key removed on first set
    - find_active_speakerphone_sessions scans + filtering

Design doc: src/rnd/v0.1.7/2026.05.11-tts-interaction-mode-solo-chorus/11-phase2-bridge-rename-design.md

Storage isolation via tempfile.TemporaryDirectory + monkeypatched SESSION_DIR.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_bridge( session_dir, sid, **fields ):
    """Drop a bridge file at session_dir/cc-<sid-prefix>.json with the given fields."""
    path = session_dir / f"cc-{sid[ :8 ]}.json"
    data = { "session_id": sid, "stable_session_id": sid }
    data.update( fields )
    path.write_text( json.dumps( data, indent=2 ) )
    return path


@pytest.fixture
def isolated_session_dir( monkeypatch ):
    """Yield a temporary SESSION_DIR with session_bridge.SESSION_DIR patched."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path( tmp )
        monkeypatch.setattr( session_bridge, "SESSION_DIR", tmp_path )
        # Trust-host-pids must be False so we don't skip pids in glob (tests run in this proc)
        monkeypatch.setattr( session_bridge, "_can_trust_host_pids", lambda: False )
        yield tmp_path


# ---------------------------------------------------------------------------
# Mode-aware default tests
# ---------------------------------------------------------------------------

@patch( "cosa.utils.util.get_tts_interaction_mode", return_value="solo" )
def test_get_speakerphone_default_solo_returns_false( mock_mode, isolated_session_dir ):
    """Bridge with no `speakerphone_on` field returns False in solo mode (preserves today's behavior)."""
    sid = "aaaaaaaa-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, cwd="/tmp" )

    assert session_bridge.get_speakerphone( sid ) is False


@patch( "cosa.utils.util.get_tts_interaction_mode", return_value="chorus" )
def test_get_speakerphone_default_chorus_returns_true( mock_mode, isolated_session_dir ):
    """Bridge with no `speakerphone_on` field returns True in chorus mode (at-distance default)."""
    sid = "bbbbbbbb-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, cwd="/tmp" )

    assert session_bridge.get_speakerphone( sid ) is True


def test_get_speakerphone_explicit_true_wins_over_default( isolated_session_dir ):
    """Explicit speakerphone_on=true wins over any mode-aware default."""
    sid = "cccccccc-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, speakerphone_on=True, format_version=2 )

    assert session_bridge.get_speakerphone( sid ) is True


def test_get_speakerphone_explicit_false_wins_over_default( isolated_session_dir ):
    """Explicit speakerphone_on=false wins over any mode-aware default."""
    sid = "dddddddd-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, speakerphone_on=False, format_version=2 )

    assert session_bridge.get_speakerphone( sid ) is False


def test_get_speakerphone_missing_bridge_returns_false( isolated_session_dir ):
    """No bridge file at all → return False (no mode lookup; fail-closed)."""
    assert session_bridge.get_speakerphone( "doesntexist" ) is False


# ---------------------------------------------------------------------------
# set_speakerphone — upgrade-on-write semantics
# ---------------------------------------------------------------------------

def test_set_speakerphone_stamps_format_version( isolated_session_dir ):
    """set_speakerphone writes both speakerphone_on AND format_version=2."""
    sid = "eeeeeeee-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, cwd="/tmp" )

    assert session_bridge.set_speakerphone( sid, True ) is True

    path = isolated_session_dir / f"cc-{sid[ :8 ]}.json"
    data = json.loads( path.read_text() )
    assert data[ "speakerphone_on" ] is True
    assert data[ "format_version" ] == session_bridge.BRIDGE_FORMAT_VERSION
    assert data[ "format_version" ] == 2


def test_set_speakerphone_removes_legacy_field( isolated_session_dir ):
    """First set_speakerphone on a v1 bridge drops the stale conversation_mode_active key."""
    sid = "ffffffff-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, conversation_mode_active=True, cwd="/tmp" )

    assert session_bridge.set_speakerphone( sid, False ) is True

    path = isolated_session_dir / f"cc-{sid[ :8 ]}.json"
    data = json.loads( path.read_text() )
    assert "conversation_mode_active" not in data
    assert data[ "speakerphone_on" ] is False


def test_set_speakerphone_preserves_other_fields( isolated_session_dir ):
    """set_speakerphone preserves voice_persona, session_topic, last_autonarrated_turn_id, etc."""
    sid = "01010101-1111-2222-3333-444444444444"
    _write_bridge(
        isolated_session_dir, sid,
        voice_persona={ "name": "Rio", "voice_id": "abc" },
        session_topic="Test topic",
        last_autonarrated_turn_id="turn-42",
        cwd="/tmp"
    )

    assert session_bridge.set_speakerphone( sid, True ) is True

    path = isolated_session_dir / f"cc-{sid[ :8 ]}.json"
    data = json.loads( path.read_text() )
    assert data[ "voice_persona" ] == { "name": "Rio", "voice_id": "abc" }
    assert data[ "session_topic" ] == "Test topic"
    assert data[ "last_autonarrated_turn_id" ] == "turn-42"


def test_set_speakerphone_missing_bridge_returns_false( isolated_session_dir ):
    """set_speakerphone on missing bridge returns False (no auto-create — caller's job)."""
    assert session_bridge.set_speakerphone( "doesntexist", True ) is False


def test_set_get_round_trip( isolated_session_dir ):
    """set then get returns the value just written."""
    sid = "02020202-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, cwd="/tmp" )

    session_bridge.set_speakerphone( sid, True )
    assert session_bridge.get_speakerphone( sid ) is True

    session_bridge.set_speakerphone( sid, False )
    assert session_bridge.get_speakerphone( sid ) is False


# ---------------------------------------------------------------------------
# find_active_speakerphone_sessions
# ---------------------------------------------------------------------------

def test_find_active_speakerphone_sessions_empty_dir( isolated_session_dir ):
    """No bridges → empty list."""
    assert session_bridge.find_active_speakerphone_sessions() == []


def test_find_active_speakerphone_sessions_skips_inactive( isolated_session_dir ):
    """Bridges with speakerphone_on=false are excluded."""
    _write_bridge( isolated_session_dir, "03030303-1111-2222-3333-444444444444",
                   speakerphone_on=False, format_version=2 )
    assert session_bridge.find_active_speakerphone_sessions() == []


def test_find_active_speakerphone_sessions_returns_active( isolated_session_dir ):
    """Bridges with speakerphone_on=true are returned."""
    sid_active = "04040404-1111-2222-3333-444444444444"
    sid_inactive = "05050505-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid_active, speakerphone_on=True, format_version=2 )
    _write_bridge( isolated_session_dir, sid_inactive, speakerphone_on=False, format_version=2 )

    results = session_bridge.find_active_speakerphone_sessions()
    sids = [ r[ 1 ] for r in results ]
    assert sid_active in sids
    assert sid_inactive not in sids


def test_find_active_speakerphone_sessions_skips_v1_bridges( isolated_session_dir ):
    """v1 bridges (no speakerphone_on field) treated as inactive — no destructive discard."""
    sid = "06060606-1111-2222-3333-444444444444"
    path = _write_bridge( isolated_session_dir, sid, conversation_mode_active=True )

    results = session_bridge.find_active_speakerphone_sessions()
    assert results == []

    # File still exists — upgrade-on-write means we DON'T destructively unlink.
    assert path.exists()


def test_find_active_speakerphone_sessions_excludes_self( isolated_session_dir ):
    """exclude_session_id filters out the matching bridge."""
    sid_a = "07070707-1111-2222-3333-444444444444"
    sid_b = "08080808-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid_a, speakerphone_on=True, format_version=2 )
    _write_bridge( isolated_session_dir, sid_b, speakerphone_on=True, format_version=2 )

    results = session_bridge.find_active_speakerphone_sessions( exclude_session_id=sid_a )
    sids = [ r[ 1 ] for r in results ]
    assert sid_a not in sids
    assert sid_b in sids


# ---------------------------------------------------------------------------
# Module-level constant
# ---------------------------------------------------------------------------

def test_bridge_format_version_is_2():
    """BRIDGE_FORMAT_VERSION exposes the schema version."""
    assert session_bridge.BRIDGE_FORMAT_VERSION == 2


# ---------------------------------------------------------------------------
# Smoke entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
