#!/usr/bin/env python3
"""
THE CONTAINMENT BOUNDARY — a test must not be able to block on a human (row e625e608).

On 2026-09-04 plain `pytest src/tests/unit/ -q` runs fired 33 REAL yes/no prompts at Rick
between 18:33:24 and 18:48:36. He read it as one prompt re-firing however he answered; it
was many separate tests each firing a separate ask.

⚠️ TWO DIFFERENT TIERS LEAKED AND ONE RAN FROM A PROPERLY CONFIGURED CHECKOUT. The first
report emphasised that one offending process had `LUPIN_ROOT` in `/tmp` — that explained
the `sender_id: unknown` stamp, never the leak. This is not one misconfigured seat.

🔴 WHY THE ASSERTIONS BELOW ARE ABOUT A REFUSAL AND NOT ABOUT A STUB. "That test should
have stubbed it" lasts until the next unstubbed test. Worse, Rio measured that the obvious
stub DOES NOT EVEN WORK: `approval_for_promotion( ..., ask_fn=_default_ask )` binds that
default AT DEFINITION TIME, so patching the module attribute leaves the bound default in
place and the test believes it stubbed something it did not.
"""
import os
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.notifications import human_ask_containment as guard


# ---------------------------------------------------------------------------
# The predicate
# ---------------------------------------------------------------------------

def test_a_test_context_is_detected_without_anyone_opting_in():
    """
    THE PROPERTY THE WHOLE FIX RESTS ON. pytest sets PYTEST_CURRENT_TEST itself, per test.
    This assertion is live proof: this very test is running, so the var is set, and no
    line of this file set it.
    """
    assert guard.test_node_id() is not None
    assert "test_a_test_context_is_detected_without_anyone_opting_in" in guard.test_node_id()


def test_the_refusal_names_the_test_that_tried():
    """A refusal must identify the CULPRIT, not the victim — otherwise it is a mystery."""
    refusal = guard.refusal_for_human_ask( "Allow it?" )
    assert refusal is not None
    assert "test_the_refusal_names_the_test_that_tried" in refusal
    assert "e625e608" in refusal
    assert "Allow it?" in refusal


def test_production_is_untouched( monkeypatch ):
    """
    🔴 THE NEGATIVE CONTROL, AND WITHOUT IT EVERY ARM ABOVE IS SATISFIED BY A GUARD THAT
    REFUSES EVERYONE — which would take the promotion ask away from Rick entirely, turning
    a containment fix into an outage of the feature it protects.
    """
    monkeypatch.delenv( guard.PYTEST_NODE_ENV_VAR, raising=False )
    assert guard.test_node_id() is None
    assert guard.refusal_for_human_ask( "Allow it?" ) is None


def test_the_waiver_is_exact_and_not_merely_truthy( monkeypatch ):
    """
    The escape exists for tests OF the ask path. It must not be openable by accident, so
    only the exact string "1" counts — "0", "", "true" and "yes" must all stay closed.
    """
    for value, waived in ( ( "1", True ), ( "0", False ), ( "", False ),
                           ( "true", False ), ( "yes", False ), ( " 1 ", True ) ):
        monkeypatch.setenv( guard.ALLOW_ENV_VAR, value )
        assert guard.containment_is_waived() is waived, f"{value!r} decided wrongly"
        assert ( guard.refusal_for_human_ask() is None ) is waived


# ---------------------------------------------------------------------------
# The boundary, at the function every live ask actually passes through
# ---------------------------------------------------------------------------

def test_notify_user_sync_REFUSES_from_inside_a_test():
    """
    THE ONE THIS FILE EXISTS FOR. Not the predicate — the real entry point, called the way
    the promotion gate calls it. If this passes while the wiring is gone, the file is
    testing a module nobody reaches.
    """
    from lupin_cli.notifications.notify_user_sync import notify_user_sync, HumanAskInTestError
    from lupin_cli.notifications.notification_models import (
        NotificationRequest, NotificationType, NotificationPriority, ResponseType
    )
    request = NotificationRequest(
        message           = "operator foolish goat wants to promote a row out of the holding area. Allow it?",
        abstract          = "**Promotion out of the holding area**",
        response_type     = ResponseType.YES_NO,
        notification_type = NotificationType.CUSTOM,
        priority          = NotificationPriority.HIGH,
        timeout_seconds   = 120,
        response_default  = "yes",
        human_only        = True,
    )
    with pytest.raises( HumanAskInTestError ) as excinfo:
        notify_user_sync( request=request )

    assert "test_notify_user_sync_REFUSES_from_inside_a_test" in str( excinfo.value )


def test_the_refusal_RAISES_rather_than_returning_a_quiet_error_code():
    """
    ⚠️ THE FAILURE MODE IS THE POINT, AND THE ALTERNATIVE LOOKS REASONABLE. Returning
    exit_code 1 would respect the function's old "never raises" contract — and the
    offending test would go GREEN having silently asked nobody. That is precisely the
    incident: 33 prompts and nothing telling anyone. A containment breach must REDDEN.
    """
    from lupin_cli.notifications.notify_user_sync import HumanAskInTestError
    assert issubclass( HumanAskInTestError, RuntimeError )


# ---------------------------------------------------------------------------
# End-to-end: the tier itself
# ---------------------------------------------------------------------------

@pytest.mark.skipif( not os.environ.get( "LUPIN_ROOT" ), reason="needs LUPIN_ROOT pinned" )
def test_a_FRESH_pytest_subprocess_cannot_reach_the_human_ask_path():
    """
    THE ARM THAT SPEAKS TO THE INCIDENT, entered at the layer the incident entered at:
    a real pytest SUBPROCESS calling the real `_default_ask`, not an in-process call.

    A subprocess is required and is not ceremony — `PYTEST_CURRENT_TEST` belongs to the
    process that sets it, so an in-process arm cannot show that a FRESH tier is contained.

    🔴 THIS PROBE PRINTS THREE DISTINCT OUTCOMES, AND THE FIRST CUT PRINTED TWO. It
    labelled one branch `NOT_CONTAINED_OR_SHORT_CIRCUITED` and then asserted on it as
    though it meant "not contained". It fired — because `approval_for_promotion` returned
    before ever reaching the ask — and that read as the guard failing when it was the
    probe being unable to tell two states apart. An assertion whose label admits it covers
    two cases cannot discriminate between them, which is the whole defect this row is
    about, one level down.

    ⇒ So the probe drives `_default_ask` DIRECTLY. That is the ask path itself, and it
    cannot be short-circuited by upstream policy (manager-hood, enforcement flags) that
    has nothing to do with containment.
    """
    root = os.environ[ "LUPIN_ROOT" ]
    probe = (
        "from cosa.rest.task_promotion_gate import _default_ask\n"
        "from lupin_cli.notifications.notify_user_sync import HumanAskInTestError\n"
        "def test_probe():\n"
        "    try:\n"
        "        _default_ask( question='Allow it?', abstract='a', priority='high',\n"
        "                      timeout_seconds=120, response_default='yes', human_only=True )\n"
        "    except HumanAskInTestError as e:\n"
        "        print( 'OUTCOME=CONTAINED' ); assert 'test_probe' in str( e ); return\n"
        "    except Exception as e:\n"
        "        print( f'OUTCOME=OTHER_ERROR:{type(e).__name__}' ); return\n"
        "    print( 'OUTCOME=REACHED_THE_HUMAN' )\n"
    )
    probe_path = os.path.join( root, "src", "tests", "unit", "test_zz_containment_probe.py" )
    try:
        with open( probe_path, "w" ) as fh: fh.write( probe )
        out = subprocess.run(
            [ os.path.join( root, ".venv", "bin", "python" ), "-m", "pytest",
              probe_path, "-q", "-s", "--no-header" ],
            capture_output=True, text=True, timeout=180,
            env={ **os.environ, "LUPIN_ROOT": root, "PYTHONPATH": os.path.join( root, "src" ) },
        )
    finally:
        if os.path.exists( probe_path ): os.remove( probe_path )

    # A positive control FIRST: an empty or crashed probe prints no OUTCOME at all, and
    # every assertion below would then pass vacuously on a run that measured nothing.
    assert "OUTCOME=" in out.stdout, (
        f"the probe produced no outcome line — it never ran, so this proves nothing.\n"
        f"{out.stdout[ -2000: ]}\n{out.stderr[ -1000: ]}"
    )
    assert "OUTCOME=REACHED_THE_HUMAN" not in out.stdout, (
        f"a fresh pytest subprocess reached the live human ask path — the incident is open.\n"
        f"{out.stdout[ -2000: ]}"
    )
    assert "OUTCOME=CONTAINED" in out.stdout, (
        f"the probe neither reached a human nor was contained — inconclusive, not green.\n"
        f"{out.stdout[ -2000: ]}"
    )
