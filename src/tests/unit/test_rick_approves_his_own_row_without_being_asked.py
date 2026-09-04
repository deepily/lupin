#!/usr/bin/env python3
"""
SHAPE (b): RICK PASSES DOOR 2 BY ACCOUNT, AND IS NOT ASKED ABOUT HIS OWN CLICK.

Rick's ruling, 2026-09-04, row 998c7529 — the second half of the P0 (9d3a975e). Door 1
(the approver allowlist) was opened by the account map. He was then refused by door 2:

    'operator foolish goat' is not a manager — promoting a row out of the holding area
    is manager-only (credential: manager-figure; no session id reached the gate, so
    nothing could be resolved).

A BROWSER HAS NO SESSION BRIDGE. `is_manager_figure` reads one, so Rick — the human the
bridges belong to — is not a manager-figure at all. Opening that door by account then
runs straight into the ask, which `human_only=True` sends to Rick: he would be asked to
bless the click he had just made. His ruling was to skip it.

🔴 THE FAILURE MODE THIS FILE EXISTS TO CATCH IS NOT "Rick is refused". It is
**"the skip extends to everyone"** — María's words, and the reason `ASK_EXEMPT_PERSONAS`
is a separate list from every approver list. A manager mapped to a login account is still
a manager and MUST still send the question. `test_a_manager_with_an_account_is_STILL_asked`
is the arm that says so, and it is the one to look at first if this file ever goes green
while the feature is wrong.

⚠️ WHAT THIS FILE DOES NOT COVER. It says nothing about door 1 (guarded in
`test_task_approval_gate.py` and `test_the_browser_actor_satisfies_the_approver_gate.py`)
and nothing about NO MANAGER BATCHES, which is a separate ruling and a separate surface.
"""
import os
import sys
from dataclasses import dataclass

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_promotion_gate as gate


@dataclass
class Outcome:
    """The AskOutcome shape the gate reads: an answer plus whether it was defaulted."""
    answer       : str  = "yes"
    default_used : bool = False


@pytest.fixture
def asks():
    """Every ask fired during a test. An EMPTY list is the assertion for Rick's path."""
    return [ ]


@pytest.fixture
def spy_ask( asks ):
    def _ask( **kwargs ):
        asks.append( kwargs.get( "question" ) )
        return Outcome()
    return _ask


def _promote( spy_ask, account_persona=None, is_manager=False, actor="operator foolish goat" ):
    return gate.approval_for_promotion(
        session_id      = "",                       # a browser resolves none — the whole point
        actor           = actor,
        task_id         = "row-1",
        title           = "a row waiting in the holding area",
        is_manager_fn   = lambda _sid: is_manager,
        ask_fn          = spy_ask,
        account_persona = account_persona,
    )


def test_rick_passes_door_2_from_a_browser_with_no_session_id( spy_ask, asks ):
    """
    🔴 HALF ONE OF THE RULING. Before this, an authenticated Rick with no session bridge
    was refused here even after door 1 admitted him.
    """
    result = _promote( spy_ask, account_persona="rick" )
    assert result.allowed, (
        f"Rick is still refused by the promotion gate from a browser — the second half "
        f"of the P0 is not fixed. Refusal: {result.refusal}"
    )


def test_rick_is_NOT_asked_about_his_own_promotion( spy_ask, asks ):
    """
    🔴 HALF TWO, AND THE ONE A NAIVE FIX MISSES. Opening door 2 without this leaves the
    gate asking Rick to approve the click he just made — `human_only=True`, so nothing
    else can answer it and he is simply stuck with a prompt about his own action.
    """
    _promote( spy_ask, account_persona="rick" )
    assert asks == [ ], f"an ask was fired at Rick about his own promotion: {asks!r}"


def test_the_row_records_that_no_ask_was_fired( spy_ask ):
    """
    ATTRIBUTION. "keypress" means Rick answered a question. He was never asked one here,
    and this gate's own history says the thing it must never do is put his name on a
    decision he did not make — so the source has its own word and its own wording.
    """
    result = _promote( spy_ask, account_persona="rick" )
    assert result.approval_source == gate.APPROVAL_SELF
    assert result.authority_suffix() == "rick-approved (his own promotion, no ask fired)"
    assert "keypress" not in result.authority_suffix()


@pytest.mark.parametrize( "persona", [ "maria", "cheech", "mr radio" ] )
def test_a_manager_with_an_account_is_STILL_asked( spy_ask, asks, persona ):
    """
    🔴 THE DISCRIMINATOR, AND MARÍA'S NAMED FAILURE MODE: "the skip must not extend to
    everyone." Without this arm, `if account_persona is not None: skip the ask` passes
    every test above while silently removing Rick from every promotion decision on the
    fleet — the gate deleted rather than fixed.
    """
    result = _promote( spy_ask, account_persona=persona )
    assert result.allowed, f"a manager account was refused promotion: {result.refusal}"
    assert len( asks ) == 1, (
        f"a manager ({persona}) mapped to a login account was NOT asked. The ask-skip has "
        f"leaked beyond Rick, which removes him from promotions he is supposed to rule on."
    )
    assert result.approval_source != gate.APPROVAL_SELF


def test_the_ask_exempt_list_is_not_any_approver_list( ):
    """
    WHY THE LISTS ARE SEPARATE OBJECTS. "Who may approve" and "who IS the human the ask
    would reach" are different questions that agree today by coincidence. Aliasing them
    means the day anyone is added to an approver list they silently stop being asked —
    which is the failure mode above, arriving through a config edit instead of a code one.
    """
    from cosa.rest import task_approval_settings as approval
    assert gate.ASK_EXEMPT_PERSONAS == ( "rick", )
    assert gate.ASK_EXEMPT_PERSONAS is not approval.UNCONDITIONAL_APPROVERS


def test_a_caller_with_no_account_is_unchanged( spy_ask, asks ):
    """REGRESSION. A non-manager with no login account is still refused, and still silently."""
    result = _promote( spy_ask, account_persona=None, is_manager=False )
    assert not result.allowed
    assert "is not a manager" in result.refusal
    assert asks == [ ], "a refused caller must never cost Rick an interruption"


def test_a_real_manager_figure_is_unchanged( spy_ask, asks ):
    """REGRESSION. The bridge-resolved manager path still works and still asks."""
    result = _promote( spy_ask, account_persona=None, is_manager=True )
    assert result.allowed
    assert len( asks ) == 1
    assert result.authority_suffix() == "rick-approved (keypress)"


def test_an_absent_rick_still_auto_approves_for_a_manager( ):
    """
    REGRESSION on Rick's OTHER standing ruling, re-confirmed 2026-09-04: an absent Rick
    must not become a blocker. A timed-out default still allows, and still records that
    it was a default rather than a keypress.
    """
    result = gate.approval_for_promotion(
        session_id="", actor="a manager", task_id="row-1", title="t",
        is_manager_fn=lambda _s: True,
        ask_fn=lambda **_k: Outcome( answer="yes", default_used=True ),
    )
    assert result.allowed
    assert result.approval_source == gate.APPROVAL_DEFAULT
    assert "timed-out default" in result.authority_suffix()


def test_ricks_no_still_vetoes( ):
    """REGRESSION. Skipping the ask for Rick must not weaken the veto for anyone else."""
    result = gate.approval_for_promotion(
        session_id="", actor="a manager", task_id="row-1", title="t",
        is_manager_fn=lambda _s: True,
        ask_fn=lambda **_k: Outcome( answer="no", default_used=False ),
    )
    assert not result.allowed
    assert "answered no" in result.refusal
