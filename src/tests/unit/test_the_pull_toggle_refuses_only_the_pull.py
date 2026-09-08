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
    # It must not read as a permission problem, because it is not one.
    assert "not a permission problem" in detail


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
