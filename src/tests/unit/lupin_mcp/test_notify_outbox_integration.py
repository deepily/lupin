"""
Integration-glue tests for the durable outbox wiring inside cosa_voice_mcp.

Covers _outbox_config / _outbox_dir_for_session / _outbox_send_fn /
_spool_failed_notify — every branch — with monkeypatched config + delivery
(no network, no real disk under /io). The outbox module itself is covered by
test_notify_outbox.py.

Venue: :7999-eligible (pure unit; mocks only).
"""

import types

import pytest

from lupin_mcp import cosa_voice_mcp as m


class TestOutboxConfig:

    def test_reads_ini_values( self ):
        cfg = m._outbox_config()
        assert cfg[ "enabled" ] is True
        assert cfg[ "dir" ] == "/io/notify-outbox"
        assert cfg[ "flush_interval" ] == 30
        assert cfg[ "ttl" ] == 86400

    def test_falls_back_to_defaults_on_cm_error( self, monkeypatch ):
        import cosa.config.configuration_manager as cm_mod
        def boom( *a, **k ):
            raise RuntimeError( "no config manager" )
        monkeypatch.setattr( cm_mod, "ConfigurationManager", boom )
        assert m._outbox_config() == m._OUTBOX_DEFAULTS


class TestOutboxDirForSession:

    def test_per_session_path_under_configured_dir( self ):
        cfg = dict( m._OUTBOX_DEFAULTS )
        d   = m._outbox_dir_for_session( cfg )
        assert "/io/notify-outbox/" in d            # configured dir, project-root-anchored
        sid = ( m.SESSION_ID or "default" ).replace( "/", "_" )
        assert d.endswith( sid )


class _FakeARQ:
    """Stand-in for AsyncNotificationRequest with a controllable model_validate."""
    _raise = False

    @staticmethod
    def model_validate( payload ):
        if _FakeARQ._raise:
            raise ValueError( "bad payload" )
        return "RECONSTRUCTED_REQ"


class TestOutboxSendFn:

    def test_returns_true_on_ack( self, monkeypatch ):
        _FakeARQ._raise = False
        monkeypatch.setattr( m, "AsyncNotificationRequest", _FakeARQ )
        monkeypatch.setattr( m, "notify_user_async", lambda request, debug=False: types.SimpleNamespace( success=True ) )
        assert m._outbox_send_fn( { "x": 1 } ) is True

    def test_returns_false_when_server_nacks( self, monkeypatch ):
        _FakeARQ._raise = False
        monkeypatch.setattr( m, "AsyncNotificationRequest", _FakeARQ )
        monkeypatch.setattr( m, "notify_user_async", lambda request, debug=False: types.SimpleNamespace( success=False ) )
        assert m._outbox_send_fn( { "x": 1 } ) is False

    def test_returns_false_on_exception( self, monkeypatch ):
        _FakeARQ._raise = True
        monkeypatch.setattr( m, "AsyncNotificationRequest", _FakeARQ )
        assert m._outbox_send_fn( { "x": 1 } ) is False
        _FakeARQ._raise = False


class TestSpoolFailedNotify:

    def test_disabled_returns_false( self, monkeypatch ):
        monkeypatch.setattr( m, "_outbox_config", lambda: { "enabled": False, "dir": "/io/x", "flush_interval": 30, "ttl": 10 } )
        assert m._spool_failed_notify( object() ) is False

    def test_enabled_spools_and_starts_flusher( self, monkeypatch, tmp_path ):
        calls = { "spool": 0, "flush": 0 }
        monkeypatch.setattr( m, "_outbox_config", lambda: { "enabled": True, "dir": "/io/x", "flush_interval": 30, "ttl": 10 } )
        monkeypatch.setattr( m, "_outbox_dir_for_session", lambda cfg: str( tmp_path ) )
        monkeypatch.setattr( m._notify_outbox, "spool", lambda req, d: calls.__setitem__( "spool", calls[ "spool" ] + 1 ) )
        monkeypatch.setattr( m._notify_outbox, "start_flusher", lambda *a, **k: calls.__setitem__( "flush", calls[ "flush" ] + 1 ) or True )
        assert m._spool_failed_notify( object() ) is True
        assert calls == { "spool": 1, "flush": 1 }

    def test_spool_error_returns_false_never_raises( self, monkeypatch, tmp_path ):
        monkeypatch.setattr( m, "_outbox_config", lambda: { "enabled": True, "dir": "/io/x", "flush_interval": 30, "ttl": 10 } )
        monkeypatch.setattr( m, "_outbox_dir_for_session", lambda cfg: str( tmp_path ) )
        def boom( req, d ):
            raise OSError( "disk full" )
        monkeypatch.setattr( m._notify_outbox, "spool", boom )
        assert m._spool_failed_notify( object() ) is False


class TestOutboxHasBacklog:

    def test_disabled_returns_false( self, monkeypatch ):
        monkeypatch.setattr( m, "_outbox_config", lambda: { "enabled": False, "dir": "/io/x", "flush_interval": 30, "ttl": 10 } )
        assert m._outbox_has_backlog() is False

    def test_empty_returns_false( self, monkeypatch ):
        monkeypatch.setattr( m, "_outbox_config", lambda: { "enabled": True, "dir": "/io/x", "flush_interval": 30, "ttl": 10 } )
        monkeypatch.setattr( m, "_outbox_dir_for_session", lambda cfg: "/tmp/none" )
        monkeypatch.setattr( m._notify_outbox, "list_spooled", lambda d: [] )
        assert m._outbox_has_backlog() is False

    def test_nonempty_returns_true( self, monkeypatch ):
        monkeypatch.setattr( m, "_outbox_config", lambda: { "enabled": True, "dir": "/io/x", "flush_interval": 30, "ttl": 10 } )
        monkeypatch.setattr( m, "_outbox_dir_for_session", lambda cfg: "/tmp/x" )
        monkeypatch.setattr( m._notify_outbox, "list_spooled", lambda d: [ "a.json" ] )
        assert m._outbox_has_backlog() is True

    def test_error_returns_false( self, monkeypatch ):
        def boom():
            raise RuntimeError( "config blew up" )
        monkeypatch.setattr( m, "_outbox_config", boom )
        assert m._outbox_has_backlog() is False


class TestNotifyImplSendPaths:
    """Exercise the _notify_impl send branches via _internal_call=True (skips the conv-mode gate)."""

    def _patch_sender( self, monkeypatch ):
        # Must satisfy the AsyncNotificationRequest sender_id pattern (…@…​.deepily.ai#<8hex>).
        monkeypatch.setattr( m, "_wait_for_sender_id", lambda: "claude.code@lupin.deepily.ai#1333e106" )

    def _ns( self, **kw ):
        return types.SimpleNamespace( **kw )

    def test_drain_first_queues_behind_backlog( self, monkeypatch ):
        self._patch_sender( monkeypatch )
        monkeypatch.setattr( m, "_outbox_has_backlog", lambda: True )
        marks = { "spool": 0, "sent": 0 }
        monkeypatch.setattr( m, "_spool_failed_notify", lambda req: marks.__setitem__( "spool", 1 ) or True )
        monkeypatch.setattr( m, "notify_user_async", lambda request, debug=False: marks.__setitem__( "sent", 1 ) or self._ns( success=True, status="ok", message="" ) )
        out = m._notify_impl( "hi", _internal_call=True )
        assert "Queued (ordered" in out
        assert marks == { "spool": 1, "sent": 0 }          # spooled, NOT sent live

    def test_drain_first_spool_fail_falls_through_to_live( self, monkeypatch ):
        self._patch_sender( monkeypatch )
        monkeypatch.setattr( m, "_outbox_has_backlog", lambda: True )
        monkeypatch.setattr( m, "_spool_failed_notify", lambda req: False )
        monkeypatch.setattr( m, "notify_user_async", lambda request, debug=False: self._ns( success=True, status="ok", message="" ) )
        out = m._notify_impl( "hi", _internal_call=True )
        assert "Notification sent" in out

    def test_live_success( self, monkeypatch ):
        self._patch_sender( monkeypatch )
        monkeypatch.setattr( m, "_outbox_has_backlog", lambda: False )
        monkeypatch.setattr( m, "notify_user_async", lambda request, debug=False: self._ns( success=True, status="queued", message="" ) )
        assert "Notification sent" in m._notify_impl( "hi", _internal_call=True )

    def test_live_failure_spooled( self, monkeypatch ):
        self._patch_sender( monkeypatch )
        monkeypatch.setattr( m, "_outbox_has_backlog", lambda: False )
        monkeypatch.setattr( m, "notify_user_async", lambda request, debug=False: self._ns( success=False, status="err", message="down" ) )
        monkeypatch.setattr( m, "_spool_failed_notify", lambda req: True )
        assert "Queued for durable retry" in m._notify_impl( "hi", _internal_call=True )

    def test_live_failure_not_spooled( self, monkeypatch ):
        self._patch_sender( monkeypatch )
        monkeypatch.setattr( m, "_outbox_has_backlog", lambda: False )
        monkeypatch.setattr( m, "notify_user_async", lambda request, debug=False: self._ns( success=False, status="err", message="down" ) )
        monkeypatch.setattr( m, "_spool_failed_notify", lambda req: False )
        assert m._notify_impl( "hi", _internal_call=True ).startswith( "Failed:" )
