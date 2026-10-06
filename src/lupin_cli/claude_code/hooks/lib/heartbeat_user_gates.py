#!/usr/bin/env python3
"""
Heartbeat Hook: pure row logic for pending user gates.

The outward twin of the receipts-of-progress design.
A pending user gate is a direct, targeted `ask_*` to Rick, a decision only he can answer, that the session fired and still awaits.
An `awaiting: user:rick` hold used to license going quiet.
But a pending ask that is not re-surfaced is the failure the never-bury-the-decision doctrine exists to kill.
So a user-gated obligation is inverted relative to a normal hold.
While open it is a standing obligation to re-fire the `ask_*` every tick (default 10 minutes) until Rick answers: owed work, not parked.

This module owns only the pure list-of-gate-rows transforms (make, open, due, upsert, mark_answered, stamp_asked, plus the relief-valve helpers).
It performs no I/O: the rows live in the session's hold artifact (the `pending_user_gates` field of heartbeat_hold).
The IO shell (stop.py or the agent's `/loop` agenda) reads them out, calls these transforms and writes them back.
Keeping the row logic pure mirrors heartbeat_work_owed and heartbeat_decision (pure core, thin shell), so it is exhaustively unit-testable.

Gate row schema (section 9.2, the public interface; `GATE_FIELDS` holds the full ordered set):
Field `id` (str): stable gate identity, matching the ask's payload.
Field `question` (str): the question text re-asked to Rick.
Field `ask_kind` (str): "ask_yes_no", "ask_multiple_choice", "converse" and so on.
Field `ask_payload_ref` (str or None): pointer to the full ask payload (options, abstract).
Field `first_asked_ts` (str): ISO-8601 time the gate was first asked.
Field `last_asked_ts` (str or None): ISO-8601 time of the most recent (re-)ask; None means never asked.
Field `reask_interval_s` (int): re-ask cadence (v1 flat 10 minutes).
Field `answered` (bool): True once Rick answers (any non-timeout result), which clears the gate.
Fields `next_chase_ts`, `reask_count` and `reask_cap`: the relief-valve fields, described at `GATE_FIELDS`.

Design: /mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/src/rnd/2026.06.22-receipts-of-progress-heartbeat-owed-calc.md section 9.
"""

from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import _iso_age_seconds


# v1 = a flat 10-min re-ask (Rick `cd610b8a`); escalation/tightening is v2.
DEFAULT_REASK_INTERVAL_S = 600

# ── Relief valve (bug 75f392c0) — the re-ask budget default ────────────────────
# N re-asks then quiet when NO chase is scheduled (fix #2). Deliberately mirrors
# heartbeat_poke_cap.DEFAULT_POKE_CAP (3): the same "small budget then stop
# nagging" shape as the per-session poke cap, applied per-gate. When a
# next_chase_ts IS scheduled the deferral window (is_chase_deferred) governs the
# quiet period instead; this count-cap is the safety net for the un-scheduled case.
DEFAULT_REASK_CAP = 3

# Gate row field set (the public interface; hold to it exactly).
# next_chase_ts / reask_count / reask_cap are the relief-valve fields (75f392c0):
#   next_chase_ts : ISO-8601 str | None — "do not re-ask before this instant"
#                   (the scheduled chase; set on the offline/timeout-default path)
#   reask_count   : int — how many times this gate has been re-asked this window
#   reask_cap     : int — the re-ask budget before going quiet (no-chase safety net)
GATE_FIELDS = ( "id", "question", "ask_kind", "ask_payload_ref",
                "first_asked_ts", "last_asked_ts", "reask_interval_s", "answered",
                "next_chase_ts", "reask_count", "reask_cap" )


def make_gate( gate_id, question, ask_kind, ask_payload_ref=None,
               first_asked_ts=None, last_asked_ts=None,
               reask_interval_s=DEFAULT_REASK_INTERVAL_S, answered=False,
               next_chase_ts=None, reask_count=0, reask_cap=DEFAULT_REASK_CAP ):
    """
    Build one pending-user-gate row holding all `GATE_FIELDS` in fixed order.

    Requires:
        - gate_id, question, ask_kind are strings (gate_id is the stable identity)
        - ask_payload_ref is a string or None
        - first_asked_ts / last_asked_ts are ISO-8601 strings or None
        - reask_interval_s is a positive int; answered is a bool
        - next_chase_ts is an ISO-8601 string or None (the scheduled-chase deferral)
        - reask_count is a non-negative int; reask_cap is a positive int

    Ensures:
        - Returns a dict with exactly `GATE_FIELDS`, in order
        - last_asked_ts defaults to first_asked_ts when not given (a freshly asked
          gate has been asked once, so its first ask is its last ask)
        - the relief-valve fields default to no-deferral and a fresh budget (next_chase_ts
          None, reask_count 0, reask_cap `DEFAULT_REASK_CAP`), so a gate built the old
          way behaves exactly as before (backward compatible)
        - Pure: no clock, no IO (the caller injects the timestamps)
    """
    if last_asked_ts is None:
        last_asked_ts = first_asked_ts
    return {
        "id"               : gate_id,
        "question"         : question,
        "ask_kind"         : ask_kind,
        "ask_payload_ref"  : ask_payload_ref,
        "first_asked_ts"   : first_asked_ts,
        "last_asked_ts"    : last_asked_ts,
        "reask_interval_s" : reask_interval_s,
        "answered"         : answered,
        "next_chase_ts"    : next_chase_ts,
        "reask_count"      : reask_count,
        "reask_cap"        : reask_cap,
    }


def _coerce_nonneg_int( value, default ):
    """
    Return value when it is a non-bool int, else default (pure; never raises).

    The bool type is an int subclass, so it is rejected: a stray True or False must never slip through as 1 or 0.
    This mirrors the reask_interval_s guard in due_gates and the poke-cap guards.
    A non-int or unparseable value gives default.
    """
    if isinstance( value, bool ) or not isinstance( value, int ):
        return default
    return value


def is_chase_deferred( gate, now_epoch ):
    """
    Return whether a gate is deferred to a future scheduled chase and not to be re-asked yet.

    A gate with a future next_chase_ts (a scheduled chase, or the user offline until then)
    must not be re-asked before that instant.
    This holds however long ago it was last asked.

    Requires:
        - gate is a gate-row dict (foreign data tolerated); now_epoch is POSIX secs

    Ensures:
        - Returns True iff next_chase_ts is a parseable ISO-8601 stamp strictly in
          the future (now_epoch < next_chase_ts)
        - Boundary: now_epoch exactly == next_chase_ts is not deferred (the chase
          has arrived, so the gate is eligible), mirroring the >= due boundary
        - absent / unparseable next_chase_ts, or a non-dict, is not deferred (no
          scheduled chase constrains it, so it falls back to cadence)
        - Pure: no clock (now injected), no IO; never raises
    """
    if not isinstance( gate, dict ):
        return False
    # age = now - next_chase_ts; negative ⇒ the chase is in the FUTURE ⇒ deferred.
    age = _iso_age_seconds( gate.get( "next_chase_ts" ), now_epoch )
    return age is not None and age < 0


def is_reask_capped( gate ):
    """
    Return whether a gate spent its re-ask budget with no chase scheduled to resume at.

    After reask_cap re-asks a gate goes quiet. When a next_chase_ts is set, the deferral window (is_chase_deferred) governs the quiet period and its expiry.
    This count cap is the safety net for a spent budget with no chase scheduled.
    The gate stays quiet and the arbiter aged backstop resurfaces it, instead of storming every turn.

    Requires:
        - gate is a gate-row dict (foreign data tolerated)

    Ensures:
        - Returns True iff reask_count >= reask_cap and next_chase_ts is absent
        - a gate with a scheduled chase (any next_chase_ts) is governed by
          is_chase_deferred, not this cap, so it returns False
        - reask_count is coerced (bad, bool or missing gives 0); reask_cap is coerced
          (bad, bool, non-positive or missing gives `DEFAULT_REASK_CAP`)
        - a non-dict gives False
        - Pure: no IO; never raises
    """
    if not isinstance( gate, dict ):
        return False
    if gate.get( "next_chase_ts" ) is not None:
        return False
    count = _coerce_nonneg_int( gate.get( "reask_count" ), 0 )
    cap   = _coerce_nonneg_int( gate.get( "reask_cap" ), DEFAULT_REASK_CAP )
    if cap <= 0:
        cap = DEFAULT_REASK_CAP
    return count >= cap


def is_user_deferred( now_epoch, user_chase_until_epoch ):
    """
    Return whether the gate's user is deferred to a future scheduled chase right now.

    "Rick is unreachable until T" is one fact about a person, not a property of each gate.
    The IO shell derives `user_chase_until_epoch` from the store (soonest future next_chase_ts among the session's blocked_by user rows); a seat can cause it via task_transition.
    While deferred, every open gate to that user inherits it, so no hold-file gate ever needs linking to a store row.

    Requires:
        - now_epoch is POSIX seconds
        - user_chase_until_epoch is a POSIX-seconds float, or None (no per-user chase)

    Ensures:
        - Returns True iff user_chase_until_epoch is not None and now_epoch is
          strictly before it (now_epoch < user_chase_until_epoch)
        - Boundary: now_epoch exactly == user_chase_until_epoch is not deferred (the
          chase has arrived, so the gate is eligible), mirroring is_chase_deferred's >= boundary
        - Read-time expiry: once now passes the chase, the shell derives no future
          chase and this returns False, so the gate re-surfaces (parked-row semantics,
          no sweeper)
        - Pure: no clock (now injected), no IO; never raises
    """
    return user_chase_until_epoch is not None and now_epoch < user_chase_until_epoch


def pokeable_gates( gates, now_epoch, user_chase_until_epoch=None ):
    """
    Return the open gates eligible to be surfaced or re-asked, after relief-valve filtering.

    An open gate is pokeable iff its user is not deferred and it is neither chase-deferred (a future next_chase_ts) nor reask-capped. Reask-capped means the re-ask budget is spent with no scheduled chase.
    The proactive-manager re-surface consults this set; due_gates filters it further by each gate's own re-ask cadence.

    Requires:
        - gates is an iterable of gate-row dicts, or None; now_epoch is POSIX secs
        - user_chase_until_epoch is a POSIX-seconds float, or None (no per-user chase)

    Ensures:
        - Returns [] when the gate's user is deferred (is_user_deferred), so the whole
          per-user set goes quiet until the chase arrives, no matter each gate's own
          fields
        - Otherwise returns the subset of open_gates(gates) that is neither
          chase-deferred nor reask-capped
        - user_chase_until_epoch defaults to None, which gives the behavior from before the
          per-user deferral existed (no per-user suppression); backward compatible
        - Input order preserved; pure; never raises on well-formed dict input
    """
    if is_user_deferred( now_epoch, user_chase_until_epoch ):
        return [ ]
    return [ g for g in open_gates( gates )
             if not is_chase_deferred( g, now_epoch ) and not is_reask_capped( g ) ]


def open_gates( gates ):
    """
    Return the not-yet-answered gate rows, the outward-twin owed set.

    Requires:
        - gates is an iterable of gate-row dicts, or None

    Ensures:
        - Returns the list of dict rows whose `answered` is falsy
        - Non-dict entries are skipped (defensive over foreign hold data)
        - Input order preserved; pure
    """
    return [ g for g in ( gates or [ ] )
             if isinstance( g, dict ) and not g.get( "answered", False ) ]


def due_gates( gates, now_epoch, user_chase_until_epoch=None ):
    """
    Return the pokeable gates to re-fire this tick, whose re-ask cadence has elapsed.

    A gate is due iff it is pokeable and either never asked (last_asked_ts missing or undateable) or now - last_asked_ts >= reask_interval_s.
    The relief-valve filter runs first, via pokeable_gates, so a deferred user, a future chase or a spent budget is not due however stale.
    That stops the every-turn re-ask storm on an offline-user gate.

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - user_chase_until_epoch is a POSIX-seconds float, or None (no per-user chase)

    Ensures:
        - Returns the subset of pokeable_gates(gates, now_epoch, user_chase_until_epoch)
          that are due to re-ask now (relief-valve-filtered, then cadence-filtered)
        - Boundary: age exactly == reask_interval_s is due (>=), so a 10-minute-old
          ask is re-fired, matching "re-ask at least every 10 min"
        - A row with a non-int/bool reask_interval_s falls back to the default
          cadence (never crashes on foreign data)
        - user_chase_until_epoch defaults to None, which gives the behavior from before the per-user deferral existed
        - Pure: no clock, no IO; never raises on well-formed dict input
    """
    out = [ ]
    for g in pokeable_gates( gates, now_epoch, user_chase_until_epoch ):
        interval = g.get( "reask_interval_s", DEFAULT_REASK_INTERVAL_S )
        if isinstance( interval, bool ) or not isinstance( interval, int ):
            interval = DEFAULT_REASK_INTERVAL_S
        age = _iso_age_seconds( g.get( "last_asked_ts" ), now_epoch )
        if age is None or age >= interval:
            out.append( g )
    return out


def aged_open_gates( gates, now_epoch, age_seconds, user_chase_until_epoch=None ):
    """
    Return the open gates whose last (re-)ask is older than a fixed `age_seconds` threshold.

    This is the arbiter's "session stopped re-asking" signal, distinct from due_gates.
    It keys on one external ceiling (for example twice the cadence), not on each gate's own reask_interval_s.
    It honors the same per-user store chase as the seat's Stop hook, which reads the same hold file, or the nag would only move.

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - age_seconds is the staleness ceiling (positive number)
        - user_chase_until_epoch is a POSIX-seconds float, or None (no per-user chase)

    Ensures:
        - Returns [] when the gate's user is deferred (is_user_deferred)
        - Otherwise returns the subset of open_gates(gates) whose last_asked_ts age
          is None (never asked or undateable counts as aged) or >= age_seconds
        - user_chase_until_epoch defaults to None, which gives the behavior from before the per-user deferral existed
        - Pure: no clock, no IO; never raises on well-formed dict input
    """
    if is_user_deferred( now_epoch, user_chase_until_epoch ):
        return [ ]
    out = [ ]
    for g in open_gates( gates ):
        age = _iso_age_seconds( g.get( "last_asked_ts" ), now_epoch )
        if age is None or age >= age_seconds:
            out.append( g )
    return out


def _blocked_by_has_user( blocked_by ):
    """
    Return whether a store row's blocked_by has any {kind: "user"} ref (pure; never raises).

    Requires:
        - blocked_by is the row's blocked_by value (any type tolerated)

    Ensures:
        - Returns True iff blocked_by is a list containing a dict whose "kind" == "user"
        - Non-list or no user ref gives False
    """
    if not isinstance( blocked_by, list ):
        return False
    return any( isinstance( ref, dict ) and ref.get( "kind" ) == "user"
                for ref in blocked_by )


def derive_user_chase_until( rows, now_epoch ):
    """
    Return the soonest future user-chase instant among a session's blocked rows, or None.

    Given the owner's blocked rows (task_store_client.query_blocked_user_rows), it takes rows blocked on a user with a future next_chase_ts.
    The earliest instant is `user_chase_until`, which is_user_deferred consumes to suppress hold-file gates until it arrives.
    The minimum is conservative: gates re-surface at the earliest chance, never later, and a passed chase contributes nothing (read-time expiry, no sweeper).

    Requires:
        - rows is an iterable of store-row dicts, or None (foreign data tolerated)
        - now_epoch is the caller's injected "now" (POSIX seconds)

    Ensures:
        - Returns the minimum future next_chase_ts (as POSIX seconds) among rows
          blocked on a user, or None when there is no such future chase
        - A row with no user block, an absent or unparseable chase, a past chase or a chase == now is
          ignored (== now has arrived, so it is not future and the gate is eligible, mirroring the boundary)
        - Pure: no clock (now injected), no IO; never raises on well-formed dict input
    """
    soonest = None
    for row in ( rows or [ ] ):
        if not isinstance( row, dict ):
            continue
        if not _blocked_by_has_user( row.get( "blocked_by" ) ):
            continue
        # age = now - next_chase_ts; age < 0 ⇒ the chase is in the FUTURE.
        age = _iso_age_seconds( row.get( "next_chase_ts" ), now_epoch )
        if age is None or age >= 0:
            continue                                  # no / unparseable / already-arrived chase
        chase_epoch = now_epoch - age                 # reconstruct the future instant (age < 0)
        if soonest is None or chase_epoch < soonest:
            soonest = chase_epoch
    return soonest


def upsert_gate( gates, gate ):
    """
    Add `gate` to the row list, replacing any existing row with the same id.

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate is a gate-row dict carrying an "id"

    Ensures:
        - Returns a new list (input not mutated) with `gate` present exactly once
        - An existing row with gate["id"] is replaced in place (order preserved);
          otherwise `gate` is appended
        - Non-dict / id-less existing rows are preserved untouched
        - Pure: builds a new list; never raises on well-formed dict input
    """
    gid = gate.get( "id" )
    out = [ ]
    replaced = False
    for g in ( gates or [ ] ):
        if isinstance( g, dict ) and g.get( "id" ) == gid:
            out.append( gate )
            replaced = True
        else:
            out.append( g )
    if not replaced:
        out.append( gate )
    return out


def mark_answered( gates, gate_id, answered=True ):
    """
    Set the `answered` flag on the row with `gate_id` (Rick answered, so the gate clears).

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate to flag
        - answered is a bool

    Ensures:
        - Returns a new list with the matching row's `answered` set; other rows
          and order are unchanged (matching row is shallow-copied, not mutated)
        - No matching id: the list is returned shape-equivalent (no-op change)
        - Pure
    """
    out = [ ]
    for g in ( gates or [ ] ):
        if isinstance( g, dict ) and g.get( "id" ) == gate_id:
            updated = dict( g )
            updated[ "answered" ] = answered
            out.append( updated )
        else:
            out.append( g )
    return out


def stamp_asked( gates, gate_id, asked_ts ):
    """
    Stamp `last_asked_ts = asked_ts` on the row with `gate_id` (the re-ask receipt).

    The IO shell or agent calls this after re-firing the gate's `ask_*`, so the debounce clock resets until the next interval.
    The agent owns this stamp; the Stop hook only names due gates in the poke (see stop.py and the doctrine step).

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate just (re-)asked
        - asked_ts is the ISO-8601 stamp of this ask

    Ensures:
        - Returns a new list with the matching row's last_asked_ts set; if its
          first_asked_ts was None it is seeded to asked_ts too (the first ask)
        - Other rows and order unchanged; matching row shallow-copied, not mutated
        - No matching id: no-op change; pure
    """
    out = [ ]
    for g in ( gates or [ ] ):
        if isinstance( g, dict ) and g.get( "id" ) == gate_id:
            updated = dict( g )
            updated[ "last_asked_ts" ] = asked_ts
            if updated.get( "first_asked_ts" ) is None:
                updated[ "first_asked_ts" ] = asked_ts
            out.append( updated )
        else:
            out.append( g )
    return out


def bump_reask_count( gates, gate_id ):
    """
    Increment `reask_count` on the row with `gate_id`.

    The IO shell or agent calls this on each re-ask, alongside stamp_asked, so the per-gate budget advances toward reask_cap.
    Once the budget is spent with no scheduled chase, is_reask_capped keeps the gate quiet (see pokeable_gates).

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate just (re-)asked

    Ensures:
        - Returns a new list with the matching row's reask_count incremented by 1
          (a missing, bad or bool count is treated as 0, so it becomes 1)
        - Other rows and order unchanged; matching row shallow-copied, not mutated
        - No matching id: no-op change; non-dict / None rows preserved; pure
    """
    out = [ ]
    for g in ( gates or [ ] ):
        if isinstance( g, dict ) and g.get( "id" ) == gate_id:
            updated = dict( g )
            updated[ "reask_count" ] = _coerce_nonneg_int( updated.get( "reask_count" ), 0 ) + 1
            out.append( updated )
        else:
            out.append( g )
    return out


def defer_to_chase( gates, gate_id, next_chase_ts ):
    """
    Defer re-asking the row with `gate_id` until `next_chase_ts`.

    This is the offline-user handler: after an unreachable-user timeout default on a targeted ask_* to Rick, the manager stamps the chase time here.
    After that, is_chase_deferred suppresses the re-ask until that instant, ending the every-turn storm.
    The fresh chase window resets reask_count to 0, so a new budget of asks begins at the chase.

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate to defer
        - next_chase_ts is the ISO-8601 scheduled-chase stamp

    Ensures:
        - Returns a new list with the matching row's next_chase_ts set and its
          reask_count reset to 0 (fresh chase window)
        - Other rows and order unchanged; matching row shallow-copied, not mutated
        - No matching id: no-op change; non-dict / None rows preserved; pure
    """
    out = [ ]
    for g in ( gates or [ ] ):
        if isinstance( g, dict ) and g.get( "id" ) == gate_id:
            updated = dict( g )
            updated[ "next_chase_ts" ] = next_chase_ts
            updated[ "reask_count" ]   = 0
            out.append( updated )
        else:
            out.append( g )
    return out


def quick_smoke_test():
    """
    Run a self-contained smoke test of the pure gate-row transforms.

    Ensures:
        - Returns True if make, open, due, upsert, mark_answered, stamp_asked and the
          relief-valve helpers behave as designed; raises AssertionError otherwise.
    """
    import datetime

    t0  = datetime.datetime( 2026, 6, 22, 12, 0, 0, tzinfo=datetime.timezone.utc )
    now = t0.timestamp()

    def ago( s ):
        return ( t0 - datetime.timedelta( seconds=s ) ).isoformat()

    # make → 8 fields, last defaults to first
    g = make_gate( "g1", "Proceed?", "ask_yes_no", first_asked_ts=ago( 0 ) )
    assert tuple( g.keys() ) == GATE_FIELDS
    assert g[ "last_asked_ts" ] == g[ "first_asked_ts" ]
    assert g[ "reask_interval_s" ] == DEFAULT_REASK_INTERVAL_S and g[ "answered" ] is False

    # open filters answered + non-dicts
    gates = [ g, make_gate( "g2", "Merge?", "ask_yes_no", first_asked_ts=ago( 0 ), answered=True ), "junk" ]
    assert [ x[ "id" ] for x in open_gates( gates ) ] == [ "g1" ]

    # due: fresh (1 min) not due; stale (11 min) due; never-asked due
    fresh = make_gate( "f", "q", "ask_yes_no", last_asked_ts=ago( 60 ) )
    stale = make_gate( "s", "q", "ask_yes_no", last_asked_ts=ago( 660 ) )
    never = make_gate( "n", "q", "ask_yes_no", last_asked_ts=None )
    due   = [ x[ "id" ] for x in due_gates( [ fresh, stale, never ], now ) ]
    assert due == [ "s", "n" ], due

    # aged_open_gates: a fixed-threshold staleness filter (arbiter resurface)
    assert [ x[ "id" ] for x in aged_open_gates( [ fresh, stale, never ], now, 600 ) ] == [ "s", "n" ]
    assert aged_open_gates( [ fresh ], now, 600 ) == [ ]   # 1-min-old ask is not aged at 10-min ceiling

    # upsert replaces by id (order preserved) + appends new
    replaced = upsert_gate( [ g ], make_gate( "g1", "Proceed v2?", "ask_yes_no" ) )
    assert len( replaced ) == 1 and replaced[ 0 ][ "question" ] == "Proceed v2?"
    appended = upsert_gate( [ g ], make_gate( "gX", "new", "converse" ) )
    assert [ x[ "id" ] for x in appended ] == [ "g1", "gX" ]

    # mark_answered clears the open set; stamp_asked resets the clock
    answered = mark_answered( [ g ], "g1" )
    assert answered[ 0 ][ "answered" ] is True and open_gates( answered ) == [ ]
    stamped = stamp_asked( [ never ], "n", ago( 0 ) )
    assert stamped[ 0 ][ "last_asked_ts" ] == ago( 0 ) and stamped[ 0 ][ "first_asked_ts" ] == ago( 0 )
    assert due_gates( stamped, now ) == [ ]   # just re-asked ⇒ no longer due

    # no-op id misses leave the list shape-equivalent
    assert mark_answered( [ g ], "nope" )[ 0 ][ "id" ] == "g1"
    assert stamp_asked( [ g ], "nope", ago( 0 ) )[ 0 ][ "id" ] == "g1"

    # relief valve (75f392c0): a future-chase gate is deferred ⇒ NOT due even stale
    def ahead( s ):
        return ( t0 + datetime.timedelta( seconds=s ) ).isoformat()
    deferred = make_gate( "d", "q", "ask_yes_no", last_asked_ts=ago( 7200 ), next_chase_ts=ahead( 3600 ) )
    assert is_chase_deferred( deferred, now ) is True
    assert due_gates( [ deferred ], now ) == [ ]
    assert pokeable_gates( [ deferred ], now ) == [ ]
    # budget spent with no chase ⇒ capped ⇒ quiet
    capped = make_gate( "c", "q", "ask_yes_no", last_asked_ts=ago( 7200 ), reask_count=3, reask_cap=3 )
    assert is_reask_capped( capped ) is True and due_gates( [ capped ], now ) == [ ]
    # bump advances the budget; defer stamps the chase + resets the budget
    assert bump_reask_count( [ make_gate( "b", "q", "ask_yes_no" ) ], "b" )[ 0 ][ "reask_count" ] == 1
    dfr = defer_to_chase( [ make_gate( "e", "q", "ask_yes_no", reask_count=2 ) ], "e", ahead( 3600 ) )
    assert dfr[ 0 ][ "next_chase_ts" ] == ahead( 3600 ) and dfr[ 0 ][ "reask_count" ] == 0

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_user_gates smoke: {'PASS' if ok else 'FAIL'}" )
