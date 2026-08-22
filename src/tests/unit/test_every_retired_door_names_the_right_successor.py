#!/usr/bin/env python3
"""
The successor of every retired door, written down where changing it is deliberate.

THE GAP THIS CLOSES, and it was found by attack rather than by reading (Pocholo,
2026-08-21). Flip `/api/podcast-generator/submit` in RETIRED_DOORS from `/api/v2/ask` to
`/api/v2/submit` and 63 tests stay green. Every existing guard checks CONSISTENCY, not
CORRECTNESS: the count test asserts how many doors are retired, the exact-set test asserts
WHICH paths are retired, and the sentence test asserts the refusal wording matches whatever
target the table names. Flip the target and the sentence flips with it — the pair stays
internally consistent and factually wrong, which is the exact shape of defect this door
series has been killing all night.

WHY A SECOND TABLE IS NOT A DUPLICATE TABLE. The objection writes itself: this file repeats
data that already lives in `_retired_doors.py`, so a careless editor updates both and
learns nothing. That is true of the exact-set membership assertion too, and it is why that
assertion works. The value is not in the data, it is in the SECOND DELIBERATE ACT. A
successor changed by accident — a copied row, a search-and-replace, a plausible-looking
"fix" — changes one statement and goes red by name here. A successor changed on purpose
changes two, and the second one is where the person has to say what they now believe.

WHY THE ROUTE NAME CANNOT BE THE ORACLE INSTEAD, which would need no second table:
`/api/podcast-generator/submit` ends in the word `submit` and correctly retires into
`/api/v2/ask`. Its description flow held a conversation — fuzzy-match the user's documents,
ask which one they meant, ask for languages and audience, possibly answer "cancelled" —
which is what `ask` does and what `submit` refuses to do by design. Any rule derived from
the path would get that door wrong, and it is the one door most likely to be gotten wrong.

Zero external dependencies: this reads a dict.
"""

import unittest

from cosa.rest.routers._retired_doors import RETIRED_DOORS, V2_ASK, V2_SUBMIT


# The frozen expectation. One line per retired door, and the REASON its successor is what
# it is — because a reader who disagrees with a row needs to be able to refute the reason,
# not just re-read the value.
EXPECTED_SUCCESSORS = {
    # Question-shaped: a bare question, routed by the flow.
    "/api/push"                                 : V2_ASK,
    # Pulls question_text off a stored row and re-asks it — a bare question, one layer in.
    "/api/job-history/{job_id}/retry"           : V2_ASK,
    # Held a CONVERSATION: resolved a description to a document by asking, collected
    # languages and audience by asking, and could end "cancelled". That is `ask`.
    "/api/podcast-generator/submit"             : V2_ASK,

    # Everything below hands over work whose command the caller already chose.
    "/api/bug-fix-expediter/submit"             : V2_SUBMIT,
    "/api/deep-research/submit"                 : V2_SUBMIT,
    "/api/deep-research-to-podcast/submit"      : V2_SUBMIT,
    "/api/deep-research-to-presentation/submit" : V2_SUBMIT,
    "/api/presentation-generator/submit"        : V2_SUBMIT,
    "/api/swe-team/submit"                      : V2_SUBMIT,
}


class TestEveryRetiredDoorNamesTheRightSuccessor( unittest.TestCase ):

    def test_every_retired_door_has_a_frozen_expectation( self ):
        """
        A new door must be written down HERE as well as in the table. Without this, a door
        added with the wrong successor would simply not be checked — the guard would pass
        by not looking, which is the failure mode this whole file exists to prevent.
        """
        missing = sorted( set( RETIRED_DOORS ) - set( EXPECTED_SUCCESSORS ) )
        self.assertEqual( missing, [], (
            f"these retired doors have no frozen expectation: {missing}. "
            f"Add each one here with the door it retires into AND the reason, then say in "
            f"the commit message why that successor is right — do NOT derive this from "
            f"RETIRED_DOORS, which would make the guard assert that a dict equals itself."
        ) )

    def test_no_frozen_expectation_outlives_its_door( self ):
        """The other direction: a row here for a door nobody retired is a stale belief,
        and a stale belief is the thing that makes the next reader trust the wrong file."""
        extra = sorted( set( EXPECTED_SUCCESSORS ) - set( RETIRED_DOORS ) )
        self.assertEqual( extra, [], f"frozen expectations for doors that are not retired: {extra}" )

    def test_each_door_retires_into_the_door_it_is_supposed_to( self ):
        """
        RED ON REVERT, and this is the assertion the attack asked for: flip any successor in
        RETIRED_DOORS and this fails naming the path, what it now says, and what it should
        say. Everything else in the suite stays green, because everything else only ever
        checked that the table agreed with itself.
        """
        wrong = {
            path: ( RETIRED_DOORS[ path ], expected )
            for path, expected in EXPECTED_SUCCESSORS.items()
            if path in RETIRED_DOORS and RETIRED_DOORS[ path ] != expected
        }
        self.assertEqual( wrong, { }, (
            f"these doors name the wrong successor (path: table_says, should_say): {wrong}. "
            f"If the change is deliberate, change the expectation here too and say why in "
            f"the commit message."
        ) )

    def test_the_two_successors_are_the_only_ones_anybody_names( self ):
        """
        A third replacement appearing without anyone noticing would mean the fleet grew a
        front door nobody discussed. `/api/v2/resume` is live and is deliberately absent:
        resuming needs a job id, and no retired door hands one over.
        """
        self.assertEqual( set( RETIRED_DOORS.values() ), { V2_ASK, V2_SUBMIT } )

    def test_the_guard_is_not_vacuous( self ):
        """Without this, a day when both dicts empty out would pass every check above."""
        self.assertGreaterEqual( len( EXPECTED_SUCCESSORS ), 9 )
        self.assertIn( V2_ASK,    EXPECTED_SUCCESSORS.values() )
        self.assertIn( V2_SUBMIT, EXPECTED_SUCCESSORS.values() )


if __name__ == "__main__":
    unittest.main( verbosity=2 )
