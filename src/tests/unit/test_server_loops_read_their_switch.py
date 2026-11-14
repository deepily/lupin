"""
Four server loops skip their work on a tick whose switch reads false.

The jobs are notification-expiry, socket-housekeeping, commons-archival and notify-outbox.
Each test uses a real TickSwitch over a configuration file in a temporary folder. It runs
ticks with the key false, then true, and counts the calls to the work the tick would do.
"""
import asyncio
import os
import sys
import types
from unittest import mock

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_app import main
from lupin_mcp import commons_archival, cron_switch_read as csr, notify_outbox


class _Ini:
    """A configuration file holding one job's switch, which a test can flip."""

    def __init__( self, tmp_path, job ):
        self.path, self.job, self.logged = tmp_path / "lupin-app.ini", job, []

    def set( self, value ):
        self.path.write_text( f"[Lupin]\ncron job {self.job} enabled = {value}\n" )

    def switch( self ):
        return csr.TickSwitch( self.job, lambda: str( self.path ), None, self.logged.append )

    def wire( self, monkeypatch ):
        """Make the production builder hand back this file's real TickSwitch."""
        monkeypatch.setattr( csr, "for_job", lambda job, log=print: csr.TickSwitch( job, lambda: str( self.path ), None, self.logged.append ) )


class _Config:
    def get( self, key, default=None, return_type=None, silent=False ):
        return default


def _shim( flips, ini, work ):
    """
    A stand-in for `asyncio` as main.py sees it.

    The first sleep sets the switch to each value in `flips` in turn; the sleep after the last one cancels the loop.
    """
    naps = []

    async def sleep( delay ):
        naps.append( delay )
        if len( naps ) > len( flips ): raise asyncio.CancelledError()
        ini.set( flips[ len( naps ) - 1 ] )

    async def to_thread( fn, *args ):
        work.append( 1 )
        return { "swept": 0, "scanned": 0, "skipped_in_grace": 0 }

    return types.SimpleNamespace( sleep=sleep, to_thread=to_thread, CancelledError=asyncio.CancelledError ), naps


def test_the_notification_sweep_does_no_work_while_its_switch_is_false( tmp_path, monkeypatch ):
    ini, work = _Ini( tmp_path, "notification-expiry" ), []
    ini.set( "false" )
    ini.wire( monkeypatch )
    shim, naps = _shim( [ "true" ], ini, work )
    with mock.patch.object( main, "asyncio", shim ), mock.patch.object( main, "config_mgr", _Config() ):
        asyncio.run( main.notification_expiry_sweep_loop() )
    assert naps == [ 300, 300 ] and len( work ) == 1      # tick 1 skipped (false), tick 2 swept (true)
    assert any( "is false" in line for line in ini.logged ) and any( "ticks run again" in line for line in ini.logged )


def test_the_notification_sweep_refuses_a_missing_key( tmp_path, monkeypatch ):
    ini, work = _Ini( tmp_path, "notification-expiry" ), []
    ini.path.write_text( "[Lupin]\n" )
    ini.wire( monkeypatch )
    shim, naps = _shim( [], ini, work )
    with mock.patch.object( main, "asyncio", shim ), mock.patch.object( main, "config_mgr", _Config() ):
        asyncio.run( main.notification_expiry_sweep_loop() )
    assert work == [] and naps == [ 300 ] and any( "ERROR" in line for line in ini.logged )


def _run_housekeeping( loop_name, work_name, flips, tmp_path, monkeypatch ):
    ini, work = _Ini( tmp_path, "socket-housekeeping" ), []
    ini.set( "false" )
    ini.wire( monkeypatch )
    manager = mock.MagicMock()
    manager.config_mgr.get = mock.MagicMock( return_value=1 )
    setattr( manager, work_name, mock.AsyncMock( side_effect=lambda: work.append( 1 ) or 0 ) )
    shim, naps = _shim( flips, ini, [] )
    with mock.patch.object( main, "asyncio", shim ), mock.patch.object( main, "websocket_manager", manager ):
        asyncio.run( getattr( main, loop_name )() )
    return work, naps


@pytest.mark.parametrize( "loop_name, work_name", [ ( "websocket_heartbeat_loop", "heartbeat_check" ), ( "websocket_cleanup_loop", "auto_cleanup" ) ] )
def test_the_socket_housekeeping_loops_do_no_work_while_their_switch_is_false( loop_name, work_name, tmp_path, monkeypatch ):
    work, naps = _run_housekeeping( loop_name, work_name, [ "false", "true" ], tmp_path, monkeypatch )
    assert len( naps ) == 3 and len( work ) == 1       # ticks 1 and 2 skipped, tick 3 ran


class _Stop:
    """Stands in for the archiver's stop event: wait() ends the loop after `ticks` waits."""

    def __init__( self, ticks, ini, flips ):
        self.ticks, self.ini, self.flips, self.waits = ticks, ini, flips, 0

    def wait( self, timeout=None ):
        self.waits += 1
        if self.waits > self.ticks: return True
        self.ini.set( self.flips[ self.waits - 1 ] )
        return False


def test_the_commons_archiver_rotates_nothing_while_its_switch_is_false( tmp_path, monkeypatch ):
    ini, rotated = _Ini( tmp_path, "commons-archival" ), []
    ini.set( "false" )
    archiver = commons_archival.CommonsArchiver( tmp_path, switch=ini.switch() )
    archiver._stop_event = _Stop( 2, ini, [ "false", "true" ] )
    archiver.rotate_once = lambda: rotated.append( 1 )
    archiver._run_loop()
    assert archiver._stop_event.waits == 3 and len( rotated ) == 1      # tick 1 skipped, tick 2 rotated


def test_the_commons_archiver_builds_its_own_switch_when_none_is_given( tmp_path, monkeypatch ):
    ini, rotated = _Ini( tmp_path, "commons-archival" ), []
    ini.set( "true" )
    ini.wire( monkeypatch )
    archiver = commons_archival.CommonsArchiver( tmp_path )
    archiver._stop_event = _Stop( 1, ini, [ "true" ] )
    archiver.rotate_once = lambda: rotated.append( 1 )
    archiver._run_loop()
    assert len( rotated ) == 1


def test_the_notify_outbox_flushes_nothing_while_its_switch_is_false( tmp_path ):
    ini, sent = _Ini( tmp_path, "notify-outbox" ), []
    outbox = str( tmp_path / "outbox" )
    notify_outbox.spool( types.SimpleNamespace( model_dump=lambda mode: { "idempotency_key": "k1", "text": "hello" } ), outbox )
    send = lambda request: sent.append( request ) or True
    ini.set( "false" )
    assert notify_outbox.flush_tick( ini.switch(), send, outbox, 600 ) is None
    assert sent == [] and len( notify_outbox.list_spooled( outbox ) ) == 1
    ini.set( "true" )
    stats = notify_outbox.flush_tick( ini.switch(), send, outbox, 600 )
    assert stats[ "delivered" ] == 1 and len( sent ) == 1


def test_a_flush_tick_that_raises_is_logged_and_survived( tmp_path ):
    class Boom:
        def allowed( self ): raise RuntimeError( "boom" )
    logger = mock.MagicMock()
    assert notify_outbox.flush_tick( Boom(), None, str( tmp_path ), 1, logger ) is None
    assert "boom" in logger.warning.call_args[ 0 ][ 0 ]
    assert notify_outbox.flush_tick( Boom(), None, str( tmp_path ), 1 ) is None      # no logger: still no raise


@pytest.mark.parametrize( "logger", [ None, mock.MagicMock() ] )
def test_start_flusher_builds_the_notify_outbox_switch( tmp_path, monkeypatch, logger ):
    built = []
    monkeypatch.setattr( csr, "for_job", lambda job, log=print: built.append( ( job, log ) ) or object() )
    monkeypatch.setattr( notify_outbox, "_flusher_started", False )
    monkeypatch.setattr( notify_outbox.threading, "Thread", lambda **kw: mock.MagicMock() )
    assert notify_outbox.start_flusher( lambda r: True, str( tmp_path ), 10, 30, logger ) is True
    assert built[ 0 ][ 0 ] == "notify-outbox"
    assert built[ 0 ][ 1 ] is ( print if logger is None else logger.warning )
    monkeypatch.setattr( notify_outbox, "_flusher_started", False )
