"""
Unit tests — set_manager_figure_implicit bridge setter (bug e5d600bd).

Covers the read-modify-write stamp of MANAGER_FIGURE_BRIDGE_FIELD to 100%
lines/branches/functions: success (field written, others preserved),
bridge-not-found → False, and the parse/OSError degrade → False.

Storage isolation via tempfile + monkeypatched SESSION_DIR, mirroring
test_session_bridge_speakerphone.py.
"""

import json
import tempfile
from pathlib import Path

import pytest

from lupin_cli.claude_code.hooks.lib import session_bridge


def _write_bridge( session_dir, sid, **fields ):
    path = session_dir / f"cc-{sid[ :8 ]}.json"
    data = { "session_id": sid, "stable_session_id": sid }
    data.update( fields )
    path.write_text( json.dumps( data, indent=2 ) )
    return path


@pytest.fixture
def isolated_session_dir( monkeypatch ):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path( tmp )
        monkeypatch.setattr( session_bridge, "SESSION_DIR", tmp_path )
        monkeypatch.setattr( session_bridge, "_can_trust_host_pids", lambda: False )
        yield tmp_path


def test_stamp_true_written_and_other_fields_preserved( isolated_session_dir ):
    sid = "aaaaaaaa-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, cwd="/tmp",
                   voice_persona={ "name": "Tiberius" } )

    assert session_bridge.set_manager_figure_implicit( sid, True ) is True

    data = json.loads( ( isolated_session_dir / f"cc-{sid[ :8 ]}.json" ).read_text() )
    assert data[ session_bridge.MANAGER_FIGURE_BRIDGE_FIELD ] is True
    # RMW preserves everything else.
    assert data[ "cwd" ] == "/tmp"
    assert data[ "voice_persona" ] == { "name": "Tiberius" }


def test_stamp_coerces_to_bool( isolated_session_dir ):
    sid = "bbbbbbbb-1111-2222-3333-444444444444"
    _write_bridge( isolated_session_dir, sid, cwd="/tmp" )

    assert session_bridge.set_manager_figure_implicit( sid, 0 ) is True
    data = json.loads( ( isolated_session_dir / f"cc-{sid[ :8 ]}.json" ).read_text() )
    assert data[ session_bridge.MANAGER_FIGURE_BRIDGE_FIELD ] is False


def test_self_heal_from_absent_shape( isolated_session_dir ):
    """Pre-fix (pre-22:47) population: the field is ABSENT from the bridge.
    On the next SessionStart, register_session Phase 4.6 re-stamps it — the
    setter must add the field as a real bool. Distinct from the present-and-null
    shape (Arnold's guard 4406cc18, test_captured_artifact_is_the_absent_shape)."""
    sid = "cccccccc-1111-2222-3333-444444444444"
    path = _write_bridge( isolated_session_dir, sid, cwd="/tmp" )
    # Precondition: the field is genuinely ABSENT (not null).
    before = json.loads( path.read_text() )
    assert session_bridge.MANAGER_FIGURE_BRIDGE_FIELD not in before

    assert session_bridge.set_manager_figure_implicit( sid, True ) is True

    after = json.loads( path.read_text() )
    assert after[ session_bridge.MANAGER_FIGURE_BRIDGE_FIELD ] is True


def test_self_heal_from_present_and_null_shape( isolated_session_dir ):
    """The other pre-fix shape: the field is PRESENT but null (bug e071e834's
    manufactured `manager_figure_implicit: null`). The next-start re-stamp must
    overwrite null with a real bool — self-heal, not a no-op."""
    sid = "dddddddd-1111-2222-3333-444444444444"
    path = _write_bridge( isolated_session_dir, sid, cwd="/tmp",
                          **{ session_bridge.MANAGER_FIGURE_BRIDGE_FIELD: None } )
    # Precondition: the field is PRESENT and null.
    before = json.loads( path.read_text() )
    assert session_bridge.MANAGER_FIGURE_BRIDGE_FIELD in before
    assert before[ session_bridge.MANAGER_FIGURE_BRIDGE_FIELD ] is None

    assert session_bridge.set_manager_figure_implicit( sid, False ) is True

    after = json.loads( path.read_text() )
    assert after[ session_bridge.MANAGER_FIGURE_BRIDGE_FIELD ] is False


def test_bridge_not_found_returns_false( isolated_session_dir ):
    assert session_bridge.set_manager_figure_implicit( "no-such-session", True ) is False


def test_malformed_bridge_degrades_to_false( isolated_session_dir, monkeypatch ):
    # find_session_path_by_id itself skips unparseable bridges, so force it to
    # return a path pointing at malformed JSON to exercise the setter's except.
    bad = isolated_session_dir / "cc-deadbeef.json"
    bad.write_text( "{not json" )
    monkeypatch.setattr( session_bridge, "find_session_path_by_id", lambda sid: bad )

    assert session_bridge.set_manager_figure_implicit( "whatever", True ) is False
