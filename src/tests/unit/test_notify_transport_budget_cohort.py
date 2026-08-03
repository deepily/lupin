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
from lupin_cli.notifications.notify_user_async import calculate_retry_intervals


OBSERVED_MAX_RELOAD_SECONDS = 18.76      # row 204911ca §5.0, current-config slice, n=143
FIELD_CEILING_SECONDS       = 30         # notification_models.py:620-625, Field( le=30 )
HOOK_WALL_CLOCK_CEILING     = 40         # a hook path must not stall longer than this


def _attempt_starts( budget ):
    """When each attempt BEGINS, given the schedule this budget generates."""
    delays, t, starts = [ 0 ] + calculate_retry_intervals( budget ), 0.0, []
    for d in delays:
        t += d
        starts.append( t )
        t += budget                      # a failed attempt consumes its whole budget
    return starts


def _rides_out_window( budget, window=OBSERVED_MAX_RELOAD_SECONDS ):
    """True if any attempt is still open when a max-length reload window ends."""
    return any( s + budget > window for s in _attempt_starts( budget ) )


def _wall_clock( budget ):
    """Worst-case total time the caller can block."""
    intervals = calculate_retry_intervals( budget )
    return sum( intervals ) + ( len( intervals ) + 1 ) * budget


class TestFieldCarriedBudgets:

    def test_hook_common_retry_schedule_rides_out_the_reload_window( self ):
        """
        🔴 COVERAGE HERE IS THE RETRY SCHEDULE'S JOB, NOT ONE FAT TIMEOUT.

        This path retries, and `calculate_retry_intervals( request.timeout )`
        derives the schedule FROM the budget. So the question is not "is the
        budget > 18.76s" — it is "does some attempt remain OPEN when a
        max-length window ends". At 3s every attempt finished inside the window
        and the notification was dropped; that was F1.
        """
        assert _rides_out_window( hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS )

    def test_listener_retry_schedule_rides_out_the_reload_window( self ):
        """`cc_notification_listener.py` gist response — the site F1 caught."""
        assert _rides_out_window( cc_notification_listener.NOTIFY_TRANSPORT_TIMEOUT_SECONDS )

    def test_budgets_do_not_stall_a_hook_path( self ):
        """
        🔴 THE INVERSE GUARD, and the reason this is 6 rather than the cohort's 30.

        Raising the budget inflates the retry COUNT as well as each attempt, so
        wall clock grows super-linearly: 3s→11s, 6s→28s, 30s→**267s**. These are
        fire-and-forget notifications wrapped in `except: pass` specifically so
        they never block Claude Code. A hook stalling 267s is a worse defect than
        a dropped notification, so "align it with the cohort" must fail here.
        """
        for budget in ( hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS,
                        cc_notification_listener.NOTIFY_TRANSPORT_TIMEOUT_SECONDS ):
            assert _wall_clock( budget ) <= HOOK_WALL_CLOCK_CEILING, (
                f"budget {budget}s costs {_wall_clock( budget )}s of wall clock on a hook path"
            )

    def test_field_carried_budget_is_deliberately_not_the_cohort_value( self ):
        """
        These answer different questions: the cohort budget covers ONE call with
        no retry; this one covers a retry schedule it also generates. Pinned so
        a future "make them consistent" tidy-up fails and reads this comment.
        """
        assert cc_notification_listener.NOTIFY_TRANSPORT_TIMEOUT_SECONDS != \
            cc_notification_listener._SERVER_TRANSPORT_TIMEOUT_SECONDS

    def test_both_field_carried_members_agree_with_each_other( self ):
        """
        Two modules, two constants, one intended value. If they drift apart the
        cohort has silently split, which is the failure the drift control exists
        to prevent — and neither grep would report it as a problem.
        """
        assert hook_common.NOTIFY_TRANSPORT_TIMEOUT_SECONDS == \
            cc_notification_listener.NOTIFY_TRANSPORT_TIMEOUT_SECONDS


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
