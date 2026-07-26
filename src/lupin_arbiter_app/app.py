#!/usr/bin/env python3
"""
lupin-arbiter-app FastAPI app — the standalone, out-of-band fleet watcher on :8001.

Surface so far:
    GET /health  (L1) — cheap, always-answer liveness for systemd/cron (deploy §7).
    GET /state   (L4) — the single-pane composite (health watcher `health_watcher` +
                 fleet arbiter `fleet_arbiter`) read from the :8001-LOCAL store; the
                 :7999 reverse-proxy PULLS from here (R3). Read-only, zero outbound HTTP.
The health watcher (L2) is wired via an INJECTABLE `health_loop` that the app
lifespan start()s on boot and stop()s on shutdown. The fleet arbiter + R0 (L3) are
wired via the injectable `fleet_arbiter_loop`.

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

from lupin_arbiter_app import __version__
from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore


def _utcnow() -> datetime.datetime:
    """Ensures: returns the current aware UTC datetime (the wall-clock boundary)."""
    return datetime.datetime.now( datetime.timezone.utc )


def create_app(
    snapshot_store        : Optional[ LocalSnapshotStore ] = None,
    now_fn                : Optional[ Callable ]           = None,
    started_at            : Optional[ datetime.datetime ]  = None,
    health_loop           : Optional[ Any ]                = None,
    fleet_arbiter_loop    : Optional[ Any ]                = None,
    context_pressure_loop : Optional[ Any ]                = None,
    turn_age_watchdog_loop : Optional[ Any ]               = None,
) -> FastAPI:
    """
    Build the lupin-arbiter-app FastAPI app.

    Requires:
        - now_fn (if provided) is a 0-arg callable returning an aware datetime
        - started_at (if provided) is an aware datetime
        - health_loop / fleet_arbiter_loop / context_pressure_loop /
          turn_age_watchdog_loop (if provided) expose start() / stop()

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
        for lp in ( health_loop, fleet_arbiter_loop, context_pressure_loop, turn_age_watchdog_loop ):
            if lp is not None:
                lp.start()
        yield
        for lp in ( turn_age_watchdog_loop, context_pressure_loop, fleet_arbiter_loop, health_loop ):   # stop in reverse start order
            if lp is not None:
                lp.stop()

    app = FastAPI( title="lupin-arbiter-app", version=__version__, lifespan=lifespan )
    app.state.snapshot_store         = store
    app.state.started_at             = started_at
    app.state.health_loop            = health_loop
    app.state.fleet_arbiter_loop     = fleet_arbiter_loop
    app.state.context_pressure_loop  = context_pressure_loop
    app.state.turn_age_watchdog_loop = turn_age_watchdog_loop

    @app.get( "/health" )
    def health() -> dict:
        """Cheap, always-answer liveness for systemd/cron supervision (deploy §7)."""
        now    = now_fn()
        uptime = ( now - started_at ).total_seconds()
        return {
            "status"         : "ok",
            "service"        : "lupin-arbiter-app",
            "version"        : __version__,
            "started_at"     : started_at.isoformat(),
            "uptime_seconds" : uptime,
        }

    @app.get( "/state" )
    def state() -> dict:
        """
        The single-pane composite (L4) — read-only, cheap, 127.0.0.1-bind (R3).

        Reads the :8001-LOCAL section-keyed store (health watcher `health_watcher` +
        fleet arbiter `fleet_arbiter`); the :7999 reverse-proxy `GET /api/arbiter/fleet-state`
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
        composite        = store.get()
        health_watcher   = composite.get( "health_watcher" )
        fleet_arbiter    = composite.get( "fleet_arbiter" )
        context_pressure = composite.get( "context_pressure" )
        return {
            "status"           : "ok",
            "service"          : "lupin-arbiter-app",
            "version"          : __version__,
            "generated_at"     : now_fn().isoformat(),
            "health_watcher"   : health_watcher if health_watcher is not None else { "status": "awaiting" },
            "fleet_arbiter"    : fleet_arbiter if fleet_arbiter is not None
                                 else { "status": "awaiting", "session_count": 0, "sessions": [ ] },
            "context_pressure" : context_pressure if context_pressure is not None
                                 else { "status": "awaiting", "personas": { } },
        }

    return app


def _make_health_notify_fn( gateway, live_notify_fn, log_fn ):
    """
    Build the health-watcher (Loop A) escalation notify_fn — Part-6 #1/#2/#3:
    infra/self-health alerts (container unhealthy / flapping / health-watch BLIND)
    route to RICK ONLY (durable `fleet-escalations` post + best-effort live push),
    with NO manager fanout (managers don't act on containers). Keeps the structured
    `health_escalation` log line too.

    Ensures:
        - returns notify( message ) that logs `health_escalation` AND escalates to
          Rick via the shared escalation sink (durable + deduped live push); never
          raises (the escalation sink is degrade-safe)
    """
    from lupin_arbiter_app.fleet_arbiter_loop import make_escalation_notify_fn
    escalate = make_escalation_notify_fn( gateway, live_notify_fn=live_notify_fn, log_fn=log_fn )

    def notify( message ):
        log_fn( "health_escalation", message=message )
        escalate( message )                            # Part-6 #1/2/3 → Rick only (no managers)

    return notify


def _build_context_pressure_loop( cfg, store, *, clock=None, log_fn=None ):
    """
    Build the context-headroom writer (the published per-persona service),
    gated on the Phase-1 master switch `arbiter context watch enabled`.

    Reads the §6 budget-policy keys (1M→0.50, 200K→0.75, default→0.50 — Rick's
    Decision 5, config-tunable) + the existing Phase-1 leaf knobs, and wires the
    REAL leaf (`assess_fleet_context_pressure`) into a ContextPressureWriterLoop.
    Read-only — the writer takes no notify/commons seam by design (Decision 4:
    the CRITICAL→recommender stays separately gated in the Phase 2/3 lineage).

    Requires:
        - cfg exposes .get( key, default, return_type ) (real or fake)
        - store exposes set_section( name, value )
        - log_fn is the already-resolved structured logger (never None here)

    Ensures:
        - returns a ContextPressureWriterLoop when the watch is enabled
        - returns None + a context_pressure_writer_disabled log when disabled
    """
    if not cfg.get( "arbiter context watch enabled", default=True, return_type="boolean" ):
        log_fn( "context_pressure_writer_disabled", reason="arbiter context watch enabled = false" )
        return None

    from cosa.agents.heartbeat_arbiter.context_pressure import assess_fleet_context_pressure
    from lupin_arbiter_app.context_pressure_writer import ContextPressureWriterLoop

    budget_fractions = {
        1_000_000 : float( cfg.get( "arbiter context budget fraction 1000000", default=0.50, return_type="float" ) ),
        200_000   : float( cfg.get( "arbiter context budget fraction 200000",  default=0.75, return_type="float" ) ),
        "default" : float( cfg.get( "arbiter context budget fraction default", default=0.50, return_type="float" ) ),
    }
    leaf_kwargs = {
        "reserve"            : int( cfg.get( "arbiter context autocompact reserve tokens", default=0, return_type="int" ) ),
        "max_response"       : int( cfg.get( "arbiter context max response tokens", default=0, return_type="int" ) ),
        "warn_pct"           : float( cfg.get( "arbiter context warn threshold pct", default=70, return_type="float" ) ),
        "critical_pct"       : float( cfg.get( "arbiter context critical threshold pct", default=85, return_type="float" ) ),
        "idle_mtime_seconds" : int( cfg.get( "arbiter context idle mtime seconds", default=1800, return_type="int" ) ),
        "default_window"     : int( cfg.get( "arbiter context default window tokens", default=1_000_000, return_type="int" ) ),
    }
    return ContextPressureWriterLoop(
        assess_fleet_context_pressure, store,
        budget_fractions = budget_fractions,
        leaf_kwargs      = leaf_kwargs,
        clock            = clock,
        log_fn           = log_fn,
        interval_seconds = int( cfg.get( "arbiter context watch interval seconds", default=60, return_type="int" ) ),
    )


def assemble_app(
    cfg,
    gateway,
    *,
    store          : Optional[ LocalSnapshotStore ] = None,
    live_notify_fn : Optional[ Callable ]           = None,
    live_retry_fn  : Optional[ Callable ]           = None,
    dm_push_fn     : Optional[ Callable ]           = None,
    tmux_push_fn   : Optional[ Callable ]           = None,   # Thread C+D host-side tmux wake hop
    log_fn         : Optional[ Callable ]           = None,
    clock          : Optional[ Any ]                = None,
) -> FastAPI:
    """
    Testable production wiring (Tiberius's principle: a factory that BRANCHES on
    config is NOT an IO boundary — inject the deps, pragma only literal external
    construction). Builds the health watcher (gated on `arbiter health watch enabled`)
    + the fleet arbiter (the standing recycle-supervised v2.2 arbiter) wired to ONE
    shared :8001-local store, and returns the FastAPI app.

    Requires:
        - cfg exposes .get( key, default, return_type ) (real or fake)
        - gateway satisfies the ArbiterGateway protocol (who/send_to/post/read)

    Ensures:
        - the fleet arbiter (FleetArbiterLoop) is ALWAYS wired (the service IS the standing arbiter)
        - the health watcher (HealthWatcherLoop) is wired iff `arbiter health watch enabled`
          (disabled → health_loop=None + a health_watcher_disabled log)
        - the context-headroom writer (ContextPressureWriterLoop) is wired iff
          `arbiter context watch enabled` (disabled → None + a disabled log)
        - all loops write sections of the SAME store; this function makes NO
          :7999/:8000 HTTP and builds NO job until the runner starts (testable
          with a fake cfg + fake gateway)
    """
    from lupin_arbiter_app.health_watcher import HealthWatcherLoop, docker_inspect_health
    from lupin_arbiter_app.fleet_arbiter_loop import (
        FleetArbiterLoop, build_fleet_arbiter_job_factory, make_follow_through_watcher_factory,
        make_escalation_notify_fn,
    )
    from cosa.agents.heartbeat_arbiter.turn_age_watchdog import TurnAgeWatchdog
    from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn
    # Relocated 2026-06-11 (fleet-roster reserve-from-random): the roster
    # reader lives with its env-var siblings in voice_persona_helpers now
    # that the allocation corridor is its second consumer.
    from cosa.rest.voice_persona_helpers import pick_declared_managers_from_env

    store = store if store is not None else LocalSnapshotStore()

    # ── journal log_fns (Item A §2.2 + §3.8 of the 2026.06.11 receipts design):
    # tz from the INI (deploy-tunable); each loop journals under its OWN label —
    # pre-design, every fleet-arbiter event wore the health watcher's loop label
    # because ONE health-watcher default was passed everywhere (the §1.4 lie).
    # An injected log_fn (test seam) still overrides all of them.
    tz_name = cfg.get( "arbiter journal local timezone", default="America/New_York" ) or "America/New_York"
    if log_fn is None:
        wiring_log_fn  = make_log_fn( loop="app_wiring",              tz_name=tz_name )
        arbiter_log_fn = make_log_fn( loop="fleet_arbiter",           tz_name=tz_name )
        health_log_fn  = make_log_fn( loop="health_watcher",          tz_name=tz_name )
        cp_log_fn      = make_log_fn( loop="context_pressure_writer", tz_name=tz_name )
    else:
        wiring_log_fn = arbiter_log_fn = health_log_fn = cp_log_fn = log_fn
    log_fn = wiring_log_fn

    # ── declared-manager roster (COSA_VOICE_MANAGERS__<PROJECT>, Rick 2026-06-11):
    # multi-manager-per-repo support. Feeds fanout, badging, and the per-worker
    # declared fallback; never OCCUPIES a persona (allocation-side reserve-from-
    # random lives in voice_persona_helpers, not here). Project resolved the
    # same way every other arbiter surface does (detect_project from cwd/git),
    # degrade-safe to "lupin" (this app IS the lupin fleet's arbiter).
    try:
        from cosa.agents.utils.sender_id import detect_project
        _arbiter_project = detect_project()
    except Exception:
        _arbiter_project = "lupin"
    declared_managers = pick_declared_managers_from_env( _arbiter_project )
    log_fn( "declared_managers_resolved", project=_arbiter_project, managers=declared_managers )

    # ── audience scalpel: the EFFECTIVE poke-audience configuration, logged once at
    # startup. The per-session `arbiter_poke_gate` event covers the two
    # session-directed tiers (worker/manager) via its why_not vectors, but the
    # OPERATOR audience is subsystem-level — it has no per-session row, so a
    # Rick-side silence was NOT diagnosable from production telemetry at all
    # (found 2026-07-19 when María asked for live proof of the operator path and
    # there was none to give). This line makes all three observable at the same
    # place the arbiter logs its other boot-time resolutions, so "why did I stop
    # hearing from the arbiter" is answerable from the journal alone.
    _poke_master = cfg.get( "arbiter auto poke enabled", default=True, return_type="boolean" )
    log_fn( "arbiter_poke_audience_config",
            master   = _poke_master,
            workers  = cfg.get( "arbiter auto poke workers enabled",  default=True, return_type="boolean" ),
            managers = cfg.get( "arbiter auto poke managers enabled", default=True, return_type="boolean" ),
            operator = cfg.get( "arbiter auto poke operator enabled", default=True, return_type="boolean" ),
            note     = ( "master OFF — every audience silent regardless of the three below"
                         if not _poke_master else "master ON — each audience answers for itself" ) )

    # ── eng#7 (2026-06-17): the follow-through aged-escalation watcher factory.
    # Built here (cfg + gateway in hand) and threaded into every recycled job so
    # the watcher rides the arbiter poll loop (build-plan §3b). REUSES the job's
    # session_is_not_owed predicate for §4.5 hygiene (bound per-job inside the
    # factory). Inert at runtime until `follow through escalation enabled` flips
    # true (default false) — wiring it in is behavior-neutral.
    follow_through_watcher_factory = make_follow_through_watcher_factory(
        cfg, gateway, log_fn=arbiter_log_fn )

    # ── fleet arbiter (L3): the standing v2.2 arbiter on the recycle supervisor ──
    fleet_arbiter_factory = build_fleet_arbiter_job_factory(
        gateway, store,
        clock                = clock,
        log_fn               = arbiter_log_fn,
        live_notify_fn       = live_notify_fn,
        poll_seconds         = int( cfg.get( "arbiter poll seconds", default=60, return_type="int" ) ),
        manager_on_duty      = cfg.get( "arbiter manager on duty", default="manager-on-duty" ) or "manager-on-duty",
        declared_managers    = declared_managers,
        alive_threshold      = int( cfg.get( "arbiter alive threshold seconds", default=600, return_type="int" ) ),
        quiet_threshold      = int( cfg.get( "arbiter quiet threshold seconds", default=300, return_type="int" ) ),
        tap_min_interval     = int( cfg.get( "arbiter tap min interval seconds", default=300, return_type="int" ) ),
        ack_window           = int( cfg.get( "arbiter manager ack window seconds", default=600, return_type="int" ) ),
        stall_window         = int( cfg.get( "arbiter fleet stall window seconds", default=1800, return_type="int" ) ),
        poll_error_escalate_threshold = int( cfg.get( "arbiter poll error escalate threshold", default=3, return_type="int" ) ),
        auto_poke_enabled    = cfg.get( "arbiter auto poke enabled", default=True, return_type="boolean" ),
        # AUDIENCE SCALPEL (2026-07-19, Rick via María): three audience-scoped gates
        # UNDER the master above. Master off ⇒ all silent (panic button); master on ⇒
        # silence the crew while Rick keeps his own stream (scalpel). Default True ⇒
        # unconfigured behaves exactly as before.
        poke_workers_enabled  = cfg.get( "arbiter auto poke workers enabled",  default=True, return_type="boolean" ),
        poke_managers_enabled = cfg.get( "arbiter auto poke managers enabled", default=True, return_type="boolean" ),
        poke_operator_enabled = cfg.get( "arbiter auto poke operator enabled", default=True, return_type="boolean" ),
        # ee59d5ed orphan-bridge janitor — DEFAULT-OFF (fleet-wide reap-semantics change; flip on for Rick's awareness)
        orphan_bridge_sweep_enabled = cfg.get( "arbiter orphan bridge sweep enabled", default=False, return_type="boolean" ),
        orphan_bridge_sweep_debounce_polls = int( cfg.get( "arbiter orphan bridge sweep debounce polls", default=2, return_type="int" ) ),
        poke_stall_threshold = int( cfg.get( "arbiter poke stall threshold seconds", default=720, return_type="int" ) ),
        poke_max_per_episode = int( cfg.get( "arbiter poke max per episode", default=3, return_type="int" ) ),
        stuck_poke_min_interval_seconds = int( cfg.get( "arbiter stuck poke min interval seconds", default=0, return_type="int" ) ),   # bug 5a1f17f8 (c)
        manager_stale_poke_threshold = int( cfg.get( "arbiter manager stale poke threshold seconds", default=2700, return_type="int" ) ),
        manager_stale_poke_max_age   = int( cfg.get( "arbiter manager stale poke max age seconds", default=7200, return_type="int" ) ),
        # role-goals Phase 2-3 (D1): role-selected north-star goal echoes appended to
        # the stuck-poke + manager-staleness poke bodies. Runtime-tunable; "" leaves
        # the poke body unchanged. Canonical: planning-is-prompting -> workflow/role-goals.md.
        manager_goal_line    = cfg.get( "heartbeat manager goal line", default="" ) or "",
        worker_goal_line     = cfg.get( "heartbeat worker goal line",  default="" ) or "",
        # 6929f4ac outward-twin backstop: the aged-gate resurface ceiling (hold_reader_fn
        # itself defaults to the real read_hold inside the factory, mirroring owed_work_fn).
        user_gate_resurface_seconds = int( cfg.get( "arbiter user gate resurface seconds", default=1800, return_type="int" ) ),
        # A2/A3 (fcb5dbc0): the operator-gate NORMAL-urgency digest cadence (operator_gates_fn
        # itself defaults to the real fleet-wide store reader inside the factory).
        operator_digest_cadence_seconds = int( cfg.get( "arbiter operator gate digest cadence seconds", default=1800, return_type="int" ) ),
        start_period_seconds = int( cfg.get( "arbiter start period seconds", default=120, return_type="int" ) ),
        # Item B (2026.06.11 receipts design): delivery-receipt seams + knobs.
        # Ledger path: relative INI value combined with the project root at
        # runtime (PATH MANAGEMENT) — file-backed so re-announce survives both
        # the 12h recycle and a service restart.
        dm_push_fn           = dm_push_fn,
        tmux_push_fn         = tmux_push_fn,
        # Thread C+D: the wake-surface selector. Default "tmux" (host-side direct
        # inject, wakes a dormant pane) — load-bearing now that the internal
        # self-poke is confirmed broken; "dm" reverts to dm/send-only.
        poke_wake_mechanism  = cfg.get( "arbiter poke wake mechanism", default="tmux" ) or "tmux",
        live_retry_fn        = live_retry_fn,
        outreach_ack_window  = int( cfg.get( "arbiter outreach ack window seconds", default=900, return_type="int" ) ),
        reannounce_interval  = int( cfg.get( "arbiter outreach reannounce interval seconds", default=300, return_type="int" ) ),
        reannounce_ttl       = int( cfg.get( "arbiter outreach reannounce ttl seconds", default=86400, return_type="int" ) ),
        pending_ledger_path  = _pending_ledger_path( cfg ),
        lineage_carry_path   = _lineage_carry_path( cfg ),
        offsets_state_path   = _offsets_state_path( cfg ),                      # bug 5a1f17f8 (b) durable event offsets
        # DM-as-liveness toggle (2026-06-17): a cfg-closed lambda re-read EACH poll
        # (ConfigurationManager.get is mtime-gated) so `arbiter count dm as liveness`
        # is runtime-tunable with NO :8001 bounce — flip the INI, takes effect on
        # the next poll. Default TRUE (the feature is on out of the box; OFF is the
        # rollback). dm_activity_fn defaults to the real DB reader inside the factory.
        count_dm_as_liveness_fn = lambda: cfg.get( "arbiter count dm as liveness", default=True, return_type="boolean" ),
        follow_through_watcher_factory = follow_through_watcher_factory,        # eng#7 §3b
    )
    # Hold-file RECLAMATION (row 11461241, Rick's direct ruling 2026-07-26: "wire it —
    # the arbiter calls the janitor"). This is the ONE call site that opens deletion:
    # `enable_hold_deletion` defaults FALSE in the constructor so that omission stays
    # the safe state everywhere else, and the opt-in is stated out loud here.
    #
    # INI-gated for a no-bounce rollback — a destructive capability should be
    # revocable by an operator without a code change. Cargo-bearing holds are KEPT
    # regardless of this flag: that guard is structural in classify_hold_file and is
    # NOT reachable from here.
    fleet_arbiter_loop = FleetArbiterLoop(
        fleet_arbiter_factory, log_fn=arbiter_log_fn,
        enable_hold_deletion = cfg.get( "arbiter enable hold deletion", default=True, return_type="boolean" ),
    )

    # ── context-headroom writer: gated on `arbiter context watch enabled` ──
    context_pressure_loop = _build_context_pressure_loop( cfg, store, clock=clock, log_fn=cp_log_fn )

    # ── turn-age watchdog (wedge fix f1a21917 lever (ii)): the held-turn DETECTOR ──
    # A standalone daemon (NO ArbiterConsumerJob coupling — it reads transcripts +
    # panes directly) that flags a CC session whose last tool_use has gone
    # un-resulted past `arbiter turn age watchdog threshold seconds` while its pane
    # is idle → ONE operator advisory on the SAME rail as manager-stale (the durable
    # fleet-escalations post + best-effort live push), one-shot per (session,
    # tool_use). Self-gates on `arbiter turn age watchdog enabled` (default false):
    # start() is a no-op and sweep_once does zero IO until the flag flips, so wiring
    # it in is behavior-neutral. Its session-lister / transcript-reader / pane-oracle
    # default to the real IO boundaries inside the watchdog; only the advisory sink
    # is injected here to route onto the arbiter's outreach rail. Design:
    # src/rnd/v0.1.9/2026.07.03-notify-turn-hold-fix-design.md §3 (lever ii).
    turn_age_watchdog_loop = TurnAgeWatchdog(
        cfg,
        advisory_fn = make_escalation_notify_fn( gateway, live_notify_fn=live_notify_fn, log_fn=arbiter_log_fn ),
    )

    # ── health watcher (L2): gated on the master enable ──
    if not cfg.get( "arbiter health watch enabled", default=True, return_type="boolean" ):
        log_fn( "health_watcher_disabled", reason="arbiter health watch enabled = false" )
        return create_app( snapshot_store=store, health_loop=None, fleet_arbiter_loop=fleet_arbiter_loop,
                           context_pressure_loop=context_pressure_loop,
                           turn_age_watchdog_loop=turn_age_watchdog_loop )

    def _csv( key, default ):
        raw = cfg.get( key, default=default ) or default
        return [ c.strip() for c in raw.split( "," ) if c.strip() ]

    health_loop = HealthWatcherLoop(
        containers            = _csv( "arbiter health watch containers", "lupin-rest-dev,lupin-rest-test,lupin-model-server,lupin-postgres" ),
        inspect_fn            = lambda name: docker_inspect_health( name, int( cfg.get( "arbiter health inspect timeout seconds", default=5, return_type="int" ) ) ),
        notify_fn             = _make_health_notify_fn( gateway, live_notify_fn, health_log_fn ),   # Part-6 #1/2/3 → Rick
        store                 = store,
        log_fn                = health_log_fn,
        interval_seconds      = int( cfg.get( "arbiter health watch interval seconds", default=30, return_type="int" ) ),
        flap_window_seconds   = int( cfg.get( "arbiter health flap window seconds", default=600, return_type="int" ) ),
        flap_threshold        = int( cfg.get( "arbiter health flap threshold transitions", default=3, return_type="int" ) ),
        flap_exclude          = _csv( "arbiter health flap exclude containers", "lupin-rest-dev" ),
        blind_threshold_polls = int( cfg.get( "arbiter health blind threshold polls", default=3, return_type="int" ) ),
    )
    return create_app( snapshot_store=store, health_loop=health_loop, fleet_arbiter_loop=fleet_arbiter_loop,
                       context_pressure_loop=context_pressure_loop,
                       turn_age_watchdog_loop=turn_age_watchdog_loop )


def _pending_ledger_path( cfg ):
    """
    Resolve the §3.5 pending-ledger file path: relative INI value combined with
    the canonical project root at runtime (PATH MANAGEMENT mandate).

    Ensures:
        - returns <project_root> + <`arbiter outreach pending ledger path`>
    """
    import cosa.utils.util as cu
    rel = ( cfg.get( "arbiter outreach pending ledger path",
                     default="/io/arbiter/outreach-pending.json" )
            or "/io/arbiter/outreach-pending.json" )
    return cu.get_project_root() + rel


def _lineage_carry_path( cfg ):
    """
    Resolve the F-A lineage-carry file path (2026.06.11 lineage-persistence
    design): relative INI value + the canonical project root (PATH MANAGEMENT).

    Ensures:
        - returns <project_root> + <`arbiter lineage carry path`>
    """
    import cosa.utils.util as cu
    rel = ( cfg.get( "arbiter lineage carry path",
                     default="/io/arbiter/lineage-carry.json" )
            or "/io/arbiter/lineage-carry.json" )
    return cu.get_project_root() + rel


def _offsets_state_path( cfg ):
    """
    Resolve the durable event-offset store path (bug 5a1f17f8 (b)): relative INI
    value + the canonical project root (PATH MANAGEMENT). Persisting the per-session
    byte offsets here lets a :8001 restart RESUME tailing instead of re-reading every
    events file from byte 0 — the STUCK-poke replay root cause.

    Ensures:
        - returns <project_root> + <`arbiter event offsets state path`>
    """
    import cosa.utils.util as cu
    rel = ( cfg.get( "arbiter event offsets state path",
                     default="/io/arbiter/event-offsets.json" )
            or "/io/arbiter/event-offsets.json" )
    return cu.get_project_root() + rel


def _build_arbiter_outreach_hops( cfg, gateway ):   # pragma: no cover - literal external IO boundary (config, env credential, urllib)
    """
    Build the best-effort outreach hops (2026.06.11 receipts design + Thread C+D):
    ( live_notify_fn, live_retry_fn, dm_push_fn, tmux_push_fn ) — the first three
    are the :7999 hops (each None when unavailable); tmux_push_fn is the host-side
    wake hop, ALWAYS built (independent of the :7999 api_key) and returned in every
    path.

    The IO boundary for the :7999 hops: reads the gating INI knobs + the
    X-API-Key from `~/.lupin/config` (canonical cosa.utils.config_loader) and
    assembles the outcome-returning transports. The request SHAPES, outcome
    parsing, dedup guard, misconfig validator, and key resolver are unit-tested;
    only this wiring + the urllib round-trips are no-cover.

    Ensures:
        - feature disabled or credential unresolvable → ( None, None, None )
          (logged; escalations stay durable on the commons topic)
        - §3.6 misconfig guard: an empty / env-skeleton target_user (tonight's
          R1: literal ${LUPIN_DEV_EMAIL}) logs `live_notify_misconfigured`
          LOUDLY, best-effort posts the misconfiguration to fleet-escalations,
          and disables the live hops — no doomed-404 spam, and every subsequent
          Rick-bound outreach journals outcome "disabled" (visible, not silent)
        - happy path → live_notify_fn = dedup-guarded transport (first sends,
          persist=True → one forensic row); live_retry_fn = the RAW persist=False
          transport (re-announce bypasses content-dedup by design — it re-sends the
          same text — AND skips the DB insert so retries never mint duplicate rows,
          bug e1bbe011); dm_push_fn = the §3.3 register-question hop (or None when
          its gate is off)
    """
    from cosa.utils.config_loader import get_api_config, load_api_key
    from lupin_arbiter_app.arbiter_live_notify import (
        make_notify_transport, make_live_notify_fn, make_dm_push_fn, make_tmux_push_fn,
        resolve_arbiter_api_key, validate_live_notify_target, _default_log_fn,
    )

    # Thread C+D: the host-side tmux wake hop is INDEPENDENT of the :7999 live-
    # notify-to-Rick hop and its api_key — it reaches peer panes' tmux directly.
    # Build it unconditionally (returned in EVERY path); the
    # `arbiter poke wake mechanism` selector (read in assemble_app) decides
    # whether _emit_dm actually uses it.
    tmux_push_fn = make_tmux_push_fn()

    if not cfg.get( "arbiter live notify enabled", default=True, return_type="boolean" ):
        _default_log_fn( "live_notify_disabled", reason="arbiter live notify enabled = false" )
        return None, None, None, tmux_push_fn

    config_env = cfg.get( "arbiter live notify config env", default="development" ) or "development"
    api_key    = resolve_arbiter_api_key( get_api_config, load_api_key, env=config_env )
    if not api_key:
        return None, None, None, tmux_push_fn   # resolver already logged live_notify_disabled with the cause

    base_url     = cfg.get( "arbiter live notify url", default="http://127.0.0.1:7999" ) or "http://127.0.0.1:7999"
    target_user  = cfg.get( "arbiter live notify target user", default="" ) or ""
    sender_id    = cfg.get( "arbiter live notify sender id",
                            default="heartbeat-arbiter@lupin.deepily.ai" ) or "heartbeat-arbiter@lupin.deepily.ai"
    dedup_window = int( cfg.get( "arbiter live notify dedup window seconds", default=900, return_type="int" ) )
    timeout      = int( cfg.get( "arbiter live notify timeout seconds", default=30, return_type="int" ) )

    dm_push_fn = None
    if cfg.get( "arbiter outreach dm push enabled", default=True, return_type="boolean" ):
        dm_push_fn = make_dm_push_fn(
            base_url         = base_url,
            api_key          = api_key,
            sender_session_id = "lupin-arbiter-app-8001",
            timeout_seconds  = timeout,
        )

    target_error = validate_live_notify_target( target_user )
    if target_error:
        _default_log_fn( "live_notify_misconfigured", error=target_error )
        try:
            gateway.post( "fleet-escalations",
                          f"ARBITER MISCONFIGURED — live push to Rick is DISABLED: {target_error}" )
        except Exception as e:
            _default_log_fn( "escalation_post_error", error=str( e ) )
        return None, None, dm_push_fn, tmux_push_fn

    # Two transports (bug e1bbe011): the first-send transport persists a forensic
    # row (persist=True); the re-announce transport does NOT (persist=False) — so a
    # pending advisory re-pushed every reannounce_interval to an offline Rick
    # re-attempts LIVE delivery WITHOUT minting a duplicate DB row each retry (the
    # 3000+-row flood). Live delivery + the user_not_available/queued outcome are
    # unaffected, so re-announce still lands + terminates when Rick returns.
    transport = make_notify_transport(
        base_url=base_url, target_user=target_user, sender_id=sender_id,
        api_key=api_key, timeout_seconds=timeout,
    )
    retry_transport = make_notify_transport(
        base_url=base_url, target_user=target_user, sender_id=sender_id,
        api_key=api_key, timeout_seconds=timeout, persist=False,
    )
    return ( make_live_notify_fn( transport, dedup_window_seconds=dedup_window ),
             retry_transport, dm_push_fn, tmux_push_fn )


def create_production_app() -> FastAPI:   # pragma: no cover - literal external construction (config, gateway)
    """
    uvicorn `--factory` target: build the literal externals (ConfigurationManager,
    the bridge-less commons gateway, the :7999 outreach hops) and delegate ALL
    wiring/branching to the testable assemble_app. The hops are best-effort,
    escalation-path only; escalations always land durably on the
    fleet-escalations commons topic regardless.
    """
    from cosa.config.configuration_manager import ConfigurationManager
    from cosa.agents.heartbeat_arbiter.arbiter_gateway import LupinArbiterGateway
    cfg     = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    gateway = LupinArbiterGateway.from_environment( sender_session_id="lupin-arbiter-app-8001" )
    live_notify_fn, live_retry_fn, dm_push_fn, tmux_push_fn = _build_arbiter_outreach_hops( cfg, gateway )
    return assemble_app( cfg, gateway, live_notify_fn=live_notify_fn,
                         live_retry_fn=live_retry_fn, dm_push_fn=dm_push_fn,
                         tmux_push_fn=tmux_push_fn )


# Module-level loop-less ASGI entrypoint (safe to import; used by /health-only boots
# and unit tests). Production uses `create_production_app` via uvicorn --factory.
app = create_app()
