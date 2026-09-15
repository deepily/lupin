#!/usr/bin/env python3
"""
`refusal_for_pledge` — which deletion tickets an admit request may name (row ab8c5728).

One arm per row of the table in src/rnd/2026.09.14-sword-of-damocles-enforcement-plan.md
§3.2, run with the switch on and off where the switch matters. Pure function: no
database, no bridge — the router hands it the facts.
"""
import os
import sys
from types import SimpleNamespace

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.task_request_pledge import refusal_for_pledge

TARGET = "11111111-1111-1111-1111-111111111111"
PLEDGE = "22222222-2222-2222-2222-222222222222"
OTHER  = "33333333-3333-3333-3333-333333333333"


def _row( owner="mr radio", status="queued" ):
    return SimpleNamespace( owner_persona=owner, status=status )


def _ask( move="admit", switch_on=True, pledge_id=PLEDGE, pledge_row="default",
          requester="mr radio", pledged_on=None ):
    return refusal_for_pledge(
        move              = move,
        switch_on         = switch_on,
        target_id         = TARGET,
        pledge_id         = pledge_id,
        pledge_row        = _row() if pledge_row == "default" else pledge_row,
        requester_persona = requester,
        pledged_on        = pledged_on,
    )


# ── the positive arms, so the refusals below mean something ─────────────────

@pytest.mark.parametrize( "switch_on", [ True, False ] )
def test_an_admit_pledging_a_LIVE_row_of_YOUR_OWN_is_accepted( switch_on ):
    assert _ask( switch_on=switch_on ) is None


def test_an_admit_with_NO_pledge_is_accepted_when_the_switch_is_OFF():
    assert _ask( switch_on=False, pledge_id=None, pledge_row=None ) is None


@pytest.mark.parametrize( "switch_on", [ True, False ] )
def test_a_demote_with_NO_pledge_is_accepted_either_way( switch_on ):
    """Q3: demote is exempt."""
    assert _ask( move="demote", switch_on=switch_on, pledge_id=None, pledge_row=None ) is None


def test_the_owner_comparison_is_by_CANONICAL_persona_key():
    """The bridge says "Mr. Radio"; the store holds "mr radio". Same person."""
    assert _ask( requester="Mr. Radio" ) is None


# ── case 1: switch on, admit, no pledge ───────────────────────────────────────

def test_1_an_admit_with_NO_pledge_is_422_when_the_switch_is_ON():
    code, detail = _ask( pledge_id=None, pledge_row=None )
    assert code == 422
    assert "deletion_task_id" in detail
    assert "sword_of_damocles_active" in detail


# ── case 2: a pledge on a demote ─────────────────────────────────────────────

@pytest.mark.parametrize( "switch_on", [ True, False ] )
def test_2_a_pledge_on_a_DEMOTE_is_422_not_ignored( switch_on ):
    code, detail = _ask( move="demote", switch_on=switch_on )
    assert code == 422
    assert "demote" in detail


# ── cases 3–7, with the switch on and off ────────────────────────────────────

@pytest.mark.parametrize( "switch_on", [ True, False ] )
def test_3_a_row_cannot_pledge_ITSELF( switch_on ):
    code, detail = _ask( switch_on=switch_on, pledge_id=TARGET )
    assert code == 422
    assert "itself" in detail


@pytest.mark.parametrize( "switch_on", [ True, False ] )
def test_4_a_pledge_that_does_not_EXIST_is_422_naming_it( switch_on ):
    code, detail = _ask( switch_on=switch_on, pledge_row=None )
    assert code == 422
    assert PLEDGE in detail


@pytest.mark.parametrize( "switch_on", [ True, False ] )
def test_5_a_pledge_owned_by_SOMEONE_ELSE_is_403( switch_on ):
    code, detail = _ask( switch_on=switch_on, pledge_row=_row( owner="maria" ) )
    assert code == 403
    assert "maria" in detail


@pytest.mark.parametrize( "requester", [ None, "", "   " ] )
def test_5a_NO_persona_from_the_bridge_is_403_never_a_fallback( requester ):
    code, detail = _ask( requester=requester )
    assert code == 403
    assert "bridge" in detail


@pytest.mark.parametrize( "status", [ "done", "dropped", "wont_fix" ] )
def test_6_a_FINISHED_pledge_is_409_it_is_a_close_not_a_deletion( status ):
    code, detail = _ask( pledge_row=_row( status=status ) )
    assert code == 409
    assert status in detail


def test_6_a_row_in_the_HOLDING_AREA_is_a_live_pledge():
    assert _ask( pledge_row=_row( status="not_approved" ) ) is None


def test_7_a_pledge_already_named_on_ANOTHER_pending_admit_is_409():
    code, detail = _ask( pledged_on=OTHER )
    assert code == 409
    assert OTHER in detail
