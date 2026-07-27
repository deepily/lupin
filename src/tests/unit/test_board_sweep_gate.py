"""
THE BOARD-SWEEP GATE (Rick's broadcast `40626d03`, 2026-07-25).

Rick ordered both board-holding seats to iterate EVERY owed row once — *is it done?* and
*has it been overtaken by events?* — and ordered the Stop-hook poke to hold them to it:

    "do not stop reviewing them until you have iterated your way through all of your
     22 or your 71 items, depending on who you are."

WHAT THIS FILE PROVES
  · the gate is PERSONA-scoped, so two seats sweeping simultaneously get different numbers
  · it COUNTS DOWN rather than repeating a constant
  · the denominator is FROZEN, so the gate cannot be closed by dropping rows
  · the only silent arm is "this seat is not sweeping" — every could-not-tell arm is loud
  · a non-sweeping seat's poke is BYTE-IDENTICAL to the pre-gate output

⚠️ WHAT IT DOES NOT PROVE, said here rather than discovered later:
  1. IT DOES NOT ATTEST THAT A SWEEP WAS HONEST. The ledger records what the seat SAYS it
     reviewed. Nothing cross-checks a recorded id against evidence that Rick's two
     questions were actually asked of it. This gate makes stopping-early VISIBLE; it
     cannot make lying impossible, and a green here is not a claim that it can.
  2. IT DOES NOT RUN THE HOOK. `stop.py`'s `_board_sweep_line` reads a live session bridge;
     these tests drive the pure functions and the injection seam. That the deployed hook
     actually calls it is the import-chain check, not an assertion here.
"""

import json

import pytest

from lupin_cli.claude_code.hooks.lib import board_sweep
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import (
    build_poke_reason, evaluate_work_owed, TODO_IN_PROGRESS,
)


@pytest.fixture
def sweep_dir( tmp_path, monkeypatch ):
    """Point the ledger store at a temp dir — never the operator's real ~/.claude."""
    monkeypatch.setattr( board_sweep, "SWEEP_DIR", tmp_path )
    return tmp_path


# ---------------------------------------------------------------- slug + addressing

@pytest.mark.parametrize( "persona,expected", [
    ( "mr radio",  "mr-radio" ),
    ( "Mr. Radio", "mr-radio" ),          # display form and store key must address ONE ledger
    ( "  maría  ", "maría" ),
    ( "a  b",      "a-b" ),               # collapsed, never a double hyphen
    ( None,        "" ),
    ( "",          "" ),
] )
def test_persona_slug( persona, expected ):
    assert board_sweep.persona_slug( persona ) == expected


def test_two_seats_get_two_ledgers( sweep_dir ):
    """
    THE REASON THIS IS NOT AN INI KEY. Both sweeping seats resolve to role `worker`, so a
    role-scoped goal line would say the same N to both and let one stop early.
    """
    board_sweep.record_reviewed( "mr radio", [ "a" ], total_at_start=71 )
    board_sweep.record_reviewed( "maria",    [ "x" ], total_at_start=22 )

    assert "1/71" in board_sweep.sweep_progress_line( "mr radio", live_owed=71 )
    assert "1/22" in board_sweep.sweep_progress_line( "maria", live_owed=22 )


# ---------------------------------------------------------------- the failure table

def test_no_ledger_is_the_only_silent_arm( sweep_dir ):
    assert board_sweep.sweep_progress_line( "nobody" ) == ""


def test_an_incomplete_sweep_counts_down( sweep_dir ):
    board_sweep.record_reviewed( "mr radio", [ "a", "b", "c" ], total_at_start=10 )
    line = board_sweep.sweep_progress_line( "mr radio", live_owed=10 )
    assert "3/10" in line and "7 to go" in line
    assert "BOARD SWEEP IN PROGRESS" in line

    board_sweep.record_reviewed( "mr radio", [ "d" ] )
    assert "4/10" in board_sweep.sweep_progress_line( "mr radio", live_owed=10 )   # it MOVES


def test_a_complete_sweep_is_loud_not_silent( sweep_dir ):
    """
    A finished sweep reverting to silence is indistinguishable from one that never
    started — and that difference is the entire receipt.
    """
    board_sweep.record_reviewed( "mr radio", [ "a", "b" ], total_at_start=2 )
    line = board_sweep.sweep_progress_line( "mr radio", live_owed=2 )
    assert line != "" and "owed NOW" in line and "reviewed 2" in line


@pytest.mark.parametrize( "bad_content", [
    "{ not json",
    '"a string, not an object"',
    '{"reviewed": []}',                                  # no total_at_start
    '{"total_at_start": 5}',                             # no reviewed list
    '{"total_at_start": "five", "reviewed": []}',        # wrong type
] )
def test_an_unusable_ledger_is_LOUD_never_silent( sweep_dir, bad_content ):
    """
    THE ARM THAT MATTERS MOST. A counter reporting "nothing to sweep" because it could not
    read its own state is the alarm-gated-on-the-healthy-value defect, and this gate exists
    precisely to survive a seat that would like to stop.
    """
    ( sweep_dir / "board-sweep-mr-radio.json" ).write_text( bad_content, encoding="utf-8" )
    line = board_sweep.sweep_progress_line( "mr radio", live_owed=5 )
    assert line != "", f"an unusable ledger went SILENT on: {bad_content}"
    assert "UNVERIFIED" in line and "board-sweep-mr-radio.json" in line


@pytest.mark.parametrize( "persona", [ None, "", "   " ] )
def test_an_unaddressable_seat_yields_no_ledger_and_no_line( sweep_dir, persona ):
    """
    No slug, no ledger to address. Silent rather than loud BECAUSE it means "there is no
    seat here", not "I could not read this seat's state" — the same distinction the
    unreadable arm above turns on, from the other side.
    """
    assert board_sweep.ledger_path( persona ) is None
    assert board_sweep.read_ledger( persona ) == ( None, "" )
    assert board_sweep.sweep_progress_line( persona, live_owed=5 ) == ""


def test_read_ledger_distinguishes_absent_from_unreadable( sweep_dir ):
    """`absent` and `unreadable` mean opposite things; collapsing them is the defect."""
    assert board_sweep.read_ledger( "ghost" ) == ( None, "" )

    ( sweep_dir / "board-sweep-ghost.json" ).write_text( "{ nope", encoding="utf-8" )
    ledger, error = board_sweep.read_ledger( "ghost" )
    assert ledger is None and error


# ---------------------------------------------------------------- the anti-gaming rules

def test_re_reviewing_a_row_is_not_progress( sweep_dir ):
    board_sweep.record_reviewed( "mr radio", [ "a", "a", "a" ], total_at_start=3 )
    assert "1/3" in board_sweep.sweep_progress_line( "mr radio", live_owed=3 )


def test_the_LEDGER_still_freezes_total_at_start_as_history( sweep_dir ):
    """
    `total_at_start` is still frozen ON DISK — it is the record of what the sweep began
    against, and a later record_reviewed cannot rewrite it. What changed 2026-07-27 is
    that it is no longer the DENOMINATOR anyone is shown; see the next test.
    """
    board_sweep.record_reviewed( "mr radio", [ "a" ], total_at_start=71 )
    board_sweep.record_reviewed( "mr radio", [ "b" ], total_at_start=2 )   # ignored
    assert json.loads( ( sweep_dir / "board-sweep-mr-radio.json" ).read_text() )[ "total_at_start" ] == 71


def test_the_DISPLAYED_denominator_is_the_LIVE_board_not_the_frozen_total( sweep_dir ):
    """
    🔴 RICK'S RULING, 2026-07-27, overturning my earlier design: "your argument about
    gaming the board … is specious, and irrelevant. I as a human operator will catch
    gaming of the system in a heartbeat."

    He is also right on the merits. The sweep asks "review every row you owe." If the
    board legitimately shrank, a seat that reviewed what remains IS done — and the frozen
    denominator was holding a satisfied gate open against work that no longer existed.
    The freeze defended against a dishonest seat by lying to an honest one every tick.
    """
    board_sweep.record_reviewed( "mr radio", [ "a", "b" ], total_at_start=71 )
    assert "2/12" in board_sweep.sweep_progress_line( "mr radio", live_owed=12 )
    assert "2/71" not in board_sweep.sweep_progress_line( "mr radio", live_owed=12 )


@pytest.mark.parametrize( "bad_total", [ None, 0, -1, "71", True ] )
def test_starting_a_sweep_without_a_real_denominator_is_refused( sweep_dir, bad_total ):
    """A gate that can never close is an outage; `True` is rejected because bool is an int."""
    with pytest.raises( ValueError ):
        board_sweep.record_reviewed( "mr radio", [ "a" ], total_at_start=bad_total )


def test_appending_to_an_unusable_ledger_is_refused( sweep_dir ):
    ( sweep_dir / "board-sweep-mr-radio.json" ).write_text( "{ broken", encoding="utf-8" )
    with pytest.raises( ValueError ):
        board_sweep.record_reviewed( "mr radio", [ "a" ] )


# ---------------------------------------------------------------- the injection seam

def _owed_verdict():
    return evaluate_work_owed( todo_items=[ { "status": TODO_IN_PROGRESS, "owned_by_me": True } ] )


def test_a_non_sweeping_seat_gets_a_BYTE_IDENTICAL_poke():
    """
    The regression guard. Every session in the fleet that is not sweeping must see exactly
    the reason it saw yesterday — a gate that changes everyone's poke is a fleet-wide edit
    wearing a two-seat order's clothes.
    """
    verdict = _owed_verdict()
    assert build_poke_reason( verdict, goal_line="GOAL", sweep_line="" ) == \
           build_poke_reason( verdict, goal_line="GOAL" )


def test_the_sweep_line_lands_LAST_after_the_role_goal():
    """
    Ordering is deliberate: the sweep gate names a count that must reach a number, so it
    must not read as a footnote to the general role goal above it.
    """
    reason = build_poke_reason( _owed_verdict(), goal_line="ROLE GOAL", sweep_line="SWEEP GATE" )
    assert reason.index( "ROLE GOAL" ) < reason.index( "SWEEP GATE" )
    assert reason.endswith( "SWEEP GATE" )


def test_decide_heartbeat_threads_the_sweep_line_to_the_reason():
    """The seam, end to end through the pure decision core."""
    from lupin_cli.claude_code.hooks.lib.heartbeat_decision import decide_heartbeat
    result = decide_heartbeat( None, _owed_verdict(), 0, 5, goal_line="G", sweep_line="SWEEP-MARKER" )
    # The reason rides `hook_output.reason` — the top-level Stop-hook field, NOT
    # systemMessage. Asserting on the nested path rather than a flattened one keeps this
    # test failing if the emission channel ever moves.
    assert result[ "hook_output" ][ "decision" ] == "block"
    assert "SWEEP-MARKER" in result[ "hook_output" ][ "reason" ]


# ---------------------------------------------------------------- the numerator's floor
#
# María 🌸 (fae1bbc4) broke the first version with a PLANTED-JUNK CONTROL, not by reading:
# a `deadbeef-…` id that is on nobody's board advanced her counter 5/22 -> 6/22. The
# denominator was frozen so dropping could not shrink the gate open; the numerator had the
# identical hole from the other side — it could not be shrunk, but it could be PADDED.

def test_a_junk_id_cannot_pad_the_numerator( sweep_dir ):
    """THE REGRESSION. Twenty-two arbitrary strings must not close a 22-row gate."""
    board = [ "row-1", "row-2", "row-3" ]
    board_sweep.record_reviewed( "maria", [ "row-1" ], total_at_start=3, board_ids=board )

    with pytest.raises( ValueError ) as excinfo:
        board_sweep.record_reviewed( "maria", [ "deadbeef-0000-0000-0000-000000000000" ] )
    assert "deadbeef" in str( excinfo.value )
    assert "1/3" in board_sweep.sweep_progress_line( "maria", live_owed=3 )      # unmoved


def test_a_stray_is_refused_WITHOUT_dropping_the_valid_ids_in_the_same_call( sweep_dir ):
    """
    All-or-nothing, deliberately. A partial write would leave the caller believing the
    whole batch landed — the failure is loud precisely so the batch can be re-sent clean.
    """
    board_sweep.record_reviewed( "maria", [ ], total_at_start=3, board_ids=[ "a", "b", "c" ] )
    with pytest.raises( ValueError ):
        board_sweep.record_reviewed( "maria", [ "a", "junk" ] )
    assert "0/3" in board_sweep.sweep_progress_line( "maria", live_owed=3 )


def test_membership_is_the_FROZEN_set_not_a_live_board( sweep_dir ):
    """
    María's caveat, and it is the subtle half: a row legitimately DROPPED mid-sweep leaves
    the live board. A naive live intersection would then reject the id of a row you just
    reviewed and dropped — punishing exactly the work the gate rewards. The frozen set
    still contains it, so recording it works.
    """
    board_sweep.record_reviewed( "mr radio", [ ], total_at_start=2, board_ids=[ "kept", "dropped-by-me" ] )
    board_sweep.record_reviewed( "mr radio", [ "dropped-by-me" ] )   # no longer on the live board
    assert "1/2" in board_sweep.sweep_progress_line( "mr radio", live_owed=2 )


def test_a_ledger_with_no_frozen_set_still_counts_but_says_it_is_UNVERIFIED( sweep_dir ):
    """
    The honest degrade for ledgers predating the check. Refusing to count would strand a
    live sweep; counting SILENTLY would be the false green. So it counts and confesses.
    """
    board_sweep.record_reviewed( "mr radio", [ "anything at all" ], total_at_start=2 )
    line = board_sweep.sweep_progress_line( "mr radio", live_owed=2 )
    assert "1/2" in line
    assert "NO FROZEN START-SET" in line and "UNVERIFIED" in line


def test_the_unvalidated_warning_also_rides_the_COMPLETE_line( sweep_dir ):
    """A sweep that 'completed' on unverifiable ids must not report a clean ✅."""
    board_sweep.record_reviewed( "mr radio", [ "x", "y" ], total_at_start=2 )
    line = board_sweep.sweep_progress_line( "mr radio", live_owed=2 )
    assert "owed NOW" in line and "UNVERIFIED" in line


def test_a_validated_ledger_carries_NO_warning( sweep_dir ):
    """The negative control — the warning must not fire on a correctly-armed ledger."""
    board_sweep.record_reviewed( "mr radio", [ "a" ], total_at_start=2, board_ids=[ "a", "b" ] )
    assert "UNVERIFIED" not in board_sweep.sweep_progress_line( "mr radio", live_owed=3 )


# ---------------------------------------------------------------- re-arm must not un-freeze
#
# María 🌸's third catch of the evening, and the sharpest: the first re-arm helper
# INTERSECTED prior progress with the live board. A row reviewed-and-closed is terminal and
# has left the live board, so it was discarded from `reviewed` AND the denominator
# re-derived from the same shrunken list. Re-arming un-froze the freeze. Close ten of
# seventy-one, re-arm, and the gate silently becomes 61.

def test_rearm_carries_completed_rows_INTO_the_frozen_set( sweep_dir ):
    """THE REGRESSION. A row that left the live board BY BEING REVIEWED still counts."""
    board_sweep.record_reviewed( "maria", [ "closed-by-me", "a" ],
                                 total_at_start=3, board_ids=[ "closed-by-me", "a", "b" ] )
    live = [ "a", "b" ]                                   # `closed-by-me` is now terminal

    ledger, carried, total = board_sweep.rearm( "maria", live )

    assert total   == 3, "the denominator SHRANK — re-arming un-froze the freeze"
    assert carried == 2, "completed work was discarded from the numerator"
    assert "closed-by-me" in ledger[ "board_ids" ]
    assert "2/3" in board_sweep.sweep_progress_line( "maria", live_owed=3 )


def test_rearm_admits_rows_that_are_NEW_on_the_live_board( sweep_dir ):
    """Union in both directions — a row minted mid-sweep joins the set."""
    board_sweep.record_reviewed( "maria", [ "a" ], total_at_start=2, board_ids=[ "a", "b" ] )
    _, _, total = board_sweep.rearm( "maria", [ "a", "b", "freshly-minted" ] )
    assert total == 3
    board_sweep.record_reviewed( "maria", [ "freshly-minted" ] )     # accepted, not a stray


def test_rearm_from_no_prior_ledger_is_just_a_start( sweep_dir ):
    ledger, carried, total = board_sweep.rearm( "mr radio", [ "a", "b", "c" ] )
    assert ( carried, total ) == ( 0, 3 )
    assert "0/3" in board_sweep.sweep_progress_line( "mr radio", live_owed=3 )


def test_rearm_still_enforces_membership_afterwards( sweep_dir ):
    """The re-armed ledger is a VALIDATED one — the junk floor survives a re-arm."""
    board_sweep.rearm( "mr radio", [ "a" ] )
    with pytest.raises( ValueError ):
        board_sweep.record_reviewed( "mr radio", [ "deadbeef-0000-0000-0000-000000000000" ] )
    assert "UNVERIFIED" not in board_sweep.sweep_progress_line( "mr radio", live_owed=3 )


def test_rearm_refuses_an_unreadable_prior_ledger( sweep_dir ):
    """Silently starting over would erase a seat's whole sweep and report success."""
    ( sweep_dir / "board-sweep-mr-radio.json" ).write_text( "{ broken", encoding="utf-8" )
    with pytest.raises( ValueError ):
        board_sweep.rearm( "mr radio", [ "a" ] )


# ---------------------------------------------------------------- live_owed on the COMPLETE arm
#
# Rick saw "✅ BOARD SWEEP COMPLETE: 71/71 owed rows iterated" in a live poke on 2026-07-27
# and asked whether 71 was real. It was — on 2026-07-25. The ledger has no expiry, so a
# finished sweep asserted a two-day-old fraction in the present tense forever. His fix: look
# the total up each iteration, which costs nothing because the Stop hook already fetches it.
#
# ⚠️ THE SPLIT THESE PIN. A live denominator on the IN-PROGRESS arm would re-open the hole
# the freeze exists to close (drop the unreviewed rows and the gate reads complete). So
# live_owed is consulted ONLY once the gate is already satisfied.


def _complete_ledger( persona="seat", total=71 ):
    ids = [ f"id-{i}" for i in range( total ) ]
    board_sweep.record_reviewed( persona, ids, total_at_start=total )


def test_reviewing_everything_currently_owed_satisfies_the_sweep( sweep_dir ):
    """Reviewed >= live owed ⇒ satisfied. Reviewing is still not DOING, and it says so."""
    board_sweep.record_reviewed( "seat", [ f"id-{i}" for i in range( 12 ) ], total_at_start=71 )
    line = board_sweep.sweep_progress_line( "seat", live_owed=12 )
    assert "12 owed NOW" in line and "reviewed 12" in line
    assert "reviewing is not doing" in line


def test_a_shrinking_board_closes_the_gate_and_that_is_INTENDED( sweep_dir ):
    """
    The behaviour my earlier design forbade, now pinned as correct. 60 reviewed of a board
    that has fallen to 60 = satisfied. Rick owns catching a seat that shrank it dishonestly;
    the gate's job is to be true for the honest one.
    """
    board_sweep.record_reviewed( "seat", [ f"id-{i}" for i in range( 60 ) ], total_at_start=71 )
    line = board_sweep.sweep_progress_line( "seat", live_owed=60 )
    assert "IN PROGRESS" not in line
    assert "60 owed NOW" in line


def test_zero_owed_is_the_only_CLEAR_line( sweep_dir ):
    board_sweep.record_reviewed( "seat", [ "a" ], total_at_start=71 )
    assert "COMPLETE — 0 owed now" in board_sweep.sweep_progress_line( "seat", live_owed=0 )


def test_unknown_live_count_NEVER_falls_back_to_the_frozen_total( sweep_dir ):
    """
    ⚠️ None means UNKNOWN. Falling back to `total_at_start` would restore the exact stale
    number this change removed — 71 reported against a board of 12 — and it would do so
    on precisely the ticks nobody could check it.
    """
    board_sweep.record_reviewed( "seat", [ "a" ], total_at_start=71 )
    line = board_sweep.sweep_progress_line( "seat", live_owed=None )
    assert "could not be read" in line
    assert "1/71" not in line and "CLEAR" not in line and "COMPLETE" not in line


def test_the_frozen_total_appears_only_as_dated_history( sweep_dir ):
    board_sweep.record_reviewed( "seat", [ "a" ], total_at_start=71 )
    line = board_sweep.sweep_progress_line( "seat", live_owed=12 )
    assert "sweep began 71 rows" in line
