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

# Gate row field set (the public interface; hold to it exactly).
GATE_FIELDS = ( "id", "question", "ask_kind", "ask_payload_ref",
                "first_asked_ts", "last_asked_ts", "reask_interval_s", "answered" )


def make_gate( gate_id, question, ask_kind, ask_payload_ref=None,
               first_asked_ts=None, last_asked_ts=None,
               reask_interval_s=DEFAULT_REASK_INTERVAL_S, answered=False ):
    """
    Build one pending-user-gate row (all 8 schema fields, fixed order).

    Requires:
        - gate_id, question, ask_kind are strings (gate_id is the stable identity)
        - ask_payload_ref is a string or None
        - first_asked_ts / last_asked_ts are ISO-8601 strings or None
        - reask_interval_s is a positive int; answered is a bool

    Ensures:
        - Returns a dict with EXACTLY GATE_FIELDS, in order
        - last_asked_ts defaults to first_asked_ts when not given (a freshly-asked
          gate has been asked once — its first ask IS its last ask)
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
    }


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
    Open gates whose re-ask cadence has elapsed — the ones to RE-FIRE this tick.

    A gate is DUE iff it is open AND ( it has never been asked (last_asked_ts
    missing/undateable ⇒ bias-to-ask) OR now − last_asked_ts ≥ reask_interval_s ).

    Requires:
        - gates is an iterable of gate-row dicts, or None
        - now_epoch is the caller's injected "now" (POSIX seconds)

    Ensures:
        - Returns the subset of open_gates(gates) that are due to re-ask now
        - Boundary: age EXACTLY == reask_interval_s is DUE (>=) — a 10-min-old
          ask is re-fired, matching "re-ask at least every 10 min"
        - A row with a non-int/bool reask_interval_s falls back to the default
          cadence (never crashes on foreign data)
        - PURE: no clock, no IO; never raises on well-formed dict input
    """
    out = [ ]
    for g in open_gates( gates ):
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

    return True


if __name__ == "__main__":   # pragma: no cover - manual smoke entrypoint
    ok = quick_smoke_test()
    print( f"heartbeat_user_gates smoke: {'PASS' if ok else 'FAIL'}" )
