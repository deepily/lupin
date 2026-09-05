"""
Headroom must be a PROJECTION of the ratio gate, never a second gate.

🔴 THE DEFECT THIS PINS. `ratio_gate_advisory` already decides whether a create is
admitted. A headroom number derived independently from the same inputs would be a SECOND
piece of code answering one question — and the day the two disagree, the board tells an
operator the gate is open while the gate refuses, with nothing reporting the
disagreement. Mr. Radio's ruling 2026-09-05: "if your number ever disagrees with what the
gate actually does, the number is wrong."

⇒ So the load-bearing test here is not any single expected value. It is
`test_headroom_agrees_with_walking_the_real_gate`, which asks the GATE, one create at a
time, across a grid — a second instrument over the same question. The hand-written cases
below exist so that a bug making BOTH the search and the walk wrong in the same direction
still gets caught; the walk alone could agree with a broken search.
"""

import math

import pytest

from cosa.rest.task_store_rules import (
    ratio_gate_advisory,
    ratio_gate_headroom,
    ratio_gate_close_needed,
    _HEADROOM_PROBE_CEILING,
)


def _walk_the_gate( created, closed, allow_below, ceiling=2000 ):
    """Count admitted creates by asking the gate one at a time — the slow, obvious way."""
    n = 0
    while n < ceiling and ratio_gate_advisory( created + n, closed, allow_below=allow_below ) is None:
        n += 1
    return n


# ---------------------------------------------------------------------------
# The agreement test — the reason this file exists.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "closed",      [ 0, 1, 3, 7, 13, 40 ] )
@pytest.mark.parametrize( "created",     [ 0, 1, 5, 14, 60 ] )
@pytest.mark.parametrize( "allow_below", [ 0.0, 0.25, 0.5, 1.0, 1.5, 2.0 ] )
def test_headroom_agrees_with_walking_the_real_gate( created, closed, allow_below ):
    """
    The projection and the gate must answer identically on every cell of the grid.

    This is the structural claim. If it fails, headroom has become a second gate.
    """
    assert ratio_gate_headroom( created, closed, allow_below ) == \
           _walk_the_gate( created, closed, allow_below )


def test_the_grid_actually_exercises_both_verdicts():
    """
    POSITIVE CONTROL for the grid above.

    A grid on which the gate always refuses would make every agreement trivially true —
    0 == 0, 180 times — and the suite would look thorough while measuring nothing. So
    assert the grid contains BOTH an admitting cell and a refusing one.
    """
    admits  = ratio_gate_headroom(  0, 40, 2.0 )
    refuses = ratio_gate_headroom( 60,  1, 0.25 )
    assert admits  >  0, "grid must contain a case the gate admits"
    assert refuses == 0, "grid must contain a case the gate refuses outright"


# ---------------------------------------------------------------------------
# Hand-written expectations — independent of the walk, so a shared bug still fails.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "created,closed,allow_below,expected,why", [
    ( 10, 13, 1.0,  3, "the gate admits the create that TIPS the ratio to exactly 1.00, "
                       "because it is judged one row earlier — the spec algebra says 2" ),
    (  0,  0, 1.0,  1, "an idle window admits the next create and refuses the one after" ),
    ( 14,  3, 1.0,  0, "already over the line" ),
    (  5,  0, 1.0,  0, "nothing closed — no denominator" ),
    ( 10, 13, 0.0,  0, "a zero threshold is a hard stop no closure can open" ),
    (  0, 10, 1.0, 10, "an empty window against 10 closures" ),
    (  0, 10, 0.5,  5, "the threshold scales the answer" ),
    (  9, 10, 1.0,  1, "one below the line admits exactly one" ),
] )
def test_headroom_hand_written_cases( created, closed, allow_below, expected, why ):
    assert ratio_gate_headroom( created, closed, allow_below ) == expected, why


def test_the_ten_thirteen_case_disagrees_with_the_spec_algebra_and_the_gate_wins():
    """
    Pins the off-by-one EXPLICITLY, so a future editor who reaches for the design doc's
    formula finds a test saying why it is not what shipped.

    Spec: largest N with (created + N) / closed < allow_below  ->  N = 2
    Gate: admits 3, because a create is judged against the counts BEFORE it lands.
    """
    created, closed, allow_below = 10, 13, 1.0

    spec_n = math.ceil( closed * allow_below - created ) - 1
    assert spec_n == 2, "the spec algebra, computed here only to show what it yields"

    assert ratio_gate_headroom( created, closed, allow_below ) == 3
    # And the gate itself confirms the third create is admitted, so 3 is not our opinion.
    assert ratio_gate_advisory( created + 2, closed, allow_below=allow_below ) is None
    assert ratio_gate_advisory( created + 3, closed, allow_below=allow_below ) is not None


# ---------------------------------------------------------------------------
# Purity and bounds.
# ---------------------------------------------------------------------------

def test_headroom_never_reads_the_settings_module( monkeypatch ):
    """
    The projection must use the threshold the CALLER read, never read one itself.

    Two reads of a live operator dial can return two values, and the whole point of the
    projection is that it shares the gate's inputs. Booby-trap every getter.
    """
    from cosa.rest import flow_ratio_settings as frs

    def _boom( *a, **k ):
        raise AssertionError( "ratio_gate_headroom read the settings module" )

    monkeypatch.setattr( frs, "get_allow_below",        _boom )
    monkeypatch.setattr( frs, "get_window_hours",       _boom )
    monkeypatch.setattr( frs, "get_enforcement_active", _boom )

    assert ratio_gate_headroom( 10, 13, 1.0 ) == 3


def test_the_booby_trap_would_actually_fire():
    """
    POSITIVE CONTROL for the test above: prove the trap catches a real read.

    Without this, a monkeypatch that silently failed to bind would make the purity test
    pass for the wrong reason — the exact "an empty result is two different failures"
    shape this repo keeps re-deriving.
    """
    from cosa.rest import flow_ratio_settings as frs
    import unittest.mock as m

    with m.patch.object( frs, "get_allow_below", side_effect=AssertionError( "read!" ) ):
        with pytest.raises( AssertionError ):
            frs.get_allow_below()


def test_an_unbounded_threshold_reports_none_rather_than_a_huge_number():
    """
    A threshold so high that a million more creates are admitted is not a gate. Report
    None, never a large number a caller could render as a target to aim at.
    """
    assert ratio_gate_headroom( 0, _HEADROOM_PROBE_CEILING, 10.0 ) is None


# ---------------------------------------------------------------------------
# CLOSE N — the mirror direction. Same loop, one variable swapped.
# ---------------------------------------------------------------------------

def _walk_the_gate_closing( created, closed, allow_below, ceiling=3000 ):
    """Count closures needed by asking the gate one at a time — the slow, obvious way."""
    if ratio_gate_advisory( created, closed, allow_below=allow_below ) is None: return 0
    n = 1
    while n < ceiling:
        if ratio_gate_advisory( created, closed + n, allow_below=allow_below ) is None: return n
        n += 1
    return None


@pytest.mark.parametrize( "created,closed,allow_below", [
    (   14,  3, 1.0 ),
    (   10, 13, 1.0 ),
    (    5,  0, 1.0 ),
    (  100, 10, 1.0 ),   # 🔴 THE REGRESSION CASE. A first cut of the close-direction loop
                         # stepped +1 up to 64 then DOUBLED, jumping 65 -> 130 and skipping
                         # the true answer 91. Only the brute-force cross-check caught it;
                         # every hand-written case I had chosen happened to sit below the
                         # jump. Keep a case on the far side of it.
    (   65,  1, 1.0 ),   # exactly at the old step boundary
    (  129,  1, 1.0 ),   # past the first doubling
    ( 1000,  3, 1.0 ),
    (    7,  2, 0.5 ),
    (   20,  5, 2.0 ),
    (    0,  0, 1.0 ),
] )
def test_close_needed_agrees_with_walking_the_real_gate( created, closed, allow_below ):
    """
    The mirror projection must also be the GATE's answer, not an algebra's.
    """
    assert ratio_gate_close_needed( created, closed, allow_below ) == \
           _walk_the_gate_closing( created, closed, allow_below )


def test_the_close_grid_exercises_a_real_closure_requirement():
    """
    POSITIVE CONTROL: a grid of all-zeros would satisfy every agreement above trivially.
    """
    assert ratio_gate_close_needed( 100, 10, 1.0 ) == 91, "a real, large, non-zero answer"
    assert ratio_gate_close_needed(  10, 13, 1.0 ) ==  0, "and a genuine zero when admitting"


def test_a_zero_threshold_reports_none_because_no_closure_can_open_it():
    """
    A gate set to 0 is shut for everything. There is no N. Reporting a number would name
    a target that cannot be reached — the same reason headroom reports None rather than a
    large number.
    """
    assert ratio_gate_close_needed( 10, 13, 0.0 ) is None


def test_the_two_directions_answer_opposite_questions_and_are_never_both_positive():
    """
    Under gate truth the two states partition: either the gate admits (headroom > 0,
    nothing to close) or it refuses (headroom == 0, something to close).

    🔴 THIS IS THE TEST THAT DOCUMENTS WHY `FULL` IS UNREACHABLE. `FULL` was ratified as
    "N == 0 but still legal". There is no such state when the number comes from the gate:
    if the gate admits, at least one more create gets in. Surfaced to Rick; built to the
    gate per Mr. Radio's 2026-09-05 ruling.
    """
    for created, closed, allow_below in [ ( 10, 13, 1.0 ), ( 9, 10, 1.0 ), ( 14, 3, 1.0 ),
                                          ( 0, 0, 1.0 ), ( 5, 0, 1.0 ) ]:
        room  = ratio_gate_headroom(     created, closed, allow_below )
        close = ratio_gate_close_needed( created, closed, allow_below )
        assert not ( room > 0 and close > 0 ), "the two states must never both be positive"
        assert room > 0 or close > 0, "one of the two must always have something to say"


def test_the_nine_ten_case_is_the_one_that_kills_FULL():
    """
    Pins the collision explicitly, with the numbers, so nobody re-derives it.

    Rick's sketch renders FULL here. The gate admits one more (judged at 9/10 = 0.90).
    """
    assert ratio_gate_headroom( 9, 10, 1.0 ) == 1, "the gate admits one more, so not FULL"
    assert ratio_gate_advisory( 9, 10, allow_below=1.0 ) is None, "and it really does admit"
