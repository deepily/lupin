"""
The caveat check's proximity window, proven to discriminate AT ITS BOUNDARY.

WHY A BOUNDARY TEST AND NOT AN "IT WORKS" TEST (Mr. Radio 🦉, 2026-09-01)
-------------------------------------------------------------------------
`remedy_carries_its_caveat` first searched the WHOLE message, so a caveat word
occurring anywhere satisfied a hazard. A green said "these words are present
somewhere", not "this command is qualified". Measured: a `git checkout` remedy left
entirely unqualified PASSED while the word "overwrite" sat three paragraphs above it,
about an unrelated queue.

The fix is a window of CAVEAT_WINDOW_LINES either side. A window is a HEURISTIC, and
the honest way to ship one is to pin where it STOPS — otherwise the number is an
unmeasured guess wearing a default's clothing.

⇒ SO THESE CASES SIT ON BOTH SIDES OF THE LINE. A test showing only that a near caveat
passes would hold for a window of 2, of 20, or of infinity — and infinity is precisely
the version that carried the defect. It is the FAR case that gives the near case its
meaning.

⚠️ This pins the BOUNDARY, not that 2 is the right number. If a guard message is later
written with its caveats further away, widen `window` at the call site and add a case
here; do not read a green as evidence the default is optimal.

Venue: :7999-eligible. Pure string work — no guard imported, no server, no filesystem.
"""
import pytest

from tests.helpers.guard_remedy import (
    CAVEAT_WINDOW_LINES, remedy_carries_its_caveat,
)

HAZARD = "  git checkout <sha> -- <path>"
CAVEAT = "It OVERWRITES the working copy and moves no ref, so there is no reflog entry."


def _message( distance ):
    """
    Requires:
        - distance is a positive number of lines between the hazard and its caveat

    Ensures:
        - returns a message whose caveat sits exactly `distance` lines below the hazard
        - the hazard and caveat text are IDENTICAL at every distance, so the only
          variable across the cases below is the gap
    """
    filler = [ "Some unrelated prose that names no hazard and no caveat." ] * ( distance - 1 )
    return "\n".join( [ "Refusing this operation.", HAZARD, *filler, CAVEAT ] )


@pytest.mark.parametrize( "distance", range( 1, CAVEAT_WINDOW_LINES + 1 ) )
def test_a_caveat_INSIDE_the_window_qualifies_its_hazard( distance ):
    """Near enough to reach the reader who is looking at the command."""
    assert not remedy_carries_its_caveat( _message( distance ) ), (
        f"a caveat {distance} line(s) below its hazard was not counted, inside a window "
        f"of {CAVEAT_WINDOW_LINES}"
    )


@pytest.mark.parametrize( "distance", [ CAVEAT_WINDOW_LINES + 1, CAVEAT_WINDOW_LINES + 5 ] )
def test_a_caveat_OUTSIDE_the_window_does_NOT_qualify_it( distance ):
    """
    The case that earns the window.

    Without it every assertion above would also hold for an unbounded search — exactly
    the version that shipped the false positive.
    """
    assert remedy_carries_its_caveat( _message( distance ) ), (
        f"a caveat {distance} line(s) away still qualified the hazard — the window is "
        f"not bounded, and a green would mean 'these words are present somewhere'"
    )


def test_the_two_verdicts_differ_ONLY_in_the_GAP():
    """
    The controlled pair. Same hazard, same caveat, same words — only the distance moves,
    so the window is provably what decides the verdict rather than some difference in
    the text. The parametrised lists above vary one thing too, but this states it as an
    assertion instead of leaving it to be read off two separate cases.
    """
    near, far = _message( CAVEAT_WINDOW_LINES ), _message( CAVEAT_WINDOW_LINES + 1 )
    assert HAZARD in near and HAZARD in far
    assert CAVEAT in near and CAVEAT in far
    assert not remedy_carries_its_caveat( near )
    assert     remedy_carries_its_caveat( far )
