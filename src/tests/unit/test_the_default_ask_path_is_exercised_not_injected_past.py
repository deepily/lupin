"""
Guard: the DEFAULT ask path is EXERCISED, not injected past.

🔴 THIS FILE IS RED ON ITS OWN AND THAT IS THE POINT. It is committed off
47cff912 WITHOUT the one-word import fix, so the commit that makes it green is
the commit that fixes the defect. Land the two together: a guard merged after
its fix has never been seen to fail, and one merged before it leaves a red.

Written by Maya for row 47cff912, and PROVEN to discriminate rather than merely
pass — two arms, one variable, in a detached worktree at 47cff912:

    branch as-is (import reads `notifications.models`)
        -> FAILS: ModuleNotFoundError: No module named 'lupin_cli.notifications.models'
    with the one-word fix (`notification_models`)
        -> PASSES, and Pocholo's own 25 stay green (25 passed)

WHY THE PATCH GOES WHERE IT GOES, and this is the whole trick: every existing
test injects `ask_fn`, which routes AROUND `_default_ask` and therefore around
the import that is broken. This one deliberately does NOT pass `ask_fn`. It
patches one level LOWER — at `notify_user_sync`, the boundary `_default_ask`
imports — so the function body, including its import, actually runs.

Patching by dotted string works because the import sits INSIDE `_default_ask`
and is therefore resolved at CALL time, not at module import. Measured, not
assumed: that is what arms 1 and 2 above establish.

⚠️ `_default_ask` carries `# pragma: no cover`, which is one of the three
reasons the defect was invisible. A guard that exercises it should come with
that pragma reconsidered, or the coverage gate still cannot see this function.


The whole point is that it does NOT pass ask_fn. It patches one level LOWER —
at notify_user_sync, the boundary _default_ask imports — so the import inside
_default_ask actually runs.
"""
import pytest
from cosa.rest import task_promotion_gate as gate


class _Resp:
    def __init__( self, value, default_used, exit_code=0, status="responded", answered_by=None ):
        self.response_value = value
        self.default_used   = default_used
        # ⚠️ exit_code MODELS THE REAL RESPONSE (row 96d2341c). 0 vs 1 is the only
        # thing separating "a human answered" from "we never reached one" — the
        # client RETURNS on a transport failure rather than raising.
        self.exit_code      = exit_code
        self.status         = status
        # Who the server saw post the answer (row e20e249a), as NotificationResponse carries it.
        self.answered_by    = answered_by


def test_the_default_ask_path_can_actually_reach_the_notification_surface( monkeypatch ):
    seen = {}

    # Row e20e249a: the gate counts the yes only when it was posted on the operator's own
    # login, so the fake answers AS that login and the gate's lookup maps it to an
    # ask-exempt persona. It also proves `_default_ask` carries `answered_by` through.
    operator_answer = { "user_id": "operator-uid", "account_email": "operator.login@example.com", "method": "jwt" }
    real_lookup     = gate.approver_persona_for_account
    monkeypatch.setattr(
        gate, "approver_persona_for_account",
        lambda email: gate.ASK_EXEMPT_PERSONAS[ 0 ] if email == operator_answer[ "account_email" ] else real_lookup( email ) )

    def fake_notify_user_sync( request, **kw ):
        seen[ "request" ] = request
        return _Resp( "yes", False, answered_by=operator_answer )

    # Patched at the module _default_ask imports FROM, because the import is
    # inside the function and therefore resolved at call time.
    monkeypatch.setattr(
        "lupin_cli.notifications.notify_user_sync.notify_user_sync",
        fake_notify_user_sync
    )

    approval = gate.approval_for_promotion(
        session_id = "sid", actor = "maria 4f98d12f",
        task_id = "t1", title = "a row",
        is_manager_fn = lambda s: True,
        # ask_fn DELIBERATELY NOT PASSED — that is the entire subject
    )

    assert "request" in seen, "the default ask path never reached notify_user_sync"
    assert approval.allowed
    assert approval.approval_source == gate.APPROVAL_KEYPRESS
