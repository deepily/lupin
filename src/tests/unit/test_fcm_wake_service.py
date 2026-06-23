#!/usr/bin/env python3
"""
Unit — FcmWakeService (S6 silent-relay wake sender).

Pins:
    - AC-S6.2 policy arms: fires with no mobile WS, suppressed by a live mobile
      WS, NOT suppressed by web-only (the liveness callable answers mobile-only),
      debounce inside the window
    - AC-S6.3 contract: data-only payload {type, reason, ts}, two-value reason
      enum, android priority HIGH at the real-transport seam
    - OSQ-7 tolerance: every Firebase-absent arm boots DISABLED with a named
      reason and never raises

Venue: :7999 (pure unit — fake config, fake firebase modules, injected transports).
"""

import os
import sys
import time
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.fcm_wake_service import (
    FcmWakeService, build_wake_payload,
    WAKE_REASONS, WAKE_REASON_UNDELIVERED, WAKE_REASON_RECONNECT_HINT,
    FIREBASE_APP_NAME
)


class _FakeConfig:
    """ConfigurationManager stand-in returning canned values per key."""

    def __init__( self, overrides=None ):
        self._overrides = overrides or {}

    def get( self, key, default=None, return_type=None, silent=False ):
        return self._overrides.get( key, default )


def _service( monkeypatch=None, overrides=None, tokens=None, mobile_live=False,
              transport="capture", debug=False, verbose=False ):
    """Build an FcmWakeService with simple injected collaborators; returns (service, sent)."""
    sent = []
    transport_fn = ( lambda t, d: sent.append( ( t, d ) ) ) if transport == "capture" else transport
    service = FcmWakeService(
        _FakeConfig( overrides ),
        token_lookup    = lambda u: list( tokens or [] ),
        mobile_liveness = lambda u: mobile_live,
        transport       = transport_fn,
        debug           = debug,
        verbose         = verbose
    )
    return service, sent


def _install_fake_firebase( monkeypatch, get_app_exists=False, certificate_error=None ):
    """Inject a fake firebase_admin module tree into sys.modules; returns the fakes."""
    fake_admin       = MagicMock( name="firebase_admin" )
    fake_credentials = MagicMock( name="credentials" )
    fake_messaging   = MagicMock( name="messaging" )

    if certificate_error is not None:
        fake_credentials.Certificate.side_effect = certificate_error
    if get_app_exists:
        fake_admin.get_app.return_value = "existing-app"
    else:
        fake_admin.get_app.side_effect = ValueError( "app does not exist" )
    fake_admin.initialize_app.return_value = "new-app"

    fake_admin.credentials = fake_credentials
    fake_admin.messaging   = fake_messaging
    monkeypatch.setitem( sys.modules, "firebase_admin", fake_admin )
    return fake_admin, fake_credentials, fake_messaging


# ── build_wake_payload (AC-S6.3 contract pin) ────────────────────────────────

class TestBuildWakePayload:

    def test_payload_is_exactly_the_contract_keys( self ):
        payload = build_wake_payload( WAKE_REASON_UNDELIVERED )
        assert set( payload.keys() ) == { "type", "reason", "ts" }

    def test_type_is_ws_wake( self ):
        assert build_wake_payload( WAKE_REASON_UNDELIVERED )[ "type" ] == "ws_wake"

    def test_both_enum_values_accepted( self ):
        assert build_wake_payload( WAKE_REASON_UNDELIVERED )[ "reason" ]    == "undelivered"
        assert build_wake_payload( WAKE_REASON_RECONNECT_HINT )[ "reason" ] == "reconnect-hint"

    def test_enum_is_exactly_two_values( self ):
        assert WAKE_REASONS == ( "undelivered", "reconnect-hint" )

    def test_non_enum_reason_raises( self ):
        with pytest.raises( ValueError ):
            build_wake_payload( "new-message" )

    def test_all_values_are_strings_and_content_free( self ):
        payload = build_wake_payload( WAKE_REASON_RECONNECT_HINT )
        assert all( isinstance( v, str ) for v in payload.values() )
        # ISO-8601 ts sanity
        assert "T" in payload[ "ts" ]


# ── Construction / disabled arms (OSQ-7 tolerance) ───────────────────────────

class TestConstructionArms:

    def test_master_switch_off_disables( self ):
        service, _ = _service( overrides={ "fcm wake push enabled": False } )
        assert service.enabled is False
        assert "master switch" in service.disabled_reason

    def test_injected_transport_enables( self ):
        service, _ = _service()
        assert service.enabled is True and service.disabled_reason is None

    def test_injected_transport_enables_with_debug( self, capsys ):
        service, _ = _service( debug=True )
        assert service.enabled is True
        assert "injected transport" in capsys.readouterr().out

    def test_env_var_unset_disables( self, monkeypatch ):
        monkeypatch.delenv( "FCM_SERVICE_ACCOUNT_JSON", raising=False )
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [], mobile_liveness=lambda u: False )
        assert service.enabled is False
        assert "FCM_SERVICE_ACCOUNT_JSON" in service.disabled_reason
        assert "not set" in service.disabled_reason

    def test_credentials_file_missing_disables( self, monkeypatch, tmp_path ):
        monkeypatch.setenv( "FCM_SERVICE_ACCOUNT_JSON", str( tmp_path / "nope.json" ) )
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [], mobile_liveness=lambda u: False )
        assert service.enabled is False
        assert "not found" in service.disabled_reason

    def test_module_missing_disables( self, monkeypatch, tmp_path ):
        creds = tmp_path / "sa.json"
        creds.write_text( "{}" )
        monkeypatch.setenv( "FCM_SERVICE_ACCOUNT_JSON", str( creds ) )
        # Block the import even if firebase_admin ever gets installed
        monkeypatch.setitem( sys.modules, "firebase_admin", None )
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [], mobile_liveness=lambda u: False )
        assert service.enabled is False
        assert "not importable" in service.disabled_reason

    def test_init_failure_disables( self, monkeypatch, tmp_path ):
        creds = tmp_path / "sa.json"
        creds.write_text( "{}" )
        monkeypatch.setenv( "FCM_SERVICE_ACCOUNT_JSON", str( creds ) )
        _install_fake_firebase( monkeypatch, certificate_error=RuntimeError( "malformed service account" ) )
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [], mobile_liveness=lambda u: False )
        assert service.enabled is False
        assert "Firebase init failed" in service.disabled_reason

    def test_custom_env_var_name_from_ini( self, monkeypatch ):
        monkeypatch.delenv( "MY_FCM_CREDS", raising=False )
        service = FcmWakeService(
            _FakeConfig( { "fcm service account credentials env var": "MY_FCM_CREDS" } ),
            token_lookup=lambda u: [], mobile_liveness=lambda u: False
        )
        assert service.enabled is False
        assert "MY_FCM_CREDS" in service.disabled_reason

    def test_debounce_window_loaded_from_ini( self ):
        service, _ = _service( overrides={ "fcm wake debounce seconds": 7 } )
        assert service.debounce_seconds == 7

    def test_auth_mode_defaults_to_key_file( self ):
        service, _ = _service()
        assert service._auth_mode == "key_file"

    def test_auth_mode_loaded_from_ini( self ):
        service, _ = _service( overrides={ "fcm wake auth mode": "adc" } )
        assert service._auth_mode == "adc"


# ── Real-transport init success (fake firebase) + AC-S6.3 priority pin ───────

class TestRealTransport:

    def _enabled_real_service( self, monkeypatch, tmp_path, get_app_exists=False ):
        creds = tmp_path / "sa.json"
        creds.write_text( "{}" )
        monkeypatch.setenv( "FCM_SERVICE_ACCOUNT_JSON", str( creds ) )
        fakes   = _install_fake_firebase( monkeypatch, get_app_exists=get_app_exists )
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [ "tok-A" ], mobile_liveness=lambda u: False )
        return service, fakes

    def test_init_success_creates_named_app( self, monkeypatch, tmp_path ):
        service, ( fake_admin, fake_credentials, _ ) = self._enabled_real_service( monkeypatch, tmp_path )
        assert service.enabled is True
        fake_admin.initialize_app.assert_called_once()
        _args, kwargs = fake_admin.initialize_app.call_args
        assert kwargs[ "name" ] == FIREBASE_APP_NAME

    def test_init_reuses_existing_named_app( self, monkeypatch, tmp_path ):
        service, ( fake_admin, _, _ ) = self._enabled_real_service( monkeypatch, tmp_path, get_app_exists=True )
        assert service.enabled is True
        fake_admin.initialize_app.assert_not_called()

    def test_real_transport_sends_data_only_high_priority( self, monkeypatch, tmp_path ):
        service, ( fake_admin, _, fake_messaging ) = self._enabled_real_service( monkeypatch, tmp_path )

        payload = build_wake_payload( WAKE_REASON_UNDELIVERED )
        service._transport( "tok-A", payload )

        # AC-S6.3: Message built with token + data ONLY (no notification block),
        # AndroidConfig at high priority, sent on the named app.
        _args, kwargs = fake_messaging.Message.call_args
        assert kwargs[ "token" ] == "tok-A"
        assert kwargs[ "data" ]  == payload
        assert "notification" not in kwargs
        _aargs, akwargs = fake_messaging.AndroidConfig.call_args
        assert akwargs[ "priority" ] == "high"
        _sargs, skwargs = fake_messaging.send.call_args
        assert skwargs[ "app" ] == "new-app"


# ── ADC (keyless) real-transport init — feature-flag fork ────────────────────

class TestAdcAuthMode:
    """
    The keyless ADC auth path (org policy iam.disableServiceAccountKeyCreation
    blocks downloaded keys). No key FILE, no env var: credentials resolve via
    firebase_admin.credentials.ApplicationDefault(), then the SAME named-app +
    messaging transport flow as key_file mode.
    """

    def _adc_service( self, monkeypatch, get_app_exists=False, adc_error=None ):
        """Build an ADC-mode service against fake firebase; no env var / file set."""
        # ADC mode must NOT consult the env var — prove it by clearing it.
        monkeypatch.delenv( "FCM_SERVICE_ACCOUNT_JSON", raising=False )
        fakes = _install_fake_firebase( monkeypatch, get_app_exists=get_app_exists )
        _fake_admin, fake_credentials, _fake_messaging = fakes
        if adc_error is not None:
            fake_credentials.ApplicationDefault.side_effect = adc_error
        service = FcmWakeService(
            _FakeConfig( { "fcm wake auth mode": "adc" } ),
            token_lookup    = lambda u: [ "tok-A" ],
            mobile_liveness = lambda u: False
        )
        return service, fakes

    def test_adc_init_success_creates_named_app( self, monkeypatch ):
        service, ( fake_admin, fake_credentials, _ ) = self._adc_service( monkeypatch )
        assert service.enabled is True and service.disabled_reason is None
        fake_credentials.ApplicationDefault.assert_called_once()
        # Key-file path must NOT have been consulted in ADC mode.
        fake_credentials.Certificate.assert_not_called()
        fake_admin.initialize_app.assert_called_once()
        _args, kwargs = fake_admin.initialize_app.call_args
        assert kwargs[ "name" ] == FIREBASE_APP_NAME

    def test_adc_init_reuses_existing_named_app( self, monkeypatch ):
        service, ( fake_admin, _, _ ) = self._adc_service( monkeypatch, get_app_exists=True )
        assert service.enabled is True
        fake_admin.initialize_app.assert_not_called()

    def test_adc_enabled_log_line_names_adc( self, monkeypatch, capsys ):
        self._adc_service( monkeypatch )
        out = capsys.readouterr().out
        assert "[FCM-WAKE] Enabled" in out and "(ADC)" in out

    def test_adc_transport_sends_data_only_high_priority( self, monkeypatch ):
        service, ( _fake_admin, _, fake_messaging ) = self._adc_service( monkeypatch )
        payload = build_wake_payload( WAKE_REASON_UNDELIVERED )
        service._transport( "tok-A", payload )

        _args, kwargs = fake_messaging.Message.call_args
        assert kwargs[ "token" ] == "tok-A"
        assert kwargs[ "data" ]  == payload
        assert "notification" not in kwargs
        _aargs, akwargs = fake_messaging.AndroidConfig.call_args
        assert akwargs[ "priority" ] == "high"
        _sargs, skwargs = fake_messaging.send.call_args
        assert skwargs[ "app" ] == "new-app"

    def test_adc_resolution_failure_disables( self, monkeypatch ):
        service, _ = self._adc_service( monkeypatch, adc_error=RuntimeError( "no metadata server" ) )
        assert service.enabled is False
        assert "Application Default Credentials could not be resolved" in service.disabled_reason

    def test_adc_init_app_failure_disables( self, monkeypatch ):
        # ApplicationDefault() resolves, but initialize_app() then errors.
        fakes = _install_fake_firebase( monkeypatch )
        fake_admin, _fake_credentials, _ = fakes
        fake_admin.initialize_app.side_effect = RuntimeError( "project mismatch" )
        service = FcmWakeService(
            _FakeConfig( { "fcm wake auth mode": "adc" } ),
            token_lookup=lambda u: [], mobile_liveness=lambda u: False
        )
        assert service.enabled is False
        assert "Firebase init failed (ADC)" in service.disabled_reason

    def test_adc_module_missing_disables( self, monkeypatch ):
        monkeypatch.setitem( sys.modules, "firebase_admin", None )
        service = FcmWakeService(
            _FakeConfig( { "fcm wake auth mode": "adc" } ),
            token_lookup=lambda u: [], mobile_liveness=lambda u: False
        )
        assert service.enabled is False
        assert "not importable" in service.disabled_reason

    def test_key_file_mode_does_not_call_application_default( self, monkeypatch, tmp_path ):
        # Belt-and-suspenders: explicit key_file mode never touches ADC.
        creds = tmp_path / "sa.json"
        creds.write_text( "{}" )
        monkeypatch.setenv( "FCM_SERVICE_ACCOUNT_JSON", str( creds ) )
        _fake_admin, fake_credentials, _ = _install_fake_firebase( monkeypatch )
        service = FcmWakeService(
            _FakeConfig( { "fcm wake auth mode": "key_file" } ),
            token_lookup=lambda u: [], mobile_liveness=lambda u: False
        )
        assert service.enabled is True
        fake_credentials.Certificate.assert_called_once()
        fake_credentials.ApplicationDefault.assert_not_called()


# ── maybe_send_wake policy arms (AC-S6.2) ────────────────────────────────────

class TestMaybeSendWakePolicy:

    def test_disabled_short_circuits( self ):
        service, sent = _service( overrides={ "fcm wake push enabled": False }, tokens=[ "tok-1" ] )
        assert service.maybe_send_wake( "u1" ) == "disabled"
        assert sent == []

    def test_live_mobile_ws_suppresses( self ):
        service, sent = _service( tokens=[ "tok-1" ], mobile_live=True )
        assert service.maybe_send_wake( "u1" ) == "mobile_ws_live"
        assert sent == []

    def test_live_mobile_ws_suppresses_verbose_branch( self, capsys ):
        service, _ = _service( tokens=[ "tok-1" ], mobile_live=True, debug=True, verbose=True )
        assert service.maybe_send_wake( "u1" ) == "mobile_ws_live"
        assert "live mobile WS" in capsys.readouterr().out

    def test_web_only_user_still_wakes( self ):
        # The liveness callable answers MOBILE liveness only — a user with a
        # live web/desktop WS reports False here, so the wake fires (§3.0).
        service, sent = _service( tokens=[ "tok-1" ], mobile_live=False )
        assert service.maybe_send_wake( "u1" ) == "submitted"
        service._executor.shutdown( wait=True )
        assert [ t for t, _d in sent ] == [ "tok-1" ]

    def test_no_tokens_arm( self ):
        service, sent = _service( tokens=[] )
        assert service.maybe_send_wake( "u1" ) == "no_tokens"
        assert sent == []

    def test_debounce_suppresses_second_wake( self ):
        service, sent = _service( tokens=[ "tok-1" ] )
        assert service.maybe_send_wake( "u1" ) == "submitted"
        assert service.maybe_send_wake( "u1" ) == "debounced"
        service._executor.shutdown( wait=True )
        assert len( sent ) == 1

    def test_debounce_suppresses_second_wake_verbose_branch( self, capsys ):
        service, _ = _service( tokens=[ "tok-1" ], debug=True, verbose=True )
        service.maybe_send_wake( "u1" )
        assert service.maybe_send_wake( "u1" ) == "debounced"
        service._executor.shutdown( wait=True )
        assert "Debounced" in capsys.readouterr().out

    def test_debounce_is_per_user( self ):
        service, sent = _service( tokens=[ "tok-1" ] )
        assert service.maybe_send_wake( "u1" ) == "submitted"
        assert service.maybe_send_wake( "u2" ) == "submitted"
        service._executor.shutdown( wait=True )
        assert len( sent ) == 2

    def test_wake_allowed_after_window_expires( self ):
        service, sent = _service( tokens=[ "tok-1" ] )
        service.maybe_send_wake( "u1" )
        # Age the recorded attempt past the window instead of sleeping
        service._last_wake_at[ "u1" ] = time.monotonic() - ( service.debounce_seconds + 1 )
        assert service.maybe_send_wake( "u1" ) == "submitted"
        service._executor.shutdown( wait=True )
        assert len( sent ) == 2

    def test_no_token_attempt_burns_debounce_slot( self ):
        # Documented trade-off: the slot is burned at attempt time, even when
        # the token lookup then comes up empty.
        service, _ = _service( tokens=[] )
        assert service.maybe_send_wake( "u1" ) == "no_tokens"
        assert service.maybe_send_wake( "u1" ) == "debounced"

    def test_liveness_failure_returns_error_not_raise( self ):
        def boom( user_id ):
            raise RuntimeError( "ws manager exploded" )
        service = FcmWakeService( _FakeConfig(), token_lookup=lambda u: [ "tok-1" ],
                                  mobile_liveness=boom, transport=lambda t, d: None )
        assert service.maybe_send_wake( "u1" ) == "error"

    def test_token_lookup_failure_returns_error_not_raise( self ):
        def boom( user_id ):
            raise RuntimeError( "db down" )
        service = FcmWakeService( _FakeConfig(), token_lookup=boom,
                                  mobile_liveness=lambda u: False, transport=lambda t, d: None )
        assert service.maybe_send_wake( "u1" ) == "error"

    def test_submitted_debug_branch( self, capsys ):
        service, _ = _service( tokens=[ "tok-1" ], debug=True )
        assert service.maybe_send_wake( "u1" ) == "submitted"
        service._executor.shutdown( wait=True )
        assert "Wake submitted" in capsys.readouterr().out

    def test_payload_reaching_transport_is_contract_shaped( self ):
        service, sent = _service( tokens=[ "tok-1" ] )
        service.maybe_send_wake( "u1", reason=WAKE_REASON_RECONNECT_HINT )
        service._executor.shutdown( wait=True )
        _token, payload = sent[ 0 ]
        assert set( payload.keys() ) == { "type", "reason", "ts" }
        assert payload[ "reason" ] == "reconnect-hint"


# ── _send_to_all delivery semantics ──────────────────────────────────────────

class TestSendToAll:

    def test_sends_to_every_token( self ):
        service, sent = _service()
        count = service._send_to_all( "u1", [ "tok-1", "tok-2", "tok-3" ], { "type": "ws_wake" } )
        assert count == 3
        assert [ t for t, _d in sent ] == [ "tok-1", "tok-2", "tok-3" ]

    def test_one_dead_token_does_not_mask_live_devices( self, capsys ):
        calls = []
        def flaky( token, data ):
            if token == "tok-dead":
                raise RuntimeError( "UNREGISTERED" )
            calls.append( token )
        service, _ = _service( transport=flaky )
        count = service._send_to_all( "u1", [ "tok-dead", "tok-live" ], { "type": "ws_wake" } )
        assert count == 1
        assert calls == [ "tok-live" ]
        assert "Send failed" in capsys.readouterr().out

    def test_debug_summary_branch( self, capsys ):
        service, _ = _service( debug=True )
        service._send_to_all( "u1", [ "tok-1" ], { "type": "ws_wake" } )
        assert "Wake delivered" in capsys.readouterr().out


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
