"""
`main()` of the installer's notification probe, run in-process.

The sibling file classifies replies and drives the installer script.
These cases stand in for the sender, so the probe's own request and its exit mapping are visible.
"""

import importlib.util
import os

import pytest

PROBE = os.path.join( os.environ[ "LUPIN_ROOT" ], "src/scripts/lib/installer_notify_probe.py" )


def _load():
    spec = importlib.util.spec_from_file_location( "installer_notify_probe_main", PROBE )
    mod  = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( mod )
    return mod


class _Resp:
    def __init__( self, success, status, message="m" ):
        self.success, self.status, self.message = success, status, message


@pytest.fixture
def sender( monkeypatch ):
    """Replace the real sender; `calls` records each request it was given."""
    import lupin_cli.notifications.notify_user_async as nua
    calls = { "reqs": [ ], "urls": [ ], "reply": _Resp( True, "queued" ) }
    def fake( req, server_url=None ):
        calls[ "reqs" ].append( req )
        calls[ "urls" ].append( server_url )
        if isinstance( calls[ "reply" ], Exception ): raise calls[ "reply" ]
        return calls[ "reply" ]
    monkeypatch.setattr( nua, "notify_user_async", fake )
    return calls


def test_main_needs_lupin_root( monkeypatch ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    with pytest.raises( RuntimeError, match = "LUPIN_ROOT not set" ):
        _load().main( [ "probe", "http://x" ] )


@pytest.mark.parametrize( "argv", [ [ "probe" ], [ "probe", "http://x", "extra" ] ] )
def test_main_needs_exactly_one_server_url( argv ):
    with pytest.raises( RuntimeError, match = "usage" ):
        _load().main( argv )


def test_a_delivered_reply_prints_ok_and_exits_zero( sender, capsys ):
    mod = _load()
    assert mod.main( [ "probe", "http://server.example:1" ] ) == mod.EXIT_OK
    assert capsys.readouterr().out.strip() == "ok: queued"
    assert sender[ "urls" ] == [ "http://server.example:1" ]
    assert sender[ "reqs" ][ 0 ].message == "cosa-voice bootstrapper: test notification"
    assert sender[ "reqs" ][ 0 ].sender_id == "claude.code@installer.deepily.ai"


def test_a_no_listener_reply_exits_skipped( sender, capsys ):
    mod = _load()
    sender[ "reply" ] = _Resp( True, mod.NO_LISTENER_STATUS, "nobody home" )
    assert mod.main( [ "probe", "http://x" ] ) == mod.EXIT_SKIPPED
    assert capsys.readouterr().out.startswith( "skipped: " )


def test_a_sender_that_raises_prints_the_error_and_exits_failed( sender, capsys ):
    mod = _load()
    sender[ "reply" ] = ConnectionError( "refused" )
    assert mod.main( [ "probe", "http://x" ] ) == mod.EXIT_FAILED
    assert capsys.readouterr().out.strip() == "fail: ConnectionError: refused"
