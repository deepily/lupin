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
    def __init__( self, value, default_used ):
        self.response_value = value
        self.default_used   = default_used


def test_the_default_ask_path_can_actually_reach_the_notification_surface( monkeypatch ):
    seen = {}

    def fake_notify_user_sync( request, **kw ):
        seen[ "request" ] = request
        return _Resp( "yes", False )

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
