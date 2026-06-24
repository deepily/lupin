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
                      stale_seconds = DEFAULT_STALE_SECONDS,
                      count_dm      = True,
                      hold_mtime    = None ):
    """
    Build the per-session LIVENESS block — SIX distinct ages + verdict.

    The verdict rides the FRESHEST of up-to-SIX direct-signal ages (arbiter
    liveness fix, Part 7 / Step 1.5 + DM-as-liveness toggle, 2026-06-17 +
    hold-mtime, task 70be69f2) — the OLD code saw only {bridge, event}, so a
    worker live-by-commons or live-by-idle_prompt (but with a stale stop-event)
    read `offline`: the false WHOLE-FLEET-STALL bug. The ages stay DISTINCT
    columns (never collapsed):
        - bridge_age_s      — bridge-file mtime (wedge-resilient PRIMARY, §10.1)
        - event_age_s       — last STOP/non-idle_prompt event ts (stop-event age)
        - commons_age_s     — last commons_who activity ts
        - idle_prompt_age_s — last kind=idle_prompt recency beacon ts (Step 1.3)
        - dm_age_s          — last SENT ai_to_ai DM ts (DM-as-liveness toggle):
          an EXPLICIT, store-sourced, hook-independent sign of LIFE that closes
          the coordination-only / MCP-tool coverage hole — a manager whose only
          activity is dm_send (no Read/Edit/Bash, so its bridge-mtime may never
          bump) is genuinely alive but today ages into STALE. dm_age_s is ALWAYS
          computed (an auditable column — "LIVE by DM @HH:MM"), but enters the
          freshest-of union ONLY when `count_dm` is True (the runtime toggle
          `arbiter count dm as liveness`, default TRUE). count_dm=False
          reproduces the prior 4-signal verdict BYTE-IDENTICALLY (the
          reversibility guarantee). DM is a LIFE signal, never a PROGRESS or
          STATE signal (C4): dm_ts feeds liveness ONLY, never the progress
          signature.
        - hold_age_s        — `.heartbeat-hold-<sid>.json` file mtime (task
          70be69f2): an interactive, no-`/loop` MANAGER that refreshes its hold
          every Stop (held_at re-stamped → file mtime bumps) is provably ALIVE
          even when it never posts to commons / bumps the bridge — the canonical
          MANAGER-STALE false-positive (Tiberius's sess 6ec69a8c: hold rewritten
          every turn yet reported "silent 75m+" because the detector read only
          commons last_post_ts). hold_age is UNCONDITIONAL (no toggle): a fresh
          hold mtime is the Stop hook having run = the process is alive, an
          unambiguous fail-safe sign of LIFE. ADDITIVE — it can only make a
          session read MORE alive, NEVER suppress a genuinely-dark one (a dark
          session's hold mtime ages out with everything else). LIFE signal only,
          never STATE / the progress signature (C4). hold_mtime=None ⇒ hold_age_s
          is None and the verdict is byte-identical to the prior 5-signal block.
    A session is LIVE if ANY counted signal is fresh (bias-to-alive); offline
    only when NONE is recent.

    Requires:
        - view is a per-session fleet-view dict (build_fleet_view output) — it
          carries last_event_ts / commons_ts / idle_prompt_ts / dm_ts as
          DISTINCT fields
        - bridge_mtime is an epoch-seconds float or None (get_bridge_mtime)
        - now is an aware datetime; thresholds are positive seconds
        - count_dm is a bool — whether dm_age joins the freshest-of union
        - hold_mtime is an epoch-seconds float or None (the hold-file mtime;
          the arbiter reads it out-of-band per session, mirroring bridge_mtime)

    Ensures:
        - returns { bridge_age_s, event_age_s, commons_age_s, idle_prompt_age_s,
          dm_age_s, hold_age_s, freshest_age_s, verdict } — ages are int seconds
          (or None), verdict is the §10.2 label off `freshest_age_s = min(present
          counted ages)`
        - dm_age_s is ALWAYS present (auditable) regardless of count_dm; it joins
          the freshest-of union ONLY when count_dm is True. count_dm=False ⇒ the
          freshest_age_s + verdict are byte-identical to the prior 4-signal block
        - hold_age_s is present iff hold_mtime is not None; when present it ALWAYS
          joins the freshest-of union (unconditional fail-safe LIFE signal).
          hold_mtime=None ⇒ hold_age_s is None and the verdict matches the prior
          5-signal block (additive, reversible)
        - state is NOT consulted here (orthogonal columns, C4)
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

    candidates = [ a for a in ( bridge_age, event_age, commons_age, idle_prompt_age ) if a is not None ]
    if count_dm and dm_age is not None:
        candidates.append( dm_age )
    if hold_age is not None:
        candidates.append( hold_age )
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


def _lookup_dead( process_dead, sid ):
    """
    Prefix-tolerant membership test for the confirmed-dead session set.

    Mirrors _sid_matches' short-id/full-uuid tolerance so a `fleet_view` key
    (often an 8-char id) matches a dead-set entry carrying the full uuid, and
    vice-versa. A falsy / empty `process_dead` is never a match.

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
                    alive_threshold_seconds = None ):
    """
    Build the JSON-able full-fleet snapshot for the GET endpoint (§10.4), enriched
    with per-session hierarchy (Fleet-Status P1, design §4) and live-only-by-default
    (Fleet-Status D6 / §5.2).

    Requires:
        - fleet_view is { session_id: VIEW } (build_fleet_view output)
        - bridge_mtimes is { session_id: epoch-float|None }
        - now is an aware datetime

    Ensures:
        - returns { generated_at(iso), session_count, sessions: [row, ...] }
          sorted by session_id for stable rendering/diffing
        - PUBLISHED-VIEW PRUNE (D6 / §5.2): by default (include_offline=False) a
          session whose computed liveness verdict is "offline" is OMITTED — the
          published snapshot carries only the live fleet (LIVE/quiet/stale), so the
          multi-day dead-session graveyard never reaches consumers. Pass
          include_offline=True to retain offline rows (audit/back-compat). This
          prunes the PUBLISHED snapshot ONLY — the arbiter's decision logic reads
          `fleet_view`, not this snapshot, so routing/stall-detection are untouched.
        - PID FAST-DEATH OVERRIDE (kill-0): `process_dead` is an optional iterable
          of CONFIRMED-dead session-ids (default None). A row whose sid prefix-
          matches one is forced verdict="offline" + liveness.process_dead=True,
          regardless of its signal ages — so a /exit'd session drops in ~1 poll
          instead of aging out over ~1h. Bias-to-alive: only a positive dead
          reading overrides; an absent sid keeps its age verdict. The verdict
          STRING set is unchanged (the frontend offline-split is untouched);
          `process_dead` is an additive transparency flag on the liveness block.
        - count_dm_as_liveness (default True, the `arbiter count dm as liveness`
          toggle) is threaded verbatim to compute_liveness(count_dm=...): True ⇒
          a session's SENT-DM age joins the freshest-of liveness union (a
          coordination-only manager reads LIVE); False ⇒ each row's liveness
          block is byte-identical to the prior 4-signal verdict (dm_age_s still
          present for audit, just excluded from the union). DM feeds LIVENESS
          only, never STATE / the progress signature (C4)
        - hold_mtimes (default None, the task-70be69f2 hold-file-mtime liveness
          source) is { session_id: epoch-float|None }; each row's hold mtime is
          threaded to compute_liveness(hold_mtime=...) → its hold_age_s joins the
          freshest-of union UNCONDITIONALLY (an interactive manager that only
          Stop-refreshes its hold reads LIVE, not MANAGER-STALE). None / a missing
          sid ⇒ hold_age_s None for that row, byte-identical to the prior block.
          Hold-mtime feeds LIVENESS only, never STATE / the progress signature (C4)
        - alive_threshold_seconds (default None) gates the bug-65d1247f DISPLAY
          sanitization: a row whose HOLDER SESSION is beyond the alive threshold
          (dependency_graph.session_is_stale — the SAME predicate the peer-EDGE gate
          uses, threaded from the arbiter's self.alive_threshold_seconds) renders its
          `peer:X` holding_on as the neutral "none", so the displayed hold AGREES with
          edge inference (37511bfb). None (the default) ⇒ NO gate, byte-identical to
          the prior render; peer-prefix-gated (user:/commons: holds untouched);
          fail-SAFE (missing/unparseable last_activity_ts ⇒ NOT stale ⇒ raw value
          kept — never hide a LIVE hold). DISPLAY ONLY — edge inference + the :1070
          deadlock escalation are untouched
        - each row keeps STATE and LIVENESS as separate keys (C4) PLUS the two
          hierarchy keys (role, manager):
          { session_id, persona, state, holding_on, stuck, liveness{...},
            role, manager }
        - role = "manager" if the session-id (prefix-tolerantly) belongs to the
          injected manager set (list_managers_fn) OR its persona is in the
          DECLARED roster (`declared_managers`, case-insensitive — from
          COSA_VOICE_MANAGERS__<PROJECT>; a declared manager badges as manager
          even before its first spawn, Rick 2026-06-11), else "worker"
        - manager = resolve_manager_fn(sid).manager_persona ONLY when its source
          is "lineage"; for declared/unresolved/error → None (degrade-safe: we
          NEVER show a guessed manager — None lands the row in the "Unmanaged"
          group rather than mis-parenting a worker)
        - INJECTED seams (both default None) keep this function pure + 100%-
          testable with fakes, mirroring arbiter_job's resolve_active_managers_fn
          injection. With neither injected → role="worker", manager=None for every
          row (back-compatible flat snapshot)
        - session_count reflects the EMITTED rows (post-prune), not the input size
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
    Retain last-known manager lineage across polls — the "Unmanaged" offline-row fix
    (Fleet-Status, 2026-06-10).

    A reaped worker loses BOTH lineage sources in the SAME instant
    (`session_spawner.dismiss_sessions`): its bridge file is unlinked (kills the
    PRIMARY `spawned_by` path) AND its spawn-manifest entry is dropped (kills the
    FALLBACK manifest-name scan). So the very next poll's resolve_manager misses on
    both paths → SOURCE_UNRESOLVED → build_snapshot sets manager=None → the row drops
    to the "Unmanaged" group, even though it lingers in its ~1h "stale Nm" decay
    window (published, not yet offline-pruned). The focus-bar badge — event-sourced
    at spawn, client-cached — still shows the manager, so the table contradicting it
    reads as a bug.

    This replays the manager from the most recent poll that DID resolve it, until the
    row evicts from the published snapshot.

    Requires:
        - snapshot is a build_snapshot() result (or falsy / non-dict → returned as-is
          with an empty next-lineage)
        - prior_lineage is { session_id: manager_persona } carried from the prior poll
          (caller-owned, threaded across polls); None / non-dict → treated as {}

    Ensures:
        - returns ( snapshot, next_lineage ):
            * a row with a non-None manager REFRESHES next_lineage[sid]; row untouched
              (fresh lineage always wins over a carried value)
            * a row with manager None whose sid is in prior_lineage is FILLED —
              row["manager"] = prior_lineage[sid], row["manager_retained"] = True
              (honest transparency flag) — and keeps carrying in next_lineage
            * a row with manager None and no prior entry stays genuinely Unmanaged
            * next_lineage is PRUNED to the snapshot's CURRENT sids — a row gone from
              the published snapshot (evicted: offline-pruned, or left the fleet)
              FORGETS its lineage. Bounded; matches "until row eviction".
        - NEVER invents lineage — only ever replays a persona THIS fleet resolved
          before — and NEVER raises (a malformed snapshot/row degrades to a skipped
          row / an empty carry); the manager field stays orthogonal to the semantic
          frame_signature, so the carry causes NO spurious table re-render
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
    The D6/§5.2 offline-prune as a standalone PURE helper (post-game 2026-06-11).

    The arbiter now builds ONE full snapshot (include_offline=True) so its
    post-game detectors (manager-staleness F2, fleet-dark F3) can see offline
    rows, then derives the PUBLISHED live-only view through this helper — the
    published contract (live rows only, recounted) is unchanged from the old
    in-build prune. Design: src/rnd/v0.1.8/
    2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md §3.2.

    Requires:
        - snapshot is a build_snapshot() result (or any malformed value)

    Ensures:
        - returns a NEW top-level dict: same generated_at, `sessions` filtered to
          rows whose liveness verdict != "offline" (non-dict rows dropped), and
          `session_count` recounted to the EMITTED rows
        - row dicts are SHARED with the input (not copied) — callers must not
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
