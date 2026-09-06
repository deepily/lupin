#!/usr/bin/env python3
"""
DOES ANSWERING THE PROMOTION GATE STOP IT ASKING AGAIN?

Rick, USER BROADCAST 43120adf, 2026-09-04: "Whoever is testing promotion from staged
to the task queue is causing a double submission of the permission yes no prompt. No
matter how you respond the first time, it will also refire as soon as you answer."

One hypothesis in circulation (row 1544d51e) reads that literally: the gate does not
RECORD which way you answered, so a second attempt re-asks. This file measures that
claim at the layer the incident enters — the real transition door over HTTP — rather
than reasoning about it from the source.

🔴 IT IS THE `not_approved` STATUS, NOT A STORED ANSWER, THAT DECIDES WHETHER RICK IS
ASKED. `transition_task` gates on `item.status == NOT_APPROVED_STATUS` before it
reaches `approval_for_promotion`. So the answer is never persisted anywhere and never
needs to be: a YES moves the row OUT of `not_approved`, and the guard then declines to
ask on its own. Nothing remembers the answer because nothing has to.

⇒ SO THE TWO OUTCOMES DIVERGE, AND THAT DIVERGENCE IS THE WHOLE FILE:

    answered YES  -> row leaves `not_approved` -> a further POST asks NOTHING
    answered NO   -> 403, row STAYS `not_approved` -> a further POST asks AGAIN

The second is not a defect. A refused promotion that became unaskable would be a row
locked out of the queue by one mis-click, with no way back through the front door.

⚠️ WHAT THIS FILE THEREFORE DOES NOT SETTLE. It rules out "the gate forgets a YES."
It does NOT explain Rick's report, and must not be read as doing so — the surviving
candidate is the CLIENT: `_applyHoldingBatch` (notifications.js) posts one transition
per row sequentially, so a batch approve raises one gate per row and the next lands the
instant you answer the last. That is a different layer with a different fix, and this
file is deliberately silent about it. Measured separately: 8 asks in the :7999 log
carried 8 DISTINCT notification ids for 8 DISTINCT rows, and each showed one create,
one WebSocket push, one response — no row was asked about twice, and no ask was
delivered twice.

⚠️ AND THE ARMS ARE NOT INTERCHANGEABLE. Arm 1 alone would be satisfied by a door that
asks on every POST forever; arm 2 alone would be satisfied by a door that asks once and
then never again for any reason, which would strand a refused row. Only the pair says
the guard keys on the row's STATUS rather than on having asked before.

Harness shape borrowed from `test_the_transition_door_calls_the_promotion_gate.py` —
the real handler, a mocked repository, enforcement forced ON inside the test and never
in `lupin-app.ini`, because putting the gate into service is Rick's word alone.
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
def gate( monkeypatch ):
    """
    Counts every ask the door fires, and lets the test choose the answer.

    The patch is deliberately NOT `raising=False`: if the call site is renamed or its
    import dropped, this must fail LOUD rather than quietly record zero asks and leave
    the file reporting on a door it no longer reaches. A recorder that cannot fail is
    the same shape as the gap it is meant to close.

    Patched on the GATE MODULE, not on `tasks` — `task_promotion_gate` binds its own
    seams as def-time default arguments, and `tasks.py` reaches it through the module
    attribute, so that is the only place a stand-in is seen.
    """
    assert hasattr( tasks, "promotion_gate" )
    assert hasattr( promotion_gate, "approval_for_promotion" )

    state = { "asks": [ ], "answer": True }

    def _record( session_id, actor, task_id, title, **kw ):
        state[ "asks" ].append( str( task_id ) )
        if state[ "answer" ]:
            return promotion_gate.PromotionApproval(
                allowed         = True,
                approval_source = promotion_gate.APPROVAL_KEYPRESS,
            )
        return promotion_gate.PromotionApproval(
            allowed = False,
            refusal = "Rick said no.",
        )

    monkeypatch.setattr( promotion_gate, "approval_for_promotion", _record )
    return state


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


def _post( client, item, to_status, actor ):
    return client.post( f"/api/tasks/{item.id}/transition",
                        json={ "to_status": to_status, "actor": actor } )


def _armed( repo, item, transition="not_approved->queued" ):
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=MANAGER,
        transition=transition, receipt_refs=None, authority="standing",
    )


def test_the_isolation_actually_isolates( settings ):
    """
    Runs first and guards every test under it. Without it a green file is equally
    consistent with the module reading the real fleet settings off disk — and this
    file forces enforcement ON, which is exactly the setting that must not leak.
    """
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()


def test_promoting_a_held_row_asks_exactly_once( client, repo, settings, gate ):
    """
    THE POSITIVE CONTROL. Without it the two arms below are equally consistent with a
    door that never asks at all, and an ask-count of zero would read as a pass.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    _armed( repo, item )

    r = _post( client, item, "queued", MANAGER )

    assert r.status_code == 200, r.text
    assert gate[ "asks" ] == [ str( item.id ) ], "one promotion must raise exactly one gate"


def test_a_row_already_promoted_is_not_asked_about_again( client, repo, settings, gate ):
    """
    🔴 THE CLAIM UNDER TEST, AND IT COMES OUT FALSE. Row 1544d51e proposed that the
    gate forgets the answer and re-asks on a second attempt. It does not — and the
    reason is worth more than the verdict: nothing REMEMBERS the answer, and nothing
    needs to. A YES moves the row out of `not_approved`, and the door's guard then
    declines to ask because of WHERE THE ROW IS, not because of what was said.

    ⚠️ THE SECOND TRANSITION HERE IS `queued -> in_progress`, NOT A REPEATED PROMOTION,
    AND THAT CHOICE IS THE WHOLE ARM. A repeated promotion (`queued -> queued`) is
    rejected upstream as a no-op edge and never reaches the guard at all — measured,
    422 "no-op transition 'queued'->'queued' rejected". An arm written that way passes
    whether the guard exists or not: it was, it did, and removing the guard entirely
    left it green. It is pinned separately below, as the different fact it is.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    _armed( repo, item )

    _post( client, item, "queued", MANAGER )
    assert len( gate[ "asks" ] ) == 1, "precondition: the first promotion asked"

    # The answer was yes, so the row has left the holding area. Move it on again — a
    # legal edge, so this DOES reach the guard, which is what makes the arm mean something.
    item.status = "queued"
    _armed( repo, item, transition="queued->in_progress" )
    r2 = _post( client, item, "in_progress", MANAGER )

    assert r2.status_code == 200, r2.text
    assert len( gate[ "asks" ] ) == 1, "a row that has left the holding area must not raise the gate"


def test_a_repeat_promotion_is_refused_before_the_gate_not_by_it( client, repo, settings, gate ):
    """
    The operator's actual second click on a stale pane, and it never reaches the gate.

    Recorded as its own test rather than folded into the arm above because the two are
    satisfied by DIFFERENT mechanisms — one by the guard declining, one by the edge
    validator refusing first — and an assertion that cannot say which of two sufficient
    causes fired is measuring their disjunction.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    _armed( repo, item )
    _post( client, item, "queued", MANAGER )

    item.status = "queued"
    _armed( repo, item, transition="queued->queued" )
    r2 = _post( client, item, "queued", MANAGER )

    assert r2.status_code == 422, r2.text
    assert "no-op transition" in r2.text
    assert len( gate[ "asks" ] ) == 1, "the repeat was refused upstream, so Rick was never asked"


def test_a_refused_row_stays_askable_and_that_is_correct( client, repo, settings, gate ):
    """
    THE ARM THAT STOPS THE ONE ABOVE FROM PROVING TOO MUCH. A door that asked once and
    then never again — for any reason — would satisfy the previous test and would
    strand a row refused by one mis-click, permanently outside the queue with no way
    back through the front door.

    A NO leaves the row in `not_approved`, so it is still askable. That is a second
    prompt for the same row, and it is the correct behaviour rather than the defect
    Rick reported: it takes a second deliberate attempt, not a single answer.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    gate[ "answer" ] = False
    item = _item( status="not_approved" )
    _armed( repo, item )

    r = _post( client, item, "queued", MANAGER )
    assert r.status_code == 403, r.text
    assert item.status == "not_approved", "a refusal must not move the row"

    _post( client, item, "queued", MANAGER )

    assert len( gate[ "asks" ] ) == 2, "a refused row must remain promotable"
