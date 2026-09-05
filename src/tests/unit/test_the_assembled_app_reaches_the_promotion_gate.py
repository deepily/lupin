#!/usr/bin/env python3
"""
THE PROMOTION GATE'S WIRING, INTERROGATED ON THE APP `lupin_app.main` ACTUALLY ASSEMBLES.

WHY THIS FILE EXISTS, measured rather than supposed. The four guards around
`task_promotion_gate.py` — `test_promotion_out_of_holding_is_manager_only_and_asks_rick`,
`test_rick_approves_his_own_row_without_being_asked`, `test_no_manager_batches`,
`test_authority_is_an_enum_not_a_sentence` — are 51 tests and they are CORRECT. They
also pass with the gate COMPLETELY UNWIRED.

  Measured 2026-09-04 at 85bc417d, detached worktree:
      baseline                                                    51 passed
      unwire `approval_for_promotion` at tasks.py:1148             51 passed
      sha 0a4e5450e219 -> 698939bb9cd5, anchor matched exactly once

  Positive control, so that green is evidence and not silence: ZERO of those four
  files import `routers.tasks` at all, and the SAME mutation DOES break the
  router-level tests. The mutation is reachable; those guards never touch the wiring.

⇒ They establish that the gate's LOGIC is right. They cannot establish that the app
  ever CALLS it — which is the readiness question. This file is that second claim.

AND IT IS A DIFFERENT CLAIM FROM `test_the_transition_door_calls_the_approval_gate`,
which builds its own `FastAPI()` and mounts `tasks.router` into it. That proves the
HANDLER consults the gate. It cannot see `lupin_app.main` mounting a different router,
mounting it under another prefix, or a middleware short-circuiting the path. Here the
app under test is the one `main.py` assembles — 205 routes at this sha, carrying
POST `/api/tasks/{task_id}/transition`.

🔴 WHY `JWT_SECRET_KEY` IS SET AT MODULE SCOPE AND NOT IN A FIXTURE. `jwt_service.py:35`
raises AT IMPORT when the variable is unset, and the repo-root `.env` that supplies it on
this host is gitignored — so it is PRESENT in the main checkout and ABSENT in every
worktree. A fixture runs at execution time, after the collection-time import that needs
it, so a fixture cannot help. This mirrors the identical comment in
`src/cosa/tests/conftest.py`. The value is a throwaway: nothing here signs or verifies a
token, and a real secret must never be copied into a tree that gets `rm -rf`'d.
"""
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

# MUST precede the `lupin_app.main` import below — see the module docstring.
os.environ.setdefault( "JWT_SECRET_KEY", "test-only-not-a-real-secret" )

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from fastapi.testclient import TestClient

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as gate
from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

TRANSITION_PATH = "/api/tasks/{task_id}/transition"
NOW             = datetime( 2026, 9, 4, 0, 0, tzinfo=timezone.utc )
MANAGER         = "mr radio 21dff055"


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row waiting in the holding area",
        body                = None,
        project             = "lupin",
        owner_persona       = "pocholo",
        accountable_manager = "mr radio",
        created_by          = MANAGER,
        status              = approval.NOT_APPROVED_STATUS,
        priority            = "P2",
        urgency             = "normal",
        created_ts          = NOW,
        updated_ts          = NOW,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def assembled_app():
    """
    The app `lupin_app.main` builds, not one this test assembles.

    Ensures:
        - returns the real `app` object, with its own routers and middleware
        - fails loudly if the transition route is absent, because a test that
          cannot find its door must not report a pass
    """
    import lupin_app.main as main

    app   = main.app
    paths = { getattr( r, "path", None ) for r in app.routes }
    assert TRANSITION_PATH in paths, (
        f"the assembled app has no {TRANSITION_PATH} route — {len( app.routes )} routes "
        f"were mounted. This guard cannot speak to a door that is not there."
    )
    return app


@pytest.fixture
def repo( monkeypatch ):
    fake = MagicMock()

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def enforcement_on( tmp_path, monkeypatch ):
    """
    Enforcement is forced ON INSIDE THE TEST, never in `lupin-app.ini`.

    Putting the gate into service is outward-facing and Rick's word alone; a test
    must not make that call on his behalf.
    """
    monkeypatch.setattr( approval, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( approval, "approver_persona_for_account", lambda email: "mr radio" )
    return True


@pytest.fixture
def client( assembled_app, repo, enforcement_on ):
    assembled_app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    yield TestClient( assembled_app, raise_server_exceptions=False )
    assembled_app.dependency_overrides.pop( require_api_key_or_jwt, None )


def _post( client, item, to_status="queued" ):
    return client.post(
        f"/api/tasks/{item.id}/transition",
        json={ "to_status": to_status, "actor": MANAGER, "authority": "standing" },
    )


def test_the_assembled_app_CONSULTS_the_promotion_gate( client, repo, monkeypatch ):
    """
    A promotion out of the holding area, driven as a REAL request against the app
    `main.py` assembled, reaches `approval_for_promotion`.

    RED ON REVERT: delete or bypass the gate call at `tasks.py:1148` and the spy is
    never invoked. That is the revert the four module-level guards cannot see.

    ⚠️ This asserts the CALL, not a downstream effect several paths could produce —
    a shared observable cannot tell you which path reached it.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value     = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=MANAGER,
        transition=f"{approval.NOT_APPROVED_STATUS}->queued", authority="standing",
    )

    calls = []
    real  = gate.approval_for_promotion

    def _spy( **kwargs ):
        calls.append( kwargs )
        return real( **kwargs )

    monkeypatch.setattr( gate, "approval_for_promotion", _spy )

    _post( client, item )

    assert calls, (
        "the assembled app served a promotion out of the holding area WITHOUT consulting "
        "the promotion gate — the call site at tasks.py:1148 is gone or bypassed"
    )


def test_the_assembled_app_HONOURS_the_gates_refusal( client, repo, monkeypatch ):
    """
    The gate being CALLED is not the same claim as its refusal being OBEYED.

    A build that consults the gate and then ignores `allowed=False` passes the test
    above and still promotes the row. Two claims, two tests, on purpose.

    RED ON REVERT: drop the `if not promotion_approval.allowed: raise HTTPException(403)`
    and the transition is applied despite a refusal.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item

    # The real shape is ( allowed, refusal, approval_source ). Constructed directly and
    # NOT behind a hasattr/skip: a guard that skips itself when the symbol moves reports
    # a pass it never earned, which is the failure mode this whole file exists to catch.
    refusal = gate.PromotionApproval(
        allowed         = False,
        refusal         = "refused by this test, deliberately",
        approval_source = None,
    )

    monkeypatch.setattr( gate, "approval_for_promotion", lambda **kw: refusal )

    response = _post( client, item )

    assert response.status_code == 403, (
        f"the gate refused and the assembled app answered {response.status_code}, not 403"
    )
    repo.apply_transition.assert_not_called()
