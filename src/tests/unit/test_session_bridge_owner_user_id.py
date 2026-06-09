"""
Unit tests for `session_bridge.set_owner_user_id` — writer-side follow-up
to the 2026-05-14 Option C design (owner_user_id field).

Mirrors test_session_bridge_user_id.py exactly except for field name.
Distinct concept: `set_user_id` stamps the SERVICE-account identity of
the listener; `set_owner_user_id` stamps the HUMAN owner's identity,
which is what the broadcast UI's same-user filter actually compares
against. Both fields can coexist on the same bridge.

See: src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md
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
        "cc_pid"            : 99999,
        "voice_persona"     : { "name": "Maria", "icon": "🌸" },
        "user_id"           : "service-account-uuid-aaa111",
    } ) )

    def _fake_find( session_id ):
        return bridge_path if session_id in ( "test-sid", "test-sid"[ :8 ] ) else None

    monkeypatch.setattr( sb, "find_session_path_by_id", _fake_find )
    return bridge_path


# ─── set_owner_user_id — happy path ──────────────────────────────────────────


def test_set_owner_user_id_stamps_bridge_field( fake_bridge ):
    """Successful write adds `owner_user_id` to the bridge JSON."""
    ok = sb.set_owner_user_id( "test-sid", "owner-uuid-0cf47e2d" )
    assert ok is True
    data = json.loads( fake_bridge.read_text() )
    assert data[ "owner_user_id" ] == "owner-uuid-0cf47e2d"


def test_set_owner_user_id_preserves_other_fields( fake_bridge ):
    """All other bridge keys preserved (read-modify-write hygiene)."""
    sb.set_owner_user_id( "test-sid", "owner-A" )
    data = json.loads( fake_bridge.read_text() )
    assert data[ "session_id" ]        == "test-sid"
    assert data[ "stable_session_id" ] == "test-sid"
    assert data[ "cc_pid" ]            == 99999
    assert data[ "voice_persona" ]     == { "name": "Maria", "icon": "🌸" }
    assert data[ "user_id" ]           == "service-account-uuid-aaa111"
    assert data[ "owner_user_id" ]     == "owner-A"


def test_set_owner_user_id_distinct_from_user_id( fake_bridge ):
    """`owner_user_id` and `user_id` coexist as distinct fields with different values."""
    sb.set_owner_user_id( "test-sid", "human-owner-0cf47e2d" )
    data = json.loads( fake_bridge.read_text() )
    # user_id is the listener's service-account; owner_user_id is the human owner
    assert data[ "user_id" ]       == "service-account-uuid-aaa111"
    assert data[ "owner_user_id" ] == "human-owner-0cf47e2d"
    assert data[ "user_id" ]       != data[ "owner_user_id" ]


def test_set_owner_user_id_idempotent_overwrite( fake_bridge ):
    """Calling twice with different owner_user_ids overwrites (last write wins)."""
    sb.set_owner_user_id( "test-sid", "owner-A" )
    sb.set_owner_user_id( "test-sid", "owner-B" )
    data = json.loads( fake_bridge.read_text() )
    assert data[ "owner_user_id" ] == "owner-B"


def test_set_owner_user_id_coerces_non_string( fake_bridge ):
    """Non-string owner_user_id (e.g., int UUID) is coerced via str()."""
    sb.set_owner_user_id( "test-sid", 12345 )
    data = json.loads( fake_bridge.read_text() )
    assert data[ "owner_user_id" ] == "12345"


# ─── set_owner_user_id — failure paths ───────────────────────────────────────


def test_set_owner_user_id_returns_false_when_bridge_not_found( monkeypatch ):
    """No bridge for the session_id → returns False, no write."""
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda s: None )
    ok = sb.set_owner_user_id( "ghost-sid", "owner-A" )
    assert ok is False


def test_set_owner_user_id_returns_false_on_empty_session_id():
    """Empty session_id → early-return False; never raises."""
    assert sb.set_owner_user_id( "", "owner-A" )    is False
    assert sb.set_owner_user_id( None, "owner-A" )  is False


def test_set_owner_user_id_returns_false_on_empty_owner_user_id( fake_bridge ):
    """Empty owner_user_id → early-return False; bridge untouched."""
    assert sb.set_owner_user_id( "test-sid", "" )   is False
    assert sb.set_owner_user_id( "test-sid", None ) is False
    # Bridge unchanged (no owner_user_id added)
    data = json.loads( fake_bridge.read_text() )
    assert "owner_user_id" not in data


def test_set_owner_user_id_returns_false_on_corrupt_bridge( tmp_path, monkeypatch ):
    """Parse failure (corrupt JSON) → returns False, never raises."""
    bridge_path = tmp_path / "cc-corrupt.json"
    bridge_path.write_text( "{ not valid json" )
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda s: bridge_path )
    ok = sb.set_owner_user_id( "test-sid", "owner-A" )
    assert ok is False


def test_set_owner_user_id_returns_false_on_oserror( tmp_path, monkeypatch ):
    """If the bridge path can't be opened (e.g., permissions), returns False."""
    fake_path = tmp_path / "nonexistent-dir" / "cc-foo.json"
    monkeypatch.setattr( sb, "find_session_path_by_id", lambda s: fake_path )
    ok = sb.set_owner_user_id( "test-sid", "owner-A" )
    assert ok is False
