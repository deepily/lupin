"""
A ZERO THRESHOLD SHUTS THE CREATE GATE FOR EVERYTHING — and does not raise doing it.

Rick's ruling 2026-09-01, taken on a straight either/or: at 0% the gate is fully ON
and every new ticket is refused. That is the literal reading of the control's own
label — the gate opens STRICTLY BELOW the threshold, and no ratio is below zero.

⚠️ THIS FILE ALSO PINS A LIVE DIVIDE-BY-ZERO THAT SHIPPED. `MIN_ALLOW_BELOW` has
always been 0.0, so `PATCH /api/tasks/flow-ratio/settings {"allow_below": 0}` could
reach the advisory long before the slider's `min` was lowered to 0. The refusal
builder does `math.floor( created / allow_below )`, so allow_below=0 with any
closures raised ZeroDivisionError out of a function whose contract says it never
raises. Measured at created=14, closed=3 before the fix.

WHY THE IDLE CASE IS THE ONE THAT MATTERS. The guard has to sit ABOVE the
`closed == 0` branch, and only one test can tell you whether it does: an idle
window (0 created, 0 closed). Everywhere else the two placements agree. So the
discriminating pair here is 0/0 at threshold 0 (REFUSE) against 0/0 at threshold
1.0 (ALLOW) — same counts, only the threshold moves. A fixture that varied the
counts instead would go green with the guard in either position.
"""

import pytest

from cosa.rest.task_store_rules import ratio_gate_advisory


# ── the hard stop ────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "created, closed, why", [
    ( 14, 3, "the exact shape that used to raise ZeroDivisionError" ),
    (  1, 1, "a perfectly balanced board is still refused at 0%"    ),
    (  5, 0, "nothing closed — refused, as it would be at any threshold" ),
    (  0, 7, "closures with no creations do not buy an exemption"   ),
] )
def test_a_zero_threshold_refuses_every_ordinary_create( created, closed, why ):

    advisory = ratio_gate_advisory( created, closed, allow_below=0.0 )
    assert advisory is not None, f"0% must refuse: {why}"
    assert "open below 0%" in advisory


def test_a_zero_threshold_refuses_an_idle_window_too_while_a_normal_one_allows_it():
    """
    THE PLACEMENT TEST. Identical counts, only the threshold differs — so this fails
    if the zero guard is moved below the `closed == 0` branch, which is the one
    mutation the cases above cannot see.
    """
    assert ratio_gate_advisory( 0, 0, allow_below=0.0 ) is not None, \
        "an operator who shut the gate meant it, quiet day or not"
    assert ratio_gate_advisory( 0, 0, allow_below=1.0 ) is None, \
        "an idle window is not a failing window at an ordinary threshold"


def test_the_zero_refusal_offers_no_closure_target_because_none_exists():
    """
    No number of closures opens a gate at 0. The message must therefore name the
    SETTING rather than quote a target — a "close N more" line here would send the
    operator to do work that cannot possibly help.
    """
    advisory = ratio_gate_advisory( 14, 3, allow_below=0.0 )
    assert "Closing more rows will not open it" in advisory
    assert "Close or finish" not in advisory, \
        "the ordinary refusal's close-N-more phrasing must not appear at 0%"


def test_a_zero_threshold_does_not_raise_where_it_used_to():
    """
    The regression proper. `ratio_gate_advisory` documents that it never raises; this
    is the input that broke that promise.
    """
    try:
        ratio_gate_advisory( 14, 3, allow_below=0.0 )
    except ZeroDivisionError:                                    # pragma: no cover
        pytest.fail( "allow_below=0 must not divide by zero" )


# ── what a zero threshold does NOT change ────────────────────────────────────

def test_p0_is_still_exempt_at_a_zero_threshold():
    """A hard stop is not a reason to strand something that genuinely cannot wait."""
    assert ratio_gate_advisory( 14, 3, priority="P0", allow_below=0.0 ) is None


def test_an_ordinary_threshold_is_untouched_by_the_zero_guard():
    """
    The positive control. Without it, every assertion above would still pass if the
    guard swallowed the whole function and refused everything at every threshold.
    """
    assert ratio_gate_advisory( 3, 14, allow_below=1.0 ) is None,     "3/14 is below 1.0 — allow"
    assert ratio_gate_advisory( 14, 3, allow_below=1.0 ) is not None, "14/3 is above 1.0 — refuse"
    assert "Close or finish" in ratio_gate_advisory( 14, 3, allow_below=1.0 ), \
        "the ordinary refusal still quotes a closure target"


def test_a_negative_threshold_is_treated_as_a_hard_stop_too():
    """
    `MIN_ALLOW_BELOW` clamps at 0.0, so a negative should never arrive — but the guard
    reads `<= 0` rather than `== 0` precisely so an unclamped caller cannot reach the
    division. Pinning it keeps that `<=` from being "simplified" to `==`.
    """
    advisory = ratio_gate_advisory( 14, 3, allow_below=-1.0 )
    assert advisory is not None
    # ⚠️ `is not None` ALONE IS BLIND HERE and the first cut of this test had only that.
    # With `== 0` the function falls through to the ORDINARY refusal, which is also not
    # None -- so the assertion passed under the very mutation it was written to catch.
    # Naming the hard-stop wording is what makes the two outcomes distinguishable.
    assert "open below 0%" in advisory
