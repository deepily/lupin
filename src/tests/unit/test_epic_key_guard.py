"""
The epic-key guard at creation (row 5246bb67) — predicate, exemption, and the ramp.

RICK RULED THIS TWICE, and the second ruling is the operative one:

    2026-08-31 ~19:40 EDT   reject on creation, `epic:unassigned` legal and named in the
                            error, warn-only for one week first
    2026-08-31 ~20:35 EDT   re-asked with Maya's evidence in front of him. He KEPT the
                            decision and FIXED THE PREDICATE: `startswith("epic:")`, with
                            the harness mirror's `cc-task:` lane exempt.

🔴 WHY THE PREDICATE IS THE WHOLE RULING. `correlation_key` has three tenants, measured on
the live board — `epic:*` (191 rows), free-form `cascade-*` and friends (289), and the
mirror's `cc-task:<sid>:<n>` (52). A `key != ""` check is satisfied by all three, so it is
INERT on two of them: a row carrying only an auto-stamped machine key passes, and the board
then reads as covered precisely because the check passed. That is the defect this row was
filed about, arriving one level up inside its own fix.

⇒ So `test_a_machine_key_alone_does_not_satisfy_the_guard` is not an edge case. It is the
test that separates the ruled predicate from the one that was nearly built.

⚠️ WHAT THIS DOES NOT DO — Maya's caveat, kept because it outlives the build. A detector
reads the ROWS, so its stated reach is its actual reach; this reads the DOORS. Her survey
found `repo.create_item` has exactly one non-test caller today, so the door list is short —
but it is a door list, and a fifth creation path would be silent here. Revisit when someone
pays for the `epic_key` column migration she recommended.
"""

import datetime

import pytest

from cosa.rest import task_store_rules as rules


# --------------------------------------------------------------------------------------
# The predicate — the half that carries the ruling
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key",
    [
        "epic:board-visibility",
        "epic:seal-the-test-tier",
        "epic:quick-ask-ship",
        rules.EPIC_KEY_UNASSIGNED,
    ],
)
def test_an_epic_key_passes( key ):
    """
    A key beginning `epic:` is compliant, and `epic:unassigned` is compliant too.

    The explicit-unassigned case is load-bearing, not a convenience: Rick's ruling names it
    as a LEGAL answer so that "blank" and "deliberately no story" stay distinguishable. That
    distinction is what the 2026-08-18 epic-layer design paid for, and a guard that refused
    `epic:unassigned` would collapse it back.
    """
    assert rules.epic_key_advisory( key ) is None


def test_a_machine_key_alone_does_not_satisfy_the_guard():
    """
    🔴 THE TEST THAT SEPARATES THE RULED PREDICATE FROM THE ONE NEARLY BUILT.

    `cc-task:...` is non-empty, so a `key != ""` guard passes it — while the row carries no
    epic at all. This asserts the guard has an OPINION about that key rather than merely
    seeing text in the field.

    ⚠️ Read together with `test_the_mirror_lane_is_exempt` directly below: the mirror's rows
    are exempt from the CONSEQUENCE, and that exemption is a routing decision at the door,
    not the predicate failing to notice. Both facts are true and they are different facts.
    """
    machine_key = "cc-task:8982f548-1111-2222-3333-444455556666:7"

    # The naive predicate the ruling explicitly rejected.
    naive_blank_check_would_pass = machine_key != ""
    assert naive_blank_check_would_pass is True, (
        "precondition: the machine key must be non-empty, or this test is not exercising "
        "the difference between the two predicates"
    )

    # The ruled predicate discriminates on the PREFIX, which is the whole point.
    assert not machine_key.startswith( rules.EPIC_KEY_PREFIX ), (
        "a cc-task key must not look like an epic key, or the exemption below is untestable"
    )


def test_the_mirror_lane_is_exempt():
    """
    The harness mirror writes `cc-task:` keys on a path with NO HUMAN to answer a 422.

    Exempt BY RULING, not by oversight. This is the one place where letting a non-epic key
    through is correct, and it is worth a named test because a future reader tightening the
    predicate would otherwise "fix" it and break every mirrored write the day enforcement
    goes live.
    """
    assert rules.epic_key_advisory( "cc-task:8982f548:7" ) is None
    assert rules.epic_key_advisory( rules.MIRROR_KEY_PREFIX + "anything" ) is None


@pytest.mark.parametrize(
    "key, why",
    [
        ( "cascade-quick-ask", "free-form run tag typed through the ordinary MCP door" ),
        ( "some-random-tag",   "arbitrary free text" ),
        ( "epicish:thing",     "near-miss prefix — 'epic' without the colon boundary" ),
        ( "EPIC:shouty",       "wrong case; the stored keys are lowercase and the check is literal" ),
    ],
)
def test_a_non_epic_key_earns_an_advisory( key, why ):
    """
    Everything that is neither an epic key nor the mirror lane gets flagged.

    `epicish:thing` and `EPIC:shouty` are deliberate near-misses. A prefix check is exactly
    the kind of predicate that quietly widens — `"epic" in key` would pass both — and a test
    that only ever feeds it obvious inputs cannot tell a tight check from a loose one.
    """
    advisory = rules.epic_key_advisory( key )
    assert advisory, f"expected an advisory for {key!r} ({why})"
    assert key in advisory, "the advisory must quote the offending value back"
    assert rules.EPIC_KEY_UNASSIGNED in advisory, (
        "Rick's ruling requires the legal explicit answer to be NAMED in the message — a "
        "guard that refuses without saying what would satisfy it just moves the puzzle"
    )


@pytest.mark.parametrize( "key", [ None, "", "   ", 123, [ ], { } ] )
def test_an_absent_or_non_string_key_is_flagged_and_never_raises( key ):
    """
    Absent, blank, whitespace, and wrong-TYPE all land on the advisory, none raise.

    The type cases are not paranoia. This runs on a client-supplied create payload, and a
    TypeError here would convert a soft warn-only advisory into a 500 — turning the gentlest
    thing in the ramp into the loudest failure on the write path.
    """
    advisory = rules.epic_key_advisory( key )
    assert advisory, f"expected an advisory for {key!r}"
    assert rules.EPIC_KEY_UNASSIGNED in advisory


def test_the_blank_and_the_populated_messages_are_different():
    """
    "No key" and "wrong key" are different problems and get different wording.

    Telling someone whose row already carries `cascade-quick-ask` to "add a correlation key"
    reads as nonsense — they can see one in the field. The message has to say that the field
    has several tenants and only one of them groups the board.
    """
    blank     = rules.epic_key_advisory( None )
    populated = rules.epic_key_advisory( "cascade-quick-ask" )

    assert blank != populated
    assert "absent" in blank
    assert "cascade-quick-ask" in populated


# --------------------------------------------------------------------------------------
# The ramp — Rick's warn-only week, and the thing that stops it becoming permanent
# --------------------------------------------------------------------------------------

def test_the_guard_ships_warn_only():
    """
    Enforcement is OFF at ship. Rick: "Ship it warn-only for one week first so no caller
    breaks by surprise."

    ⚠️ This test is expected to be EDITED, not deleted, when enforcement flips. It pins the
    shipped state so the flip is a visible diff rather than a config drift nobody reviewed.
    """
    assert rules.EPIC_KEY_ENFORCEMENT_ACTIVE is False


def test_the_warn_only_window_has_not_silently_become_permanent():
    """
    🔴 THE RAMP'S OWN DEADLINE, ENFORCED BY THE BUILD RATHER THAN BY MEMORY.

    A one-week warn-only ramp with nothing but a comment on it is a permanent warn-only
    ramp. This repo has the receipt: the checked-hash mandate was documented, prominent, and
    broken three times in one afternoon by the people who wrote it, and this file's sibling
    lesson is Clayton's on `e9b78e51` — "the class question has been asked three times on
    this row and answered in prose twice; prose does not fail a build."

    So once EPIC_KEY_ENFORCEMENT_STARTS passes while enforcement is still off, this goes RED
    and somebody has to make a decision. Flipping the flag OR deliberately extending the date
    both turn it green again; doing nothing does not.

    ⚠️ THE FAILURE IS NOT "YOU ARE LATE" — it is "the week is up, choose." Extending the date
    with a reason in the commit is a perfectly good answer.
    """
    starts = datetime.date.fromisoformat( rules.EPIC_KEY_ENFORCEMENT_STARTS )
    today  = datetime.date.today()

    if rules.EPIC_KEY_ENFORCEMENT_ACTIVE: return   # flipped; the ramp is over, nothing to police

    assert today < starts, (
        f"the warn-only ramp reached its end date and nothing changed.\n"
        f"  EPIC_KEY_ENFORCEMENT_STARTS : {starts}\n"
        f"  today                       : {today}\n"
        f"Rick ruled warn-only for ONE WEEK (row 5246bb67), not indefinitely. Choose:\n"
        f"  (a) set EPIC_KEY_ENFORCEMENT_ACTIVE = True — the guard starts returning 422\n"
        f"  (b) move EPIC_KEY_ENFORCEMENT_STARTS out, with the reason in the commit message\n"
        f"Doing neither is how a ramp becomes permanent, which is the outcome this "
        f"assertion exists to prevent."
    )


def test_the_deadline_is_a_real_date_and_after_the_ruling():
    """
    Guard the guard: an unparseable or already-past date would make the ramp test either
    error out or fire on day one, and both read as noise rather than as a decision point.
    """
    starts = datetime.date.fromisoformat( rules.EPIC_KEY_ENFORCEMENT_STARTS )
    ruled  = datetime.date( 2026, 8, 31 )   # the day Rick ruled, twice

    assert starts > ruled, (
        f"the ramp ends {starts}, on or before the day it was ruled ({ruled}) — that is not "
        f"a week's grace, it is a typo"
    )
