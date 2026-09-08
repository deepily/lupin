#!/usr/bin/env python3
"""
THE PULL TOGGLE'S WIRING, ENTERED AT THE LAYER A CALLER ENTERS AT.

`test_the_pull_toggle_refuses_only_the_pull.py` proves the PREDICATE — 24 tests over
`refusal_for_pull`. It cannot see a revert of the CALL SITE inside `transition_task`.

🔴 MEASURED, ON MY OWN CODE, BEFORE THIS FILE EXISTED. Disabling the router's four
lines (`if False and pull_refusal is not None:`) left that file at **24 passed**. The
gate was disconnected and nothing anywhere noticed — the implemented-but-never-
installed shape, in the very work written to close an instance of it. These tests are
what reddens.

They drive the REAL handler over HTTP against a mocked repository, borrowing the
harness shape from `test_the_transition_door_calls_the_approval_gate.py`, because a
request is where the incident enters.

⚠️ THE TOGGLE IS FORCED ON **INSIDE THE TEST**, never in `lupin-app.ini`. Putting it
into service is outward-facing and Rick's word alone; a test must not make that call
on his behalf.
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
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

NOW    = datetime( 2026, 9, 6, 0, 0, tzinfo=timezone.utc )
PULLER = "maya 20467682"


def _item( **overrides ):
    fields = dict(
        id=uuid.uuid4(), item_class="task", title="a queued row somebody wants to start",
        body=None, project="lupin", owner_persona="maya", accountable_manager="mr radio",
        created_by="maya 20467682", status="queued", blocked_by=[ ], next_chase_ts=None,
        gate_class="none", priority="P2", source_qid=None, correlation_key=None,
        created_ts=NOW, updated_ts=NOW, title_trimmed=False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    fake = MagicMock()
    fake.statuses_for_ids.return_value = { }

    @contextmanager
    def _fake_get_db(): yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def client( repo, monkeypatch ):
    """Other doors on this route are stood down; none of them is this file's subject."""
    gate = getattr( tasks, "promotion_gate", None )
    if gate is not None:
        from cosa.rest.task_promotion_gate import PromotionApproval
        monkeypatch.setattr( gate, "approval_for_promotion",
                             lambda *a, **k: PromotionApproval( allowed=True,
                                                                approval_source="stubbed-for-this-file" ) )
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


@pytest.fixture
def toggle( tmp_path, monkeypatch ):
    """Isolate the override file, then flip the switch through it."""
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "manager_pull_disabled": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )

    def _set( on ):
        target.write_text( json.dumps( { "manager_pull_disabled": on } ) )
        approval._cache_mtime = None
    _set.path = target
    return _set


def _post( client, item, to_status, actor="maya 20467682" ):
    return client.post( f"/api/tasks/{item.id}/transition",
                        json={ "to_status": to_status, "actor": actor } )


def test_the_isolation_actually_isolates( toggle ):
    """Runs first. Without it a green file is also consistent with reading fleet settings."""
    toggle( True )
    assert str( toggle.path ) == approval.override_path()
    assert "projects-data" not in approval.override_path()
    assert approval.get_manager_pull_disabled() is True


# ═══ THE TWO ARMS, AT THE DOOR ═══════════════════════════════════════════════

def test_a_pull_is_refused_AT_THE_DOOR_when_the_toggle_is_ON( client, repo, toggle ):
    """
    THE ONE THAT DIES IF THE CALL SITE IS REVERTED.

    🔨 REAIMED 2026-09-07 (row 1ec67228), and the reaim is itself a finding. The shared
    `_item()` fixture is owner=`maya`, manager=`mr radio`, and `_post`'s default actor
    is `maya 20467682` -- i.e. EXACTLY the self-claim shape María ruled exempt. So the
    moment the exemption landed, this test started measuring the exempt case and
    reported 200. It was not wrong before and it is not wrong now; the world it
    described acquired a second rule.

    ⇒ It now drives a NON-owner, which is what "a manager pulls new work" actually
    looks like. The exempt case gets its own test below, so both paths are watched and
    neither is inferred from the other's silence.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    toggle( True )

    response = _post( client, item, "in_progress", actor="rio 5f0c1a22" )

    assert response.status_code == 409, response.text
    detail = response.json()[ "detail" ]
    assert "458e9947"                 in detail
    # 🔨 REAIMED 2026-09-07, row 1ec67228. This line was
    #     assert "not a permission problem" in detail
    # which was right for row 458e9947's focus measure and is wrong for Rick's standing
    # rescission -- the caller now needs an approver, not a switch. Reaimed rather than
    # dropped, and at the DOOR rather than only at the helper, so the reworded message
    # is proven to reach an actual 409 body.
    assert "1ec67228"                 in detail
    assert "approver"                 in detail.lower()
    assert "not a permission problem" not in detail


def test_the_SAME_pull_succeeds_at_the_door_when_the_toggle_is_OFF( client, repo, toggle ):
    """
    The control. Without it, a gate that refused every transition unconditionally
    would satisfy the test above — and a guard satisfied by refusing everything is
    not a guard. The row's acceptance demands both arms and this is the second.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    toggle( False )

    assert _post( client, item, "in_progress" ).status_code != 409


def test_a_NON_pull_is_untouched_at_the_door_even_with_the_toggle_ON( client, repo, toggle ):
    """The gate has one edge. `queued -> done` must be unaffected."""
    item = _item()
    repo.get_by_id_for_update.return_value = item
    toggle( True )

    assert _post( client, item, "done" ).status_code != 409


# ═══ THE SELF-CLAIM EXEMPTION, AT THE DOOR (María 🌸, row 1ec67228) ═══════════
#
# The helper's own arms live in `test_the_pull_toggle_refuses_only_the_pull.py`. These
# two exist because the exemption reads the ROW, and the row only reaches the gate if
# the router hands it over -- so a helper-level arm cannot speak to the wiring. Entered
# at the layer the caller enters at.

def test_a_worker_starting_their_OWN_assigned_row_gets_through_the_door( client, repo, toggle ):
    """
    `_item()` is owner=maya / manager=mr radio, so maya starting it is the exempt case.

    🔴 THE ONE THAT DIES IF THE ROUTER STOPS PASSING THE ROW. Drop either `item_owner`
    or `item_manager` from the call site and the exemption cannot fire, so this 200
    becomes a 409 while every helper-level arm stays green.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    toggle( True )

    # Rick's terms: permitted WITH A RECEIPT, so the reason rides the request. The
    # missing-reason arm lives in the helper's file; this one proves the router hands
    # the reason to the gate at all.
    response = client.post(
        f"/api/tasks/{item.id}/transition",
        json={ "to_status": "in_progress", "actor": "maya 20467682",
               "reason": "starting the row mr radio assigned me" },
    )

    assert response.status_code == 200, response.text


def test_a_self_claim_WITHOUT_a_reason_is_refused_at_the_door( client, repo, toggle ):
    """
    🔴 THE ONE THAT DIES IF THE ROUTER STOPS PASSING `reason`.

    Same caller, same row, same toggle as the test above — only the receipt is gone.
    Drop `reason = payload.reason` from the call site and the gate sees None forever,
    so this stays 409 while the success arm above turns red: the pair localises the
    break to the wiring rather than to the rule.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    toggle( True )

    response = _post( client, item, "in_progress", actor="maya 20467682" )

    assert response.status_code == 409, response.text
    assert "reason" in response.json()[ "detail" ]


def test_the_row_is_read_from_the_STORE_and_not_from_the_payload( client, repo, toggle ):
    """
    🔴 THE EXEMPTION MUST NOT BE SOMETHING THE CALLER CAN DECLARE.

    The actor string is already caller-supplied, which is this module's standing
    weakness. If the OWNER were caller-supplied too, the exemption would be a hole
    anybody could open by naming themselves. Here the stored row says owner=maya, and
    a caller posting an owner_persona of their own must not be able to move it.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    toggle( True )

    response = client.post(
        f"/api/tasks/{item.id}/transition",
        json={ "to_status": "in_progress", "actor": "rio 5f0c1a22",
               "owner_persona": "rio", "accountable_manager": "maria" },
    )

    assert response.status_code != 200, (
        "a caller declared themselves the owner and the exemption believed them"
    )
    # MEASURED 2026-09-07: it is a 422, not the 409 this test first expected, and the
    # 422 is the STRONGER answer -- the transition request model carries no
    # `owner_persona` / `accountable_manager` field at all, so the smuggled owner is
    # refused before the gate is even reached. Pinned as the exact code rather than
    # softened to "not 200", so that if the model ever gains those fields this test
    # reddens and whoever widened it has to come and think about this exemption.
    assert response.status_code == 422, (
        f"the transition payload now accepts an owner field (got "
        f"{response.status_code}) -- re-check that the exemption still reads the "
        f"STORED row and not the caller's claim"
    )
