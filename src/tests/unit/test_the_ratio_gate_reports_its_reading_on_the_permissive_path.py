"""
THE GATE MUST SAY WHAT IT SAW WHEN IT LETS YOU THROUGH — row aba30387, defects (1) and (2).

DEFECT (1), Mr Radio's. `ratio_gate_advisory` returns None on an allow and the create door
discarded created / closed / ratio / threshold with all four in hand. A PERMIT produced no
reading, so a working gate and an absent gate were indistinguishable from outside.

🔴 THE MEASURED COST, and it is unrecoverable. Tiffany's three creates at 16:45-16:51Z were
permitted; the row filed against them said the gate was "ARMED AND INERT". Settling that
needs the ratio AT THE TIME of each permit — nothing recorded it. Mr Radio reconstructed
what he could and reported that the deciding value "remains INFERRED, NOT MEASURED". Those
numbers do not exist anywhere now. This file does not recover them; it guarantees the next
such question is answerable.

DEFECT (2), maria's. The refusal prescribed "close N more rows" to a caller who may own
none — measured 2026-09-04, john was told to close 6 while holding zero open rows. The
count is FLEET-WIDE. An instruction that sounds actionable and cannot be performed is worse
than no instruction, because the caller waits on it.

⚠️ WHAT THIS FILE CANNOT DO, SAID PLAINLY. The wiring arm below reads the create handler's
SOURCE, not an assembled app driving a real request — the create door needs a DB session
and auth this tier does not have. A source-level check is genuinely weaker than driving the
door: it proves the call is written, not that the branch is reached. It is here because
CLAUDE.md § IMPLEMENTED BUT NOT INSTALLED is exactly the failure this row already suffered
once — `2f4852bf` fixed a nav file nothing loads — and a weak wiring check beats none. The
stronger version belongs with the integration tier.
"""

import inspect
import re

from cosa.rest import task_store_rules as rules
from cosa.rest.routers import tasks as tasks_router


# --------------------------------------------------------------------------------------
# Defect (1) — the reading itself
# --------------------------------------------------------------------------------------

def test_the_reading_helper_exists_and_is_callable():
    """
    🔴 ASSERT THE CONTROL EXISTS BEFORE ASSERTING WHAT IT DOES. Every arm below calls this
    helper; if it were absent they would error rather than measure. GREEN IN BOTH ARMS.
    """
    assert callable( getattr( rules, "ratio_gate_reading", None ) ), (
        "task_store_rules must expose ratio_gate_reading — it is the whole of defect (1)"
    )


def test_the_reading_names_every_number_the_verdict_was_computed_from():
    """
    The reading has one job: make a permit as legible as a refusal. A refusal already names
    the numerator, the denominator, the ratio and the threshold; a permit that names fewer
    leaves the next reader reconstructing, which is the defect.
    """
    # 🔴 THE RATIO AND THE THRESHOLD MUST DIFFER IN THIS FIXTURE, AND THAT IS NOT COSMETIC.
    # The first version used created=209, closed=190, which gives ratio 1.10 — IDENTICAL to
    # the threshold. `"1.10" in line` was then satisfied by either number, so a mutation
    # deleting the threshold from the reading SURVIVED a green run of this file (measured,
    # 2026-09-04). Two quantities that are interchangeable in the data cannot be told apart
    # by any assertion over it. 209/250 = 0.84 shares no digits with 1.10.
    line = rules.ratio_gate_reading( created=209, closed=250, allow_below=1.10, verdict="allow" )

    assert "209"   in line, "the reading must name what was created"
    assert "250"   in line, "the reading must name what was closed"
    assert "allow" in line, "the reading must name which path was taken"
    # Labelled, not bare: a bare substring match cannot say WHICH number it found.
    assert "threshold=1.10" in line, f"the reading must name the threshold: {line!r}"
    assert "ratio=0.84"     in line, f"the reading must name the ratio: {line!r}"


def test_the_reading_does_not_invent_a_ratio_it_cannot_compute():
    """
    With nothing closed there IS no ratio, and printing one would be manufacturing a
    reading — the same rule the zero-closed REFUSAL already follows. An idle window must
    still report, because "nothing happened" is a fact the next reader needs too.
    """
    line = rules.ratio_gate_reading( created=0, closed=0, allow_below=1.10, verdict="allow" )
    assert "n/a" in line, f"a ratio with no denominator must read n/a, not a number: {line!r}"
    assert not re.search( r"ratio=\d", line ), f"invented a ratio with no denominator: {line!r}"


# --------------------------------------------------------------------------------------
# Defect (1) — the wiring. See the module docstring for what this arm can and cannot prove.
# --------------------------------------------------------------------------------------

def test_the_create_door_reports_the_reading_on_the_allow_path():
    """
    🔴 THE ARM THAT MATTERS, AND THE ONE THIS ROW ALREADY GOT BURNED BY ONCE. A helper at
    100% that the app never calls is exactly the shape of `2f4852bf` — a nav fix landed in
    a file nothing loads. So: does the create door actually call it?

    The call must sit on the branch that runs when the gate did NOT refuse. Asserting only
    that the name appears somewhere in the module would pass if it were called on the
    refusal path, which is the one path that already reported.
    """
    source = inspect.getsource( tasks_router )

    assert "ratio_gate_reading" in source, (
        "the create door never calls ratio_gate_reading — the helper is implemented and "
        "not installed, so a permit still reports nothing"
    )

    # The call must be reachable from a branch that is NOT the refusal. `ratio_refusal` is
    # the router's own name for the verdict; the allow path is an elif/else beneath it.
    after_refusal = source.split( "if ratio_refusal:" )
    assert len( after_refusal ) == 2, "the router's ratio-gate block moved — re-anchor this guard"
    assert "ratio_gate_reading" in after_refusal[ 1 ], (
        "ratio_gate_reading is called, but not below `if ratio_refusal:` — a reading that "
        "only fires on a refusal reports the one path that already reported"
    )


# --------------------------------------------------------------------------------------
# Defect (2) — a remedy the caller can perform
# --------------------------------------------------------------------------------------

def test_the_refusal_says_whose_count_it_is():
    """
    The number is fleet-wide. A caller who reads it as their own backlog waits on work they
    do not own and cannot start. Measured: john was told to close 6 while holding zero.
    """
    message = rules.ratio_gate_advisory( created=209, closed=184, allow_below=1.10 )
    assert "FLEET-WIDE" in message.upper(), (
        f"the refusal must say the count is fleet-wide, not the caller's: {message!r}"
    )


def test_the_refusal_names_a_remedy_the_caller_can_actually_perform():
    """
    Closing rows is not an action a caller can take on demand — rows close when work
    finishes. Amending onto an existing row always is, and it is the tier-1 fallback
    session-end.md already prescribes.
    """
    message = rules.ratio_gate_advisory( created=209, closed=184, allow_below=1.10 )
    assert "task_amend" in message, (
        f"the refusal must name a remedy the refused caller can perform: {message!r}"
    )


def test_the_refusal_still_names_the_counts_and_the_escape_hatch():
    """
    Control for the two arms above. They assert what was ADDED; this asserts nothing that
    was already working got dropped while adding it. GREEN IN BOTH ARMS.
    """
    message = rules.ratio_gate_advisory( created=209, closed=184, allow_below=1.10 )
    for token in ( "209", "184", "1.14", "1.10", "P0" ):
        assert token in message, f"the refusal lost {token!r}: {message!r}"
