"""
The integration tier's declared manager seat, asked of the REAL priority firewall.

`tests/integration/manager_seat.py` writes a session bridge so a test caller counts as a manager
for rule 3 (create above P5). This drives the shipped predicate
(`task_priority_firewall.caller_is_manager_by_bridge`, through `is_manager_figure`) against
that file, in a temp sessions directory, so the fixture is proved against the code that
decides — not against its own opinion of what that code reads.

Positive control: a manager bridge passes. Negative controls: a worker bridge, no bridge, and the
bridge after the `with` block all fail. The firewall's other two rules are asserted to stay
shut, because the fixture must not widen them.
"""

import json
import os

import pytest

from cosa.rest import task_priority_firewall as fw
from lupin_cli.claude_code.hooks.lib import session_bridge
from tests.integration.manager_seat import BRIDGE_PREFIX, manager_seat, new_seat_ids


@pytest.fixture
def sessions( tmp_path, monkeypatch ):
    """Point the shipped bridge reader at a temp directory."""
    monkeypatch.setattr( session_bridge, "SESSION_DIR", tmp_path )
    return tmp_path


def test_new_seat_ids_gives_an_actor_the_firewall_can_read_a_session_id_from():
    session_id, actor = new_seat_ids()
    assert fw.session_id_from_actor( actor ) == session_id[ :8 ]
    assert new_seat_ids()[ 0 ] != session_id, "two seats shared a session id"


def test_a_declared_manager_seat_passes_rule_three_through_the_real_bridge_read( sessions ):
    session_id, actor = new_seat_ids()
    assert fw.caller_is_manager_by_bridge( actor ) is False, "positive control: no bridge yet, so not a manager"
    with manager_seat( session_id, sessions_dir=str( sessions ) ) as path:
        assert os.path.basename( path ).startswith( BRIDGE_PREFIX )
        assert fw.caller_is_manager_by_bridge( actor ) is True
        assert fw.refusal_for_priority_create( "P2", actor=actor ) is None, "a manager seat was refused a P2 create"
        assert fw.refusal_for_priority_create( "P1", actor=actor ) is None


def test_the_same_caller_without_the_bridge_is_refused_a_p2_create( sessions ):
    _, actor = new_seat_ids()
    refusal = fw.refusal_for_priority_create( "P2", actor=actor )
    assert refusal is not None and "requires the operator or a manager" in refusal


def test_a_worker_bridge_does_not_pass( sessions ):
    session_id, actor = new_seat_ids()
    with manager_seat( session_id, role="worker", sessions_dir=str( sessions ) ):
        assert fw.caller_is_manager_by_bridge( actor ) is False
        assert fw.refusal_for_priority_create( "P2", actor=actor ) is not None


def test_the_seat_does_not_widen_the_operator_only_rules( sessions ):
    session_id, actor = new_seat_ids()
    with manager_seat( session_id, sessions_dir=str( sessions ) ):
        p0 = fw.refusal_for_priority_create( "P0", actor=actor )
        assert p0 is not None and "reserved to the operator" in p0, "a manager seat created at P0"
        assert fw.refusal_for_priority_change( "P3", "P0", actor=actor ) is not None, "a manager seat raised to P0"
        assert fw.caller_is_operator( None ) is False, "no account email was supplied, so no operator proof exists"


def test_the_bridge_is_gone_after_the_block_and_after_a_raise( sessions ):
    session_id, actor = new_seat_ids()
    with manager_seat( session_id, sessions_dir=str( sessions ) ) as path:
        assert os.path.exists( path )
    assert not os.path.exists( path ), "the bridge outlived the block"
    assert fw.caller_is_manager_by_bridge( actor ) is False

    with pytest.raises( RuntimeError ):
        with manager_seat( session_id, sessions_dir=str( sessions ) ) as path:
            raise RuntimeError( "a test body failed" )
    assert not os.path.exists( path ), "the bridge outlived a raising body"


def test_the_bridge_carries_the_fields_the_reader_uses( sessions ):
    session_id, _ = new_seat_ids()
    with manager_seat( session_id, sessions_dir=str( sessions ) ) as path:
        with open( path, encoding="utf-8" ) as handle: data = json.load( handle )
    assert data[ "role" ] == "manager"
    assert data[ "session_id" ] == data[ "stable_session_id" ] == session_id


def test_the_default_directory_is_the_one_the_cc_transcript_fixture_reads():
    from tests.integration import manager_seat as module
    from tests.integration import test_cc_transcript_stream_integration as other
    assert module.HOST_SESSIONS_DIR == other.HOST_SESSIONS_DIR


def test_the_default_directory_is_used_when_none_is_given( tmp_path, monkeypatch ):
    from tests.integration import manager_seat as module
    monkeypatch.setattr( module, "HOST_SESSIONS_DIR", str( tmp_path ) )
    session_id, _ = new_seat_ids()
    with manager_seat( session_id ) as path:
        assert os.path.dirname( path ) == str( tmp_path )


def test_the_bridge_appears_whole_by_a_single_rename( sessions, monkeypatch ):
    """No `cc-*.json` exists until the rename, and what the rename moves is already parseable."""
    session_id, _ = new_seat_ids()
    seen = {}
    real_replace = os.replace

    def spy( source, target ):
        seen[ "glob_before" ] = sorted( p.name for p in sessions.glob( "cc-*.json" ) )
        seen[ "scratch_json" ] = json.load( open( source ) )
        real_replace( source, target )

    monkeypatch.setattr( os, "replace", spy )
    with manager_seat( session_id, sessions_dir=str( sessions ) ) as path:
        assert os.path.exists( path )
    assert seen[ "glob_before" ] == [], "a cc-*.json was visible before the rename"
    assert seen[ "scratch_json" ][ "role" ] == "manager", "the rename moved an incomplete file"


def test_a_failed_write_leaves_no_scratch_and_no_bridge( sessions, monkeypatch ):
    session_id, _ = new_seat_ids()

    def broken( source, target ): raise OSError( "disk said no" )

    monkeypatch.setattr( os, "replace", broken )
    with pytest.raises( OSError, match="disk said no" ):
        with manager_seat( session_id, sessions_dir=str( sessions ) ): pass
    assert list( sessions.iterdir() ) == [], "a scratch file or a bridge was left behind"
