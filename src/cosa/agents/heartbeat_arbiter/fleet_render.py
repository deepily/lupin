#!/usr/bin/env python3
"""
Pure fleet liveness block, snapshot, table, tick and change signature for the arbiter.

This is the consumer side of the direct-state visibility design. The arbiter rebuilds the fleet view every poll.
This module turns that view, plus the per-session bridge-mtime liveness clock, into the following.

    - a per-session liveness block: ages off direct signals plus a verdict label, kept orthogonal to the semantic `state` column (never collapse state and liveness)
    - a JSON-able fleet snapshot for the `GET /api/arbiter/fleet-snapshot` surface
    - a full-fleet table rendered on change, and a one-line tick showing the time since the last change when nothing changed
    - a change signature over the semantic fields only (state, holding, stuck, roster)

The signature leaves out the liveness ages, because they advance continuously and every poll would otherwise re-print the full table.
Liveness is shown as honest ages, never a bare boolean, because a binary "alive" is itself an inference and a timestamp is not.
The verdict label (`LIVE`, `quiet Nm`, `stale Nm`, `offline`) rides over the ages but never hides them.

Pure and never raises.

Design: src/rnd/v0.1.8/2026.06.04-heartbeat-hook/03-arbiter-design.md (direct-state fleet render).
"""
import datetime

from cosa.agents.heartbeat_arbiter.manager_resolver import SOURCE_LINEAGE
# bug 65d1247f: REUSE the edge gate's freshness predicate + peer prefix so the
# rendered holding_on agrees with peer-EDGE inference (single source of truth —
# do NOT re-implement a second staleness predicate).
from cosa.agents.heartbeat_arbiter.dependency_graph import PEER_PREFIX, session_is_stale
# F-B: THE one persona-equivalence normalizer (allocation/DM path's own).
from lupin_mcp.persona_normalization import canonical_persona_key


# Liveness verdict thresholds (seconds). Defaults are render-layer constants
# (not INI keys) so the lane stays config-light; the arbiter passes its own
# alive/quiet thresholds through where they line up. Tunable later if prod is
# noisy (the trust-label + manager judgment absorb mislabels meanwhile).
DEFAULT_LIVE_SECONDS    = 60      # freshest signal within a poll ⇒ LIVE
DEFAULT_QUIET_SECONDS   = 600     # within the alive window ⇒ quiet Nm
DEFAULT_STALE_SECONDS   = 3600    # within an hour ⇒ stale Nm; beyond ⇒ offline


def _fmt_age( seconds ):
    """
    Format an age in seconds as a compact string such as 4s, 6m, 2h or 3d.

    Ensures:
        - None gives "—"; a future or negative age clamps to "0s"
        - sub-minute gives Ns, sub-hour gives Nm, sub-day gives Nh, else Nd (floored)
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
    Return the liveness verdict label for the freshest direct-signal age.

    Ensures:
        - None (no signal at all) gives "offline"
        - age <= live_seconds gives "LIVE"
        - age <= quiet_seconds gives "quiet {age}"
        - age <= stale_seconds gives "stale {age}"
        - anything older gives "offline"
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
                      stale_seconds = DEFAULT_STALE_SECONDS,
                      count_dm      = True,
                      hold_mtime    = None,
                      transcript_mtime = None ):
    """
    Build the per-session liveness block: distinct signal ages plus one verdict label.

    The verdict rides the freshest of up to seven direct-signal ages, and the ages stay distinct columns, never collapsed.
    Counting only bridge and event ages made a worker read `offline` when it was live by commons or idle_prompt but had a stale stop-event. That was a false whole-fleet stall.
    A session is `LIVE` if any counted signal is fresh (bias to alive), and offline only when none is recent.

    Requires:
        - view is a per-session fleet-view dict (build_fleet_view output) carrying last_event_ts, commons_ts, idle_prompt_ts and dm_ts as distinct fields
        - bridge_mtime is an epoch-seconds float or None (get_bridge_mtime)
        - now is an aware datetime; thresholds are positive seconds
        - count_dm is a bool: whether dm_age joins the freshest-of union
        - hold_mtime is an epoch-seconds float or None (the hold-file mtime; the arbiter reads it out-of-band per session, mirroring bridge_mtime)
        - transcript_mtime is an epoch-seconds float or None (the transcript file mtime, read out-of-band like hold_mtime)

    Ensures:
        - returns { bridge_age_s, event_age_s, commons_age_s, idle_prompt_age_s, dm_age_s, hold_age_s, transcript_age_s, freshest_age_s, verdict }; ages are int seconds (or None) and the verdict is the `_verdict` label off `freshest_age_s = min(present counted ages)`
        - the ages come from the bridge-file mtime (the wedge-resilient primary), the last stop (non-idle_prompt) event ts, the last commons_who ts, the last idle_prompt beacon ts, the last sent ai_to_ai DM ts, the hold-file mtime and the transcript mtime
        - dm_age_s is always present (auditable) regardless of count_dm; it joins the freshest-of union only when count_dm is True. It is a store-sourced, hook-independent sign of life for a manager whose only activity is dm_send, whose bridge mtime may never bump. count_dm=False makes freshest_age_s and the verdict byte-identical to the prior 4-signal block. DM is a life signal, never a progress or state signal
        - hold_age_s is present iff hold_mtime is not None; when present it always joins the freshest-of union. A fresh hold mtime means the Stop hook ran, so an interactive manager that refreshes its hold every turn is alive even if it never posts to commons. It can only make a session read more alive, never hide a dark one, whose hold mtime ages out like every other signal. hold_mtime=None means hold_age_s is None and the verdict matches the prior 5-signal block
        - transcript_age_s is present iff transcript_mtime is not None; when present it always joins the freshest-of union. The harness appends to the transcript on every assistant or tool event, so its mtime bumps during a long single-turn tool sequence (plan-mode drafting, a big multi-file edit run) when no Stop fires and the other signals age past stale. A missing or unreadable transcript is no signal, so a dark session is never masked. transcript_mtime=None means transcript_age_s is None and the verdict matches the prior 6-signal block
        - state is not consulted here (orthogonal columns)
        - never raises
    """
    is_view         = isinstance( view, dict )
    bridge_age      = _bridge_age( bridge_mtime, now )
    event_age       = _event_age( view.get( "last_event_ts" )  if is_view else None, now )
    commons_age     = _event_age( view.get( "commons_ts" )     if is_view else None, now )
    idle_prompt_age = _event_age( view.get( "idle_prompt_ts" ) if is_view else None, now )
    # dm_age is ALWAYS computed (auditable column) but joins the freshest-of
    # union ONLY when the toggle is on — so count_dm=False is byte-identical to
    # the prior 4-signal verdict (the reversibility guarantee).
    dm_age          = _event_age( view.get( "dm_ts" )          if is_view else None, now )
    # hold_age (task 70be69f2): the hold-file mtime is an epoch float (same shape
    # as bridge_mtime), so _bridge_age reads it. UNCONDITIONAL in the union — a
    # fresh hold mtime is an unambiguous sign of life. None hold_mtime ⇒ None age.
    hold_age        = _bridge_age( hold_mtime, now )
    # transcript_age (bug fb332fcd): the transcript .jsonl mtime is an epoch float
    # (same shape as bridge_mtime), so _bridge_age reads it. UNCONDITIONAL in the
    # union — a fresh transcript mtime means the process is actively appending
    # turns (incl. mid-plan, when NO Stop fires and the other 6 signals age out).
    # None transcript_mtime ⇒ None age (fail-safe: a missing/unreadable transcript
    # adds NO life, so a genuinely-dark session still ages to STALE).
    transcript_age  = _bridge_age( transcript_mtime, now )

    candidates = [ a for a in ( bridge_age, event_age, commons_age, idle_prompt_age ) if a is not None ]
    if count_dm and dm_age is not None:
        candidates.append( dm_age )
    if hold_age is not None:
        candidates.append( hold_age )
    if transcript_age is not None:
        candidates.append( transcript_age )
    freshest   = min( candidates ) if candidates else None

    def _int( a ):
        return None if a is None else int( a )

    return {
        "bridge_age_s"      : _int( bridge_age ),
        "event_age_s"       : _int( event_age ),
        "commons_age_s"     : _int( commons_age ),
        "idle_prompt_age_s" : _int( idle_prompt_age ),
        "dm_age_s"          : _int( dm_age ),
        "hold_age_s"        : _int( hold_age ),
        "transcript_age_s"  : _int( transcript_age ),
        "freshest_age_s"    : _int( freshest ),
        "verdict"           : _verdict( freshest, live_seconds, quiet_seconds, stale_seconds ),
    }


def _sid_matches( a, b ):
    """
    Say whether two session ids match, tolerating short-id versus full-uuid forms.

    This mirrors `manager_resolver._id_matches` but is kept local, so build_snapshot's role membership test stays self-contained and imports no private sibling symbol.
    The fleet_view keys are often short 8-char ids while the manager set carries full uuids, so equality alone under-matches.

    Ensures:
        - True when either id equals or is a prefix of the other; False if either
          is falsy
    """
    if not a or not b:
        return False
    return a == b or a.startswith( b ) or b.startswith( a )


def _lookup_dead( process_dead, sid ):
    """
    Say whether sid prefix-matches any entry of the confirmed-dead session set.

    This mirrors _sid_matches, so a `fleet_view` key (often an 8-char id) matches a dead-set entry carrying the full uuid, and the reverse.
    A falsy or empty `process_dead` is never a match.

    Ensures:
        - True iff some entry of process_dead prefix-matches sid; else False
        - pure; never raises
    """
    return any( _sid_matches( sid, dead_sid ) for dead_sid in ( process_dead or () ) )


def build_snapshot( fleet_view, bridge_mtimes, now,
                    live_seconds         = DEFAULT_LIVE_SECONDS,
                    quiet_seconds        = DEFAULT_QUIET_SECONDS,
                    stale_seconds        = DEFAULT_STALE_SECONDS,
                    resolve_manager_fn   = None,
                    list_managers_fn     = None,
                    process_dead         = None,
                    include_offline      = False,
                    declared_managers    = None,
                    count_dm_as_liveness = True,
                    hold_mtimes          = None,
                    transcript_mtimes    = None,
                    alive_threshold_seconds = None ):
    """
    Build the JSON-able fleet snapshot with per-session hierarchy, live rows only by default.

    Each row pairs the liveness block (see compute_liveness) with the role and manager hierarchy keys.

    Requires:
        - fleet_view is { session_id: view } (build_fleet_view output)
        - bridge_mtimes is { session_id: epoch-float|None }
        - now is an aware datetime

    Ensures:
        - returns { generated_at(iso), session_count, sessions: [row, ...] } sorted by session_id for stable rendering and diffing
        - by default (include_offline=False) a session whose verdict is "offline" is omitted, so the dead-session graveyard never reaches consumers; include_offline=True keeps offline rows (audit, back-compat). Only the published snapshot is pruned: the arbiter's decision logic reads fleet_view, not this snapshot, so routing and stall detection are untouched
        - process_dead is an optional iterable of confirmed-dead session ids (default None); a row whose sid prefix-matches one is forced to verdict "offline" with liveness.process_dead=True regardless of its signal ages, so an exited session drops in about one poll instead of aging out over about an hour. Bias to alive: only a positive dead reading overrides, and an absent sid keeps its age verdict. The verdict string set is unchanged; process_dead is an additive transparency flag
        - count_dm_as_liveness (default True, the `arbiter count dm as liveness` toggle) is passed unchanged to compute_liveness(count_dm=...): True lets a session's sent-DM age join the freshest-of union (a coordination-only manager reads `LIVE`); False makes each liveness block byte-identical to the prior 4-signal verdict (dm_age_s still present for audit, only excluded from the union). DM feeds liveness only, never state or the progress signature
        - hold_mtimes (default None) is { session_id: epoch-float|None }; each row's hold mtime is passed to compute_liveness(hold_mtime=...), so its hold_age_s joins the freshest-of union unconditionally (an interactive manager that only refreshes its hold at Stop reads `LIVE`, not stale). None or a missing sid means hold_age_s is None for that row, byte-identical to the prior block. Hold mtime feeds liveness only, never state or the progress signature
        - transcript_mtimes (default None) is { session_id: epoch-float|None }; each row's transcript mtime is passed to compute_liveness(transcript_mtime=...), so its transcript_age_s joins the freshest-of union unconditionally (a manager mid-plan, appending its transcript on every tool call but emitting no Stop, reads `LIVE`, not stale). None or a missing sid means transcript_age_s is None for that row, byte-identical to the prior block; a missing or unreadable transcript is no signal, so a dark session is never masked. Transcript mtime feeds liveness only, never state or the progress signature
        - alive_threshold_seconds (default None) gates display sanitization: a row whose holder session is beyond the alive threshold (dependency_graph.session_is_stale, the same predicate the peer-edge gate uses) shows its `peer:X` holding_on as the neutral "none", so the displayed hold agrees with edge inference. None means no gate, byte-identical to the prior render. Only peer-prefixed holds are gated (user: and commons: holds are untouched). Fail-safe: a missing or unparseable last_activity_ts is not stale, so the raw value is kept and a live hold is never hidden. Display only: edge inference and the deadlock escalation are untouched
        - each row keeps state and liveness as separate keys plus the two hierarchy keys: { session_id, persona, state, holding_on, stuck, liveness{...}, role, manager }
        - role = "manager" if the session id (prefix-tolerantly) belongs to the injected manager set (list_managers_fn) or its persona is in the declared roster (`declared_managers`, compared case-insensitively through canonical_persona_key, from `COSA_VOICE_MANAGERS__<PROJECT>`; a declared manager badges as manager even before its first spawn), else "worker"
        - manager = resolve_manager_fn(sid).manager_persona only when its source is "lineage"; for declared, unresolved or error sources it is None; a guessed manager is never shown, and None lands the row in the "Unmanaged" group rather than mis-parenting a worker
        - the seams list_managers_fn and resolve_manager_fn (both default None) keep this function pure and fully testable with fakes; with neither injected every row is role="worker", manager=None (flat, back-compatible)
        - session_count reflects the emitted rows (post-prune), not the input size
        - never raises: a throwing list_managers_fn degrades to an empty manager set (all workers); a throwing resolve_manager_fn degrades that row to manager=None
    """
    manager_ids = set()
    if list_managers_fn is not None:
        try:
            manager_ids = list_managers_fn() or set()
        except Exception:
            manager_ids = set()
    # F-B (2026.06.11 lineage-persistence design): persona equivalence uses THE
    # one shared identity root (persona_normalization.canonical_persona_key —
    # "Mr. Radio"/"mr radio"/"MR.RADIO" → "mr radio"; "María" → "maria").
    # Persona strings drift structurally across signal sources (bridge keeps
    # display casing; the event-sourced fallback is lowercase punct-stripped),
    # so the journal-confirmed miss — persona "mr radio" reading role=worker,
    # with the F2 manager-staleness tier config-dead for him — is inherent to any
    # exact compare. The swap from the space-dropping match-key to the keep-spaces
    # canonical key is symmetric on both compare sides (equivalence preserved) and
    # the value now EQUALS the store key. Normalization is for COMPARISON only;
    # display casing untouched.
    declared_norm = { canonical_persona_key( str( name ) ) for name in ( declared_managers or [ ] )
                      if canonical_persona_key( str( name ) ) }

    rows = [ ]
    for sid in sorted( ( fleet_view or { } ).keys() ):
        view = fleet_view[ sid ]
        if not isinstance( view, dict ):
            continue
        liveness = compute_liveness(
            view, ( bridge_mtimes or { } ).get( sid ), now,
            live_seconds, quiet_seconds, stale_seconds,
            count_dm   = count_dm_as_liveness,
            hold_mtime = ( hold_mtimes or { } ).get( sid ),
            transcript_mtime = ( transcript_mtimes or { } ).get( sid ),
        )
        # PID fast-death override (kill-0): a CONFIRMED-dead process forces
        # "offline" now, regardless of how recent its last signal was — so a
        # /exit'd session drops in ~1 poll, not after the ~1h stale window. Only a
        # positive dead reading overrides (bias-to-alive); the additive
        # process_dead flag keeps the verdict STRING set unchanged.
        if _lookup_dead( process_dead, sid ):
            liveness[ "process_dead" ] = True
            liveness[ "verdict" ]      = "offline"
        # REAP TOMBSTONE override (reap-tombstone roster-eviction fix): a
        # host-side reap deletes the bridge BEFORE the arbiter can read the PID,
        # so process_dead (kill-0) structurally can't fire for a reaped session.
        # The authoritative kind="reaped" marker (carried on view["reaped"]) is
        # the death signal kill-0 can't supply — force "offline" so the
        # publish-prune evicts the row in ~1 poll instead of the ~60-min age-out.
        # Additive sibling to process_dead (which still catches /exit'd sessions
        # whose bridge lingers); the verdict STRING set is unchanged.
        if view.get( "reaped" ):
            liveness[ "reaped" ]  = True
            liveness[ "verdict" ] = "offline"
        # D6 / §5.2: omit offline sessions from the PUBLISHED snapshot by default.
        if not include_offline and liveness.get( "verdict" ) == "offline":
            continue
        persona_value = view.get( "persona" )
        is_declared   = bool( persona_value ) and canonical_persona_key( str( persona_value ) ) in declared_norm
        role          = "manager" if ( is_declared or any( _sid_matches( sid, mid ) for mid in manager_ids ) ) else "worker"
        manager       = None
        if resolve_manager_fn is not None:
            try:
                res = resolve_manager_fn( sid )
                if isinstance( res, dict ) and res.get( "source" ) == SOURCE_LINEAGE:
                    manager = res.get( "manager_persona" )
            except Exception:
                manager = None
        # bug 65d1247f (DISPLAY-only): make the rendered holding_on AGREE with the
        # peer-EDGE gate. 37511bfb drops a STALE holder session's peer EDGE from
        # inference; here we drop its peer DISPLAY too — a beyond-alive-threshold
        # session shows a neutral "none" instead of a phantom-active "peer:X".
        # Peer-prefix-gated (mirrors build_wait_edges: only peer holds were ever
        # edges, so user:/commons: holds stay honest) and fail-SAFE (session_is_stale
        # returns False for a missing/unparseable last_activity_ts, AND for the
        # additive alive_threshold_seconds=None default ⇒ no gate, byte-identical to
        # the prior render) — never hides a LIVE hold.
        holding_on = view.get( "holding_on" )
        if ( isinstance( holding_on, str ) and holding_on.startswith( PEER_PREFIX )
             and session_is_stale( view, now, alive_threshold_seconds ) ):
            holding_on = "none"
        rows.append( {
            "session_id" : sid,
            "persona"    : view.get( "persona" ),
            "state"      : view.get( "state" ),
            "holding_on" : holding_on,
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


def carry_forward_lineage( snapshot, prior_lineage ):
    """
    Fill a missing manager from the last poll that resolved it, until the row is evicted.

    A reaped worker loses both lineage sources at once: `session_spawner.dismiss_sessions` unlinks its bridge file and drops its spawn-manifest entry.
    The next poll's resolve_manager misses on both paths, so build_snapshot sets manager=None. The row would drop to "Unmanaged" while it still lingers in its stale decay window.
    The focus-bar badge still shows the manager, so that table would contradict it.

    Requires:
        - snapshot is a build_snapshot() result (or falsy / non-dict, returned as-is
          with an empty next-lineage)
        - prior_lineage is { session_id: manager_persona } carried from the prior poll
          (caller-owned, threaded across polls); None / non-dict is treated as {}

    Ensures:
        - returns ( snapshot, next_lineage ):
            * a row with a non-None manager refreshes next_lineage[sid]; the row is untouched
              (fresh lineage always wins over a carried value)
            * a row with manager None whose sid is in prior_lineage is filled:
              row["manager"] = prior_lineage[sid], row["manager_retained"] = True
              (a transparency flag), and it keeps carrying in next_lineage
            * a row with manager None and no prior entry stays unmanaged
            * next_lineage is pruned to the snapshot's current sids: a row gone from
              the published snapshot (offline-pruned, or left the fleet) forgets its lineage,
              which keeps the map bounded
        - never invents lineage, only replays a persona this fleet resolved before, and never raises (a malformed snapshot or row degrades to a skipped row or an empty carry); the manager field stays orthogonal to the semantic frame_signature, so the carry causes no spurious table re-render
    """
    prior        = prior_lineage if isinstance( prior_lineage, dict ) else { }
    next_lineage = { }
    rows         = ( snapshot or { } ).get( "sessions", [ ] ) if isinstance( snapshot, dict ) else [ ]
    for row in rows:
        if not isinstance( row, dict ):
            continue
        sid = row.get( "session_id" )
        if not sid:
            continue
        manager = row.get( "manager" )
        if manager is not None:
            next_lineage[ sid ] = manager                      # fresh lineage refreshes the carry
        elif sid in prior:
            row[ "manager" ]          = prior[ sid ]           # replay last-known (never invented)
            row[ "manager_retained" ] = True
            next_lineage[ sid ]       = prior[ sid ]
        # else: genuinely unmanaged — no carry, no invention
    return snapshot, next_lineage


def prune_offline_rows( snapshot ):
    """
    Drop offline rows from a snapshot and recount, giving the published live-only view.

    The arbiter builds one full snapshot (include_offline=True) so its detectors (manager staleness, fleet-dark) can see offline rows.
    It derives the published view through this helper. The published contract is live rows only, recounted.

    Requires:
        - snapshot is a build_snapshot() result (or any malformed value)

    Ensures:
        - returns a new top-level dict: same generated_at, `sessions` filtered to
          rows whose liveness verdict != "offline" (non-dict rows dropped), and
          `session_count` recounted to the emitted rows
        - row dicts are shared with the input (not copied); callers must not
          mutate rows after the split
        - a falsy / non-dict snapshot degrades to an empty snapshot dict
        - never raises
    """
    if not isinstance( snapshot, dict ):
        return { "generated_at": None, "session_count": 0, "sessions": [ ] }
    rows = [ ]
    for row in snapshot.get( "sessions", [ ] ):
        if not isinstance( row, dict ):
            continue
        liveness = row.get( "liveness" )
        verdict  = liveness.get( "verdict" ) if isinstance( liveness, dict ) else None
        if verdict != "offline":
            rows.append( row )
    out = dict( snapshot )
    out[ "sessions" ]      = rows
    out[ "session_count" ] = len( rows )
    return out


def frame_signature( snapshot ):
    """
    Return a hashable signature over the semantic fields only, not the liveness ages.

    Ensures:
        - returns a tuple capturing { session_id, persona, state, holding_on, stuck, verdict } per session, in row order (build_snapshot sorts rows by session_id); the verdict is a coarse liveness bucket (`LIVE`, quiet, stale, offline), included so a session crossing a liveness threshold counts as a change, but the raw continuously-advancing ages are excluded, so a steady fleet does not re-print every poll
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
    Render the full-fleet table, printed when the frame changes.

    Ensures:
        - returns a multi-line string: a header line plus one row per session
          with state and liveness in separate columns, liveness shown as
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
    Render the one-line tick for an unchanged frame, showing the time since the last change.

    The tick shows the duration since the last change, not just the clock. Example: `tick · no changes for 12m (since 22:29) · 5 sessions · 22:41`.

    Requires:
        - now is an aware datetime; session_count is an int
        - last_change_at is an aware datetime or None (None means never changed yet)

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
        # s5: REAPED — fresh commons would read LIVE, but the reap tombstone forces
        # offline so the publish-prune evicts it (the reap-tombstone fix).
        "s5": { "session_id": "s5", "persona": "Ed", "state": "unknown",
                "holding_on": "none", "stuck": False, "reaped": True,
                "last_event_ts": None, "commons_ts": now - datetime.timedelta( seconds=3 ) },
    }
    bridge_mtimes = { "s1": now.timestamp() - 4, "s2": None }   # s1 fresh bridge, s2 dark

    # include_offline=True keeps the offline s2 so the index-based assertions below
    # still exercise the offline path (the DEFAULT prune is asserted separately).
    snap = build_snapshot( view, bridge_mtimes, now, include_offline=True )
    assert snap[ "session_count" ] == 5
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
    # s5: reaped tombstone force-offlines it despite a 3s-fresh commons signal
    s5 = snap[ "sessions" ][ 4 ][ "liveness" ]
    assert s5[ "verdict" ] == "offline" and s5[ "reaped" ] is True and s5[ "commons_age_s" ] == 3

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
        include_offline    = True,                                   # keep s2 for the lineage assertion
    )
    e = { r[ "session_id" ]: r for r in enriched[ "sessions" ] }
    assert e[ "s1" ][ "role" ] == "manager" and e[ "s1" ][ "manager" ] is None
    assert e[ "s2" ][ "role" ] == "worker"  and e[ "s2" ][ "manager" ] == "Ann"

    # D6 / §5.2: the DEFAULT published snapshot OMITS the offline s2 (live-only),
    # while include_offline=True (above) retained it. Count reflects emitted rows.
    default_snap = build_snapshot( view, bridge_mtimes, now )
    assert default_snap[ "session_count" ] == 3
    assert { r[ "session_id" ] for r in default_snap[ "sessions" ] } == { "s1", "s3", "s4" }

    # change signature ignores the ticking ages (same buckets ⇒ same sig)
    later = now + datetime.timedelta( seconds=10 )
    snap2 = build_snapshot( view, { "s1": later.timestamp() - 9, "s2": None }, later, include_offline=True )
    assert frame_signature( snap ) == frame_signature( snap2 ), "tick must not be a change"

    table = render_fleet_table( snap )
    assert "Fleet arbiter" in table and "verdict" in table and "STUCK" in table
    assert "(no sessions)" in render_fleet_table( build_snapshot( { }, { }, now ) )

    tick = render_tick( now, now - datetime.timedelta( minutes=12 ), 5 )
    assert "no changes for 12m" in tick and "5 session(s)" in tick
    assert "no changes yet" in render_tick( now, None, 0 )
    assert _fmt_age( None ) == "—" and _fmt_age( -5 ) == "0s" and _fmt_age( 90000 ) == "1d"

    # offline-lineage carry (2026-06-10): poll-1 resolves s2→Ann (lineage); poll-2's
    # resolver misses (reaped: bridge+manifest gone) → s2 carries Ann + retained flag.
    snap_p1 = build_snapshot(
        view, bridge_mtimes, now, include_offline=True,
        resolve_manager_fn = lambda sid: (
            { "manager_persona": "Ann", "source": SOURCE_LINEAGE } if sid == "s2"
            else { "manager_persona": None, "source": "unresolved" }
        ),
    )
    snap_p1, lineage = carry_forward_lineage( snap_p1, { } )
    assert lineage == { "s2": "Ann" }
    snap_p2 = build_snapshot( view, bridge_mtimes, now, include_offline=True )   # resolver gone
    snap_p2, lineage = carry_forward_lineage( snap_p2, lineage )
    s2_p2 = { r[ "session_id" ]: r for r in snap_p2[ "sessions" ] }[ "s2" ]
    assert s2_p2[ "manager" ] == "Ann" and s2_p2[ "manager_retained" ] is True
    # a row gone from the snapshot forgets its lineage (eviction prune)
    _, pruned = carry_forward_lineage( { "sessions": [ ] }, lineage )
    assert pruned == { }

    # DM-as-liveness toggle (2026-06-17): a DM-only session (only signal is a
    # fresh SENT-DM ts — no bridge/event/commons/idle_prompt) reads LIVE when the
    # toggle is ON, and offline when OFF (the prior 4-signal verdict). dm_age_s is
    # an auditable column either way; the toggle governs only the freshest union.
    dm_view = { "dm1": { "session_id": "dm1", "persona": "Dee", "state": "working",
                         "holding_on": "none", "stuck": False,
                         "last_event_ts": None,
                         "dm_ts": now - datetime.timedelta( seconds=7 ) } }
    on_snap  = build_snapshot( dm_view, { }, now, include_offline=True, count_dm_as_liveness=True )
    on_live  = on_snap[ "sessions" ][ 0 ][ "liveness" ]
    assert on_live[ "verdict" ] == "LIVE" and on_live[ "dm_age_s" ] == 7
    assert on_live[ "freshest_age_s" ] == 7
    off_snap = build_snapshot( dm_view, { }, now, include_offline=True, count_dm_as_liveness=False )
    off_live = off_snap[ "sessions" ][ 0 ][ "liveness" ]
    # toggle OFF: dm_age_s still computed (auditable) but EXCLUDED from the union →
    # no counted signal → offline (byte-identical to the prior 4-signal verdict)
    assert off_live[ "dm_age_s" ] == 7 and off_live[ "freshest_age_s" ] is None
    assert off_live[ "verdict" ] == "offline"
    # dm_age_s is present on EVERY liveness block (auditable column)
    assert "dm_age_s" in s1[ "liveness" ]
    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"fleet_render smoke: {'PASS' if ok else 'FAIL'}" )
