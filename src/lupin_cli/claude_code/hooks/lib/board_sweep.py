"""
board_sweep.py — the Stop-hook's "you are not done sweeping yet" counter.

RICK'S ORDER, 2026-07-25 (broadcast `40626d03`): both seats holding the task board are to
iterate EVERY owed row once, asking two questions per row — *is it already done?* and *has
it been overtaken by events?* — dropping or closing what answers yes. His instruction for
this module, verbatim in effect:

    "stop poke hook says, do not stop reviewing them until you have iterated your way
     through all of your 22 or your 71 items, depending on who you are."

WHY A LEDGER AND NOT A CONFIG LINE. The obvious implementation is to edit the
`heartbeat worker goal line` INI key. It is wrong for two independent reasons, both checked
before writing this:

  1. THAT KEY IS ROLE-SCOPED, NOT PERSONA-SCOPED. Both sweeping seats resolve to `worker`,
     so ONE key cannot say "22" to María and "71" to Mr. Radio. It would say the same
     number to both, and one of them would be wrong in the direction that lets a seat stop
     early believing it had finished.
  2. A CONSTANT CANNOT COUNT DOWN. Rick asked for a poke that keeps firing "until you have
     iterated through all of them", which needs PROGRESS, not a fixed sentence. A line that
     says "sweep your 71" on tick 1 and on tick 71 alike is a reminder, not a gate.

⚠️ HOW THIS FAILS, STATED OUT LOUD, because the whole point is a gate that cannot be
   satisfied by accident:

   · NO LEDGER FILE            -> returns "". A seat not sweeping gets a byte-identical
                                  poke to yesterday's. This is the ONLY silent arm, and it
                                  is silent because "no sweep in progress" is the normal
                                  state of every session in the fleet.
   · LEDGER PRESENT, INCOMPLETE-> the DO-NOT-STOP line, carrying the live count.
   · LEDGER PRESENT, COMPLETE  -> a distinct "sweep complete" line. NOT silence. A finished
                                  sweep that reverts to saying nothing is indistinguishable
                                  from a sweep that never started, and that difference is
                                  the entire receipt.
   · LEDGER UNREADABLE/CORRUPT -> a LOUD line naming the file and the parse failure. It does
                                  NOT degrade to "". A counter that reports "nothing to
                                  sweep" because it could not read its own state is the
                                  alarm-gated-on-the-healthy-value defect, and this gate
                                  exists precisely to survive a seat that wants to stop.

   The ordering matters: only the arm meaning "this seat is not sweeping" may be quiet.
   Every arm meaning "I could not tell" is loud.

THE COUNTER COUNTS REVIEWS, NOT DROPS. A row that survives the sweep is REVIEWED — Rick's
two questions were asked and both answered no. Counting only drops would make a careful
sweep look idle and would reward dropping, which is the one outcome nobody wants from a
board-hygiene pass. For the same reason `total_at_start` is FROZEN at sweep start: if the
denominator shrank as rows were dropped, the gate could be closed by dropping instead of by
reviewing.
"""

import json
import os

from datetime import datetime, timezone
from pathlib import Path

SWEEP_DIR = Path( os.path.expanduser( "~/.claude/sessions" ) )


def persona_slug( persona ):
    """
    Filesystem-safe slug for a persona display name.

    Requires:
        - persona is a string (any case/spacing) or None

    Ensures:
        - returns lowercase with spaces/dots/underscores collapsed to single hyphens
        - returns "" for None/blank, which callers treat as "no ledger addressable"
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
        - ( None, "" )      -> no ledger file: this seat is not sweeping
        - ( dict, "" )      -> a parsed, structurally-valid ledger
        - ( None, "<why>" ) -> the file EXISTS and could not be used. Never collapsed into
          the no-file case: "absent" and "unreadable" mean opposite things to the caller,
          and only one of them is safe to be quiet about
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


def sweep_progress_line( persona ):
    """
    The sentence the Stop-hook appends to its self-poke reason.

    Requires:
        - persona is the seat's display name (str) or None

    Ensures:
        - "" ONLY when this seat has no ledger — see the module docstring's failure table
        - an incomplete sweep yields a DO-NOT-STOP line carrying reviewed/total and the
          number remaining, so the poke counts DOWN rather than repeating a constant
        - a complete sweep yields a distinct completion line (never silence)
        - an unreadable ledger yields a LOUD line naming the file and the reason
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

    if reviewed >= total:
        return ( f"✅ BOARD SWEEP COMPLETE: {reviewed}/{total} owed rows iterated. Rick's two "
                 f"questions were asked of every one. Work the survivors in priority order — "
                 f"and report the pass with its counts, not with 'the sweep is done'." )

    remaining = total - reviewed
    return ( f"⛔ BOARD SWEEP IN PROGRESS — {reviewed}/{total} rows iterated, {remaining} NOT "
             f"YET REVIEWED. Rick's standing order (2026-07-25): do NOT stop reviewing until "
             f"you have iterated your way through ALL {total} of your items. Per row ask "
             f"(1) is this ALREADY DONE — if so close it to `done` WITH a receipt, or drop it "
             f"if there is nothing to cite; (2) has it been OVERTAKEN BY EVENTS — if so drop "
             f"it with the reason. An expired chase is NEITHER: a hold Rick placed does not "
             f"lapse because our scheduler fired. Before you KEEP a row, run "
             f"`git log -S\"<the mechanism it names>\" -- <the file it names>` — a row is "
             f"often closed by a commit landed under a DIFFERENT row's id, and that is the "
             f"expensive direction: you keep a dead row and spend real attention on it." )


def record_reviewed( persona, task_ids, total_at_start=None ):
    """
    Mark one or more rows as iterated, creating the ledger on first call.

    Requires:
        - persona is the seat's display name
        - task_ids is an iterable of task-id strings (duplicates fine — de-duped on read)
        - total_at_start is the owed count at sweep start; REQUIRED on the call that
          CREATES the ledger and ignored afterwards, so the denominator cannot drift down
          as rows are dropped

    Ensures:
        - returns the written ledger dict
        - raises ValueError when creating a ledger without a positive total_at_start — a
          sweep with no denominator can never be completed, and a gate that cannot close is
          an outage
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

    seen = list( ledger[ "reviewed" ] )
    seen.extend( str( t ) for t in task_ids )
    ledger[ "reviewed" ]   = sorted( set( seen ) )
    ledger[ "updated_at" ] = datetime.now( timezone.utc ).isoformat()

    path = ledger_path( persona )
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( ledger, indent=2 ), encoding="utf-8" )
    return ledger


def quick_smoke_test():
    """Self-contained smoke test — writes only inside a temp dir."""
    import tempfile

    global SWEEP_DIR
    original = SWEEP_DIR
    try:
        with tempfile.TemporaryDirectory() as tmp:
            SWEEP_DIR = Path( tmp )

            # No ledger -> silent, and this is the ONLY silent arm.
            assert sweep_progress_line( "mr radio" ) == "", "a non-sweeping seat must be unchanged"

            # Start a sweep -> the DO-NOT-STOP line counts down.
            record_reviewed( "mr radio", [ "a", "b" ], total_at_start=5 )
            line = sweep_progress_line( "mr radio" )
            assert "2/5" in line and "3 NOT YET REVIEWED" in line, line

            # Re-reviewing a row is not progress.
            record_reviewed( "mr radio", [ "a" ] )
            assert "2/5" in sweep_progress_line( "mr radio" )

            # Completion is LOUD, not silence.
            record_reviewed( "mr radio", [ "c", "d", "e" ] )
            assert "SWEEP COMPLETE" in sweep_progress_line( "mr radio" )

            # A corrupt ledger must NOT read as "no sweep".
            ledger_path( "mr radio" ).write_text( "{ not json", encoding="utf-8" )
            corrupt = sweep_progress_line( "mr radio" )
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
