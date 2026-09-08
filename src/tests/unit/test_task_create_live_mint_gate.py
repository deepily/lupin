"""
THE CREATE DOOR — Rick's P0, row 0ef62dfd, 2026-09-08.

WHAT WENT WRONG. The holding-area default was applied only when a caller OMITTED
`status`. Naming `status="queued"` won, by design, with a comment at the call site
explaining why that was correct. Three of María's rows reached Rick's live board
having never entered holding — so there was no request for him to allow or deny.
A gate that is never consulted is worse than one that says yes: a denial at least
leaves an audit event.

WHAT THESE TESTS ARE FOR. The refusal, its FOUR exemptions, and — the one that
matters most — proof that the router still calls it. A gate can be perfectly
implemented and imported by nobody, and every predicate test here would still pass.
"""
import os, sys

import pytest

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )

from cosa.rest import task_approval_settings as approval
from cosa.rest.task_store_rules import NOT_APPROVED_STATUS


@pytest.fixture
def holding_on( monkeypatch ):
    """The gate is only a gate when the holding default is ON. Pin it, don't hope."""
    monkeypatch.setattr( approval, "default_mint_status", lambda: NOT_APPROVED_STATUS )


# ── THE REFUSAL ───────────────────────────────────────────────────────────────

def test_an_explicit_QUEUED_mint_is_REFUSED( holding_on ):
    """The exact call María made three times, now refused."""
    refusal = approval.refusal_for_live_mint( "queued", True, "P5" )
    assert refusal is not None
    assert "holding area" in refusal


def test_the_refusal_NAMES_THE_WAY_OUT_rather_than_just_saying_no( holding_on ):
    """
    A refusal that does not say what to do instead gets worked around, which is
    how this defect happened in the first place.
    """
    refusal = approval.refusal_for_live_mint( "queued", True, "P5" )
    assert "OMIT" in refusal
    assert NOT_APPROVED_STATUS in refusal
    assert str( "P5" ) in refusal, "the refusal should quote the priority it judged"


def test_an_explicit_BLOCKED_mint_is_ALSO_refused( holding_on ):
    """
    🔴 FLAGGED FOR RICK, NOT DECIDED BY ME. His 2026-07-20 ruling lets a manager
    mint status="blocked" in one call. His 2026-09-08 ruling refuses a live status
    on create except for P0. A blocked row IS on the live board, so it bypasses
    holding exactly as a queued one does — this test encodes the literal reading of
    the newer ruling. If that costs a feature he wants, this test is where it
    surfaces, by name, instead of in a silent behaviour change.
    """
    assert approval.refusal_for_live_mint( "blocked", True, "P5" ) is not None


# ── THE FOUR EXEMPTIONS — each is a POSITIVE CONTROL ─────────────────────────
#
# Without these the suite would pass against a predicate that refused EVERYTHING,
# which would break every create in the fleet.

def test_an_OMITTED_status_is_NOT_refused( holding_on ):
    """The ordinary path. The default already routes it to holding; refusing here
    would break every well-behaved caller in the fleet."""
    assert approval.refusal_for_live_mint( "queued", False, "P5" ) is None


def test_a_P0_MAY_mint_live_because_Rick_said_so( holding_on ):
    """His carve-out, quoted: 'refuse a live status on create except in the case of
    P0 tickets.' He sets P0 himself, so a live P0 claims an instruction he can check."""
    assert approval.refusal_for_live_mint( "queued", True, "P0" ) is None


@pytest.mark.parametrize( "spelling", [ "P0", "p0", " P0 " ] )
def test_the_P0_carve_out_is_not_defeated_by_spelling( holding_on, spelling ):
    assert approval.refusal_for_live_mint( "queued", True, spelling ) is None


def test_asking_explicitly_for_HOLDING_is_not_a_bypass( holding_on ):
    """Naming the status the gate would have given you is not walking around it."""
    assert approval.refusal_for_live_mint( NOT_APPROVED_STATUS, True, "P5" ) is None


def test_with_the_holding_default_OFF_nothing_is_refused( monkeypatch ):
    """
    🔴 THE DEPLOYMENT CONTROL. Where the holding area is switched off there is
    nothing to bypass, and refusing there would break callers who never had a gate.
    """
    monkeypatch.setattr( approval, "default_mint_status", lambda: "queued" )
    assert approval.refusal_for_live_mint( "queued",  True, "P5" ) is None
    assert approval.refusal_for_live_mint( "blocked", True, "P5" ) is None


# ── SOURCE-SHAPE CHECKS — and an honest label, because the first version lied ──
#
# 🔴 THESE TWO USED TO BE CALLED "THE WIRING TESTS" AND THEY WERE A FALSE GREEN.
# They read the router's source with `inspect.getsource` and looked for the call
# name. Unwiring the gate with `if False:` leaves that text exactly where it was,
# so all twelve tests in this file stayed green against a door that no longer
# refused anything. The mutation arm caught it; nothing else in the suite would
# have, and I had written this file specifically to prove the gate worked.
#
# ⇒ A TEST THAT READS SOURCE TEXT CANNOT TELL A CALL FROM A CALL THAT NEVER FIRES.
# Renamed to say what they actually check. The real proof that the gate FIRES is
# in test_tasks_router.py, which drives the door through the real client:
#
#     test_create_with_an_EXPLICIT_queued_status_is_REFUSED_at_the_door   <- the kill
#     test_a_P0_MAY_still_mint_live_at_the_door                           <- control
#     test_a_create_that_NAMES_NO_status_is_untouched_by_the_gate         <- control
#     test_with_the_holding_default_OFF_..._is_NOT_refused                <- control
#
# Mutation arm, measured: unwiring the refusal reddens exactly the first of those
# and leaves the three controls green.


def test_the_router_holds_THIS_module_and_names_the_predicate():
    """
    Cheap import-level check: the router imports this module and mentions the
    predicate. ⚠️ It does NOT prove the call executes — see the note above.
    """
    import inspect

    import cosa.rest.routers.tasks as tasks_router

    assert tasks_router.approval is approval
    assert "refusal_for_live_mint" in inspect.getsource( tasks_router )


def test_the_call_site_reads_the_PAYLOAD_and_not_the_substituted_value():
    """
    A source-shape check with real value, and it is worth keeping even though it
    cannot fail on an unwired gate: passing `mint_status` would make an OMITTED
    status look explicit exactly where the holding default is on, and every
    ordinary create in the fleet would start failing. The door test
    `test_a_create_that_NAMES_NO_status_is_untouched_by_the_gate` is what actually
    catches that at runtime; this names the cause when it happens.
    """
    import inspect

    import cosa.rest.routers.tasks as tasks_router

    call = inspect.getsource( tasks_router ).split( "refusal_for_live_mint(", 1 )[ 1 ].split( ")", 1 )[ 0 ]
    assert "payload.status"   in call, "must judge what the caller ASKED for"
    assert "model_fields_set" in call, "must separate an omitted status from an explicit one"
    assert "mint_status"  not in call, "must NOT read the post-substitution value"
