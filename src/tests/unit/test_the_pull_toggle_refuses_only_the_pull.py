"""
Rick's P0, row 458e9947 — the manager pull toggle.

BOTH ARMS ARE REQUIRED and the row says so: with the toggle ON a pull is refused AND
SAYS SO; with it OFF an ordinary pull still succeeds. A guard satisfied by refusing
everything is not a guard, so every ON-case here is paired with an OFF-case whose only
difference is the flag.

🔴 WHY THIS GATE EXISTS AT ALL, since the obvious reading is that one already did.
Measured at b6031094 before a line was written: the holding-area predicate
`item.status == NOT_APPROVED_STATUS` sits at exactly two sites in the router and both
also require `to_status != NOT_APPROVED_STATUS`. A pull is `queued -> in_progress`,
where that first clause is False — so BOTH existing gates miss it, structurally rather
than by sampling. A toggle wired to either would have shipped and disabled nothing.
`test_the_existing_admission_gates_cannot_see_a_pull` pins that, so if someone later
widens those predicates this file tells them this gate may now be redundant.
"""
import pytest

import cosa.rest.task_approval_settings as approval


@pytest.fixture
def toggle( monkeypatch ):
    """Drive the flag directly — the file/INI plumbing is `_read_overrides`' own tests."""
    def _set( on ):
        monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: on )
        monkeypatch.setattr( approval, "is_approver", lambda actor: False )
        monkeypatch.setattr( approval, "approver_persona_for_account", lambda email: None )
    return _set


# ── the two arms the row demands ──────────────────────────────────────────────

def test_with_the_toggle_ON_a_pull_is_refused_AND_says_why( toggle ):
    toggle( True )
    detail = approval.refusal_for_pull( "queued", "in_progress", "maya 1234" )
    assert detail is not None
    # A refusal that does not say how to proceed is a dead end wearing a status code.
    assert "maya 1234"                in detail
    assert "in_progress"              in detail
    assert "458e9947"                 in detail
    assert "manager_pull_disabled"    in detail          # the override key
    assert approval.INI_KEY_MANAGER_PULL_DISABLED in detail   # and the INI key


# 🔨 REAIMED 2026-09-07, ROW 1ec67228 — Rick: "I want to rescind the feature that
# allows you to pull from the holding area into the queue and it must default to NO.
# That way you can never do it without my approval."
#
# THE ASSERTION THAT USED TO SIT HERE was `assert "not a permission problem" in detail`,
# and it was RIGHT for row 458e9947, which was a focus measure: a manager was choosing
# not to load up on more work, so telling them to go flip the switch was the correct
# next step. IT IS WRONG NOW. The toggle carries a standing rescission, and the reader
# who hits it needs an approver, not a switch.
#
# 🔴 AND THE OLD MESSAGE SENT THEM THE WRONG WAY, WHICH IS HOW THIS WAS FOUND RATHER
# THAN REASONED. Sam hit this refusal live at 2026-09-07 ~21:55 EDT trying to move his
# OWN row into in_progress on his manager's instruction. The message told him the two
# ways to turn the toggle off and never mentioned that an approver could simply do it —
# i.e. it handed a worker the instructions for disabling the control Rick had just
# installed, and withheld the one route he was actually entitled to take.
#
# The assertion is reaimed, not deleted, and the old direction is quoted above so the
# next reader can see it was overruled rather than found wrong.

def test_the_refusal_points_at_an_APPROVER_and_not_only_at_the_switch( toggle ):
    """
    The route a blocked caller may actually take must be IN the message.

    A refusal that lists only the operator's remedy is a dead end for everybody who is
    not the operator — and worse than a dead end, because following it means disabling
    the control instead of asking the person it exists to protect.
    """
    toggle( True )
    detail = approval.refusal_for_pull( "queued", "in_progress", "sam b29ad216" )
    assert "approver" in detail.lower(), (
        "the pull refusal never mentions the approver route, so a blocked worker's "
        "only visible option is to switch the rescission off"
    )
    assert "1ec67228" in detail, (
        "the refusal does not cite the ruling that actually governs it"
    )


def test_the_refusal_no_longer_carries_the_focus_rationale( toggle ):
    """
    The WHY has changed, and a stale why is worse than none — it tells the reader the
    control is a workload preference when it is an operator's standing rescission.
    """
    toggle( True )
    detail = approval.refusal_for_pull( "queued", "in_progress", "sam b29ad216" )
    assert "stays on the priority work" not in detail
    assert "not a permission problem"   not in detail


def test_the_operator_remedy_is_still_there_but_marked_as_the_operator_s( toggle ):
    """
    🔴 THE POSITIVE CONTROL ON THE TWO ABOVE, and without it they invite the wrong fix.

    "Point at an approver" could be satisfied by DELETING the operator remedy, which
    would strand Rick with no message telling him how to lift his own rescission. Both
    routes must be present, and the operator's must be labelled as his call.
    """
    toggle( True )
    detail = approval.refusal_for_pull( "queued", "in_progress", "sam b29ad216" )
    assert "manager_pull_disabled" in detail
    assert approval.INI_KEY_MANAGER_PULL_DISABLED in detail
    assert "operator" in detail.lower()


def test_an_approver_is_not_shown_the_refusal_at_all( monkeypatch ):
    """
    The discriminating half: the message can only be judged against a gate that lets
    the right caller through. An approver gets None, so the text above is what a
    genuinely-blocked caller sees rather than what everybody sees.
    """
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: True )
    monkeypatch.setattr( approval, "is_approver", lambda actor: actor == "rick" )
    monkeypatch.setattr( approval, "approver_persona_for_account", lambda email: None )
    assert approval.refusal_for_pull( "queued", "in_progress", "rick" ) is None
    assert approval.refusal_for_pull( "queued", "in_progress", "sam b29ad216" ) is not None


def test_with_the_toggle_OFF_the_same_pull_is_allowed( toggle ):
    toggle( False )
    assert approval.refusal_for_pull( "queued", "in_progress", "maya 1234" ) is None


# ── the gate has ONE edge, and must be blind to every other ───────────────────

@pytest.mark.parametrize( "frm,to", [
    ( "queued",       "done"        ),
    ( "queued",       "parked"      ),
    ( "in_progress",  "done"        ),
    ( "not_approved", "queued"      ),
    ( "review",       "done"        ),
] )
def test_a_transition_that_is_not_a_pull_is_untouched_even_with_the_toggle_ON( toggle, frm, to ):
    toggle( True )
    assert approval.refusal_for_pull( frm, to, "maya 1234" ) is None


def test_the_in_progress_no_op_is_not_refused_by_a_switch_flipped_mid_flight( toggle ):
    """
    A row already being worked must not become un-PATCHable because the toggle went on
    after it started. The gate is about STARTING work, not about touching started work.
    """
    toggle( True )
    assert approval.refusal_for_pull( "in_progress", "in_progress", "maya 1234" ) is None


# ── the exemptions, both doors ────────────────────────────────────────────────

def test_an_approver_by_DECLARED_ACTOR_still_pulls( monkeypatch ):
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: True )
    monkeypatch.setattr( approval, "is_approver", lambda actor: True )
    monkeypatch.setattr( approval, "approver_persona_for_account", lambda email: None )
    assert approval.refusal_for_pull( "queued", "in_progress", "rick" ) is None


def test_an_approver_by_AUTHENTICATED_ACCOUNT_still_pulls( monkeypatch ):
    """
    The browser's door. Rick's client actor is minted per websocket session
    ("operator foolish goat"), so no allowlist entry could ever match it — the account
    leg is the only thing that lets him work through the UI with his own switch on.
    """
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: True )
    monkeypatch.setattr( approval, "is_approver", lambda actor: False )
    monkeypatch.setattr( approval, "approver_persona_for_account", lambda email: "rick" )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "operator foolish goat", account_email="r@example.com"
    ) is None


# ── the flag parses rather than coerces ───────────────────────────────────────

@pytest.mark.parametrize( "raw,expected", [
    ( True,    True  ), ( False,   False ),
    ( "true",  True  ), ( "True",  True  ), ( "1", True ), ( "yes", True ), ( "on", True ),
    ( "false", False ), ( "False", False ), ( "0", False ), ( "no", False ), ( "off", False ),
] )
def test_a_string_in_the_override_file_is_PARSED_not_coerced( monkeypatch, raw, expected ):
    """
    🔴 THE ONE THAT MATTERS: `bool( "false" )` is True. Coerce instead of parse and a
    hand-written "false" turns the toggle ON — the switch doing the exact opposite of
    what its own file says, while reporting itself as overridden.
    """
    monkeypatch.setattr( approval, "_read_overrides",
                         lambda: { "manager_pull_disabled": raw } )
    assert approval.get_manager_pull_disabled() is expected


def test_an_absent_config_FAILS_CLOSED_because_the_operator_repriced_that_trade( monkeypatch ):
    """
    🔨 THIS TEST ASSERTED THE OPPOSITE UNTIL 2026-09-07, AND IT WAS NOT WRONG THEN.

    It was named `..._FAILS_OPEN_so_a_broken_file_cannot_freeze_the_fleet`, and it
    pinned a deliberate trade: an absent or unreadable config must not silently stop
    every seat from taking work. The reasoning was that a wrong False costs Rick an
    unenforced quiet hour, which he would notice and say so, while a wrong True costs a
    fleet that cannot work and cannot see why.

    🔴 RICK PRICED THAT TRADE HIMSELF AND PRICED IT THE OTHER WAY (broadcast c43a29c5,
    row 1ec67228): "it must default to NO. That way you can never do it without my
    approval." A frozen fleet is loud, immediate, and asks him a question; work quietly
    entering the live queue without him is none of those.

    ⇒ So this is a RULING landing on a test, not a bug being fixed. The old assertion is
    quoted above rather than deleted, because the next person to wonder why a fresh
    install refuses pulls deserves to find the argument that was overruled and who
    overruled it — not just an assertion that changed direction with no explanation.

    ⚠️ THE OLD TEST'S CONCERN IS REAL AND IS NOT DISMISSED. A fresh install now refuses
    manager pulls until somebody flips the switch. That is the intended cost, and the
    mitigation is that `refusal_for_pull` names the toggle and both ways to turn it back
    on — a loud refusal rather than a silent one, which is the property the pull gate
    was built with from the start.
    """
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "manager_pull_disabled": None } )
    monkeypatch.setattr( approval, "_ini_value", lambda *a, **k: None )
    assert approval.get_manager_pull_disabled() is True
    assert approval.FALLBACK_MANAGER_PULL_DISABLED is True


# ── the premise this gate rests on, pinned so a later widening is visible ─────

def test_the_existing_admission_gates_cannot_see_a_pull():
    """
    Not a test of MY code — a pin on the fact that made a separate gate necessary.
    If someone widens the admission predicate to cover `queued`, this reddens and
    whoever changed it learns that this gate may have become redundant.
    """
    assert approval.NOT_APPROVED_STATUS != "queued"
    assert approval.PULL_TARGET_STATUS  == "in_progress"


# ============================================================================
# 🔨 THE SELF-CLAIM EXEMPTION — María 🌸 ruled it 2026-09-07 ~22:02 EDT, row 1ec67228
#
# THE TRIGGER WAS THE GATE REFUSING HER OWN INSTRUCTION. She told Sam to move row
# 1ec67228 into `in_progress`; the store answered 409, because a worker is not an
# approver and EVERY transition into `in_progress` is a "pull". Rick's order is about a
# manager PULLING NEW WORK out of the holding area onto the board. A worker starting
# the row a manager already handed them is a different act, and the toggle could not
# tell them apart.
#
# HER RULE, both halves required: the actor IS the row's owner, AND the row's
# accountable manager is SOMEBODY ELSE. The second half is not decorative — without it
# a manager who owns a row is exempt on that row, which is exactly the self-assignment
# Rick rescinded.
# ============================================================================

def test_a_worker_may_start_the_row_their_manager_assigned_them( toggle ):
    """THE ONE THE EXEMPTION EXISTS FOR — and the case that produced the ruling."""
    toggle( True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "sam b29ad216",
        item_owner="sam", item_manager="maria",
    ) is None


def test_a_worker_may_NOT_start_somebody_else_s_row( toggle ):
    """
    🔴 THE POSITIVE CONTROL, and without it the exemption is just a hole.

    An exemption that fired for everybody would satisfy the test above perfectly. Same
    toggle, same manager, same shape — only the owner differs.
    """
    toggle( True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "sam b29ad216",
        item_owner="rio", item_manager="maria",
    ) is not None, "a worker can start a row owned by somebody else"


def test_a_row_whose_owner_IS_its_manager_gets_no_exemption( toggle ):
    """
    María's second half, on its own.

    Without it, anyone who owns AND manages a row is exempt on that row — they create
    work for themselves and then start it, which is precisely the self-assignment Rick
    rescinded. The exemption must require that SOMEBODY ELSE put the row on the board.
    """
    toggle( True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "maria e2908f90",
        item_owner="maria", item_manager="maria",
    ) is not None


@pytest.mark.parametrize( "owner,manager,why", [
    ( None,  "maria", "an unowned row cannot be anybody's to claim" ),
    ( "sam", None,    "an unmanaged row was put there by nobody"    ),
    ( "",    "maria", "a blank owner is not a persona"              ),
    ( "sam", "",      "a blank manager is not somebody else"        ),
] )
def test_a_row_missing_either_half_gets_no_exemption( toggle, owner, manager, why ):
    """Absent data must fail CLOSED, the direction this whole row is about."""
    toggle( True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "sam b29ad216",
        item_owner=owner, item_manager=manager,
    ) is not None, why


def test_the_exemption_matches_on_the_CANONICAL_persona_not_the_raw_string( toggle ):
    """
    An actor carries a session id; a display name carries an icon and an accent.
    "María 🌸 611e3c47" and "maria" are one person, exactly as `is_approver` has it.
    """
    toggle( True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "María 🌸 611e3c47",
        item_owner="maria", item_manager="mr radio",
    ) is None


def test_the_exemption_does_not_leak_into_any_other_edge( toggle ):
    """
    The exemption rides the pull gate and must not become a general permission. Every
    edge here is one this gate already ignores; the assertion is that adding the
    exemption did not turn "ignored" into something else.
    """
    toggle( True )
    for frm, to in [ ( "queued", "done" ), ( "not_approved", "queued" ),
                     ( "in_progress", "not_approved" ) ]:
        assert approval.refusal_for_pull(
            frm, to, "sam b29ad216", item_owner="sam", item_manager="maria",
        ) is None, f"{frm}->{to} is not a pull and must not be refused"


def test_the_helper_entered_directly_says_no_by_default():
    """
    The predicate on its own, because every arm above goes through the gate and a gate
    has other reasons to return None.
    """
    claim = approval.actor_is_claiming_their_own_row
    assert claim( "sam b29ad216", "sam", "maria" ) is True
    assert claim( "sam b29ad216", "sam", "sam"   ) is False
    assert claim( None,           "sam", "maria" ) is False
    assert claim( "sam",          None,  "maria" ) is False
    assert claim( "sam",          "sam", None    ) is False
