#!/usr/bin/env python3
"""
Heartbeat Hook — pending-user-gate row logic (PURE).

The outward twin of the receipts-of-progress design (6929f4ac §9). A
"pending user-gate" is a direct, targeted `ask_*` to Rick (a decision/question
only he can answer) that the session has fired and is awaiting an answer to.
Today an `awaiting: user:rick` hold is treated as a license to GO QUIET — but a
pending direct ask that isn't re-surfaced is the exact failure the
"never-bury-the-decision" doctrine exists to kill. So a user-gated obligation is
INVERTED relative to a normal hold: while it is open it is a STANDING obligation
to re-fire the `ask_*` every tick (default 10 min) until Rick answers — owed
work, not parked.

This module owns ONLY the pure list-of-gate-rows transforms (make / open / due /
upsert / mark_answered / stamp_asked). It performs NO I/O: the rows live in the
session's hold artifact (heartbeat_hold's `pending_user_gates` field), the IO
shell (stop.py / the agent's `/loop` agenda) reads them out, calls these
transforms, and writes them back. Keeping the row logic pure here mirrors the
heartbeat_work_owed / heartbeat_decision discipline (pure core, thin shell) so it
is exhaustively unit-testable.

Gate row schema (6929f4ac §9.2 — the public interface):
    id               : str   — stable gate identity (matches the ask's payload)
    question         : str   — the question text re-asked to Rick
    ask_kind         : str   — "ask_yes_no" / "ask_multiple_choice" / "converse" / …
    ask_payload_ref  : str   — pointer to the full ask payload (options/abstract) or None
    first_asked_ts   : str   — ISO-8601 when the gate was first asked
    last_asked_ts    : str   — ISO-8601 of the most-recent (re-)ask; None ⇒ never asked
    reask_interval_s : int   — re-ask cadence (v1 flat 10 min)
    answered         : bool  — True once Rick answers (any non-timeout result) ⇒ cleared

Design authority: planning-is-prompting →
    src/rnd/2026.06.22-receipts-of-progress-heartbeat-owed-calc.md §9.
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
    Build one pending-user-gate row (all GATE_FIELDS, fixed order).

    Requires:
        - gate_id, question, ask_kind are strings (gate_id is the stable identity)
        - ask_payload_ref is a string or None
        - first_asked_ts / last_asked_ts are ISO-8601 strings or None
        - reask_interval_s is a positive int; answered is a bool
        - next_chase_ts is an ISO-8601 string or None (the scheduled-chase deferral)
        - reask_count is a non-negative int; reask_cap is a positive int

    Ensures:
        - Returns a dict with EXACTLY GATE_FIELDS, in order
        - last_asked_ts defaults to first_asked_ts when not given (a freshly-asked
          gate has been asked once — its first ask IS its last ask)
        - the relief-valve fields default to no-deferral / fresh-budget (next_chase_ts
          None, reask_count 0, reask_cap DEFAULT_REASK_CAP) so a gate built the old
          way behaves EXACTLY as before (backward compatible)
        - PURE: no clock, no IO (the caller injects the timestamps)
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
    Coerce `value` to a non-bool int, else return `default` (pure; never raises).

    bool is an int subclass — rejected so a stray True/False never slips through
    as 1/0 (mirrors the reask_interval_s guard in due_gates + the poke-cap
    guards). Non-int / unparseable ⇒ default.
    """
    if isinstance( value, bool ) or not isinstance( value, int ):
        return default
    return value


def is_chase_deferred( gate, now_epoch ):
    """
    Is this gate deferred to a FUTURE scheduled chase — NOT to be re-asked yet?

    Relief valve fix #1 (bug 75f392c0): a gate carrying a next_chase_ts in the
    future (the manager scheduled the next chase / the user is offline until then)
    must NOT be re-asked before that instant, however long ago it was last asked.

    Requires:
        - gate is a gate-row dict (foreign data tolerated); now_epoch is POSIX secs

    Ensures:
        - Returns True iff next_chase_ts is a parseable ISO-8601 stamp STRICTLY in
          the future (now_epoch < next_chase_ts)
        - Boundary: now_epoch EXACTLY == next_chase_ts is NOT deferred (the chase
          has arrived ⇒ eligible), mirroring the >= due boundary
        - absent / unparseable next_chase_ts, or a non-dict ⇒ NOT deferred (no
          scheduled chase constrains it — fall back to cadence)
        - PURE: no clock (now injected), no IO; never raises
    """
    if not isinstance( gate, dict ):
        return False
    # age = now - next_chase_ts; negative ⇒ the chase is in the FUTURE ⇒ deferred.
    age = _iso_age_seconds( gate.get( "next_chase_ts" ), now_epoch )
    return age is not None and age < 0


def is_reask_capped( gate ):
    """
    Has this gate spent its re-ask budget with NO chase scheduled to resume at?

    Relief valve fix #2 (bug 75f392c0): after reask_cap re-asks a gate goes quiet.
    When a next_chase_ts IS set the deferral window (is_chase_deferred) governs the
    quiet period and its expiry; this count-cap is the SAFETY NET for the case
    where the budget is spent but NO chase was scheduled — it keeps the gate quiet
    (the arbiter aged-backstop resurfaces it) instead of storming every turn.

    Requires:
        - gate is a gate-row dict (foreign data tolerated)

    Ensures:
        - Returns True iff reask_count >= reask_cap AND next_chase_ts is absent
        - a gate WITH a scheduled chase (any next_chase_ts) is governed by
          is_chase_deferred, not this cap ⇒ returns False
        - reask_count is coerced (bad/bool/missing ⇒ 0); reask_cap is coerced
          (bad/bool/non-positive/missing ⇒ DEFAULT_REASK_CAP)
        - a non-dict ⇒ False
        - PURE: no IO; never raises
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


def pokeable_gates( gates, now_epoch ):
    """
    Open gates eligible to be surfaced/re-asked — the relief-valve-filtered set.

    An open gate is POKEABLE iff it is neither chase-deferred (a future
    next_chase_ts) nor reask-capped (budget spent with no scheduled chase). This
    is the set the proactive-manager Face-B re-surface consults; due_gates filters
    it further by each gate's own re-ask cadence.

    Requires:
        - gates is an iterable of gate-row dicts, or None; now_epoch is POSIX secs

    Ensures:
        - Returns the subset of open_gates(gates) that is neither deferred nor capped
        - Input order preserved; PURE; never raises on well-formed dict input
    """
    return [ g for g in open_gates( gates )
             if not is_chase_deferred( g, now_epoch ) and not is_reask_capped( g ) ]


def open_gates( gates ):
    """
    The not-yet-answered gate rows — the outward-twin owed set.

    Requires:
        - gates is an iterable of gate-row dicts, or None

    Ensures:
        - Returns the list of dict rows whose `answered` is falsy
        - Non-dict entries are skipped (defensive over foreign hold data)
        - Input order preserved; PURE
    """
    return [ g for g in ( gates or [ ] )
             if isinstance( g, dict ) and not g.get( "answered", False ) ]


def due_gates( gates, now_epoch ):
    """
    Gates to RE-FIRE this tick — POKEABLE gates whose re-ask cadence has elapsed.

    A gate is DUE iff it is POKEABLE (open AND neither chase-deferred nor
    reask-capped — the bug-75f392c0 relief valve) AND ( it has never been asked
    (last_asked_ts missing/undateable ⇒ bias-to-ask) OR now − last_asked_ts ≥
    reask_interval_s ).

    The relief-valve filter is applied FIRST (via pokeable_gates): a gate deferred
    to a future scheduled chase, or one that spent its re-ask budget with no chase
    scheduled, is NOT due however stale its last ask — this is what stops the
    every-turn re-ask storm on an offline-user gate.

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - now_epoch is the caller's injected "now" (POSIX seconds)

    Ensures:
        - Returns the subset of pokeable_gates(gates, now_epoch) that are due to
          re-ask now (relief-valve-filtered, then cadence-filtered)
        - Boundary: age EXACTLY == reask_interval_s is DUE (>=) — a 10-min-old
          ask is re-fired, matching "re-ask at least every 10 min"
        - A row with a non-int/bool reask_interval_s falls back to the default
          cadence (never crashes on foreign data)
        - PURE: no clock, no IO; never raises on well-formed dict input
    """
    out = [ ]
    for g in pokeable_gates( gates, now_epoch ):
        interval = g.get( "reask_interval_s", DEFAULT_REASK_INTERVAL_S )
        if isinstance( interval, bool ) or not isinstance( interval, int ):
            interval = DEFAULT_REASK_INTERVAL_S
        age = _iso_age_seconds( g.get( "last_asked_ts" ), now_epoch )
        if age is None or age >= interval:
            out.append( g )
    return out


def aged_open_gates( gates, now_epoch, age_seconds ):
    """
    Open gates whose last (re-)ask is OLDER than a FIXED `age_seconds` threshold —
    the arbiter's "this session stopped re-asking" signal (6929f4ac §9.2 backstop).

    Distinct from due_gates (which keys on each gate's OWN reask_interval_s): this
    keys on a single externally-supplied ceiling so the arbiter can resurface a
    gate only after the session has clearly failed to re-ask it for a long while
    (e.g. 2x the re-ask cadence), independent of the gate's per-row interval.

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - now_epoch is the caller's injected "now" (POSIX seconds)
        - age_seconds is the staleness ceiling (positive number)

    Ensures:
        - Returns the subset of open_gates(gates) whose last_asked_ts age is None
          (never asked / undateable ⇒ aged) OR >= age_seconds
        - PURE: no clock, no IO; never raises on well-formed dict input
    """
    out = [ ]
    for g in open_gates( gates ):
        age = _iso_age_seconds( g.get( "last_asked_ts" ), now_epoch )
        if age is None or age >= age_seconds:
            out.append( g )
    return out


def upsert_gate( gates, gate ):
    """
    Add `gate` to the row list, replacing any existing row with the same id.

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate is a gate-row dict carrying an "id"

    Ensures:
        - Returns a NEW list (input not mutated) with `gate` present exactly once
        - An existing row with gate["id"] is replaced IN PLACE (order preserved);
          otherwise `gate` is appended
        - Non-dict / id-less existing rows are preserved untouched
        - PURE: builds a new list; never raises on well-formed dict input
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
    Set the `answered` flag on the row with `gate_id` (Rick answered ⇒ cleared).

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate to flag
        - answered is a bool

    Ensures:
        - Returns a NEW list with the matching row's `answered` set; other rows
          and order are unchanged (matching row is shallow-copied, not mutated)
        - No matching id ⇒ the list is returned shape-equivalent (no-op change)
        - PURE
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
    Stamp `last_asked_ts = asked_ts` on the row with `gate_id` (re-ask receipt).

    Called by the IO shell / agent AFTER it re-fires the gate's `ask_*`, so the
    debounce clock resets and the gate isn't re-asked again until the next
    interval. (The agent owns this stamp — the Stop hook only NAMES due gates in
    the poke; see stop.py + the doctrine step.)

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate just (re-)asked
        - asked_ts is the ISO-8601 stamp of this ask

    Ensures:
        - Returns a NEW list with the matching row's last_asked_ts set; if its
          first_asked_ts was None it is seeded to asked_ts too (the first ask)
        - Other rows + order unchanged; matching row shallow-copied, not mutated
        - No matching id ⇒ no-op change; PURE
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
    Increment `reask_count` on the row with `gate_id` (relief valve fix #2).

    Called by the IO shell / agent on EACH re-ask (alongside stamp_asked), so the
    per-gate budget advances toward reask_cap. Once the budget is spent with no
    scheduled chase, is_reask_capped keeps the gate quiet (see pokeable_gates).

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate just (re-)asked

    Ensures:
        - Returns a NEW list with the matching row's reask_count incremented by 1
          (a missing / bad / bool count is treated as 0 ⇒ becomes 1)
        - Other rows + order unchanged; matching row shallow-copied, not mutated
        - No matching id ⇒ no-op change; non-dict / None rows preserved; PURE
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
    Defer re-asking the row with `gate_id` until `next_chase_ts` (fix #1 + #3).

    The offline/timeout-default handler: when a targeted ask_* to Rick returns the
    unreachable-user timeout default, the manager marks the gate deferred by
    stamping the scheduled chase time here. is_chase_deferred then suppresses the
    re-ask until that instant — killing the every-turn storm — and the fresh chase
    window resets reask_count to 0 (a new N-ask budget begins at the chase).

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - gate_id is the id of the gate to defer
        - next_chase_ts is the ISO-8601 scheduled-chase stamp

    Ensures:
        - Returns a NEW list with the matching row's next_chase_ts set AND its
          reask_count reset to 0 (fresh chase window)
        - Other rows + order unchanged; matching row shallow-copied, not mutated
        - No matching id ⇒ no-op change; non-dict / None rows preserved; PURE
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
    Self-contained smoke test of the pure gate-row transforms.

    Ensures:
        - Returns True if make / open / due / upsert / mark_answered / stamp_asked
          behave as designed; raises AssertionError otherwise.
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
