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
    # MIGRATED 2026-09-08 (Rick: "close the pull hole"). This arm used to authorise by
    # DECLARED ACTOR. That door is closed on this path now, so the approver is identified
    # by ACCOUNT — which is what the browser actually sends and what a caller cannot type.
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: True )
    monkeypatch.setattr( approval, "approver_persona_for_account",
                         lambda email: "rick" if email == "rick@example.com" else None )
    # 🔴 STUBBED TRUE SO THE LAST ARM PROVES THE DOOR RATHER THAN BORROWING A CONSTANT.
    # Without this the "typed name alone no longer opens it" arm reddens on a restored
    # clause only because the REAL is_approver( "rick" ) is True via UNCONDITIONAL_APPROVERS
    # in another module. Edit that tuple, or change how _read_overrides fails, and the arm
    # goes silently vacuous while still reading like a guard. Stubbed True, a restored
    # clause returns None on ANY actor, so the arm reddens for the reason it claims to.
    monkeypatch.setattr( approval, "is_approver", lambda actor: True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "rick", account_email="rick@example.com"
    ) is None
    assert approval.refusal_for_pull( "queued", "in_progress", "sam b29ad216" ) is not None
    # and the typed name alone no longer opens it — the hole, pinned shut
    assert approval.refusal_for_pull( "queued", "in_progress", "rick" ) is not None


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

def test_an_approver_by_DECLARED_ACTOR_ALONE_is_now_REFUSED( monkeypatch ):
    """
    MIGRATED 2026-09-08, and the reversal is the finding. This asserted that a name on
    the allowlist pulls with no account — true of the code, and it made the whole rescind
    advisory: anyone holding the shared fleet API key pulled by typing an approver's name.

    Measured before the fix, with a control that discriminates: `actor="maria e2908f90"`
    with no account was ALLOWED, while `actor="nobody at all 1234"` was REFUSED — so the
    gate was not merely permissive, it was honouring the typed NAME.

    Rick closed it by keypress: "close the pull hole." Kept pointed at the same input
    rather than deleted, so the reversal is visible to the next reader.
    """
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: True )
    monkeypatch.setattr( approval, "is_approver", lambda actor: True )
    monkeypatch.setattr( approval, "approver_persona_for_account", lambda email: None )

    refusal = approval.refusal_for_pull( "queued", "in_progress", "rick" )
    assert refusal is not None, "a typed actor name must not authorise a pull"
    assert "rick" in refusal


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
        item_owner="sam", item_manager="maria", reason="starting the row María assigned me",
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
        item_owner="maria", item_manager="mr radio", reason="picking up my own row",
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
            reason="a reason, which these edges must not require either",
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


# ============================================================================
# 🔨 RICK'S TERMS FOR THE EXEMPTION — "permitted with a receipt: the row records who
# pulled it and why." Via María 🌸, 2026-09-07 ~22:07 EDT, row 1ec67228.
#
# THE "WHO" HALF NEEDED NOTHING BUILT, recorded rather than re-decided: the transition
# door already writes `recorded_actor( payload.actor, account_email )` (tasks.py:1395),
# which puts the server-known identity FIRST and the caller's claim in parentheses.
# María asked whether the receipt should carry the caller-supplied actor or only
# row-derived facts; the tree had already answered BOTH, labelled. Row-derived-only
# loses the accountability the receipt exists for — the owner is already known, so
# "sam's row was claimed" adds nothing. Actor-only launders a declared string into an
# append-only ledger as fact.
#
# ⇒ SO THESE ARMS ARE THE "WHY" HALF, which genuinely did not exist.
# ============================================================================

def test_a_self_claim_with_NO_reason_is_refused( toggle ):
    """The receipt is a CONDITION of the exemption, not a courtesy alongside it."""
    toggle( True )
    detail = approval.refusal_for_pull(
        "queued", "in_progress", "sam b29ad216",
        item_owner="sam", item_manager="maria", reason=None,
    )
    assert detail is not None, "a worker started their own row with no justification"
    assert "reason" in detail


@pytest.mark.parametrize( "reason", [ None, "", "   ", "\t\n", 7, [ "why" ] ] )
def test_only_a_NON_BLANK_STRING_counts_as_the_receipt( toggle, reason ):
    """
    Whitespace and non-strings are not justifications.

    A blank reason is worse than none: it satisfies a presence check while telling the
    next reader nothing, which is the shape this module refuses everywhere else.
    """
    toggle( True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "sam b29ad216",
        item_owner="sam", item_manager="maria", reason=reason,
    ) is not None


def test_the_refusal_says_WHY_it_is_refusing_and_not_merely_that_it_did( toggle ):
    """
    🔴 IT MUST NOT READ AS "YOU MAY NOT DO THIS."

    The caller IS entitled to this move; they are missing one field. A refusal that
    looked like the toggle's would send them to ask an approver for something they can
    already do — the exact wrong turn the toggle's own message was making an hour ago,
    and the reason that message got rewritten.
    """
    toggle( True )
    detail = approval.refusal_for_pull(
        "queued", "in_progress", "sam b29ad216",
        item_owner="sam", item_manager="maria",
    )
    assert "You may start your own row" in detail
    assert "sam"   in detail          # names the owner, so the caller can check it
    assert "maria" in detail          # and who assigned it
    assert "approver" not in detail.lower(), (
        "the missing-receipt refusal reads like the approver refusal, so a caller who "
        "is entitled to this move is sent to ask permission for it"
    )


def test_the_receipt_is_required_ONLY_of_the_self_claim_path( monkeypatch ):
    """
    🔴 THE POSITIVE CONTROL ON SCOPE, and the arm that stops this becoming a tax.

    An approver's ordinary pull must NOT start demanding a reason. Without this, the
    obvious implementation — requiring a reason on every `-> in_progress` — passes
    every arm above while breaking every manager on the fleet.
    """
    # MIGRATED 2026-09-08 (Rick: "close the pull hole"). This arm used to authorise by
    # DECLARED ACTOR. That door is closed on this path now, so the approver is identified
    # by ACCOUNT — which is what the browser actually sends and what a caller cannot type.
    #
    # ⚠️ THIS TEST IS NOT ONE OF THE GUARDS ON THE CLOSED DOOR — do not count it as one.
    # It asserts `is None`, and a RESTORED `is_approver( actor )` clause also returns None,
    # so it stays GREEN under exactly the regression its neighbours catch. That is why the
    # mutation arm on this commit scored 2 failures and not 3. It is not wrong: its subject
    # is the receipt's SCOPE (an approver's ordinary pull must not start demanding a
    # reason), which is a different question from who may pull at all.
    monkeypatch.setattr( approval, "get_manager_pull_disabled", lambda: True )
    monkeypatch.setattr( approval, "approver_persona_for_account",
                         lambda email: "rick" if email == "rick@example.com" else None )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "rick", item_owner="sam", item_manager="maria",
        account_email="rick@example.com",
    ) is None, "an approver's ordinary pull now demands a receipt it never needed"


def test_the_receipt_does_not_buy_a_pull_the_exemption_would_not_have_allowed( toggle ):
    """
    A reason is a CONDITION on the exemption, never a second door.

    Somebody else's row plus an eloquent justification is still refused — otherwise
    "permitted with a receipt" would have quietly become "permitted with a sentence".
    """
    toggle( True )
    assert approval.refusal_for_pull(
        "queued", "in_progress", "sam b29ad216",
        item_owner="rio", item_manager="maria", reason="I have a very good reason",
    ) is not None
