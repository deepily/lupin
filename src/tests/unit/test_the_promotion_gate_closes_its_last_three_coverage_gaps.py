"""
Row 966b46ba — the three paths in task_promotion_gate.py that no test ever took.

Measured by Tiberius 👑, 2026-09-16, at 795ce914, over the 31 test files that name the module:
418 passed, 129 stmts, 1 miss, 46 branches, 3 partial → 98%. Missing `141->exit`, `272->exit`,
`755`. Each test below closes one of them, and each asserts the BEHAVIOUR of the path rather than
merely running it:

- `get_asynchronous_enabled` with the INI key ABSENT returns the fail-closed fallback.
- `reason_with_suffix` on a REFUSED approval returns the operator's reason unchanged (272). The
  blessed-with-no-reason arm (273) was already reached; it is pinned here too, since nothing
  asserted its value.
- `_default_ask` RAISES when the notification system never answered, and the gate turns that
  raise into a refusal that names it — never Rick's keypress.

Venue: :7999 — in-process; `notify_user_sync` is replaced at the module `_default_ask` imports
from, so no ask leaves the process.
"""

import pytest

from cosa.rest import task_promotion_gate as gate


TASK_ID = "t-966b46ba"


# ---------------------------------------------------------------------------------------------
# 141->exit — the INI key is absent
# ---------------------------------------------------------------------------------------------

def test_an_absent_asynchronous_key_fails_closed_to_the_named_fallback( monkeypatch ):
    """
    The key is absent, so `_ini_value` hands back the caller's fallback of None.

    ⚠️ Deleting the `if raw is None` line would be an EQUIVALENT mutant for the False
    answer alone — `str( None ).lower()` is "none", which is not in the truthy set either.
    So the fallback is also flipped to True: only the guard line can return it.
    """
    seen = [ ]
    def _absent( key, return_type, fallback ):
        seen.append( ( key, fallback ) )
        return fallback
    monkeypatch.setattr( gate, "_ini_value", _absent )

    assert gate.get_asynchronous_enabled() is False
    assert seen == [ ( gate.INI_KEY_ASYNCHRONOUS, None ) ]

    monkeypatch.setattr( gate, "FALLBACK_ASYNCHRONOUS", True )
    assert gate.get_asynchronous_enabled() is True


# ---------------------------------------------------------------------------------------------
# 272->exit — a refused approval; and the blessed-with-no-reason arm beside it
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize( "caller_reason", [ None, "" ] )
def test_a_blessed_promotion_with_no_operator_reason_records_the_note_alone( caller_reason ):
    decision = gate.PromotionApproval( allowed=True, approval_source=gate.APPROVAL_KEYPRESS )

    reason = decision.reason_with_suffix( caller_reason )

    assert reason == "rick-approved (keypress)"


@pytest.mark.parametrize( "caller_reason", [ "ship it", None ] )
def test_a_refused_promotion_hands_back_the_operator_reason_unchanged( caller_reason ):
    """
    Nothing was blessed, so `authority_suffix` is empty and the operator's words stand alone —
    no trailing separator on a refusal, and no note invented for a promotion that did not happen.
    """
    decision = gate.PromotionApproval( allowed=False, refusal="Rick said no" )

    assert decision.reason_with_suffix( caller_reason ) is caller_reason


def test_the_operator_reason_still_comes_first_when_both_are_present():
    """Positive control: the join arm is live, so the note-alone arm is not the only one."""
    decision = gate.PromotionApproval( allowed=True, approval_source=gate.APPROVAL_KEYPRESS )

    assert decision.reason_with_suffix( "ship it" ) == "ship it · rick-approved (keypress)"


# ---------------------------------------------------------------------------------------------
# 755 — the notification system never answered
# ---------------------------------------------------------------------------------------------

class _Resp:
    """The attributes `_default_ask` reads off a NotificationResponse."""

    def __init__( self, status, exit_code, value=None ):
        self.response_value = value
        self.default_used   = False
        self.exit_code      = exit_code
        self.status         = status
        self.answered_by    = None


def _notify_returning( monkeypatch, response ):
    calls = [ ]
    def fake_notify_user_sync( request, **kwargs ):
        calls.append( request )
        return response
    monkeypatch.setattr( "lupin_cli.notifications.notify_user_sync.notify_user_sync", fake_notify_user_sync )
    return calls


def test_an_ask_that_never_reached_the_surface_raises_instead_of_answering( monkeypatch ):
    """
    A transport failure comes back as a RETURNED response, not a raise, with a default of
    "yes" to hand. The raise is what stops that default becoming Rick's keypress.
    """
    calls  = _notify_returning( monkeypatch, _Resp( "error", 1 ) )
    kwargs = gate.promotion_ask_kwargs( "maria 4f98d12f", TASK_ID, "a row", "sid" )

    with pytest.raises( RuntimeError, match="never reached the notification surface" ) as raised:
        gate._default_ask( **kwargs )

    assert len( calls ) == 1
    assert "status='error'" in str( raised.value )
    assert "exit_code=1"    in str( raised.value )


def test_the_gate_refuses_an_ask_that_never_reached_the_surface_and_names_why( monkeypatch ):
    """The raise above, through the real default `ask_fn`, lands as a named refusal."""
    _notify_returning( monkeypatch, _Resp( "error", 1, value="yes" ) )

    decision = gate.approval_from_the_ask( session_id="sid", actor="maria 4f98d12f",
                                           task_id=TASK_ID, title="a row" )

    assert not decision.allowed
    assert decision.approval_source is None
    assert "RuntimeError: the ask never reached the notification surface" in decision.refusal
    assert "NOT a no from Rick" in decision.refusal
