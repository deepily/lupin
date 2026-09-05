#!/usr/bin/env python3
"""
THE PROMOTION GATE'S WIRING, ENTERED AT THE LAYER A CALLER ENTERS AT.

`test_promotion_out_of_holding_is_manager_only_and_asks_rick.py` proves the GATE
works — 16 tests over `manager_refusal` and `approval_for_promotion`. Not one of
them can see the gate being uninstalled.

🔴 MEASURED, NOT SUSPECTED. At `f8a0b646` the call site was removed from
`transition_task` — the `promotion_approval` block and the `transition_authority`
suffix, one edit, sha `3f412770e409` -> `5dac71c191a0`. Across
`test_promotion_out_of_holding…`, `test_the_transition_door_calls_the_approval_gate`,
`test_tasks_router` and `test_documented_task_routes_are_registered` the result was
242 passed, 0 failed — against a baseline of 1 failed, 241 passed.

⇒ REVERTING THE INSTALL MADE THE SUITE GREENER. All 16 module tests held, and the
one door-level observation went from red to GREEN, which no reader reads as a
regression. That is the worst shape a gap can take: the tree does not merely fail to
object, it rewards you.

⚠️ AND THE GATE IS NOT A PREDICATE — IT ASKS RICK. So "is it installed?" is not a
question about correctness alone. An uninstalled gate refuses nobody and interrupts
nobody, so nothing anywhere gets louder. The only thing that changes is that
promotions stop being asked about, silently, which is exactly the policy the gate
exists to make unavoidable.

WHAT THESE TESTS DO. They drive the REAL handler over HTTP against a mocked
repository — the harness shape `test_tasks_router.py` and Rachel's approval-gate door
test use — because a promotion enters as a request. Enforcement is forced ON INSIDE
the test, never in `lupin-app.ini`: putting the gate into service is outward-facing
and Rick's word alone, and a test must not make that call for him.

⚠️ THE NEGATIVE CONTROLS ARE NOT OPTIONAL, THEY ARE THE ARGUMENT. A gate wired to
fire on EVERY transition would satisfy every positive test here. The arms that say
when it must stay QUIET — a transition that is not a promotion, and enforcement
switched off — are what separate "installed on the right door" from "installed".
"""
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as promotion_gate
from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

NOW     = datetime( 2026, 9, 4, 0, 0, tzinfo=timezone.utc )
MANAGER = "maria 611e3c47"


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row waiting in the holding area",
        body                = None,
        project             = "lupin",
        owner_persona       = "pocholo",
        accountable_manager = "maria",
        created_by          = "pocholo 855b2b5f",
        status              = "not_approved",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P2",
        source_qid          = None,
        correlation_key     = None,
        created_ts          = NOW,
        updated_ts          = NOW,
        title_trimmed       = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """The router's db seams, faked. Real dicts where the code does lookups."""
    fake = MagicMock()
    fake.statuses_for_ids.return_value = { }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def asks( monkeypatch ):
    """
    Records every call the door makes into the promotion gate, and answers YES.

    🔴 THE PATCH IS DELIBERATELY NOT `raising=False`. If the call site is renamed or
    the import dropped, this must fail LOUD rather than silently no-op and leave the
    file testing a door it no longer reaches. A patch that cannot fail is the same
    shape as the gap this file exists to close.

    ⚠️ AND IT IS PATCHED ON THE GATE MODULE, NOT ON `tasks`. Rachel measured the
    difference on this branch: `task_promotion_gate` binds its own `is_manager_figure`
    as a DEF-TIME DEFAULT ARGUMENT, so patching a symbol on the outer module changes
    nothing at all. `tasks.py` reaches the gate through the module attribute, so that
    is where a stand-in has to sit.
    """
    assert hasattr( tasks, "promotion_gate" )
    assert hasattr( promotion_gate, "approval_for_promotion" )

    calls = [ ]

    def _record( session_id, actor, task_id, title, **kw ):
        calls.append( { "session_id": session_id, "actor": actor,
                        "task_id": task_id, "title": title } )
        return promotion_gate.PromotionApproval(
            allowed         = True,
            approval_source = promotion_gate.APPROVAL_KEYPRESS,
        )

    monkeypatch.setattr( promotion_gate, "approval_for_promotion", _record )
    return calls


@pytest.fixture
def client( repo, monkeypatch ):
    """
    The approver allowlist runs BEFORE this gate and would refuse first, so it is
    stood down here — it is not this file's subject and it has its own door test.
    """
    assert hasattr( tasks, "is_manager_figure" )
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid, *a, **k: True )
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """Point the approval module's override file inside tmp_path. The INI is never touched."""
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    return target


def _write( target, **body ):
    target.write_text( json.dumps( body ) )
    approval._cache_mtime = None


def _post( client, item, to_status, actor, **extra ):
    body = { "to_status": to_status, "actor": actor }
    body.update( extra )
    return client.post( f"/api/tasks/{item.id}/transition", json=body )


def _armed( repo, item, actor=MANAGER, transition="not_approved->queued" ):
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=actor,
        transition=transition, receipt_refs=None, authority="standing",
    )


def test_the_isolation_actually_isolates( settings ):
    """
    Runs first and guards every test under it. Without it a green file is equally
    consistent with the module reading the real fleet settings off disk.
    """
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()


def test_promoting_out_of_holding_reaches_the_gate_at_all( client, repo, settings, asks ):
    """
    🔴 THE ARM THE MODULE TESTS CANNOT CARRY. Delete the call site and `asks` stays
    empty while all 16 module tests keep passing.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    _armed( repo, item )

    r = _post( client, item, "queued", MANAGER )

    assert r.status_code == 200, r.text
    assert len( asks ) == 1, "the door did not reach the promotion gate at all"


def test_the_gate_is_told_which_row_and_who_is_asking( client, repo, settings, asks ):
    """
    Reaching the gate is not enough — a gate handed the wrong row asks Rick the wrong
    question, and he reads the title in the ask, so the title is load-bearing.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved", title="the row Rick is being asked about" )
    _armed( repo, item )

    _post( client, item, "queued", MANAGER )

    assert asks[ 0 ][ "actor" ]   == MANAGER
    assert asks[ 0 ][ "title" ]   == "the row Rick is being asked about"

    # The door hands the gate the row's UUID OBJECT, not a string — asserted as it
    # actually arrives rather than as I first assumed. `promotion_ask_text` renders it
    # through an f-string, so Rick sees the id either way; pinning `str( item.id )`
    # here would have been a test asserting my expectation over the code's behaviour.
    assert asks[ 0 ][ "task_id" ] == item.id
    assert str( asks[ 0 ][ "task_id" ] ) == str( item.id )


def test_a_refusal_from_the_gate_becomes_a_403_at_the_door( client, repo, settings, monkeypatch ):
    """The gate refusing in isolation is worth nothing if the door drops it on the floor."""
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    monkeypatch.setattr(
        promotion_gate, "approval_for_promotion",
        lambda **kw: promotion_gate.PromotionApproval(
            allowed=False, refusal="Rick answered no." ) )
    item = _item( status="not_approved" )
    _armed( repo, item )

    r = _post( client, item, "queued", MANAGER )

    assert r.status_code == 403, r.text
    assert "Rick answered no." in r.json()[ "detail" ]


def test_a_refused_promotion_never_reaches_the_repository( client, repo, settings, monkeypatch ):
    """A 403 that has already written the row is not a gate, it is an apology."""
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    monkeypatch.setattr(
        promotion_gate, "approval_for_promotion",
        lambda **kw: promotion_gate.PromotionApproval(
            allowed=False, refusal="Rick answered no." ) )
    item = _item( status="not_approved" )
    _armed( repo, item )

    _post( client, item, "queued", MANAGER )

    repo.apply_transition.assert_not_called()


def test_the_row_records_which_way_rick_answered( client, repo, settings, asks ):
    """
    Rick's third requirement, checked where it actually lands. A keypress and a
    timed-out default must not look identical on the row, or nobody can tell later
    which promotions he blessed.

    🔴 THE COLUMN MOVED AND THIS ASSERTION DID NOT — it was RED on this branch,
    asserting `'rick-approved' in 'standing'`. `6de5fdc4` took the prose out of
    `authority`, a String(32) enum column every combination overflowed at 58-65
    characters, and put it in `reason`, which is unbounded Text and was being left
    NULL. So the requirement is unchanged and MET; only the field carrying it moved.

    ⚠️ `authority` IS ASSERTED TOO, AND THAT ARM IS THE POINT OF THE FIX. Re-pointing
    the test at `reason` alone would leave it green if somebody put the sentence back
    into the enum column — which is the defect `6de5fdc4` closed. Pinning both says
    where it must be AND where it must not.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    _armed( repo, item )

    _post( client, item, "queued", MANAGER, authority="standing" )

    reason = repo.apply_transition.call_args.kwargs[ "reason" ]
    assert "rick-approved" in reason, reason

    # 🔴 `"keypress" in reason` IS NOT A DISCRIMINATING ASSERTION AND THE FIRST CUT OF THIS
    # TEST USED IT. The timed-out wording is "rick-approved (timed-out default, not a
    # keypress)" — it CONTAINS the substring "keypress", so the check is satisfied by the
    # exact case it exists to rule out. Measured: collapsing the keypress return into the
    # timed-out wording left this file at 9 passed. The mutation SURVIVED.
    # ⇒ Assert the OTHER TWO SOURCES ARE ABSENT. That is what makes a keypress and a
    #   default distinguishable on the row, which is Rick's requirement — not the presence
    #   of a word that both strings happen to share.
    assert "timed-out"    not in reason, f"a keypress must not be stamped as the default: {reason!r}"
    assert "no ask fired" not in reason, f"a keypress must not be stamped as a self-promotion: {reason!r}"

    authority = repo.apply_transition.call_args.kwargs[ "authority" ]
    assert authority == "standing", f"the enum column must stay a bare authority, got {authority!r}"


def test_a_transition_that_is_not_a_promotion_leaves_rick_alone( client, repo, settings, asks ):
    """
    🔴 NEGATIVE CONTROL, AND THE FILE IS WORTHLESS WITHOUT IT. Every positive test
    above is satisfied by a gate wired to fire on EVERY transition — which would ask
    Rick to bless `queued -> in_progress`, dozens of times a day. This arm is what
    says the gate is on the RIGHT door rather than merely on a door.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="queued" )
    _armed( repo, item, transition="queued->in_progress" )

    r = _post( client, item, "in_progress", MANAGER )

    assert r.status_code == 200, r.text
    assert asks == [ ], "Rick was asked about a transition that is not a promotion"


def test_the_to_status_conjunct_is_UNREACHABLE_and_this_says_so( client, repo, settings, asks ):
    """
    🔴 THIS TEST REPLACES A VACUOUS ONE, AND THE REPLACEMENT IS THE FINDING.

    It first read: post `not_approved -> not_approved` and assert Rick is not asked.
    That passed — and it passed for a reason that has nothing to do with the gate.
    Caught by the A4 arm below: with the gate's condition replaced by `if True`, so
    that it fires on EVERY transition, this test still went GREEN while its two
    siblings correctly reddened. A negative control that survives the mutant it was
    written for is not a control.

    ⚠️ THE CAUSE, MEASURED RATHER THAN GUESSED. The door rejects the edge upstream,
    before the gate is reached at all:

        422 {"detail":{"errors":["no-op transition 'not_approved'->'not_approved'
                                  rejected — not a legal edge"]}}

    So `asks == [ ]` was true because the request never got that far. Two sufficient
    causes, one assertion, and it could not tell you which one fired.

    ⇒ WHAT THAT MAKES OF THE GATE'S THIRD CONJUNCT. The call site reads

        item.status == NOT_APPROVED  and  payload.to_status != NOT_APPROVED

    and the second half can never be False while the first is True, because the only
    transition that would do it is the no-op edge the door already refuses. It is
    defence in depth and it is UNREACHABLE — which is a fine thing for a guard to be
    and a dishonest thing for a test to claim it covers.

    ⇒ So this test asserts what is actually TRUE and checkable — the upstream refusal
    — and states plainly that the conjunct is unguarded rather than pretending
    otherwise. If a future change makes that edge legal, this test fails and whoever
    is standing there learns that a real negative control is now needed.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    _armed( repo, item, transition="not_approved->not_approved" )

    r = _post( client, item, "not_approved", MANAGER )

    assert r.status_code == 422, r.text
    assert "not a legal edge" in r.text
    assert asks == [ ], "the gate was consulted on an edge the door had already refused"


def test_with_enforcement_OFF_the_gate_does_not_interrupt_him( client, repo, settings, asks ):
    """
    🔴 THE SECOND NEGATIVE CONTROL, AND IT PINS A DELIBERATE DESIGN CHOICE. The gate
    rides the SAME switch as the approver allowlist, on purpose: with holding-area
    enforcement off the room is not being policed at all, so asking Rick to bless a
    promotion nobody is restricting is noise — and noise an operator cannot silence
    from the one dial meant to control this door. Two gates on one door with two
    switches is how a "disabled" feature keeps interrupting somebody.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=False )
    item = _item( status="not_approved" )
    _armed( repo, item )

    r = _post( client, item, "queued", MANAGER )

    assert r.status_code == 200, r.text
    assert asks == [ ], "the gate asked Rick while its own enforcement switch was off"
