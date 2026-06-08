#!/usr/bin/env python3
"""
arbiter-vigilance FastAPI app — the standalone, out-of-band fleet watcher on :8001.

Surface so far:
    GET /health  (L1) — cheap, always-answer liveness for systemd/cron (deploy §7).
    GET /state   (L4) — the single-pane composite (Loop A `loop_a` + Loop B
                 `loop_b_fleet`) read from the :8001-LOCAL store; the :7999
                 reverse-proxy PULLS from here (R3). Read-only, zero outbound HTTP.
Loop A (L2, health watch) is wired via an INJECTABLE `health_loop` that the app
lifespan start()s on boot and stop()s on shutdown. Loop B + R0 (L3) are wired
via the injectable `loop_b_runner`.

Two design seams (Tiberius + Tiffany):
    • the :8001-LOCAL section-keyed `snapshot_store` on app.state — the loops
      (L2/L3) write their own sections, /state (L4) reads the composite; this
      module imports NOTHING from cosa.rest / the :7999 server and makes ZERO
      outbound HTTP, so the eventual fleet-stall path stays in-process only (R4).
    • the injectable `health_loop` — unit tests pass a fake (no real threads /
      docker); production builds the real one in create_production_app().
"""
import datetime
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional

from fastapi import FastAPI

from arbiter_vigilance import __version__
from arbiter_vigilance.local_snapshot_store import LocalSnapshotStore


def _utcnow() -> datetime.datetime:
    """Ensures: returns the current aware UTC datetime (the wall-clock boundary)."""
    return datetime.datetime.now( datetime.timezone.utc )


def create_app(
    snapshot_store : Optional[ LocalSnapshotStore ] = None,
    now_fn         : Optional[ Callable ]           = None,
    started_at     : Optional[ datetime.datetime ]  = None,
    health_loop    : Optional[ Any ]                = None,
    loop_b_runner  : Optional[ Any ]                = None,
) -> FastAPI:
    """
    Build the arbiter-vigilance FastAPI app.

    Requires:
        - now_fn (if provided) is a 0-arg callable returning an aware datetime
        - started_at (if provided) is an aware datetime
        - health_loop / loop_b_runner (if provided) expose start() / stop()

    Ensures:
        - returns a FastAPI app exposing GET /health
        - carries an injectable :8001-LOCAL section-keyed snapshot_store on
          app.state (default: a fresh LocalSnapshotStore)
        - the lifespan start()s every provided background loop on boot and stop()s
          them (in reverse) on shutdown; absent loops are no-ops
        - this module makes NO :7999/:8000 import or HTTP; /health never raises
          (no I/O, no dependency on the monitored servers)
    """
    now_fn     = now_fn if now_fn is not None else _utcnow
    started_at = started_at if started_at is not None else now_fn()
    store      = snapshot_store if snapshot_store is not None else LocalSnapshotStore()

    @asynccontextmanager
    async def lifespan( _app: FastAPI ):
        for lp in ( health_loop, loop_b_runner ):
            if lp is not None:
                lp.start()
        yield
        for lp in ( loop_b_runner, health_loop ):        # stop in reverse start order
            if lp is not None:
                lp.stop()

    app = FastAPI( title="arbiter-vigilance", version=__version__, lifespan=lifespan )
    app.state.snapshot_store = store
    app.state.started_at     = started_at
    app.state.health_loop    = health_loop
    app.state.loop_b_runner  = loop_b_runner

    @app.get( "/health" )
    def health() -> dict:
        """Cheap, always-answer liveness for systemd/cron supervision (deploy §7)."""
        now    = now_fn()
        uptime = ( now - started_at ).total_seconds()
        return {
            "status"         : "ok",
            "service"        : "arbiter-vigilance",
            "version"        : __version__,
            "started_at"     : started_at.isoformat(),
            "uptime_seconds" : uptime,
        }

    @app.get( "/state" )
    def state() -> dict:
        """
        The single-pane composite (L4) — read-only, cheap, 127.0.0.1-bind (R3).

        Reads the :8001-LOCAL section-keyed store (Loop A `loop_a` + Loop B
        `loop_b_fleet`); the :7999 reverse-proxy `GET /api/arbiter/fleet-state`
        PULLS from here (R3: this service NEVER pushes). Makes ZERO outbound HTTP
        and reads only the in-process store (R4 independence preserved).

        Ensures:
            - top-level `status` is always "ok" — the WATCHER itself is alive and
              answering (orthogonal to fleet health)
            - each section is its real value once its loop has written it, else an
              explicit per-section "awaiting" placeholder — NEVER a bare null, so a
              cold loop (not yet written) is distinguishable from a genuinely empty
              fleet (the §10.4 awaiting idiom, mirrored from /api/arbiter/fleet-snapshot)
        """
        composite    = store.get()
        loop_a       = composite.get( "loop_a" )
        loop_b_fleet = composite.get( "loop_b_fleet" )
        return {
            "status"       : "ok",
            "service"      : "arbiter-vigilance",
            "version"      : __version__,
            "generated_at" : now_fn().isoformat(),
            "loop_a"       : loop_a if loop_a is not None else { "status": "awaiting" },
            "loop_b_fleet" : loop_b_fleet if loop_b_fleet is not None
                             else { "status": "awaiting", "session_count": 0, "sessions": [ ] },
        }

    return app


def assemble_app(
    cfg,
    gateway,
    *,
    store          : Optional[ LocalSnapshotStore ] = None,
    live_notify_fn : Optional[ Callable ]           = None,
    log_fn         : Optional[ Callable ]           = None,
    clock          : Optional[ Any ]                = None,
) -> FastAPI:
    """
    Testable production wiring (Tiberius's principle: a factory that BRANCHES on
    config is NOT an IO boundary — inject the deps, pragma only literal external
    construction). Builds Loop A (gated on `arbiter health watch enabled`) + Loop B
    (the standing recycle-supervised v2.2 arbiter) wired to ONE shared :8001-local
    store, and returns the FastAPI app.

    Requires:
        - cfg exposes .get( key, default, return_type ) (real or fake)
        - gateway satisfies the ArbiterGateway protocol (who/send_to/post/read)

    Ensures:
        - Loop B (LoopBRunner) is ALWAYS wired (the service IS the standing arbiter)
        - Loop A (HealthWatchLoop) is wired iff `arbiter health watch enabled`
          (disabled → health_loop=None + a loop_a_disabled log)
        - both loops write sections of the SAME store; this function makes NO
          :7999/:8000 HTTP and builds NO job until the runner starts (testable
          with a fake cfg + fake gateway)
    """
    from arbiter_vigilance.health_watch import HealthWatchLoop, docker_inspect_health
    from arbiter_vigilance.health_watch import _default_log_fn as _log_default
    from arbiter_vigilance.loop_b import LoopBRunner, build_loop_b_job_factory

    store  = store  if store  is not None else LocalSnapshotStore()
    log_fn = log_fn if log_fn is not None else _log_default

    # ── Loop B (L3): the standing v2.2 arbiter on the recycle supervisor ──
    loop_b_factory = build_loop_b_job_factory(
        gateway, store,
        clock                = clock,
        log_fn               = log_fn,
        live_notify_fn       = live_notify_fn,
        poll_seconds         = int( cfg.get( "arbiter poll seconds", default=60, return_type="int" ) ),
        manager_on_duty      = cfg.get( "arbiter manager on duty", default="manager-on-duty" ) or "manager-on-duty",
        alive_threshold      = int( cfg.get( "arbiter alive threshold seconds", default=600, return_type="int" ) ),
        quiet_threshold      = int( cfg.get( "arbiter quiet threshold seconds", default=300, return_type="int" ) ),
        tap_min_interval     = int( cfg.get( "arbiter tap min interval seconds", default=300, return_type="int" ) ),
        ack_window           = int( cfg.get( "arbiter manager ack window seconds", default=600, return_type="int" ) ),
        stall_window         = int( cfg.get( "arbiter fleet stall window seconds", default=1800, return_type="int" ) ),
        start_period_seconds = int( cfg.get( "arbiter start period seconds", default=120, return_type="int" ) ),
    )
    loop_b_runner = LoopBRunner( loop_b_factory, log_fn=log_fn )

    # ── Loop A (L2): gated on the master enable ──
    if not cfg.get( "arbiter health watch enabled", default=True, return_type="boolean" ):
        log_fn( "loop_a_disabled", reason="arbiter health watch enabled = false" )
        return create_app( snapshot_store=store, health_loop=None, loop_b_runner=loop_b_runner )

    def _csv( key, default ):
        raw = cfg.get( key, default=default ) or default
        return [ c.strip() for c in raw.split( "," ) if c.strip() ]

    health_loop = HealthWatchLoop(
        containers            = _csv( "arbiter health watch containers", "lupin-rest-dev,lupin-rest-test,lupin-model-server,lupin-postgres" ),
        inspect_fn            = lambda name: docker_inspect_health( name, int( cfg.get( "arbiter health inspect timeout seconds", default=5, return_type="int" ) ) ),
        notify_fn             = lambda msg: log_fn( "health_escalation", message=msg ),
        store                 = store,
        log_fn                = log_fn,
        interval_seconds      = int( cfg.get( "arbiter health watch interval seconds", default=30, return_type="int" ) ),
        flap_window_seconds   = int( cfg.get( "arbiter health flap window seconds", default=600, return_type="int" ) ),
        flap_threshold        = int( cfg.get( "arbiter health flap threshold transitions", default=3, return_type="int" ) ),
        flap_exclude          = _csv( "arbiter health flap exclude containers", "lupin-rest-dev" ),
        blind_threshold_polls = int( cfg.get( "arbiter health blind threshold polls", default=3, return_type="int" ) ),
    )
    return create_app( snapshot_store=store, health_loop=health_loop, loop_b_runner=loop_b_runner )


def create_production_app() -> FastAPI:   # pragma: no cover - literal external construction (config, gateway)
    """
    uvicorn `--factory` target: build the literal externals (ConfigurationManager,
    the bridge-less commons gateway) and delegate ALL wiring/branching to the
    testable assemble_app. live_notify_fn stays None in V1 (the best-effort :7999
    live-notify ingress is a documented build-time follow-up; escalations always
    land durably on the fleet-escalations commons topic regardless).
    """
    from cosa.config.configuration_manager import ConfigurationManager
    from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway
    cfg     = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    gateway = LupinArbiterGateway.from_environment( sender_session_id="arbiter-vigilance-8001" )
    return assemble_app( cfg, gateway )


# Module-level loop-less ASGI entrypoint (safe to import; used by /health-only boots
# and unit tests). Production uses `create_production_app` via uvicorn --factory.
app = create_app()
