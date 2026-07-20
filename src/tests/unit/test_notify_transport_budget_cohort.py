"""
Row `204911ca` §9(a) F1 — the FIELD-CARRIED members of the transport cohort.

WHAT THIS GUARDS, AND WHY IT EXISTS SEPARATELY.

Most `:7999` clients pass their budget at the call site (`requests.post(
timeout=… )`, `urlopen( …, timeout=… )`). Two do not: they set it as a Pydantic
FIELD on `AsyncNotificationRequest`, which `notify_user_async.py:197-201` then
consumes as a **bare** `requests.post( timeout=request.timeout )`. Bare governs
BOTH the connect and the read leg, so the read leg is exposed to a `:7999`
reload exactly like any direct call site.

🔴 THE FIRST PASS MISSED BOTH, AND THE REASON IS THE POINT.
The cohort's stated drift control was `grep -rn _SERVER_TRANSPORT_TIMEOUT_SECONDS`.
A field assignment is invisible to that grep, so `cc_notification_listener.py`
had its two `urlopen` sites raised to 30s while `:983` — in the same file, three
hundred lines up — stayed at 3s. A reload silently dropped that notification via
`except Exception: self._log(…)`.

⇒ The searches that actually cover this cohort are TWO:
     grep -rn _SERVER_TRANSPORT_TIMEOUT_SECONDS
     grep -rn "AsyncNotificationRequest(" -A14 | grep timeout
Running only the first returns the set the first grep can see, which is not the
cohort. That correction is now carried in every constant block.

⚠️ CEILING COUPLING. `AsyncNotificationRequest.timeout` is
`Field( ge=1, le=30 )` (`notification_models.py:620-625`). **30 is the maximum
the field accepts.** These tests pin that coupling: if someone raises the cohort
constant above 30 without moving the field bound, construction raises
ValidationError at runtime, and `test_cohort_budget_fits_the_field_ceiling`
fails first with the reason.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert( 0, str( Path( __file__ ).resolve().parents[ 3 ] ) )

from lupin_cli.claude_code.hooks.lib import hook_common
from lupin_cli.claude_code.hooks.lib import cc_notification_listener
from lupin_cli.notifications.notification_models import AsyncNotificationRequest


OBSERVED_MAX_RELOAD_SECONDS = 18.76      # row 204911ca §5.0, current-config slice, n=143
FIELD_CEILING_SECONDS       = 30         # notification_models.py:620-625, Field( le=30 )


class TestFieldCarriedBudgets:

    def test_hook_common_notify_budget_outlasts_the_reload_window( self ):
        """`hook_common.py:424` — was 3s, silently dropped inside `except: pass`."""
        assert hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS > OBSERVED_MAX_RELOAD_SECONDS

    def test_listener_gist_budget_outlasts_the_reload_window( self ):
        """`cc_notification_listener.py:983` — the site F1 caught."""
        assert cc_notification_listener._SERVER_TRANSPORT_TIMEOUT_SECONDS > OBSERVED_MAX_RELOAD_SECONDS

    def test_both_field_carried_members_agree_with_each_other( self ):
        """
        Two modules, two constants, one intended value. If they drift apart the
        cohort has silently split, which is the failure the drift control exists
        to prevent — and neither grep would report it as a problem.
        """
        assert hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS == \
            cc_notification_listener._SERVER_TRANSPORT_TIMEOUT_SECONDS


class TestFieldCeilingCoupling:

    def test_cohort_budget_fits_the_field_ceiling( self ):
        """
        🔴 The guard that makes a future raise fail HERE with a reason, rather
        than at runtime as a bare ValidationError from a hook nobody is watching.
        """
        assert hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS <= FIELD_CEILING_SECONDS, (
            "cohort budget exceeds AsyncNotificationRequest.timeout's Field( le=30 ) — "
            "raise the field bound in notification_models.py first"
        )

    def test_the_budget_actually_constructs( self ):
        """
        Pin the coupling against the real model rather than against a constant
        that merely restates it. If `le=` moves down, this fails even though
        FIELD_CEILING_SECONDS above still says 30.
        """
        req = AsyncNotificationRequest(
            message = "cohort budget probe",
            timeout = hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS
        )
        assert req.timeout == hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS

    def test_a_budget_above_the_ceiling_is_rejected_by_the_model( self ):
        """
        🔴 THE CONTROL FOR THE CONTROL. Proves the field bound is real and
        enforced — without this, `test_the_budget_actually_constructs` passing
        would be consistent with the model having no bound at all.
        """
        with pytest.raises( Exception ):
            AsyncNotificationRequest( message = "over ceiling", timeout = FIELD_CEILING_SECONDS + 1 )


class TestNoBareThreeSecondBudgetsRemain:
    """
    The regression guard proper: assert the two sites are wired to their
    constants, so a revert to a literal `3` fails here.
    """

    def test_hook_common_does_not_hardcode_a_short_literal( self ):
        src = Path( hook_common.__file__ ).read_text()
        assert "timeout            = 3\n" not in src, (
            "hook_common.py reverted to a literal 3s notification budget — "
            "a reload will silently drop the notification"
        )

    def test_listener_does_not_hardcode_a_short_literal( self ):
        src = Path( cc_notification_listener.__file__ ).read_text()
        assert "timeout           = 3\n" not in src, (
            "cc_notification_listener.py reverted to a literal 3s notification "
            "budget — a reload will silently drop the gist response"
        )
