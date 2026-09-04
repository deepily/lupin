#!/usr/bin/env python3
"""
NO MANAGER BATCHES — Rick, 2026-09-04, relayed by María.

    "A manager should never be able to fire a batch. They should only ever request
     1 ticket at a time."

Batch approve and batch won't-fix are RICK-ONLY, and the refusal is SERVER-SIDE. A UI
that merely hides the button is NOT the control — this repo's own standing position
about won't-fix, which counts toward the create/close ratio while `dropped` does not, so
bulk closing is half a mint-by-deletion loop.

🔴 THERE IS NOTHING IN THE REQUEST TO REFUSE, AND THAT IS WHY THIS IS A COUNT.
Measured 2026-09-04, with a positive control (the same search finds
`admin/users/batch-delete`, so the zero is evidence rather than silence):

    task routes                             14 decorators, 10 distinct paths
    batch or bulk doors                     NONE
    list-valued row field on a task model   NONE

The UI's batch approve is a CLIENT-SIDE LOOP — `notifications.js:12383
_applyHoldingBatch` → `for ( const id of ids ) await this._transitionTask( id, ... )` at
:12419. Every iteration is a well-formed single-row POST, byte-indistinguishable from
somebody approving one ticket. **No per-request predicate can tell request 3 of 8 from a
lawful request**, and a guard claiming to would be implying coverage it does not have.

⇒ So the rule is CARDINALITY OVER TIME, counted off the append-only event trail: no new
state, nothing to lose on a bounce, and the evidence for any refusal is a row somebody
can go and read.

⚠️ POLICY CONTROL, NOT A SECURITY BOUNDARY. It keys on `actor`, which is caller-declared,
so a caller who varies it between requests is not counted together. That is the same
limit `refusal_for_admission` already documents; this inherits it and does not pretend to
close it.
"""
import json
import os
import sys
import tempfile
from unittest import mock

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as gate

BATCH_ACTOR = "operator foolish goat"   # the real client's per-session actor
WINDOW      = 60


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """The approval override file, inside tmp_path. The real INI is never touched."""
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None,
                                               "default_to_holding": None, "approver_accounts": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( { "approvers": [ "cheech", "maria", "mr radio" ],
                                     "enforcement_active": True } ) )
    return target


@pytest.fixture
def rule_on( monkeypatch ):
    """Turn the throttle on IN THE TEST. Never in lupin-app.ini — that is Rick's word."""
    monkeypatch.setattr( approval, "get_admission_window_seconds", lambda: WINDOW )


def test_the_isolation_actually_isolates( settings ):
    """Runs first. Without it a green file is also consistent with reading fleet settings."""
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()


def test_the_rule_ships_OFF( settings ):
    """
    🔴 THE FALLBACK DIRECTION, and it is the same one every flag in this module chose. An
    absent key must not silently start refusing an approver's second ticket. Turning a
    throttle ON is outward-facing and explicit; wrong-OFF leaves today's behaviour visibly
    in place, wrong-ON quietly blocks the people doing the work.
    """
    assert approval.get_admission_window_seconds() == 0
    assert approval.refusal_for_batch( BATCH_ACTOR, "maria", 5 ) is None


def test_a_managers_FIRST_ticket_always_passes( settings, rule_on ):
    """"One ticket at a time" means the first one is never refused."""
    assert approval.refusal_for_batch( BATCH_ACTOR, "maria", 0 ) is None


@pytest.mark.parametrize( "already", [ 1, 2, 7 ] )
def test_a_managers_SECOND_and_beyond_is_refused( settings, rule_on, already ):
    """🔴 THE ONE THIS FILE EXISTS FOR — a manager cannot fire a batch."""
    refusal = approval.refusal_for_batch( BATCH_ACTOR, "maria", already )
    assert refusal, f"a manager admitted row {already + 1} inside the window — the batch rule is not firing"
    assert str( already ) in refusal


@pytest.mark.parametrize( "already", [ 0, 1, 7 ] )
def test_RICK_may_batch( settings, rule_on, already ):
    """
    🔴 THE DISCRIMINATOR, AND IT IS NOT A COURTESY. The ruling restricts MANAGERS; batch
    approve is Rick's own control. A rule that throttled him too would satisfy every
    refusal arm above while removing the feature he asked for.
    """
    assert approval.refusal_for_batch( BATCH_ACTOR, "rick", already ) is None


def test_the_exemption_is_the_SAME_list_that_decides_the_promotion_ask( ):
    """
    Both answer "is this Rick?", not "may this caller approve?" — so they are one list on
    purpose. Keeping them in step by hand is the coincidence-not-construction defect that
    produced the door-2 row in the first place.
    """
    assert gate.ASK_EXEMPT_PERSONAS == ( "rick", )
    refusal = None
    with mock.patch.object( approval, "get_admission_window_seconds", lambda: WINDOW ):
        for persona in gate.ASK_EXEMPT_PERSONAS:
            refusal = refusal or approval.refusal_for_batch( BATCH_ACTOR, persona, 9 )
    assert refusal is None


def test_the_refusal_reads_as_a_THROTTLE_not_a_permissions_problem( settings, rule_on ):
    """
    A manager who meets this has the permission and is going too fast. Telling them they
    are not an approver would send them at the permissions system — the mislabelled-failure
    shape `manager_refusal` already spends four paragraphs avoiding.
    """
    refusal = approval.refusal_for_batch( BATCH_ACTOR, "maria", 3 )
    assert "THROTTLE" in refusal
    assert f"wait {WINDOW}s" in refusal
    assert approval.INI_KEY_ADMISSION_WINDOW in refusal
    assert "not an approver" not in refusal


@pytest.mark.parametrize( "bad", [ "-5", "banana", None, "" ] )
def test_a_MALFORMED_window_fails_OPEN( bad ):
    """
    A broken throttle must not block work. Same direction as every other key here: the
    gate must not close hardest exactly when it understands least.
    """
    with mock.patch.object( approval, "_ini_value", lambda *_a, **_k: bad ):
        assert approval.get_admission_window_seconds() == 0
