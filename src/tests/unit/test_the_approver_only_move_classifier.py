"""
WHICH APPROVER-ONLY MOVE IS THIS — `requested_move` and `move_for_ticket`, row c9fafb9d.

These two were hoisted out of `refusal_for_admission`'s four-branch ladder so the future
request door can ask the gate which move it is looking at instead of restating the rule.
The refusal's own wording is unchanged and is covered where it always was; what is new,
and what this file guards, is that the classification is now a value other code can read.

🔴 THE ORDER OF THE TESTS IS THE ORDER OF THE LADDER, AND THAT IS NOT COSMETIC. A
`not_approved -> wont_fix` is a WON'T-FIX, not an admission, because the won't-fix clause
is tested first. Reorder the function and that edge silently changes hands — from a move
nobody may request to one a manager may. The arm below pins it.

⚠️ WHY A DIRECT UNIT FILE RATHER THAN MORE DOOR ARMS. `move_for_ticket` has a branch the
HTTP door cannot reach today: it classifies a DEMOTE ticket, and no caller mints one
until the request door lands. Covering it through the door would mean waiting for a
feature; covering it here measures the function that already exists. Every OTHER claim in
this row is proven at the door, in `test_rick_alone_promotes_and_demotes.py`.
"""

import pytest

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_store_rules       as rules


HOLDING  = approval.NOT_APPROVED_STATUS
WONT_FIX = approval.WONT_FIX_STATUS
PARKED   = rules.PARK_STATUS


# ---------------------------------------------------------------------------
# `requested_move` — all four moves, and the ways to be none of them
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "frm,to,expected", [
    # WON'T-FIX IS TESTED FIRST IN THE LADDER, so it wins even from the holding area.
    ( HOLDING,       WONT_FIX,  approval.MOVE_WONT_FIX ),
    ( "queued",      WONT_FIX,  approval.MOVE_WONT_FIX ),
    ( "in_progress", WONT_FIX,  approval.MOVE_WONT_FIX ),

    # ADMIT — out of the holding area, onto any board state.
    ( HOLDING,       "queued",      approval.MOVE_ADMIT ),
    ( HOLDING,       "in_progress", approval.MOVE_ADMIT ),
    ( HOLDING,       "blocked",     approval.MOVE_ADMIT ),

    # DEMOTE — back INTO the holding area, from anywhere else.
    ( "queued",      HOLDING, approval.MOVE_DEMOTE ),
    ( "in_progress", HOLDING, approval.MOVE_DEMOTE ),
    ( "blocked",     HOLDING, approval.MOVE_DEMOTE ),

    # UN-PARK — out of `parked` (Rick's P0, row 03d3bf78).
    ( PARKED, "queued",      approval.MOVE_UN_PARK ),
    ( PARKED, "in_progress", approval.MOVE_UN_PARK ),

    # NONE OF THEM. The two no-ops are illegal edges in the transition graph already;
    # answering them with a permission verdict would name the wrong defect.
    ( HOLDING,       HOLDING,       None ),
    ( PARKED,        PARKED,        None ),
    ( "queued",      "in_progress", None ),
    ( "in_progress", "done",        None ),
] )
def test_every_move_and_every_non_move( frm, to, expected ):
    assert approval.requested_move( frm, to ) == expected


def test_a_wont_fix_out_of_the_holding_area_is_a_wont_fix_and_not_an_admission():
    """
    🔴 THE ORDERING ARM, SEPARATE BECAUSE IT IS THE ONE THAT WOULD SURVIVE A REORDER
    UNNOTICED. `not_approved -> wont_fix` satisfies BOTH the won't-fix clause and the
    admit clause, so which one it gets is decided purely by which is tested first.

    ⚠️ AND IT MATTERS BEYOND TIDINESS. `REQUESTABLE_MOVES` is {admit, demote} — so if
    this edge classified as an admission, a manager could REQUEST a won't-fix close.
    That is the move `refusal_for_admission`'s own note calls load-bearing, because a
    seat that can close rows this way holds both halves of a mint-by-deletion loop
    against the create/close ratio gate.
    """
    assert approval.requested_move( HOLDING, WONT_FIX ) == approval.MOVE_WONT_FIX
    assert approval.MOVE_WONT_FIX not in approval.REQUESTABLE_MOVES


def test_every_move_has_a_sentence_and_every_sentence_a_move():
    """
    The refusal indexes `MOVE_SENTENCES` with whatever `requested_move` returns, so a
    move added to one and not the other is a KeyError inside a 403 — an authorization
    refusal turning into a 500, which reads to the caller as a server fault rather than
    a permission one.

    ⚠️ IT ASSERTS THE SETS ARE EQUAL RATHER THAN LISTING TODAY'S FOUR. A test naming the
    four would need editing whenever a fifth is ruled, and that edit is exactly the step
    somebody skips.
    """
    moves = { approval.MOVE_ADMIT, approval.MOVE_WONT_FIX,
              approval.MOVE_DEMOTE, approval.MOVE_UN_PARK }
    assert set( approval.MOVE_SENTENCES ) == moves
    assert approval.REQUESTABLE_MOVES <= moves
    for move, sentence in approval.MOVE_SENTENCES.items():
        assert sentence.strip(), f"{move} has a blank sentence"


# ---------------------------------------------------------------------------
# `move_for_ticket` — the shorter rule, and the population it is sound over
# ---------------------------------------------------------------------------

def test_a_ticket_into_the_holding_area_is_a_demote():
    assert approval.move_for_ticket( HOLDING ) == approval.MOVE_DEMOTE


@pytest.mark.parametrize( "to", [ "queued", "in_progress", "blocked" ] )
def test_a_ticket_out_of_the_holding_area_is_an_admission( to ):
    assert approval.move_for_ticket( to ) == approval.MOVE_ADMIT


def test_the_two_classifiers_agree_on_every_move_a_ticket_can_carry():
    """
    🔴 THE ARM THAT MAKES THE SHORTER RULE SAFE. `move_for_ticket` reads ONE field where
    `requested_move` reads two, and that is sound only over the population a ticket can
    actually carry — `REQUESTABLE_MOVES`, which is {admit, demote}. This walks that
    population and checks the two agree.

    ⚠️ IT DELIBERATELY DOES NOT WALK THE WHOLE STATUS SPACE. Fed `queued -> wont_fix`
    the short rule answers MOVE_ADMIT, confidently and wrongly — that is documented at
    the function and is not a defect, because no ticket is ever minted for a won't-fix.
    A test asserting agreement everywhere would be asserting something false.
    """
    cases = [ ( HOLDING, "queued" ), ( HOLDING, "in_progress" ), ( HOLDING, "blocked" ),
              ( "queued", HOLDING ), ( "in_progress", HOLDING ), ( "blocked", HOLDING ) ]

    assert cases, "the loop found nothing to compare — every assertion below is vacuous"
    for frm, to in cases:
        full = approval.requested_move( frm, to )
        assert full in approval.REQUESTABLE_MOVES, (
            f"{frm}->{to} is not a move a ticket can carry, so it does not belong in "
            f"this population"
        )
        assert approval.move_for_ticket( to ) == full, (
            f"the two classifiers disagree about {frm}->{to}: requested_move says "
            f"{full}, move_for_ticket says {approval.move_for_ticket( to )}"
        )
