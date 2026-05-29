"""
Unit tests for `session_bridge.set_user_id` — Phase 3 Option 2 fix.

Covers Option 2 of `src/rnd/v0.1.7/2026.05.13-broadcast-ui-no-active-sessions-bug.md`:
the listener resolves the authenticated user_id at startup and stamps it on
the session bridge. Once landed, the inter-session-commons broadcast filter
in `routers/commons.py` tightens from graceful-degradation to strict
cross-user isolation automatically.
"""

import json

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge as sb


@pytest.fixture
def fake_bridge( tmp_path, monkeypatch ):
    """Fake bridge at tmp_path/cc-99999.json; find_session_path_by_id mocked."""
    bridge_path = tmp_path / "cc-99999.json"
    bridge_path.write_text( json.dumps( {
        "session_id"        : "test-sid",
        "stable_session_id" : "test-sid",
        "ppid"              : 99999,
        "voice_persona"     : { "name": "Maria", "icon": "🌸" },
    } ) )

    def _fake_find( session_id ):
        return bridge_path if session_id in ( "test-sid", "test-sid"[ :8 ] ) else None

    monkeypatch.setattr( sb, "find_session_path_by_id", _fake_find )
    return bridge_path


# ─── set_user_id — happy path ────────────────────────────────────────────────


def test_set_user_id_stamps_bridge_field( fake_bridge ):
    """Successful write adds `user_id` to the bridge JSON."""
    ok = sb.set_user_id( "test-sid", "user-uuid-abc123" )
    assert ok is True
    data = json.loads( fake_bridge.read_text() )
    assert data[ "user_id" ] == "user-uuid-abc123"


def test_set_user_id_preserves_other_fields( fake_bridge ):
    """All other bridge keys are preserved (read-modify-write hygiene)."""
    sb.set_user_id( "test-sid", "user-A" )
    data = json.loads( fake_bridge.read_text() )
    assert data[ "session_id" ]        == "test-sid"
    assert data[ "stable_session_id" ] == "test-sid"
    assert data[ "ppid" ]              == 99999
    assert data[ "voice_persona" ]     == { "name": "Maria", "icon": "🌸" }
    assert data[ "user_id" ]           == "user-A"


def test_set_user_id_idempotent_overwrite( fake_bridge ):
    """Calling twice with different user_ids overwrites (last write wins)."""
    sb.set_user_id( "test-sid", "user-A" )
    sb.set_user_id( "test-sid", "user-B" )
    data = json.loads( fake_bridge.read_text() )
    assert data[ "user_id" ] == "user-B"


def test_set_user_id_coerces_non_string( fake_bridge ):
    """Non-string user_id (e.g., int UUID) is coerced via str()."""
    sb.set_user_id( "test-sid", 12345 )
    data = json.loads( fake_bridge.read_text() )
    assert data[ "user_id" ] == "12345"


# ─── set_user_id — failure paths ─────────────────────────────────────────────


def test_set_user_id_returns_false_when_bridge_not_found( monkeypatch ):
    """No bridge for the session_id → returns False, no write."""
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda s: None )
    ok = sb.set_user_id( "ghost-sid", "user-A" )
    assert ok is False


def test_set_user_id_returns_false_on_empty_session_id():
    """Empty session_id → early-return False; never raises."""
    assert sb.set_user_id( "", "user-A" )    is False
    assert sb.set_user_id( None, "user-A" )  is False


def test_set_user_id_returns_false_on_empty_user_id( fake_bridge ):
    """Empty user_id → early-return False; bridge untouched."""
    assert sb.set_user_id( "test-sid", "" )   is False
    assert sb.set_user_id( "test-sid", None ) is False
    # Bridge unchanged
    data = json.loads( fake_bridge.read_text() )
    assert "user_id" not in data


def test_set_user_id_returns_false_on_corrupt_bridge( tmp_path, monkeypatch ):
    """Parse failure (corrupt JSON) → returns False, never raises."""
    bridge_path = tmp_path / "cc-corrupt.json"
    bridge_path.write_text( "{ not valid json" )
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda s: bridge_path )
    ok = sb.set_user_id( "test-sid", "user-A" )
    assert ok is False


def test_set_user_id_returns_false_on_oserror( tmp_path, monkeypatch ):
    """If the bridge path can't be opened (e.g., permissions), returns False."""
    fake_path = tmp_path / "nonexistent-dir" / "cc-foo.json"
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda s: fake_path )
    ok = sb.set_user_id( "test-sid", "user-A" )
    assert ok is False
