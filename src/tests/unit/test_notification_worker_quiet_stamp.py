"""
The notification event carries `worker_quiet` for a quiet worker only.

The tests write real bridge files into a temporary session directory. The shapes are a plain spawned worker,
Cheech, Maria, a legacy bridge with no stamp, and a worker Rick flipped to speakerphone. Cheech was spawned
with role "author" and is a standing manager by persona stamp. Maria was spawned with role "manager".
"""
import json
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.notification_fifo_queue as nfq
from lupin_cli.claude_code.hooks.lib import session_bridge as sb

STAMP = sb.MANAGER_FIGURE_BRIDGE_FIELD


@pytest.fixture( autouse=True )
def _zone( monkeypatch ):
    monkeypatch.setattr( nfq, "get_app_timezone", lambda config_mgr: "America/New_York" )


@pytest.fixture
def bridges( monkeypatch, tmp_path ):
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )

    def write( prefix, **fields ):
        base = { "session_id": f"{prefix}-0000-0000-0000-000000000000",
                 "stable_session_id": f"{prefix}-0000-0000-0000-000000000000" }
        base.update( fields )
        ( tmp_path / f"cc-{prefix}.json" ).write_text( json.dumps( base ) )
        return f"claude.code@lupin.deepily.ai#{prefix}"
    return write


def _queue( monkeypatch ):
    monkeypatch.setattr( nfq, "InputAndOutputTable", lambda **k: types.SimpleNamespace() )
    ws = MagicMock()
    q  = nfq.NotificationFifoQueue( websocket_mgr=ws, emit_enabled=True, debug=False )
    monkeypatch.setattr( q, "_log_to_io_tbl", lambda *a, **k: None )
    return q, ws


def _emitted( ws ):
    for call in ws.emit.call_args_list:
        if call.args and call.args[ 0 ] == "notification_queue_update":
            return call.args[ 1 ][ "notification" ]
    raise AssertionError( "no emit captured" )


@pytest.mark.parametrize( "fields,expected", [
    ( dict( spawned_by="m", role="author", speakerphone_on=False, **{ STAMP: False } ), True ),
    ( dict( spawned_by="m", role="author", speakerphone_on=False, **{ STAMP: True } ),  False ),   # Cheech
    ( dict( spawned_by="m", role="manager", speakerphone_on=False, **{ STAMP: True } ), False ),   # Maria
    ( dict( spawned_by="m", role="manager-aide", speakerphone_on=False, **{ STAMP: False } ), True ),
    ( dict( spawned_by="m", role="author", speakerphone_on=False ), False ),                       # legacy, no stamp
    ( dict( spawned_by="m", role="author", speakerphone_on=True, **{ STAMP: False } ), False ),    # Rick flipped it on
    ( dict( role="author", speakerphone_on=False, **{ STAMP: False } ), False ),                   # not spawned
] )
@pytest.mark.parametrize( "priority", [ "medium", "high", "urgent" ] )
def test_event_carries_worker_quiet_only_for_a_quiet_worker( monkeypatch, bridges, fields, expected, priority ):
    sender = bridges( "wk000001", **fields )
    q, ws  = _queue( monkeypatch )
    q.push_notification( "hello", priority=priority, sender_id=sender, user_id=None )
    notif = _emitted( ws )
    assert notif[ "priority" ] == priority
    assert ( notif.get( "worker_quiet" ) is True ) is expected
    if not expected: assert "worker_quiet" not in notif


@pytest.mark.parametrize( "sender", [ None, "", "claude.code@unknown.deepily.ai", "claude.code@lupin.deepily.ai#", "claude.code@lupin.deepily.ai#nosuchbr" ] )
def test_no_bridge_no_stamp( sender ):
    assert nfq._worker_quiet_for_sender( sender ) is False


def test_is_quiet_worker_survives_a_corrupt_bridge( monkeypatch, tmp_path ):
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: False )
    ( tmp_path / "cc-bad00001.json" ).write_text( "[1, 2]" )
    assert sb.is_quiet_worker( "bad00001" ) is False


def test_is_quiet_worker_survives_a_missing_predicate_module( monkeypatch, bridges ):
    bridges( "wk000002", spawned_by="m", role="author", speakerphone_on=False, **{ STAMP: False } )
    monkeypatch.setitem( sys.modules, "lupin_mcp.worker_voice_mode", None )   # import now raises ImportError
    assert sb.is_quiet_worker( "wk000002" ) is False
