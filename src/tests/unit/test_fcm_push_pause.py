#!/usr/bin/env python3
"""
Unit — the admin global mobile-push pause (row 7df08e59; design R1.6).

The mechanism has two halves and each is pinned separately:
    1. FcmWakeService.maybe_send_wake re-reads the LIVE `fcm wake push enabled` key on every
       call. `self.enabled` is a copy taken at startup, so without this a set_config() changes
       nothing the service looks at.
    2. cosa.rest.fcm_push_pause.PushPauseController + POST/GET /api/fcm/push-pause set the key
       False in memory (never the INI), arm ONE resume timer, and resume to the BOOT-TIME value.

Rick's ruling (R1.4): nothing is persisted; a restart ends the pause.

Venue: :7999 (pure unit — fake config, fake loop, injected transport, TestClient).
"""

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.fcm_push_pause as pause_mod
from cosa.rest.fcm_push_pause import PushPauseController, MAX_PAUSE_MINUTES, PUSH_ENABLED_KEY
from cosa.rest.fcm_wake_service import FcmWakeService
from cosa.rest.routers.fcm import router
from cosa.rest.auth_middleware import get_current_user


class _LiveConfig:
    """ConfigurationManager stand-in with a real in-memory set_config, like the singleton's."""

    def __init__( self, push_enabled=True ):
        self.values = { PUSH_ENABLED_KEY: push_enabled }

    def get( self, key, default=None, return_type=None, silent=False ):
        return self.values.get( key, default )

    def set_config( self, key, value ):
        self.values[ key ] = value


class _FakeHandle:
    def __init__( self ): self.cancelled = False
    def cancel( self ): self.cancelled = True


class _FakeLoop:
    """Records call_later so a test can inspect the delay and fire the callback by hand."""

    def __init__( self ): self.scheduled = []

    def call_later( self, delay, callback ):
        handle = _FakeHandle()
        self.scheduled.append( ( delay, callback, handle ) )
        return handle


def _wake_service( config, tokens=( "tok-1", ), mobile_live=False ):
    """A service with injected collaborators; returns (service, sent, calls)."""
    sent, calls = [], { "liveness": 0, "lookup": 0 }

    def _liveness( u ):
        calls[ "liveness" ] += 1
        return mobile_live

    def _lookup( u ):
        calls[ "lookup" ] += 1
        return list( tokens )

    service = FcmWakeService( config, token_lookup=_lookup, mobile_liveness=_liveness,
                              transport=lambda t, d: sent.append( ( t, d ) ) )
    return service, sent, calls


# ── 1. the service re-reads the live key on every call ───────────────────────

class TestServiceReadsTheLiveKey:

    def test_pausing_through_the_config_makes_maybe_send_wake_return_paused_and_resuming_restores_sent( self ):
        config = _LiveConfig()
        service, sent, calls = _wake_service( config )

        config.set_config( PUSH_ENABLED_KEY, False )
        assert service.maybe_send_wake( "u1" ) == "paused"
        service._executor.shutdown( wait=True )
        # Paused means NOTHING ran: no transport, no token lookup, no liveness check.
        assert sent == [] and calls == { "liveness": 0, "lookup": 0 }

        config.set_config( PUSH_ENABLED_KEY, True )
        service2, sent2, _ = _wake_service( config )   # fresh service: the paused call burned no debounce slot either
        assert service2.maybe_send_wake( "u1" ) == "submitted"
        service2._executor.shutdown( wait=True )
        assert [ t for t, _d in sent2 ] == [ "tok-1" ]

    def test_a_paused_call_burns_no_debounce_slot_so_resume_sends_at_once( self ):
        config = _LiveConfig()
        service, sent, _ = _wake_service( config )
        config.set_config( PUSH_ENABLED_KEY, False )
        assert service.maybe_send_wake( "u1" ) == "paused"
        config.set_config( PUSH_ENABLED_KEY, True )
        assert service.maybe_send_wake( "u1" ) == "submitted"   # "debounced"/"deferred" would mean the pause spent the window
        service._executor.shutdown( wait=True )
        assert len( sent ) == 1

    def test_a_pause_that_lands_after_construction_still_stops_the_wake( self ):
        """THE MUTANT TARGET. `self.enabled` alone is the startup copy: with the key read only
        once, this call would return "submitted". Going back to `self.enabled` alone must
        turn THIS test red (verified 2026-09-29, recorded in the commit)."""
        config = _LiveConfig( push_enabled=True )
        service, sent, _ = _wake_service( config )
        assert service.enabled is True                       # the startup copy says on
        config.set_config( PUSH_ENABLED_KEY, False )         # the running process is told otherwise
        assert service.maybe_send_wake( "u1" ) == "paused"
        service._executor.shutdown( wait=True )
        assert sent == []

    def test_a_pause_stops_a_trailing_wake_already_scheduled( self ):
        config = _LiveConfig()
        service, sent, _ = _wake_service( config )
        assert service.maybe_send_wake( "u1" ) == "submitted"    # opens the window
        assert service.maybe_send_wake( "u1" ) == "deferred"     # arms the trailing wake
        config.set_config( PUSH_ENABLED_KEY, False )
        # The trailing timer re-enters maybe_send_wake; a paused server must stop it there.
        assert service.maybe_send_wake( "u1" ) == "paused"
        service.shutdown()
        assert len( sent ) <= 1


# ── 2. the controller: timer, replace, cancel, boot value ────────────────────

class TestController:

    def test_pause_sets_the_key_false_and_arms_one_timer_for_minutes_times_sixty( self ):
        config, loop = _LiveConfig(), _FakeLoop()
        c = PushPauseController( config )
        state = c.pause( 2, "admin@x", loop )
        assert config.values[ PUSH_ENABLED_KEY ] is False
        assert [ d for d, _cb, _h in loop.scheduled ] == [ 120 ]
        assert state[ "paused" ] is True and state[ "set_by" ] == "admin@x" and state[ "push_enabled" ] is False

    def test_the_timer_resumes_after_its_delay( self ):
        config, loop = _LiveConfig(), _FakeLoop()
        c = PushPauseController( config )
        c.pause( 1, "admin@x", loop )
        _delay, fire, _h = loop.scheduled[ 0 ]
        fire()
        assert config.values[ PUSH_ENABLED_KEY ] is True
        assert c.status()[ "paused" ] is False and c.status()[ "resumes_at" ] is None

    def test_the_timer_works_on_a_real_event_loop( self ):
        """The fake loop proves the wiring; this proves the real call_later actually resumes."""
        config = _LiveConfig()
        c = PushPauseController( config )

        async def _drive():
            loop = asyncio.get_running_loop()
            c.pause( 1, "admin@x", _ShortLoop( loop ) )   # 1 minute, compressed to 50 ms
            await asyncio.sleep( 0.2 )

        asyncio.run( _drive() )
        assert config.values[ PUSH_ENABLED_KEY ] is True

    def test_a_second_pause_cancels_the_first_timer_before_arming_its_own( self ):
        config, loop = _LiveConfig(), _FakeLoop()
        c = PushPauseController( config )
        c.pause( 5, "a", loop )
        c.pause( 10, "b", loop )
        first, second = loop.scheduled[ 0 ][ 2 ], loop.scheduled[ 1 ][ 2 ]
        assert first.cancelled is True and second.cancelled is False
        assert c.status()[ "set_by" ] == "b"

    def test_an_explicit_resume_cancels_the_timer_and_restores_the_key( self ):
        config, loop = _LiveConfig(), _FakeLoop()
        c = PushPauseController( config )
        c.pause( 5, "a", loop )
        state = c.resume( "a" )
        assert loop.scheduled[ 0 ][ 2 ].cancelled is True
        assert config.values[ PUSH_ENABLED_KEY ] is True and state[ "paused" ] is False

    def test_a_pause_without_minutes_arms_no_timer_and_reports_no_end_time( self ):
        config, loop = _LiveConfig(), _FakeLoop()
        c = PushPauseController( config )
        state = c.pause( None, "a", loop )
        assert loop.scheduled == [] and state[ "resumes_at" ] is None and state[ "paused" ] is True

    def test_resumes_at_is_now_plus_minutes( self ):
        now = datetime( 2026, 9, 29, 12, 0, tzinfo=timezone.utc )
        c = PushPauseController( _LiveConfig(), clock=lambda: now )
        state = c.pause( 90, "a", _FakeLoop() )
        assert state[ "resumes_at" ] == ( now + timedelta( minutes=90 ) ).isoformat()
        assert state[ "set_at" ] == now.isoformat()

    def test_resume_restores_the_boot_time_value_not_a_hard_coded_true( self ):
        config, loop = _LiveConfig( push_enabled=False ), _FakeLoop()   # the file says OFF
        c = PushPauseController( config )
        assert c.boot_value is False
        c.pause( 1, "a", loop )
        loop.scheduled[ 0 ][ 1 ]()                                     # timer resume
        assert config.values[ PUSH_ENABLED_KEY ] is False
        c.pause( None, "a", loop )
        c.resume( "a" )                                                # explicit resume
        assert config.values[ PUSH_ENABLED_KEY ] is False

    @pytest.mark.parametrize( "minutes", [ 0, -5, MAX_PAUSE_MINUTES + 1 ] )
    def test_minutes_outside_one_to_the_cap_is_refused_and_changes_nothing( self, minutes ):
        config, loop = _LiveConfig(), _FakeLoop()
        c = PushPauseController( config )
        with pytest.raises( ValueError ):
            c.pause( minutes, "a", loop )
        assert config.values[ PUSH_ENABLED_KEY ] is True and loop.scheduled == []

    def test_shutdown_logs_an_active_pause_and_cancels_its_timer( self, capsys ):
        config, loop = _LiveConfig(), _FakeLoop()
        c = PushPauseController( config )
        c.pause( 30, "admin@x", loop )
        capsys.readouterr()
        c.shutdown()
        out = capsys.readouterr().out
        assert "push pause ACTIVE" in out and "admin@x" in out and "not persisted" in out
        assert loop.scheduled[ 0 ][ 2 ].cancelled is True

    def test_shutdown_with_no_pause_logs_nothing( self, capsys ):
        c = PushPauseController( _LiveConfig() )
        c.shutdown()
        assert capsys.readouterr().out == ""

    def test_shutdown_with_an_untimed_pause_names_no_end_time( self, capsys ):
        c = PushPauseController( _LiveConfig() )
        c.pause( None, "a", _FakeLoop() )
        capsys.readouterr()
        c.shutdown()
        assert "no end time" in capsys.readouterr().out


class _ShortLoop:
    """Wraps a real loop so `minutes * 60` seconds becomes 50 ms; the timer machinery stays real."""

    def __init__( self, loop ): self._loop = loop
    def call_later( self, delay, callback ): return self._loop.call_later( 0.05, callback )


class TestControllerRegistry:

    def test_init_controller_replaces_the_process_wide_controller( self ):
        first  = pause_mod.init_controller( _LiveConfig() )
        second = pause_mod.init_controller( _LiveConfig() )
        assert pause_mod.get_controller() is second and second is not first

    def test_get_controller_builds_from_the_live_config_when_startup_never_did( self, monkeypatch ):
        config = _LiveConfig( push_enabled=True )
        import cosa.config.configuration_manager as cm

        class _Stub:
            def __new__( cls, *a, **kw ): return config

        monkeypatch.setattr( cm, "ConfigurationManager", _Stub )
        monkeypatch.setattr( pause_mod, "_controller", None )
        built = pause_mod.get_controller()
        assert built.boot_value is True and pause_mod.get_controller() is built


# ── 3. the endpoint ──────────────────────────────────────────────────────────

ADMIN = { "uid": "u-admin", "email": "admin@example.com", "roles": [ "admin", "user" ] }
USER  = { "uid": "u-user",  "email": "user@example.com",  "roles": [ "user" ] }


@pytest.fixture
def api():
    config = _LiveConfig()
    pause_mod.init_controller( config )
    app = FastAPI()
    app.include_router( router )
    who = { "user": ADMIN }
    app.dependency_overrides[ get_current_user ] = lambda: who[ "user" ]
    with TestClient( app ) as client:     # `with` keeps ONE event loop alive across requests
        yield client, config, who
    app.dependency_overrides.clear()


class TestEndpoint:

    def test_a_non_admin_is_refused_403_on_both_verbs_and_nothing_changes( self, api ):
        client, config, who = api
        who[ "user" ] = USER
        assert client.post( "/api/fcm/push-pause", json={ "paused": True } ).status_code == 403
        assert client.get( "/api/fcm/push-pause" ).status_code == 403
        assert config.values[ PUSH_ENABLED_KEY ] is True

    def test_minutes_above_the_cap_is_400_and_the_cap_itself_is_accepted( self, api ):
        client, config, _ = api
        over = client.post( "/api/fcm/push-pause", json={ "paused": True, "minutes": MAX_PAUSE_MINUTES + 1 } )
        assert over.status_code == 400 and "1440" in over.json()[ "detail" ]
        assert config.values[ PUSH_ENABLED_KEY ] is True
        at = client.post( "/api/fcm/push-pause", json={ "paused": True, "minutes": MAX_PAUSE_MINUTES } )
        assert at.status_code == 200

    def test_zero_minutes_is_400( self, api ):
        client, _, _ = api
        assert client.post( "/api/fcm/push-pause", json={ "paused": True, "minutes": 0 } ).status_code == 400

    def test_a_body_without_paused_is_422( self, api ):
        client, _, _ = api
        assert client.post( "/api/fcm/push-pause", json={ "minutes": 5 } ).status_code == 422

    def test_get_reports_exactly_what_post_set( self, api ):
        client, config, _ = api
        posted = client.post( "/api/fcm/push-pause", json={ "paused": True, "minutes": 120 } ).json()
        got    = client.get( "/api/fcm/push-pause" ).json()
        assert got == posted
        assert got[ "paused" ] is True and got[ "set_by" ] == "admin@example.com" and got[ "push_enabled" ] is False
        assert got[ "resumes_at" ] is not None
        assert config.values[ PUSH_ENABLED_KEY ] is False

    def test_paused_false_resumes_now_and_get_agrees( self, api ):
        client, config, _ = api
        client.post( "/api/fcm/push-pause", json={ "paused": True, "minutes": 120 } )
        resumed = client.post( "/api/fcm/push-pause", json={ "paused": False } ).json()
        assert resumed[ "paused" ] is False and resumed[ "push_enabled" ] is True
        assert client.get( "/api/fcm/push-pause" ).json() == resumed
        assert config.values[ PUSH_ENABLED_KEY ] is True

    def test_the_actor_falls_back_to_the_uid_then_to_unknown( self, api ):
        client, _, who = api
        who[ "user" ] = { "uid": "u-only", "roles": [ "admin" ] }
        assert client.post( "/api/fcm/push-pause", json={ "paused": True } ).json()[ "set_by" ] == "u-only"
        who[ "user" ] = { "roles": [ "admin" ] }
        assert client.post( "/api/fcm/push-pause", json={ "paused": True } ).json()[ "set_by" ] == "unknown"


# ── 4. the INI file on disk is never touched ─────────────────────────────────

class TestIniIsNeverWritten:

    def test_the_ini_file_is_byte_identical_after_a_pause_and_a_resume( self ):
        from cosa.config.configuration_manager import ConfigurationManager

        ini = "[default]\nfcm wake push enabled = True\napp debug = False\n"
        with tempfile.TemporaryDirectory() as tmp:
            config_path   = os.path.join( tmp, "main.ini" )
            splainer_path = os.path.join( tmp, "splainer.ini" )
            with open( config_path, "w" ) as f:   f.write( ini )
            with open( splainer_path, "w" ) as f: f.write( "[default]\napp debug = Debug switch.\n\n[app debug]\n" )
            before = open( config_path, "rb" ).read()
            try:
                config = ConfigurationManager( config_path=config_path, splainer_path=splainer_path,
                                               config_block_id="default", silent=True, _reset_singleton=True )
                c = PushPauseController( config )
                assert c.boot_value is True
                c.pause( 1, "a", _FakeLoop() )
                # Positive control: the change IS real in memory, so an unchanged file means
                # "never written", not "never changed".
                assert config.get( PUSH_ENABLED_KEY, default=True, return_type="boolean", silent=True ) is False
                c.resume( "a" )
                assert config.get( PUSH_ENABLED_KEY, default=True, return_type="boolean", silent=True ) is True
            finally:
                ConfigurationManager.reset_for_testing()
            assert open( config_path, "rb" ).read() == before
