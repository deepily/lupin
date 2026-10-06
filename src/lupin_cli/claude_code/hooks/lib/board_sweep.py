"""
board_sweep.py: the Stop-hook counter that says you are not done sweeping yet.

Seats holding the task board iterate every owed row once, asking whether it is already done
and whether events have overtaken it. The hook keeps poking until every row is iterated.

Why a ledger and not the `heartbeat worker goal line` INI key:
  1. That key is role-scoped, not persona-scoped. Both sweeping seats resolve to `worker`,
     so one key shows both the same number, and a seat could stop early believing it was done.
  2. A constant cannot count down. A fixed sentence is a reminder, not a gate.

Only the arm meaning "this seat is not sweeping" may be quiet. Every arm meaning "I could
not tell" is loud:
  - No ledger file: returns "", the only silent arm, because no sweep is the fleet norm.
  - Incomplete: the do-not-stop line with the live count.
  - Complete: a distinct completion line. A finished sweep that goes quiet looks like one
    that never started.
  - Unreadable or corrupt ledger: a loud line naming the file and the parse failure, never "".
  - Older than the TTL: a loud expired line instead of any fraction.

A ledger with no expiry would report a finished sweep forever. Nothing in the hooks tree
calls `rearm()`, so `reviewed >= live_owed` stayed true. The fix is an expiry
read at display time, since wiring in `rearm()` needs live board ids the Stop hook lacks.
  - Only the arms comparing `reviewed` (which ages) with `live_owed` (fetched fresh each
    tick) become the expired line. The `live_owed is None` and `live_owed == 0` arms describe
    the live board, stay true at any age, and gain a staleness note. Alarming on "0 owed
    now" would be crying wolf.
  - Age is a distance (`abs`), not a difference: a future-stamped ledger is as untrustworthy
    as an old one. A signed comparison would read it as fresh, failing toward quiet.

The counter counts reviews, not drops, since counting drops would reward dropping. The shown
denominator is the live owed count, so a shrunken board cannot hold a satisfied gate open.
`total_at_start` stays in the ledger as history. The numerator needs a floor too.
The start-set of row ids is frozen with the count and an id outside it is refused, so
arbitrary strings cannot pad it. Membership uses that frozen set, never a live re-query,
because a row dropped mid-sweep leaves the live board.
A ledger with no frozen start-set is reported as unvalidated on every tick, since an unverifiable numerator is a false green.
"""

import json
import os

from datetime import datetime, timedelta, timezone
from pathlib import Path

from lupin_cli.claude_code.hooks.lib.sessions_dir import sessions_dir

# Row 8ccc20ab — derived from the one seam (see lib/sessions_dir.py).
SWEEP_DIR = sessions_dir()

# Bug c2d6bcfa. A seat actively sweeping rewrites `updated_at` on EVERY `record_reviewed`,
# so an in-flight sweep — however slow — stays inside this window by construction. Only a
# ledger nobody has touched for a day ages out, which is exactly the population the bug
# describes: finished-and-frozen, or abandoned.
SWEEP_LEDGER_TTL_SECONDS = 24 * 3600


def _ledger_age_seconds( ledger, now ):
    """
    How far this ledger's newest timestamp sits from `now`, in seconds.

    Requires:
        - ledger is a parsed ledger dict
        - now is a timezone-aware datetime

    Ensures:
        - prefers `updated_at`; falls back to `started_at` when it is absent or unparseable
        - returns a non-negative float, the distance and not the difference. A future-dated
          ledger (clock moved backwards) is untrustworthy in the same way an ancient one is,
          and a signed comparison would read it as freshly written
        - assumes UTC for a naive timestamp, since every stamp this module writes is UTC
        - returns None when no timestamp is parseable; the caller treats that as expired,
          matching the module rule to be loud whenever it could not tell
        - never raises
    """
    for key in ( "updated_at", "started_at" ):
        raw = ledger.get( key )
        if not raw: continue
        try:
            stamp = datetime.fromisoformat( str( raw ) )
        except ( TypeError, ValueError ):
            continue
        if stamp.tzinfo is None: stamp = stamp.replace( tzinfo=timezone.utc )
        return abs( ( now - stamp ).total_seconds() )
    return None


def _age_phrase( age ):
    """
    Render a ledger age for a human reading a poke.

    Ensures:
        - None -> names the missing timestamp rather than inventing an age. An "unknown
          age" would read as a measurement that came back vague; it is not a measurement at all
        - otherwise a coarse "N hours old" or "N days old"; the reader needs the order of
          magnitude to decide, not a precise duration
        - never raises
    """
    if age is None: return "it carries no readable timestamp"
    hours = age / 3600.0
    if hours < 48: return f"{hours:.0f} hours old"
    return f"{hours / 24.0:.0f} days old"


def persona_slug( persona ):
    """
    Filesystem-safe slug for a persona display name.

    Requires:
        - persona is a string (any case or spacing) or None

    Ensures:
        - returns lowercase with spaces, dots, underscores and slashes collapsed to single hyphens
        - returns "" for None or blank, which callers treat as no ledger addressable
        - never raises
    """
    if not persona: return ""
    slug = str( persona ).strip().lower()
    for ch in ( " ", ".", "_", "/" ):
        slug = slug.replace( ch, "-" )
    while "--" in slug: slug = slug.replace( "--", "-" )
    return slug.strip( "-" )


def ledger_path( persona ):
    """
    Ensures:
        - returns the per-persona ledger Path, or None when persona has no slug
    """
    slug = persona_slug( persona )
    return SWEEP_DIR / f"board-sweep-{slug}.json" if slug else None


def read_ledger( persona ):
    """
    Load one persona's sweep ledger.

    Ensures:
        - returns ( ledger_dict, error_string ); at most one is truthy
        - ( None, "" ) -> no ledger file: this seat is not sweeping
        - ( dict, "" ) -> a parsed, structurally valid ledger
        - ( None, "<why>" ) means the file exists and could not be used. It is never collapsed
          into the no-file case: absent and unreadable mean opposite things to the caller, and
          only one of them is safe to be quiet about
        - never raises
    """
    path = ledger_path( persona )
    if path is None:      return None, ""
    if not path.exists(): return None, ""

    try:
        data = json.loads( path.read_text( encoding="utf-8" ) )
    except ( OSError, ValueError ) as e:
        return None, f"{path} is unreadable ({type( e ).__name__}: {e})"

    if not isinstance( data, dict ):
        return None, f"{path} does not hold a JSON object"
    if not isinstance( data.get( "total_at_start" ), int ):
        return None, f"{path} has no integer 'total_at_start'"
    if not isinstance( data.get( "reviewed" ), list ):
        return None, f"{path} has no 'reviewed' list"

    return data, ""


def sweep_progress_line( persona, live_owed=None, now=None ):
    """
    The sentence the Stop-hook appends to its self-poke reason.

    The denominator is the live owed count, not the frozen `total_at_start` (kept as history).
    A frozen fraction was asserted in the present tense long after the board had shrunk.
    A frozen denominator would hold a satisfied gate open when the work is gone.

    Requires:
        - persona is the seat's display name (str) or None
        - live_owed is the seat's current owed-row count, or None when the caller could not
          resolve it (store unreachable); the caller must pass None rather than 0, since 0 is
          a real and very different answer
        - now is a timezone-aware datetime, or None to read the clock; a test seam, and the
          stop.py call site passes neither

    Ensures:
        - "" only when this seat has no ledger; see the module docstring for the state table
        - the denominator is `live_owed` on both arms; `total_at_start` is reported only as
          dated history
        - live_owed None means the count is unknown and says so; it never falls back to the
          frozen total, which is the stale number this design removes
        - an incomplete sweep yields a do-not-stop line with the number remaining
        - a complete sweep yields a distinct completion line (never silence)
        - an unreadable ledger yields a loud line naming the file and the reason
        - a ledger older than `SWEEP_LEDGER_TTL_SECONDS` (or carrying no parseable timestamp)
          yields a loud expired line instead of either arm that compares `reviewed` against
          `live_owed`, because a stale ledger satisfies that comparison forever
        - the two arms that describe the live board rather than the ledger (live_owed None,
          live_owed 0) keep their verdict and gain an appended staleness note; they are true
          at any ledger age, and alarming on them would be a false alarm
        - never raises
    """
    ledger, error = read_ledger( persona )

    if error:
        return ( f"⛔ BOARD SWEEP: your sweep ledger could not be read — {error}. "
                 f"Treat your sweep as UNVERIFIED, not finished: repair or re-create the "
                 f"ledger before you claim the pass is done." )

    if ledger is None:
        return ""

    total    = ledger[ "total_at_start" ]
    # De-duped: re-reviewing a row you already reviewed is not progress.
    reviewed = len( { str( r ) for r in ledger[ "reviewed" ] } )
    # A ledger with no frozen start-set cannot tell a reviewed row from an arbitrary
    # string. It still counts — refusing to count would strand a live sweep — but it
    # NEVER reports a bare fraction, because an unverifiable numerator rendered cleanly
    # is the false green this gate exists to prevent.
    unvalidated = ( "  ⚠️ THIS LEDGER HAS NO FROZEN START-SET, so the count above is "
                    "UNVERIFIED — any string would advance it. Re-create it with the "
                    "board_ids of your owed rows before trusting the number."
                    if ledger.get( "board_ids" ) is None else "" )

    when     = str( ledger.get( "started_at" ) or "" )[ :10 ] or "an earlier date"
    began    = f"(sweep began {total} rows, {when})"

    # Bug c2d6bcfa. `age is None` means no timestamp was parseable, which is a
    # could-not-tell and therefore loud — never quietly fresh.
    age     = _ledger_age_seconds( ledger, now or datetime.now( timezone.utc ) )
    expired = age is None or age > SWEEP_LEDGER_TTL_SECONDS
    stale   = ( f"  ⚠️ Your sweep ledger is STALE ({_age_phrase( age )}) — it describes an "
                f"older board. Re-arm it before you read any fraction from it."
                if expired else "" )

    # live_owed is UNKNOWN, not zero, and must NOT fall back to `total` — the frozen
    # number is the stale figure this whole change exists to stop showing.
    if live_owed is None:
        return ( f"⚠️ BOARD SWEEP: your CURRENT owed count could not be read this tick "
                 f"{began}, so no number here describes your board as it stands. Do NOT "
                 f"treat this as a clean board — re-check before you stop." + stale + unvalidated )

    if live_owed == 0:
        return ( f"✅ BOARD SWEEP COMPLETE — 0 owed now {began}." + stale + unvalidated )

    # Both arms below compare `reviewed` — the one input that ages — against a live count.
    # A ledger past its TTL satisfies that comparison forever, so neither arm may render.
    if expired:
        return ( f"⛔ BOARD SWEEP LEDGER EXPIRED — {_age_phrase( age )} {began}. It claims "
                 f"{reviewed} reviewed against {live_owed} owed NOW, but nothing has "
                 f"refreshed it, so that fraction describes a board you may no longer have. "
                 f"Re-arm the ledger against your current owed rows before you trust any "
                 f"number here, and do NOT read this as a satisfied sweep." + unvalidated )

    if reviewed >= live_owed:
        return ( f"⛔ {live_owed} owed NOW {began}. You have reviewed {reviewed}, so the "
                 f"sweep is satisfied — but reviewing is not doing. Work them in priority "
                 f"order and report the pass with its counts." + unvalidated )

    remaining = live_owed - reviewed
    return ( f"⛔ BOARD SWEEP IN PROGRESS — {reviewed}/{live_owed} reviewed, {remaining} to go "
             f"{began}. Per row ask (1) is this ALREADY DONE — close it to `done` WITH a "
             f"receipt, or drop it if there is nothing to cite; (2) has it been OVERTAKEN BY "
             f"EVENTS — drop it with the reason. An expired chase is NEITHER: a hold Rick "
             f"placed does not lapse because our scheduler fired. Before you KEEP a row, run "
             f"`git log -S\"<the mechanism it names>\" -- <the file it names>` — a row is often "
             f"closed by a commit landed under a DIFFERENT row's id, and keeping a dead row "
             f"is the expensive direction." + unvalidated )


def record_reviewed( persona, task_ids, total_at_start=None, board_ids=None ):
    """
    Mark rows as iterated in the seat's ledger, creating it on the first call.

    Requires:
        - persona is the seat's display name
        - task_ids is an iterable of task-id strings (duplicates fine, de-duped on read)
        - total_at_start is the owed count at sweep start; required on the call that creates
          the ledger and ignored afterwards, so the denominator cannot drift down as rows
          are dropped
        - board_ids is the seat's frozen start-set of owed row ids. Supplied on the creating
          call; ignored afterwards. When present, every recorded id must belong to it

    Ensures:
        - returns the written ledger dict
        - raises ValueError when creating a ledger without a positive total_at_start; a sweep
          with no denominator can never be completed, and a gate that cannot close is an outage
        - raises ValueError, naming the offending ids, when a recorded id is not in the frozen
          start-set; the numerator cannot be padded past the board
        - a ledger with no frozen start-set accepts anything, and `sweep_progress_line` then
          reports itself unvalidated on every tick. Accepting silently and reporting cleanly
          would be a false green; accepting loudly is the honest degrade for the ledgers that
          predate this check
        - membership is checked against the frozen set, never a live re-query: a row
          legitimately dropped mid-sweep leaves the live board, and rejecting it would
          punish the work the gate rewards
        - raises ValueError rather than appending to an unreadable ledger
    """
    ledger, error = read_ledger( persona )
    if error: raise ValueError( f"refusing to append to an unusable ledger: {error}" )

    if ledger is None:
        if not isinstance( total_at_start, int ) or isinstance( total_at_start, bool ) or total_at_start < 1:
            raise ValueError( "total_at_start (a positive int) is required to START a sweep ledger" )
        ledger = {
            "persona"        : persona,
            "started_at"     : datetime.now( timezone.utc ).isoformat(),
            "total_at_start" : total_at_start,
            "reviewed"       : [ ],
        }
        if board_ids is not None:
            ledger[ "board_ids" ] = sorted( { str( b ) for b in board_ids } )

    frozen  = ledger.get( "board_ids" )
    recorded = [ str( t ) for t in task_ids ]
    if frozen is not None:
        strays = sorted( { t for t in recorded if t not in set( frozen ) } )
        if strays:
            raise ValueError(
                f"refusing to record {len( strays )} id(s) that are not on this seat's frozen "
                f"start-set: {strays}. The numerator must count YOUR rows, not arbitrary "
                f"strings — otherwise {ledger[ 'total_at_start' ]} junk ids close the gate."
            )

    seen = list( ledger[ "reviewed" ] )
    seen.extend( recorded )
    ledger[ "reviewed" ]   = sorted( set( seen ) )
    ledger[ "updated_at" ] = datetime.now( timezone.utc ).isoformat()

    path = ledger_path( persona )
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( ledger, indent=2 ), encoding="utf-8" )
    return ledger


def rearm( persona, live_board_ids ):
    """
    Re-create a seat's ledger on a fresh board, keeping progress and the start-set.

    Nothing calls this, and wiring it into the Stop hook is not wanted.
    The hook lacks the owed row ids and would need a per-tick store round-trip. The expiry covers stale ledgers.
    This stays as the operator's manual re-arm.

    Requires:
        - persona is the seat's display name
        - live_board_ids is the current owed-row id set for that seat

    Ensures:
        - the frozen start-set is union( live_board_ids, prior reviewed ), never an
          intersection, so completed
          work can neither shrink the denominator nor be discarded from the numerator. A row
          reviewed and closed has left the live board, and an intersection would drop it from
          `reviewed`, punishing progress. Absent from the live board means both "I closed it" and "it was never mine"
        - prior `reviewed` entries are carried forward in full
        - returns ( ledger, carried_forward_count, frozen_total )
        - raises ValueError on an unreadable prior ledger rather than silently starting over
    """
    prior, error = read_ledger( persona )
    if error: raise ValueError( f"refusing to re-arm over an unusable ledger: {error}" )

    reviewed = [ str( r ) for r in ( prior or { } ).get( "reviewed", [ ] ) ]
    frozen   = sorted( { str( b ) for b in live_board_ids } | set( reviewed ) )

    path = ledger_path( persona )
    if path is not None and path.exists(): path.unlink()

    ledger = record_reviewed( persona, reviewed, total_at_start=len( frozen ), board_ids=frozen )
    return ledger, len( reviewed ), len( frozen )


def quick_smoke_test():
    """
    Self-contained smoke test of the sweep ledger; writes only inside a temp dir.

    It asserts the current API: the unknown-owed arm, the live-count arms, expiry, a corrupt
    ledger and a refused start. Nothing runs it automatically, so an assertion here can decay.
    The real gate is `src/tests/unit/test_board_sweep_gate.py`.
    """
    import tempfile

    global SWEEP_DIR
    original = SWEEP_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            SWEEP_DIR = Path( tmp )

            # No ledger -> silent, and this is the ONLY silent arm.
            assert sweep_progress_line( "mr radio" ) == "", "a non-sweeping seat must be unchanged"

            # Start a sweep -> the DO-NOT-STOP line counts down against the LIVE board.
            record_reviewed( "mr radio", [ "a", "b" ], total_at_start=5 )
            line = sweep_progress_line( "mr radio", live_owed=5 )
            assert "2/5" in line and "3 to go" in line, line

            # Re-reviewing a row is not progress.
            record_reviewed( "mr radio", [ "a" ] )
            assert "2/5" in sweep_progress_line( "mr radio", live_owed=5 )

            # Completion is LOUD, not silence.
            record_reviewed( "mr radio", [ "c", "d", "e" ] )
            assert "owed NOW" in sweep_progress_line( "mr radio", live_owed=5 )

            # Bug c2d6bcfa — the SAME satisfied ledger, read a week later, must NOT
            # still read as satisfied. Both arms, because only the pair is evidence.
            later = datetime.now( timezone.utc ) + timedelta( days=7 )
            assert "EXPIRED" in sweep_progress_line( "mr radio", live_owed=5, now=later )
            assert "EXPIRED" not in sweep_progress_line( "mr radio", live_owed=5 )

            # A corrupt ledger must NOT read as "no sweep".
            ledger_path( "mr radio" ).write_text( "{ not json", encoding="utf-8" )
            corrupt = sweep_progress_line( "mr radio", live_owed=5 )
            assert corrupt != "" and "unreadable" in corrupt, corrupt

            # Starting without a denominator is refused.
            try:
                record_reviewed( "maria", [ "x" ] )
                raise AssertionError( "a ledger with no total_at_start must be refused" )
            except ValueError:
                pass

        print( "✓ board_sweep smoke test passed" )
        return True
    finally:
        SWEEP_DIR = original


if __name__ == "__main__":
    quick_smoke_test()
