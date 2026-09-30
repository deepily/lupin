"""
The P0 petition relay — it ROUTES a refusal to Rick and GRANTS nothing.

ROW 9c26bf04, filed by María 🌸 after her own probe: she re-ran a P0 create with
`authority="user_direct"`, got an identical 403, and read at source that
`refusal_for_priority_create` does not take `authority` at all. The relay concept
existed in the verb's vocabulary and never reached the function that refuses.

🔴 WHAT THIS FILE IS ACTUALLY GUARDING, and it is not the happy path. Rick closed a
hole on 2026-09-07 (row b8205986): the actor string is caller-supplied, so anyone
could type an operator's name. `authority` is caller-supplied in exactly the same way.
If a later change ever makes it GRANT rather than ROUTE, that hole is reopened — and
the change would look like a small convenience. These tests are what should redden.

⚠️ THE MOST IMPORTANT ASSERTION HERE IS THE ONE ABOUT THE REFUSAL STILL FIRING. A
petition that quietly turned into a permission would pass every "petition works" test
in this file. So each availability test has a sibling proving the door it rides on is
still shut.

Run: PYTHONPATH=src python3 -m pytest src/tests/unit/test_the_p0_petition_routes_and_never_grants.py -v
"""

import pytest

from cosa.rest import task_priority_firewall as firewall
from cosa.rest import task_promotion_resolver as resolver


# ---------------------------------------------------------------------------
# THE PREDICATE — who may petition, and who may not
# ---------------------------------------------------------------------------

def test_a_manager_relaying_the_operator_may_petition():
    assert firewall.petition_is_available( "P0", "user_direct", bridge_role="manager" ) is True


def test_but_the_refusal_it_rides_on_is_still_a_refusal():
    """
    🔴 THE LOAD-BEARING ONE. The petition is a route around nothing — the firewall's
    answer to "may this caller set P0" must still be NO. If this ever passes as None,
    the petition stopped being an escalation and became a permission, and every other
    test in this file would still be green.
    """
    refusal = firewall.refusal_for_priority_create( "P0", bridge_role="manager" )
    assert refusal is not None, "a manager may still NOT create at P0 — the petition escalates, it does not permit"
    assert "reserved to the operator" in refusal


def test_a_worker_gets_no_petition_even_claiming_a_relay():
    """
    Rick's sentence order: "a worker escalates through their manager, who petitions the
    operator." The worker's escalation path is their manager, not this door.
    """
    assert firewall.petition_is_available( "P0", "user_direct", bridge_role="worker" ) is False


def test_a_manager_NOT_claiming_a_relay_gets_the_flat_refusal():
    """
    A manager exercising its OWN judgement is not relaying anybody. Only a caller
    claiming to carry the operator's instruction is escalated.
    """
    assert firewall.petition_is_available( "P0", "standing", bridge_role="manager" ) is False
    assert firewall.petition_is_available( "P0", None,       bridge_role="manager" ) is False


@pytest.mark.parametrize( "wanted", [ "P1", "P2", "P3", "P4", "P5" ] )
def test_only_P0_is_petitionable( wanted ):
    """
    P1-P4 already have a door — a manager sets them directly — so petitioning for one
    would be a second way to do a permitted thing. P5 is the worker floor. A petition
    exists to reach P0 and nothing else.
    """
    assert firewall.petition_is_available( wanted, "user_direct", bridge_role="manager" ) is False


@pytest.mark.parametrize( "junk", [ None, "", "banana", "P9", 7 ] )
def test_an_unreadable_priority_is_not_petitionable( junk ):
    assert firewall.petition_is_available( junk, "user_direct", bridge_role="manager" ) is False


@pytest.mark.parametrize( "sloppy", [ "p0 ", " P0", "p0", "  p0  " ] )
def test_a_sloppily_spelled_P0_still_petitions( sloppy ):
    """
    🔴 THIS TEST CAUGHT ME WRITING THE WRONG ASSERTION. I first listed "p0 " as junk.
    It is not — `normalize_priority` trims and upcases, so "p0 " IS P0, and the
    petition SHOULD be available for it.

    Which is the behaviour that matters: the value arrives from a hand-typed MCP call,
    and refusing a petition over a trailing space would send Rick's own instruction to
    a 403 on a whitespace technicality. Pinned so a later "tightening" of the matcher
    has to argue with a named test rather than silently narrow it.
    """
    assert firewall.petition_is_available( sloppy, "user_direct", bridge_role="manager" ) is True


def test_the_operator_never_petitions_because_he_is_never_refused( monkeypatch ):
    """
    A petition from Rick's own account would be a second path to a thing rule 1 already
    permits. Two ways to do one thing is how the two drift.
    """
    monkeypatch.setattr( firewall, "caller_is_operator", lambda email: True )
    assert firewall.petition_is_available( "P0", "user_direct", bridge_role="manager",
                                           account_email="rick@example.com" ) is False


def test_the_petitionable_authority_is_the_one_the_verb_already_speaks():
    """
    `task_create` has always accepted authority in {standing, user_direct, manager_relay}.
    Routing on a value the vocabulary already carries is what makes this a wiring change
    rather than a new concept — and it is the exact string María's probe sent.
    """
    assert firewall.PETITIONABLE_AUTHORITY == "user_direct"


# ---------------------------------------------------------------------------
# THE INTENT — what the ticket carries, and what it must NOT
# ---------------------------------------------------------------------------

def _intent( **over ):
    base = dict( to_status="queued", actor="mr radio 81381447", recorded_actor="mr radio 81381447",
                 authority="user_direct", receipt_refs=None, blocked_by=None, reason=None,
                 park_reason=None, next_chase_ts=None, title="a row", session_id="81381447" )
    base.update( over )
    return resolver.TransitionIntent( **base )


def test_an_ordinary_admission_carries_no_priority():
    """The field exists for petitions only; every existing mint site is unaffected."""
    assert _intent( authority="standing" ).priority is None


def test_a_petition_round_trips_its_priority():
    i = _intent( priority="P0" )
    assert resolver.TransitionIntent.from_payload( i.as_payload() ) == i


def test_a_payload_written_before_this_field_existed_still_reads():
    """
    The ticket is written in one process and read in another, minutes or a restart
    apart. A ticket minted by the old code must not explode in the new resolver.
    """
    assert resolver.TransitionIntent.from_payload( { "to_status": "queued" } ).priority is None


def test_the_persisted_payload_carries_no_authorization_decision():
    """
    🔴 THE b8205986 REGRESSION GUARD, and the reason this file exists at all.

    `TransitionIntent`'s own docstring states the rule: "Persisting a resolved
    authorization decision and replaying it later makes it forgeable by anyone who can
    write this JSON." The petition must carry the REQUEST and never the ANSWER — Rick's
    approval is read from his actual keypress at resolve time, never from this dict.

    ⚠️ ASSERTED AS AN ABSENCE OVER THE WHOLE KEY SET, not against a list of three
    field names I happened to think of. A future field called `operator_ok` would slip
    past a named-field check and is exactly what this must catch.
    """
    keys = set( _intent( priority="P0" ).as_payload().keys() )
    forbidden = { k for k in keys
                  if any( t in k.lower() for t in ( "approv", "allow", "grant", "operator", "rick", "permit" ) ) }
    assert forbidden == set(), (
        f"the ticket payload carries {forbidden}, which reads as a persisted authorization "
        "decision — replaying one is forgeable by anyone who can write this JSON (b8205986)"
    )


def test_the_payload_is_json_safe():
    """It lands in a JSONB column; a datetime that never serialized would fail at write."""
    import json
    json.dumps( _intent( priority="P0" ).as_payload() )
