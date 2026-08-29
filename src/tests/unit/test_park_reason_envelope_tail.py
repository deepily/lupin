"""
park_reason must refuse its own tool-call envelope tail — row 91ccbc26.

THE DEFECT. Two authors, two rows, two different fragment sizes of the writer's
OWN tool-call markup captured into park_reason. sam's row 9baba1f7 said so in its
own field: "Third park attempt — the two before it captured a stray close-tag
from my own tool call into this field." Rio's row 2ebe4ccb ended with a closing
park_reason tag, a newline, a closing invoke tag, a newline — two tags past the
end of the author's sentence. Both writes landed SILENTLY.

BOTH SPECIMENS ARE GONE: leaving `parked` clears park_reason by design, so the
evidence evaporated when those rows moved. The fixtures below are manufactured,
and the shapes are taken verbatim from the quotations the row preserved in prose.

WHERE IT ENTERS — MEASURED 2026-08-29, and it decides the remedy. A park_reason
carrying the corruption shape PLUS deliberate legitimate angle brackets went
through the live MCP verb and came back out of postgres byte-identical: 188
bytes, md5 91216ff1f24c05189d8e05c1fe761985. The transport and the store's write
path are innocent; the caller composes it. So the store REJECTS rather than
strips — stripping would paper over a caller-side defect, and every stripping
rule is one bad guess away from eating content an author meant.

⚠️ WHY THE TAGS IN THIS FILE ARE BUILT FROM PIECES. Writing one literally
truncates the tool call that authors the file — I hit exactly that while writing
this suite, which is the mechanism reproducing itself one layer up.
"""
import pytest

from cosa.rest.task_store_rules import envelope_tail_tag, validate_park

C = "<" + "/"
G = ">"

def tag( name ):
    return C + name + G

CHASE = "2026-09-05T09:00:00-04:00"

# Rio's specimen, from row 91ccbc26's 2026-08-28 15:47 amendment, which quoted
# the field's last 60 bytes before the field itself was destroyed.
RIO_TAIL = ( "thing to run the checklist against." + tag( "park_reason" )
             + "\n" + tag( "invoke" ) + "\n" )

# sam's, from row 9baba1f7's own park_reason: "a stray close-tag".
SAM_TAIL = "Third park attempt — held behind the branch cut." + tag( "parameter" )


# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------
@pytest.mark.parametrize( "name", [ "park_reason", "invoke", "parameter",
                                    "function_calls", "antml:invoke", "antml:parameter" ] )
def test_every_envelope_tag_is_caught_at_the_tail( name ):
    """One case per barred tag — a list nobody exercises is a list that rots."""
    assert envelope_tail_tag( "a real reason." + tag( name ) ) == tag( name )


def test_rios_specimen_is_refused():
    """The exact shape row 91ccbc26 preserved in prose after the field was cleared."""
    assert envelope_tail_tag( RIO_TAIL ) == tag( "invoke" )


def test_sams_specimen_is_refused():
    """
    A SINGLE stray close-tag — the smaller of the two fragment sizes. sam's exact
    bytes are gone; the row records only "a stray close-tag from my own tool
    call", so this fixture is that description, not a transcript.
    """
    assert envelope_tail_tag( SAM_TAIL ) == tag( "parameter" )


def test_trailing_whitespace_does_not_hide_the_tail():
    """The observed specimen ended with a newline; a trailing-newline blind spot
    would miss the only shape actually on record."""
    assert envelope_tail_tag( "reason." + tag( "invoke" ) + "\n\n  \t\n" ) == tag( "invoke" )


def test_the_tag_nearest_the_end_is_the_one_named():
    """The corruption STACKS. Naming the outer tag would send the author looking
    at the wrong end of their own field."""
    stacked = "reason." + tag( "park_reason" ) + "\n" + tag( "invoke" ) + "\n"
    assert envelope_tail_tag( stacked ) == tag( "invoke" )


# ---------------------------------------------------------------------------
# Controls — what the guard must NOT refuse
# ---------------------------------------------------------------------------
def test_a_reason_that_QUOTES_the_markup_mid_sentence_survives():
    """
    THE CONTROL THAT MAKES THIS GUARD SAFE, and it is not hypothetical: row
    91ccbc26 itself quotes both specimens in its prose. A guard that banned the
    characters outright would refuse the very rows written about this defect.
    """
    reason = ( "Parked because the specimen ends with " + tag( "invoke" )
               + " and we need it intact to study." )
    assert envelope_tail_tag( reason ) is None


def test_legitimate_angle_brackets_survive():
    """A reason may quote code. That was the second half of the live round-trip."""
    reason = 'Held: the branch cut. Condition was  if x < 3 and y > 4: emit("<tag>")'
    assert envelope_tail_tag( reason ) is None


def test_an_ordinary_reason_survives():
    assert envelope_tail_tag( "NOT TO BE WORKED per Rick's direct instruction" ) is None


def test_an_unrelated_closing_tag_is_not_barred():
    """The bar is the ENVELOPE, not markup. A reason ending in an html tag is a
    reason, not a corrupted write."""
    assert envelope_tail_tag( "see the note in " + tag( "div" ) ) is None


@pytest.mark.parametrize( "value", [ None, 42, [ ], "", "   " ] )
def test_non_strings_and_blanks_are_not_this_guards_business( value ):
    """validate_park already owns the REQUIRED message; two rules answering one
    input is how a caller gets two contradictory errors for one mistake."""
    assert envelope_tail_tag( value ) is None


# ---------------------------------------------------------------------------
# Wired into the verb — what the RUN produces, not what the function returns
# ---------------------------------------------------------------------------
def test_validate_park_refuses_the_corrupted_write():
    """
    The detector matters only if the transition actually refuses. This is the
    behaviour that turns a silent corruption into a loud one.
    """
    errors = validate_park( "in_progress", CHASE, RIO_TAIL )
    assert len( errors ) == 1
    assert tag( "invoke" ) in errors[ 0 ]
    assert "Re-send the reason" in errors[ 0 ]


def test_validate_park_still_accepts_a_good_reason():
    """NEGATIVE CONTROL. A guard that refuses everything also refuses nothing
    useful — this proves the ordinary park still goes through."""
    assert validate_park( "in_progress", CHASE, "Held behind the branch cut." ) == [ ]


def test_a_blank_reason_gets_ONE_message_not_two():
    """The REQUIRED rule and the envelope rule must not both fire on one input."""
    errors = validate_park( "in_progress", CHASE, "   " )
    assert len( errors ) == 1
    assert "REQUIRED" in errors[ 0 ]


def test_the_envelope_error_rides_ALONGSIDE_the_other_park_errors():
    """
    A corrupted reason on an illegal source status must report BOTH. Collapsing
    them would make the author fix one thing, re-send, and be refused again.
    """
    errors = validate_park( "done", None, RIO_TAIL )
    assert len( errors ) == 3
    assert any( "cannot park from" in e for e in errors )
    assert any( "next_chase_ts is REQUIRED" in e for e in errors )
    assert any( tag( "invoke" ) in e for e in errors )
