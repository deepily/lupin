#!/usr/bin/env python3
"""
Unit tests for the lupin-arbiter-app app + section-keyed local store (L1, evolved in L2).

Venue: :7999-eligible (pure in-process TestClient — no network, no persistent
state mutation, no real threads/docker; the health_loop is a fake). Coverage
target: 100% line+branch+function on app.py + local_snapshot_store.py.

NO curl (TestClient only).
"""
import datetime

from fastapi.testclient import TestClient

from lupin_arbiter_app import __version__
from lupin_arbiter_app.app import create_app, assemble_app, _utcnow, _make_health_notify_fn
from lupin_arbiter_app.health_watcher import HealthWatcherLoop
from lupin_arbiter_app.fleet_arbiter_loop import FleetArbiterLoop
from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore


UTC = datetime.timezone.utc


class _FakeLoop:
    """Records start()/stop() so the lifespan wiring is testable without threads."""
    def __init__( self ):
        self.started = False
        self.stopped = False
    def start( self ):
        self.started = True
    def stop( self ):
        self.stopped = True


class _FakeGW:
    def __init__( self ): self.posts = [ ]
    def post( self, topic, body ): self.posts.append( ( topic, body ) )


def test_make_health_notify_fn_logs_and_escalates_rick_only():
    """Part-6 #1/2/3: health escalation logs AND pushes to Rick (durable post +
    live push) — no manager fanout."""
    gw, logs, live = _FakeGW(), [ ], [ ]
    notify = _make_health_notify_fn( gw, live_notify_fn=live.append,
                                     log_fn=lambda ev, **kw: logs.append( ( ev, kw ) ) )
    notify( "postgres unhealthy" )
    assert ( "health_escalation", { "message": "postgres unhealthy" } ) in logs   # the structured log
    assert gw.posts == [ ( "fleet-escalations", "postgres unhealthy" ) ]          # durable, Rick
    assert live == [ "postgres unhealthy" ]                                       # live push to Rick


def test_health_defaults():
    """create_app() defaults: real clock, fresh local store, no health loop."""
    with TestClient( create_app() ) as client:        # `with` runs the lifespan (loop-None branch)
        resp = client.get( "/health" )
        assert resp.status_code == 200
        body = resp.json()
        assert body[ "status" ]         == "ok"
        assert body[ "service" ]        == "lupin-arbiter-app"
        assert body[ "version" ]        == __version__
        assert body[ "uptime_seconds" ] >= 0.0
        assert isinstance( client.app.state.snapshot_store, LocalSnapshotStore )
        assert client.app.state.health_loop is None


def test_health_injected_clock_is_deterministic():
    """Injected now_fn + started_at + store give a deterministic uptime."""
    started = datetime.datetime( 2026, 6, 7, 12, 0, 0, tzinfo=UTC )
    now     = datetime.datetime( 2026, 6, 7, 12, 0, 5, tzinfo=UTC )
    store   = LocalSnapshotStore()

    with TestClient( create_app( snapshot_store=store, now_fn=lambda: now, started_at=started ) ) as client:
        body = client.get( "/health" ).json()
        assert body[ "uptime_seconds" ] == 5.0
        assert body[ "started_at" ]     == started.isoformat()
        assert client.app.state.snapshot_store is store


def test_lifespan_starts_and_stops_injected_health_loop():
    """When a health_loop is injected, the lifespan start()s + stop()s it."""
    loop = _FakeLoop()
    with TestClient( create_app( health_loop=loop ) ) as client:
        assert loop.started is True          # started on lifespan enter
        assert loop.stopped is False
        assert client.app.state.health_loop is loop
    assert loop.stopped is True              # stopped on lifespan exit


def test_lifespan_starts_and_stops_both_loops():
    """Both background loops (health watcher + fleet arbiter) are started + stopped by the lifespan."""
    a, b = _FakeLoop(), _FakeLoop()
    with TestClient( create_app( health_loop=a, fleet_arbiter_loop=b ) ) as client:
        assert a.started is True and b.started is True
        assert client.app.state.fleet_arbiter_loop is b
    assert a.stopped is True and b.stopped is True


class _FakeCfg:
    """Fake ConfigurationManager for assemble_app's enable-gate branches."""
    def __init__( self, enabled ):
        self._enabled = enabled
    def get( self, key, default=None, return_type="string" ):
        if key == "arbiter health watch enabled":
            return self._enabled                              # bool (boolean return_type)
        if key == "arbiter health watch containers":
            return "c1,c2"
        if key == "arbiter health flap exclude containers":
            return "c1"
        return default                                        # int/string keys → their defaults


class _FakeGateway:
    """Minimal ArbiterGateway stand-in (assemble_app only captures it — no calls)."""
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body ): pass
    def post( self, topic, body ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


def test_assemble_app_enabled_wires_both_loops():
    """enabled=true → the health watcher (HealthWatcherLoop) AND the fleet arbiter (FleetArbiterLoop) wired."""
    app = assemble_app( _FakeCfg( enabled=True ), _FakeGateway() )
    assert isinstance( app.state.health_loop, HealthWatcherLoop )
    assert isinstance( app.state.fleet_arbiter_loop, FleetArbiterLoop )


def test_assemble_app_health_disabled_still_wires_fleet_arbiter( capsys ):
    """enabled=false → health_loop None + health_watcher_disabled log; the fleet arbiter still wired."""
    app = assemble_app( _FakeCfg( enabled=False ), _FakeGateway() )
    assert app.state.health_loop is None
    assert isinstance( app.state.fleet_arbiter_loop, FleetArbiterLoop )
    assert isinstance( app.state.snapshot_store, LocalSnapshotStore )
    assert "health_watcher_disabled" in capsys.readouterr().out


def test_utcnow_returns_aware_utc_datetime():
    """_utcnow (the wall-clock boundary) returns an aware UTC datetime."""
    ts = _utcnow()
    assert ts.tzinfo is not None
    assert ts.utcoffset() == datetime.timedelta( 0 )


def test_local_snapshot_store_sections():
    """Section-keyed store: per-section writes coexist; get() is the composite."""
    store = LocalSnapshotStore()
    assert store.get() == { }
    assert store.get_section( "health_watcher" ) is None

    store.set_section( "health_watcher", { "containers": { } } )
    store.set_section( "fleet_arbiter", { "session_count": 2 } )
    # two writers, no clobber
    assert store.get_section( "health_watcher" ) == { "containers": { } }
    assert store.get_section( "fleet_arbiter" ) == { "session_count": 2 }
    assert store.get() == { "health_watcher": { "containers": { } }, "fleet_arbiter": { "session_count": 2 } }

    # overwriting one section leaves the other untouched
    store.set_section( "health_watcher", { "containers": { "c": 1 } } )
    assert store.get_section( "health_watcher" ) == { "containers": { "c": 1 } }
    assert store.get_section( "fleet_arbiter" ) == { "session_count": 2 }

    store.clear()
    assert store.get() == { }


# ── GET /state (L4) — single-pane composite + per-section awaiting placeholder ──

def test_state_cold_start_both_sections_awaiting():
    """Empty store → top-level ok + per-section 'awaiting' placeholders (never bare null)."""
    now = datetime.datetime( 2026, 6, 7, 12, 0, 0, tzinfo=UTC )
    with TestClient( create_app( now_fn=lambda: now ) ) as client:
        resp = client.get( "/state" )
        assert resp.status_code == 200
        body = resp.json()
        assert body[ "status" ]         == "ok"
        assert body[ "service" ]        == "lupin-arbiter-app"
        assert body[ "version" ]        == __version__
        assert body[ "generated_at" ]   == now.isoformat()
        assert body[ "health_watcher" ] == { "status": "awaiting" }
        assert body[ "fleet_arbiter" ]  == { "status": "awaiting", "session_count": 0, "sessions": [ ] }
        # the OLD generic keys are GONE — the /state contract break is real, not additive
        assert "loop_a" not in body and "loop_b_fleet" not in body


def test_state_populated_returns_real_sections():
    """Both loops have written → /state echoes their real section values."""
    store = LocalSnapshotStore()
    store.set_section( "health_watcher", { "containers": { "lupin-rest-dev": "healthy" } } )
    store.set_section( "fleet_arbiter", { "status": "ok", "session_count": 2, "sessions": [ { "session_id": "s1" } ] } )
    with TestClient( create_app( snapshot_store=store ) ) as client:
        body = client.get( "/state" ).json()
        assert body[ "status" ]         == "ok"
        assert body[ "health_watcher" ] == { "containers": { "lupin-rest-dev": "healthy" } }
        assert body[ "fleet_arbiter" ][ "session_count" ] == 2
        assert body[ "fleet_arbiter" ][ "sessions" ][ 0 ][ "session_id" ] == "s1"


def test_state_partial_one_section_awaiting():
    """Health watcher written, fleet arbiter not → health_watcher real, fleet_arbiter 'awaiting' (both None-arms covered)."""
    store = LocalSnapshotStore()
    store.set_section( "health_watcher", { "containers": { } } )
    with TestClient( create_app( snapshot_store=store ) ) as client:
        body = client.get( "/state" ).json()
        assert body[ "health_watcher" ] == { "containers": { } }
        assert body[ "fleet_arbiter" ]  == { "status": "awaiting", "session_count": 0, "sessions": [ ] }
