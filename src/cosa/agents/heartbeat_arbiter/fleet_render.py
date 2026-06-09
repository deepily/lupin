#!/usr/bin/env python3
"""
Heartbeat Arbiter — v2.1 direct-state fleet render + snapshot (pure).

The consumer-side of the v2.1 "direct-state visibility" design (arbiter design
`03` §10.2-§10.4). The arbiter rebuilds the fleet view every poll; THIS module
turns that view (+ the per-session bridge-mtime liveness clock) into:

    - a per-session LIVENESS block — ages off direct signals + a verdict label,
      kept ORTHOGONAL to the semantic `state` column (redline C4 / §10.2:
      "Never collapse state and liveness");
    - a JSON-able fleet SNAPSHOT for the `GET /api/arbiter/fleet-snapshot`
      surface (§10.4);
    - a full-fleet TABLE rendered on change, and a one-line TICK showing the
      duration-since-last-change when nothing changed (§10.3 / D1);
    - a change SIGNATURE over the SEMANTIC fields only (state/holding/stuck/
      roster) so the continuously-advancing liveness ages do NOT count as a
      "change" (else every poll would re-print the full table).

Liveness is shown as honest AGES, never a bare boolean — "a binary 'alive' is
itself an inference; a timestamp is not" (source analysis §3). The verdict label
(`LIVE` / `quiet Nm` / `stale Nm` / `offline`) rides OVER the ages but never
hides them.

Pure + never-raises. Design authority: lupin
    src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md §10.
"""
import datetime

from cosa.agents.heartbeat_arbiter.manager_resolver import SOURCE_LINEAGE


# Liveness verdict thresholds (seconds). Defaults are render-layer constants
# (not INI keys) so the lane stays config-light; the arbiter passes its own
# alive/quiet thresholds through where they line up. Tunable later if prod is
# noisy (the trust-label + manager judgment absorb mislabels meanwhile).
DEFAULT_LIVE_SECONDS    = 60      # freshest signal within a poll ⇒ LIVE
DEFAULT_QUIET_SECONDS   = 600     # within the alive window ⇒ quiet Nm
DEFAULT_STALE_SECONDS   = 3600    # within an hour ⇒ stale Nm; beyond ⇒ offline


def _fmt_age( seconds ):
    """
    Human-compact age string: '4s' / '6m' / '2h' / '3d'; '—' for None/negative.

    Ensures:
        - None ⇒ "—"; a future/negative age clamps to "0s"
        - sub-minute ⇒ Ns, sub-hour ⇒ Nm, sub-day ⇒ Nh, else Nd (floored)
        - never raises
    """
    if seconds is None:
        return "—"
    s = int( seconds )
    if s < 0:
        return "0s"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _bridge_age( bridge_mtime, now ):
    """Seconds since the bridge-file mtime (epoch float), or None. Never raises."""
    if bridge_mtime is None:
        return None
    try:
        return now.timestamp() - float( bridge_mtime )
    except ( TypeError, ValueError, OSError, OverflowError ):
        return None


def _event_age( last_event_ts, now ):
    """Seconds since the last heartbeat-event ts (aware datetime), or None."""
    if last_event_ts is None:
        return None
    try:
        return ( now - last_event_ts ).total_seconds()
    except ( TypeError, AttributeError ):
        return None


def _verdict( freshest_age, live_seconds, quiet_seconds, stale_seconds ):
    """
    Liveness verdict label from the FRESHEST direct-signal age (§10.2).

    Ensures:
        - None (no signal at all) ⇒ "offline"
        - age <= live_seconds        ⇒ "LIVE"
        - age <= quiet_seconds       ⇒ "quiet {age}"
        - age <= stale_seconds       ⇒ "stale {age}"
        - else                       ⇒ "offline"
        - the label carries the age (never a bare state); never raises
    """
    if freshest_age is None:
        return "offline"
    if freshest_age <= live_seconds:
        return "LIVE"
    if freshest_age <= quiet_seconds:
        return f"quiet {_fmt_age( freshest_age )}"
    if freshest_age <= stale_seconds:
        return f"stale {_fmt_age( freshest_age )}"
    return "offline"


def compute_liveness( view, bridge_mtime, now,
                      live_seconds  = DEFAULT_LIVE_SECONDS,
                      quiet_seconds = DEFAULT_QUIET_SECONDS,
                      stale_seconds = DEFAULT_STALE_SECONDS ):
    """
    Build the per-session LIVENESS block — FOUR distinct ages + verdict.

    The verdict rides the FRESHEST of FOUR direct-signal ages (arbiter liveness
    fix, Part 7 / Step 1.5) — the OLD code saw only {bridge, event}, so a worker
    live-by-commons or live-by-idle_prompt (but with a stale stop-event) read
    `offline`: the false WHOLE-FLEET-STALL bug. The four ages stay DISTINCT
    columns (never collapsed):
        - bridge_age_s      — bridge-file mtime (wedge-resilient PRIMARY, §10.1)
        - event_age_s       — last STOP/non-idle_prompt event ts (stop-event age)
        - commons_age_s     — last commons_who activity ts
        - idle_prompt_age_s — last kind=idle_prompt recency beacon ts (Step 1.3)
    A session is LIVE if ANY signal is fresh (bias-to-alive); offline only when
    NONE is recent.

    Requires:
        - view is a per-session fleet-view dict (build_fleet_view output) — it
          carries last_event_ts / commons_ts / idle_prompt_ts as DISTINCT fields
        - bridge_mtime is an epoch-seconds float or None (get_bridge_mtime)
        - now is an aware datetime; thresholds are positive seconds

    Ensures:
        - returns { bridge_age_s, event_age_s, commons_age_s, idle_prompt_age_s,
          freshest_age_s, verdict } — ages are int seconds (or None), verdict is
          the §10.2 label off `freshest_age_s = min(present ages)`
        - state is NOT consulted here (orthogonal columns, C4)
        - never raises
    """
    is_view         = isinstance( view, dict )
    bridge_age      = _bridge_age( bridge_mtime, now )
    event_age       = _event_age( view.get( "last_event_ts" )  if is_view else None, now )
    commons_age     = _event_age( view.get( "commons_ts" )     if is_view else None, now )
    idle_prompt_age = _event_age( view.get( "idle_prompt_ts" ) if is_view else None, now )

    candidates = [ a for a in ( bridge_age, event_age, commons_age, idle_prompt_age ) if a is not None ]
    freshest   = min( candidates ) if candidates else None

    def _int( a ):
        return None if a is None else int( a )

    return {
        "bridge_age_s"      : _int( bridge_age ),
        "event_age_s"       : _int( event_age ),
        "commons_age_s"     : _int( commons_age ),
        "idle_prompt_age_s" : _int( idle_prompt_age ),
        "freshest_age_s"    : _int( freshest ),
        "verdict"           : _verdict( freshest, live_seconds, quiet_seconds, stale_seconds ),
    }


def _sid_matches( a, b ):
    """
    Prefix-tolerant session-id match (short 8-char ids vs full uuids).

    Mirrors `manager_resolver._id_matches` — kept LOCAL so build_snapshot's role
    membership test stays self-contained and pure (no import of a sibling's
    private symbol). The fleet_view keys are often short 8-char ids while the
    manager set carries full slugified uuids, so equality alone under-matches.

    Ensures:
        - True when either id equals or is a prefix of the other; False if either
          is falsy
    """
    if not a or not b:
        return False
    return a == b or a.startswith( b ) or b.startswith( a )


def build_snapshot( fleet_view, bridge_mtimes, now,
                    live_seconds       = DEFAULT_LIVE_SECONDS,
                    quiet_seconds      = DEFAULT_QUIET_SECONDS,
                    stale_seconds      = DEFAULT_STALE_SECONDS,
                    resolve_manager_fn = None,
                    list_managers_fn   = None ):
    """
    Build the JSON-able full-fleet snapshot for the GET endpoint (§10.4), enriched
    with per-session hierarchy (Fleet-Status P1, design §4).

    Requires:
        - fleet_view is { session_id: VIEW } (build_fleet_view output)
        - bridge_mtimes is { session_id: epoch-float|None }
        - now is an aware datetime

    Ensures:
        - returns { generated_at(iso), session_count, sessions: [row, ...] }
          sorted by session_id for stable rendering/diffing
        - each row keeps STATE and LIVENESS as separate keys (C4) PLUS the two
          hierarchy keys (role, manager):
          { session_id, persona, state, holding_on, stuck, liveness{...},
            role, manager }
        - role = "manager" if the session-id (prefix-tolerantly) belongs to the
          injected manager set (list_managers_fn), else "worker"
        - manager = resolve_manager_fn(sid).manager_persona ONLY when its source
          is "lineage"; for declared/unresolved/error → None (degrade-safe: we
          NEVER show a guessed manager — None lands the row in the "Unmanaged"
          group rather than mis-parenting a worker)
        - INJECTED seams (both default None) keep this function pure + 100%-
          testable with fakes, mirroring arbiter_job's resolve_active_managers_fn
          injection. With neither injected → role="worker", manager=None for every
          row (back-compatible flat snapshot)
        - never raises — a throwing list_managers_fn degrades to an empty manager
          set (all workers); a throwing resolve_manager_fn degrades that row to
          manager=None
    """
    manager_ids = set()
    if list_managers_fn is not None:
        try:
            manager_ids = list_managers_fn() or set()
        except Exception:
            manager_ids = set()

    rows = [ ]
    for sid in sorted( ( fleet_view or { } ).keys() ):
        view = fleet_view[ sid ]
        if not isinstance( view, dict ):
            continue
        liveness = compute_liveness(
            view, ( bridge_mtimes or { } ).get( sid ), now,
            live_seconds, quiet_seconds, stale_seconds,
        )
        role    = "manager" if any( _sid_matches( sid, mid ) for mid in manager_ids ) else "worker"
        manager = None
        if resolve_manager_fn is not None:
            try:
                res = resolve_manager_fn( sid )
                if isinstance( res, dict ) and res.get( "source" ) == SOURCE_LINEAGE:
                    manager = res.get( "manager_persona" )
            except Exception:
                manager = None
        rows.append( {
            "session_id" : sid,
            "persona"    : view.get( "persona" ),
            "state"      : view.get( "state" ),
            "holding_on" : view.get( "holding_on" ),
            "stuck"      : bool( view.get( "stuck" ) ),
            "liveness"   : liveness,
            "role"       : role,
            "manager"    : manager,
        } )
    return {
        "generated_at"  : now.isoformat(),
        "session_count" : len( rows ),
        "sessions"      : rows,
    }


def frame_signature( snapshot ):
    """
    A hashable signature over the SEMANTIC fields only — NOT the liveness ages.

    Ensures:
        - returns a tuple capturing { session_id, persona, state, holding_on,
          stuck, verdict } per session (sorted) — the verdict is a coarse
          liveness *bucket* (LIVE/quiet/stale/offline), included so a session
          crossing a liveness threshold counts as a change, but the raw
          continuously-advancing ages are EXCLUDED so a steady fleet does NOT
          re-print every poll (§10.3 change-vs-tick)
        - never raises
    """
    sig = [ ]
    for row in ( snapshot or { } ).get( "sessions", [ ] ):
        verdict = row.get( "liveness", { } ).get( "verdict" )
        # Collapse the age-bearing verdict ("quiet 6m") to its bucket word so
        # ticking within a bucket isn't a change; only bucket transitions are.
        bucket = verdict.split( " " )[ 0 ] if isinstance( verdict, str ) else verdict
        sig.append( (
            row.get( "session_id" ), row.get( "persona" ), row.get( "state" ),
            row.get( "holding_on" ), bool( row.get( "stuck" ) ), bucket,
        ) )
    return tuple( sig )


def render_fleet_table( snapshot ):
    """
    Render the full-fleet table (printed when the frame changes — §10.3).

    Ensures:
        - returns a multi-line string: a header line + one row per session
          with STATE and LIVENESS in SEPARATE columns (C4), liveness shown as
          honest ages plus the verdict label
        - an empty fleet renders a single "(no sessions)" line under the header
        - never raises
    """
    when  = ( snapshot or { } ).get( "generated_at", "" )
    rows  = ( snapshot or { } ).get( "sessions", [ ] )
    lines = [ f"── Fleet arbiter — {len( rows )} session(s) @ {when} ──" ]
    header = f"  {'persona/sid':<18} {'state':<8} {'holding':<12} {'live(bridge/event)':<22} verdict"
    lines.append( header )
    if not rows:
        lines.append( "  (no sessions)" )
        return "\n".join( lines )
    for row in rows:
        live   = row.get( "liveness", { } )
        who    = row.get( "persona" ) or row.get( "session_id" ) or "?"
        ages   = f"{_fmt_age( live.get( 'bridge_age_s' ) )}/{_fmt_age( live.get( 'event_age_s' ) )}"
        stuck  = " STUCK" if row.get( "stuck" ) else ""
        lines.append(
            f"  {who:<18} {str( row.get( 'state' ) ):<8} "
            f"{str( row.get( 'holding_on' ) ):<12} {ages:<22} {live.get( 'verdict' )}{stuck}"
        )
    return "\n".join( lines )


def render_tick( now, last_change_at, session_count ):
    """
    Render the one-line heartbeat tick for an UNCHANGED frame (§10.3 / D1).

    Rick's proviso: show the DURATION SINCE the last change, not just the clock
    — e.g. `tick · no changes for 12m (since 22:29) · 5 sessions · 22:41`.

    Requires:
        - now is an aware datetime; session_count is an int
        - last_change_at is an aware datetime or None (None ⇒ never-changed yet)

    Ensures:
        - returns the single-line tick string with the since-duration + counts
        - never raises
    """
    clock = now.strftime( "%H:%M" )
    if last_change_at is None:
        return f"tick · no changes yet · {session_count} session(s) · {clock}"
    dur   = _fmt_age( ( now - last_change_at ).total_seconds() )
    since = last_change_at.strftime( "%H:%M" )
    return f"tick · no changes for {dur} (since {since}) · {session_count} session(s) · {clock}"


def quick_smoke_test():
    """Self-contained smoke test. Returns True or raises AssertionError."""
    now = datetime.datetime( 2026, 6, 6, 22, 41, 0, tzinfo=datetime.timezone.utc )

    view = {
        "s1": { "session_id": "s1", "persona": "Ann", "state": "working",
                "holding_on": "none", "stuck": False,
                "last_event_ts": now - datetime.timedelta( minutes=35 ) },
        "s2": { "session_id": "s2", "persona": "Bo", "state": "stuck",
                "holding_on": "peer:Ann", "stuck": True, "last_event_ts": None },
        # s3: LIVE by COMMONS ONLY — no bridge, no stop-event, fresh commons_ts.
        # The OLD 2-age verdict read this `offline` (the bug); the 4-age fix LIVEs it.
        "s3": { "session_id": "s3", "persona": "Cy", "state": "working",
                "holding_on": "none", "stuck": False,
                "last_event_ts": None, "commons_ts": now - datetime.timedelta( seconds=5 ) },
        # s4: LIVE by IDLE_PROMPT ONLY — no bridge/event/commons, fresh idle_prompt_ts.
        "s4": { "session_id": "s4", "persona": "Di", "state": "unknown",
                "holding_on": "none", "stuck": False,
                "last_event_ts": None, "idle_prompt_ts": now - datetime.timedelta( seconds=8 ) },
    }
    bridge_mtimes = { "s1": now.timestamp() - 4, "s2": None }   # s1 fresh bridge, s2 dark

    snap = build_snapshot( view, bridge_mtimes, now )
    assert snap[ "session_count" ] == 4
    s1 = snap[ "sessions" ][ 0 ]
    # s1: bridge 4s ⇒ LIVE, even though its event ts is 35m old (bridge is PRIMARY)
    assert s1[ "liveness" ][ "verdict" ] == "LIVE", s1[ "liveness" ]
    assert s1[ "liveness" ][ "bridge_age_s" ] == 4 and s1[ "liveness" ][ "event_age_s" ] == 35 * 60
    # all four age columns are present + distinct (never collapsed)
    assert set( s1[ "liveness" ] ) >= {
        "bridge_age_s", "event_age_s", "commons_age_s", "idle_prompt_age_s", "freshest_age_s", "verdict"
    }
    # state and liveness are separate keys (orthogonal columns, C4)
    assert s1[ "state" ] == "working" and "verdict" in s1[ "liveness" ]
    # s2: no bridge, no event, no commons, no idle_prompt ⇒ offline
    assert snap[ "sessions" ][ 1 ][ "liveness" ][ "verdict" ] == "offline"
    # s3: LIVE purely by commons (the 4-age fix); commons_age set, others None
    s3 = snap[ "sessions" ][ 2 ][ "liveness" ]
    assert s3[ "verdict" ] == "LIVE" and s3[ "commons_age_s" ] == 5
    assert s3[ "bridge_age_s" ] is None and s3[ "event_age_s" ] is None and s3[ "idle_prompt_age_s" ] is None
    # s4: LIVE purely by idle_prompt
    s4 = snap[ "sessions" ][ 3 ][ "liveness" ]
    assert s4[ "verdict" ] == "LIVE" and s4[ "idle_prompt_age_s" ] == 8

    # hierarchy enrichment (Fleet-Status P1 §4): default snapshot carries the two
    # keys flat (role=worker, manager=None), and the injected seams light them up.
    assert snap[ "sessions" ][ 0 ][ "role" ] == "worker" and snap[ "sessions" ][ 0 ][ "manager" ] is None
    enriched = build_snapshot(
        view, bridge_mtimes, now,
        list_managers_fn   = lambda: { "s1" },                       # s1 is a manager
        resolve_manager_fn = lambda sid: (                           # s2 reports to Ann via lineage
            { "manager_persona": "Ann", "source": SOURCE_LINEAGE } if sid == "s2"
            else { "manager_persona": None, "source": "unresolved" }
        ),
    )
    e = { r[ "session_id" ]: r for r in enriched[ "sessions" ] }
    assert e[ "s1" ][ "role" ] == "manager" and e[ "s1" ][ "manager" ] is None
    assert e[ "s2" ][ "role" ] == "worker"  and e[ "s2" ][ "manager" ] == "Ann"

    # change signature ignores the ticking ages (same buckets ⇒ same sig)
    later = now + datetime.timedelta( seconds=10 )
    snap2 = build_snapshot( view, { "s1": later.timestamp() - 9, "s2": None }, later )
    assert frame_signature( snap ) == frame_signature( snap2 ), "tick must not be a change"

    table = render_fleet_table( snap )
    assert "Fleet arbiter" in table and "verdict" in table and "STUCK" in table
    assert "(no sessions)" in render_fleet_table( build_snapshot( { }, { }, now ) )

    tick = render_tick( now, now - datetime.timedelta( minutes=12 ), 5 )
    assert "no changes for 12m" in tick and "5 session(s)" in tick
    assert "no changes yet" in render_tick( now, None, 0 )
    assert _fmt_age( None ) == "—" and _fmt_age( -5 ) == "0s" and _fmt_age( 90000 ) == "1d"
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"fleet_render smoke: {'PASS' if ok else 'FAIL'}" )
