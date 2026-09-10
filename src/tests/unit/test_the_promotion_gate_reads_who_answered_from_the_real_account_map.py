"""
Row e20e249a — the promotion gate decides WHO answered through the REAL account map.

WHY THIS FILE EXISTS BESIDE THE REPAIRED ONES. The files repaired at the checkpoint answer the
gate's ask as `OPERATOR_ANSWER` and monkeypatch `approver_persona_for_account` to map that login
to the operator. That proves the gate CONSULTS a lookup. It cannot prove the lookup the gate
actually calls maps a login to an ask-exempt persona, because the test supplied the answer the
lookup gives. Here nothing in the gate is patched: the real `task_approval_settings` reader runs
over an override file in tmp_path, and the operator is whoever that file maps to
`ASK_EXEMPT_PERSONAS`. No persona name is written into an assertion.

The first test is the positive control. Every refusal below would also pass against a map that
resolves nothing, so the control shows the map resolves the operator AND a second approver
before any arm relies on either.

Venue: :7999 — in-process, the override file lives in tmp_path, and no ask leaves the process
(`ask_fn` is injected, or `notify_user_sync` is replaced at the module `_default_ask` imports from).
"""

import json

import pytest

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as gate


OPERATOR_EMAIL = "operator.login@example.com"
MANAGER_EMAIL  = "manager.login@example.com"
TASK_ID        = "t-e20e249a"

OPERATOR_JWT = { "user_id": "operator-uid", "account_email": OPERATOR_EMAIL, "method": "jwt" }
MANAGER_JWT  = { "user_id": "manager-uid",  "account_email": MANAGER_EMAIL,  "method": "jwt" }
# An API-key caller carrying the operator's email is the sharpest API-key case: the email would
# map, so only the method can refuse it.
API_KEY_CALL = { "user_id": "service-uid",  "account_email": OPERATOR_EMAIL, "method": "api_key" }


@pytest.fixture( autouse=True )
def real_account_map( tmp_path, monkeypatch ):
    """
    Point the approval settings at an override file in tmp_path that maps two logins.

    Ensures:
        - OPERATOR_EMAIL maps to the first ask-exempt persona, MANAGER_EMAIL to "maria"
        - "maria" is an approver, so the manager's mapping survives the allowlist check
        - the module's mtime cache is cleared, so no other test's file is served from cache
        - the gate's lookup is left exactly as shipped
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", {
        "approvers": None, "enforcement_active": None,
        "default_to_holding": None, "approver_accounts": None,
    } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( {
        "approvers"         : [ "maria" ],
        "approver_accounts" : {
            OPERATOR_EMAIL : gate.ASK_EXEMPT_PERSONAS[ 0 ],
            MANAGER_EMAIL  : "maria",
        },
    } ) )
    return target


def _ask_answering( answer, answered_by, default_used=False ):
    """An injected ask that returns one AskOutcome and records that it was called."""
    calls = [ ]

    def ask_fn( **kwargs ):
        calls.append( kwargs )
        return gate.AskOutcome( answer=answer, default_used=default_used, answered_by=answered_by )

    ask_fn.calls = calls
    return ask_fn


def _decide( ask_fn ):
    return gate.approval_from_the_ask( "sid", "maria 4f98d12f", TASK_ID, "a row", ask_fn=ask_fn )


def test_the_real_map_resolves_the_operator_and_a_second_approver():
    assert gate.approver_persona_for_account is approval.approver_persona_for_account, \
        "the gate's lookup is patched, so nothing in this file tests the real map"
    assert gate.approver_persona_for_account( OPERATOR_EMAIL ) in gate.ASK_EXEMPT_PERSONAS
    assert gate.approver_persona_for_account( MANAGER_EMAIL ) == "maria"
    assert "maria" not in gate.ASK_EXEMPT_PERSONAS


def test_the_operators_own_login_saying_yes_is_a_keypress():
    ask_fn   = _ask_answering( "yes", OPERATOR_JWT )
    decision = _decide( ask_fn )

    assert len( ask_fn.calls ) == 1
    assert decision.allowed
    assert decision.approval_source == gate.APPROVAL_KEYPRESS


def test_an_api_key_yes_is_refused_and_names_the_api_key_caller():
    decision = _decide( _ask_answering( "yes", API_KEY_CALL ) )

    assert not decision.allowed
    assert "an API-key caller (user service-uid)" in decision.refusal
    assert "not by the operator's own login" in decision.refusal


def test_another_approvers_login_saying_yes_is_refused_and_named():
    decision = _decide( _ask_answering( "yes", MANAGER_JWT ) )

    assert not decision.allowed
    assert f"the login {MANAGER_EMAIL}" in decision.refusal
    assert "not by the operator's own login" in decision.refusal


def test_a_yes_the_server_recorded_nobody_posting_is_refused():
    decision = _decide( _ask_answering( "yes", None ) )

    assert not decision.allowed
    assert "nobody the server recorded" in decision.refusal


def test_a_no_from_someone_else_is_refused_as_theirs_never_as_ricks():
    decision = _decide( _ask_answering( "no", MANAGER_JWT ) )

    assert not decision.allowed
    assert f"the login {MANAGER_EMAIL}" in decision.refusal
    assert "Rick answered no" not in decision.refusal


def test_a_timed_out_default_keeps_its_own_timeout_refusal():
    decision = _decide( _ask_answering( "no", None, default_used=True ) )

    assert not decision.allowed
    assert "timed out with no answer" in decision.refusal
    assert "not by the operator's own login" not in decision.refusal


class _Resp:
    """The attributes `_default_ask` reads off a NotificationResponse."""

    def __init__( self, value, answered_by ):
        self.response_value = value
        self.default_used   = False
        self.exit_code      = 0
        self.status         = "responded"
        self.answered_by    = answered_by


def _notify_answering( monkeypatch, value, answered_by ):
    seen = { }

    def fake_notify_user_sync( request, **kwargs ):
        seen[ "request" ] = request
        return _Resp( value, answered_by )

    monkeypatch.setattr( "lupin_cli.notifications.notify_user_sync.notify_user_sync", fake_notify_user_sync )
    return seen


def test_the_default_ask_hands_the_gate_the_very_stamp_it_received( monkeypatch ):
    stamp = dict( OPERATOR_JWT )
    seen  = _notify_answering( monkeypatch, "yes", stamp )

    outcome = gate._default_ask( **gate.promotion_ask_kwargs( "maria 4f98d12f", TASK_ID, "a row", "sid" ) )

    assert "request" in seen
    assert outcome.answered_by is stamp


def test_the_default_path_end_to_end_allows_the_operator_and_refuses_a_manager( monkeypatch ):
    _notify_answering( monkeypatch, "yes", OPERATOR_JWT )
    allowed = gate.approval_for_promotion( session_id="sid", actor="maria 4f98d12f", task_id=TASK_ID,
                                           title="a row", is_manager_fn=lambda s: True )

    _notify_answering( monkeypatch, "yes", MANAGER_JWT )
    refused = gate.approval_for_promotion( session_id="sid", actor="maria 4f98d12f", task_id=TASK_ID,
                                           title="a row", is_manager_fn=lambda s: True )

    assert allowed.allowed and allowed.approval_source == gate.APPROVAL_KEYPRESS
    assert not refused.allowed
    assert f"the login {MANAGER_EMAIL}" in refused.refusal
