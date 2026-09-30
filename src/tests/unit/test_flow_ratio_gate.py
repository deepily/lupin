"""
The closed-vs-new ratio GATE at creation — the exemptions, the message, and the ramp.

DESIGN: planning-is-prompting/src/rnd/2026.09.01-closed-vs-new-ratio-gate.md @ 845a34b.
Rick's durable, mechanical replacement for the ticket moratorium he declared by voice on
2026-09-01. A moratorium depends on everyone remembering; this does not, which is the whole
point and is why anything that makes it easy to switch off defeats it.

⚠️ HE HOLDS THE THRESHOLD AS AN OPERATOR DIAL, and said so explicitly the same day: "I
wouldn't worry too much about optimizing this gate member... it is dynamically adjustable
on the fly... We're not creating perfection simply something that is good enough." So these
tests pin the RULED behaviour and the exemptions — not a tuned number. If he moves the
threshold, nothing here should need rewriting.

🔴 THE TWO EXEMPTIONS ARE THE FRAGILE PART, not the arithmetic. A gate with no escape hatch
gets switched off the first Friday it is wrong — Rick's own standing note — and a gate whose
escape hatch is unlogged is just a hole. Both are tested, and the LOGGING of the P0
exemption is tested as part of the exemption rather than as a nicety.
"""

import datetime

import pytest

from cosa.rest import task_store_rules as rules


# --------------------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "created, closed, allowed, why",
    [
        (  9, 10, True,  "closing faster than filing" ),
        ( 10, 13, True,  "the live board, 24h window, 2026-09-01" ),
        (  0, 10, True,  "closed ten, filed none — as healthy as it gets" ),
        ( 10, 10, False, "EXACTLY 1.0 refuses — the gate opens BELOW 1.0" ),
        ( 11, 10, False, "filing faster than closing" ),
        ( 14,  3, False, "María's worked example from the design doc" ),
    ],
)
def test_the_gate_follows_the_ratio( created, closed, allowed, why ):
    """
    🔴 EXACTLY 1.0 REFUSES. Rick: "adding to list requires that the threshold or ratio be
    less than 1.0". A row at 1.0 means the fleet filed exactly as many as it closed —
    treading water — and this exists to make the list shrink. `<=` is a one-character
    change that quietly permits a steady state forever.
    """
    verdict = rules.ratio_gate_advisory( created, closed )
    assert ( verdict is None ) == allowed, f"{why}: got {verdict!r}"


def test_nothing_closed_but_things_filed_refuses():
    """
    The common case on a quiet day, and the one a naive division would crash on. A window
    where nothing was finished is exactly what the gate is for.
    """
    assert rules.ratio_gate_advisory( created=5, closed=0 ) is not None


def test_an_idle_window_allows():
    """
    `0/0`. An idle window is not a failing window.

    ⚠️ SAME `closed == 0` BRANCH AS THE TEST ABOVE, opposite answer, and only `created`
    separates them. A single "closed is zero" test would pass an implementation that
    refused both — gating the fleet on an empty Sunday.
    """
    assert rules.ratio_gate_advisory( created=0, closed=0 ) is None


def test_idle_and_starved_do_not_share_an_answer():
    starved = rules.ratio_gate_advisory( created=1, closed=0 )
    idle    = rules.ratio_gate_advisory( created=0, closed=0 )
    assert ( starved is None ) != ( idle is None )


# --------------------------------------------------------------------------------------
# The exemptions — the fragile part
# --------------------------------------------------------------------------------------

def test_a_p0_is_exempt_however_bad_the_ratio():
    """
    Rick's Q4. A gate that refuses the filing of a P0 outage row is a gate that gets
    switched off the first Friday it is wrong.
    """
    assert rules.ratio_gate_advisory( created=99, closed=1, priority="P0" ) is None


@pytest.mark.parametrize( "priority", [ "p0", "P0" ] )
def test_the_p0_exemption_is_case_insensitive( priority ):
    """
    An exemption that works for "P0" and silently fails for "p0" is worse than none — it
    refuses an outage row for a reason nobody would guess from the message.
    """
    assert rules.ratio_gate_advisory( created=99, closed=1, priority=priority ) is None


@pytest.mark.parametrize( "priority", [ "P1", "P2", "P3", None, "" ] )
def test_nothing_below_p0_is_exempt( priority ):
    """
    The exemption is P0 ALONE. If P1 were exempt too the gate would be inert on most of
    what this fleet actually files — and P1 is the default reach for anything that feels
    urgent, which is every row at the moment somebody writes it.
    """
    assert rules.ratio_gate_advisory( created=99, closed=1, priority=priority ) is not None


def test_the_harness_mirror_lane_is_exempt():
    """
    The mirror writes `cc-task:` keys on a path with NO HUMAN present to answer a 422 —
    the same carve-out the epic-key guard makes, for the same reason. This is the lane
    that would break first and most silently under a naive gate.
    """
    assert rules.ratio_gate_advisory(
        created=99, closed=1, correlation_key="cc-task:8982f548:7"
    ) is None


@pytest.mark.parametrize( "key", [ "epic:board-visibility", "cascade-quick-ask", "", None ] )
def test_an_ordinary_key_is_not_exempt( key ):
    """Only the mirror lane. An epic key is a normal human write and is gated normally."""
    assert rules.ratio_gate_advisory( created=99, closed=1, correlation_key=key ) is not None


def test_a_non_string_key_does_not_raise():
    """
    The create payload is client-supplied. A TypeError here would turn a warn-only advisory
    into a 500 on the write path — the loudest possible failure for the gentlest input.
    """
    for key in ( 123, [ ], { }, object() ):
        assert rules.ratio_gate_advisory( created=99, closed=1, correlation_key=key ) is not None


# --------------------------------------------------------------------------------------
# The message — Rick asked for the numbers and the reason, not just "no"
# --------------------------------------------------------------------------------------

def test_the_refusal_names_the_real_counts_and_the_gate():
    """
    Rick asked for "the appropriate message… success if under 1.0 and failure and why".
    A bare refusal makes the reader go and find the numbers themselves.
    """
    message = rules.ratio_gate_advisory( created=14, closed=3 )

    assert "14"   in message, "the refusal must name what was created"
    assert "3"    in message, "the refusal must name what was closed"
    assert "4.67" in message, "the refusal must name the ratio it computed"
    assert "1.00" in message, "the refusal must name the threshold it is measuring against"


def test_the_refusal_says_how_many_more_to_close():
    """
    ⚠️ AND THE ARITHMETIC IS STRICT, WHICH MAKES IT 12 RATHER THAN 11.

    The design doc's worked example says "Close or finish 11 more rows" for 14 created /
    3 closed. Closing 11 more gives 14/14 = 1.00 exactly — which REFUSES, because the gate
    opens strictly below 1.0. The twelfth is the one that actually opens it: 14/15 = 0.93.

    Off by one in the doc, not in the ruling. Recording it here rather than only in a DM,
    because the doc's number is the one a reader will copy into a message.
    """
    message = rules.ratio_gate_advisory( created=14, closed=3 )
    assert "12" in message

    # And the boundary the off-by-one turns on, asserted directly rather than reasoned.
    assert rules.ratio_gate_advisory( created=14, closed=14 ) is not None, "1.00 refuses"
    assert rules.ratio_gate_advisory( created=14, closed=15 ) is None,     "0.93 allows"


def test_the_refusal_names_the_escape_hatch():
    """
    A gate that refuses without saying what would satisfy it just moves the puzzle. Same
    rule the epic-key guard follows by naming `epic:unassigned` in its own message.
    """
    assert "P0" in rules.ratio_gate_advisory( created=14, closed=3 )
    assert "P0" in rules.ratio_gate_advisory( created=5,  closed=0 )


def test_the_zero_closed_refusal_does_not_claim_a_ratio():
    """
    With no denominator there IS no ratio, and printing one would be inventing a reading.
    The message says nothing was finished instead.
    """
    message = rules.ratio_gate_advisory( created=5, closed=0 )
    assert "ratio" not in message.lower() or "no denominator" in message.lower()
    assert "0" in message


def test_success_is_silent():
    """
    An allowed create returns None — no confirmation. Rick has corrected this fleet for
    noise before; the success signal is the number already in the board header.
    """
    assert rules.ratio_gate_advisory( created=1, closed=10 ) is None


# --------------------------------------------------------------------------------------
# The ramp
# --------------------------------------------------------------------------------------

def test_enforcement_is_a_SETTING_and_not_a_code_constant():
    """
    🔨 RICK, 2026-09-02: "Why is this not included as a configuration instead of a
    constant in the Python code file? Put it where it belongs!"

    REPLACES `test_the_gate_ships_warn_only`, which asserted a module constant that no
    longer exists — that assertion would now be a change detector for a thing that
    decides nothing.

    ⚠️ THE ASYMMETRY HE OBJECTED TO WAS REAL. The window and threshold were ALREADY
    operator-adjustable at runtime; enforcement — the switch deciding whether either had
    teeth — needed a code edit and a deploy. The dials he could turn changed nothing.
    """
    from cosa.rest import flow_ratio_settings as frs

    assert hasattr( frs, "get_enforcement_active" ), (
        "enforcement must be readable from flow_ratio_settings beside the window and the "
        "threshold — that co-location IS the fix Rick asked for."
    )
    assert not hasattr( rules, "RATIO_GATE_ENFORCEMENT_ACTIVE" ), (
        "the module constant is back. Two sources for one switch is how the board and "
        "the gate come to disagree — the same drift this file already warns about for "
        "allow_below."
    )


def test_the_enforcement_fallback_fails_OPEN_not_closed( monkeypatch ):
    """
    An absent or unreadable config must WARN, never start refusing every create.

    Failing closed would take the board's whole write path down over a missing settings
    file. Asserted rather than trusted to the comment beside it: a default nobody
    exercises is a default nobody knows the value of.
    """
    from cosa.rest import flow_ratio_settings as frs

    monkeypatch.setattr( frs, "_read_overrides",
                         lambda: { "window_hours": None, "allow_below": None,
                                   "enforcement_active": None } )
    monkeypatch.setattr( frs, "_ini_value", lambda key, return_type, fallback: fallback )

    assert frs.get_enforcement_active() is False
    assert frs.FALLBACK_ENFORCEMENT_ACTIVE is False


def test_the_warn_only_window_has_not_silently_become_permanent():
    """
    🔴 THE DEADLINE, ENFORCED BY THE BUILD RATHER THAN BY MEMORY.

    A one-week ramp with only a comment on it is a permanent ramp. Same control as the
    epic-key guard, same reason — prose does not fail a build. Flipping the flag OR
    deliberately moving the date both turn this green; doing nothing does not.

    ⚠️ The failure is not "you are late", it is "the week is up, choose."
    """
    from cosa.rest import flow_ratio_settings as frs
    if frs.get_enforcement_active(): return

    starts = datetime.date.fromisoformat( rules.RATIO_GATE_ENFORCEMENT_STARTS )
    today  = datetime.date.today()

    assert today < starts, (
        f"the ratio gate's warn-only ramp ended {starts} and nothing changed (today {today}).\n"
        f"Rick ruled warn-only for ONE WEEK, not indefinitely. Choose:\n"
        f"  (a) set 'task flow ratio enforcement active = True' — creates start getting 422s\n"
        f"  (b) move RATIO_GATE_ENFORCEMENT_STARTS out, with the reason in the commit\n"
        f"Doing neither is how a ramp becomes permanent."
    )


def test_both_guards_on_this_door_ramp_together():
    """
    The epic-key guard and this one share the create chokepoint, and María's point was
    that they should land together. Same end date keeps them one decision rather than two
    someone has to remember separately.
    """
    assert rules.RATIO_GATE_ENFORCEMENT_STARTS == rules.EPIC_KEY_ENFORCEMENT_STARTS
