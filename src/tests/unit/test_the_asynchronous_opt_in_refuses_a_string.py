#!/usr/bin/env python3
"""
THE ASYNCHRONOUS OPT-IN, DRIVEN THROUGH THE ASSEMBLED APP — a string must not opt in.

🔴 WHY THIS FILE EXISTS. The asynchronous promotion path (row `3493ae9b`) returns `202`
with a ticket instead of holding the request open while Rick thinks. **A 202 is a FALSE
GREEN in every browser client**: `fetch`'s `response.ok` is `status >= 200 && < 300`, so
`ApiClient.request` does not throw, `HoldingAreaStore` returns `{ ok: true }`, and
`TaskListStore` leaves the optimistic "approved" row state it wrote BEFORE the call. The
UI would report a promotion Rick has not been asked about yet — a false FACT, not a false
red, which is the species nobody goes and investigates.

⇒ So the new status code is **opt-in**, and the opt-in must be unreachable by accident.

🔴 THE ARGUMENT THAT IT WAS UNREACHABLE WAS WRONG, AND THAT IS WHAT THIS FILE PINS.
It ran: the browser stores spread `...extras` into the body, `extras` is typed
`Record<string, string>`, and a boolean cannot be placed in one. **True about the type and
irrelevant** — that map carries the STRING `"true"` perfectly well, and a plain pydantic
`bool` COERCES it. Found by Tiffany 💍 in review; the hole and the relocation below are
hers, the original overclaim was mine.

⚠️ AND THE GUARANTEE HAD TO CHANGE LAYERS, WHICH IS THE DURABLE HALF. The first defence
lived in the CLIENT'S type system — and `notifications.js` is vanilla JS with no type
system at all, so it covered one of the two client layers and left the other bare. The
check below is at the SERVER, where both layers must pass.

🔴 WHY IT DRIVES THE ASSEMBLED APP RATHER THAN CONSTRUCTING `TaskTransitionIn`. A model
test proves the model refuses a string. It CANNOT prove the app mounts that model on that
route — a component can be complete, correct, fully covered and never reached. The
measurement that produced this rule used a scratch pydantic model; a scratch model
answering correctly is exactly what would let a real endpoint be wrong. So: real app, real
route, real request.

🔴 WHY `JWT_SECRET_KEY` IS SET AT MODULE SCOPE AND NOT IN A FIXTURE. `jwt_service.py`
raises AT IMPORT when it is unset, and the repo-root `.env` that supplies it on this host
is gitignored — present in the main checkout, absent from every worktree. A fixture runs
at execution time, AFTER the collection-time import that needs it. The value is a
throwaway: nothing here signs or verifies a token, and a real secret must never be copied
into a tree that gets `rm -rf`'d.

VENUE: `:7999`. No persistent-state mutation (the repository is a `MagicMock`), well under
two minutes, no monopoly.
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
NOW             = datetime( 2026, 9, 6, 0, 0, tzinfo=timezone.utc )
MANAGER         = "mr radio 21dff055"

# Every value a `Record<string, string>` could plausibly carry, plus the numeric forms a
# non-TypeScript caller could send. A plain `bool` coerces ALL of these to a real boolean.
COERCIBLE_TRUTHY = [ "true", "True", "TRUE", "1", 1, "yes", "on" ]
COERCIBLE_FALSY  = [ "false", "False", "0", 0, "no" ]


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
        - fails loudly if the transition route is absent, because a guard that cannot
          find its door must not report a pass
    """
    import lupin_app.main as main

    app   = main.app
    paths = { getattr( route, "path", None ) for route in app.routes }
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
def client( assembled_app, repo ):
    assembled_app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    yield TestClient( assembled_app, raise_server_exceptions=False )
    assembled_app.dependency_overrides.pop( require_api_key_or_jwt, None )


def _post( client, item, **body_extras ):
    body = { "to_status": "queued", "actor": MANAGER, "authority": "standing" }
    body.update( body_extras )
    return client.post( f"/api/tasks/{item.id}/transition", json=body )


# ---------------------------------------------------------------------------
# The kill: a string must NOT opt in
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "value", COERCIBLE_TRUTHY )
def test_a_truthy_string_is_REFUSED_by_the_real_endpoint( client, repo, value ):
    """
    `asynchronous: "true"` (and every sibling a plain bool would coerce) is a 422.

    🔴 THIS IS THE ARM THE OPT-IN ARGUMENT RESTS ON. Relax the model field from
    `StrictBool` to `bool` and every one of these is ACCEPTED and coerced to True — the
    browser's `Record<string, string>` opts itself in silently, and the false green is
    live.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item

    response = _post( client, item, asynchronous=value )

    assert response.status_code == 422, (
        f"asynchronous={value!r} was accepted with {response.status_code} — a coercible "
        f"value reached the opt-in. The field is not StrictBool, and a browser spreading "
        f"a Record<string,string> into the body can now opt itself into a 202 it reads "
        f"as success."
    )


@pytest.mark.parametrize( "value", COERCIBLE_FALSY )
def test_a_falsy_string_is_ALSO_refused_not_quietly_read_as_no( client, repo, value ):
    """
    `"false"` must be refused too, and this is a SEPARATE claim from the one above.

    A field that rejects `"true"` but silently accepts `"false"` is still coercing — it
    just happens to land on the safe answer today. It would start opting callers in the
    moment the sense of the flag is ever inverted, and nothing would have warned anybody.
    Rejecting BOTH is what makes the type the guarantee rather than the outcome.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item

    assert _post( client, item, asynchronous=value ).status_code == 422


# ---------------------------------------------------------------------------
# The controls — without these the 422s above prove only that the door can refuse
# ---------------------------------------------------------------------------

def test_a_REAL_boolean_is_accepted_so_the_refusals_above_are_about_the_TYPE( client, repo ):
    """
    POSITIVE CONTROL. A guard that refuses everything is not a type check, it is a
    broken endpoint — and it would satisfy every assertion above.

    ⚠️ `asynchronous=False` rather than `True`: this file pins the WIRE CONTRACT, not the
    behaviour behind it. Sending `True` would exercise the async path once it exists and
    make this guard's meaning drift when stage 2 lands. `False` is a real boolean, so it
    proves the field accepts its declared type, and it asks for nothing.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value     = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=MANAGER,
        transition=f"{approval.NOT_APPROVED_STATUS}->queued", authority="standing",
    )

    response = _post( client, item, asynchronous=False )

    assert response.status_code != 422, (
        f"a real boolean was refused with {response.status_code} — the field rejects its "
        f"own declared type, so the refusals above say nothing about strictness"
    )


def test_omitting_the_field_entirely_is_still_accepted( client, repo ):
    """
    SECOND POSITIVE CONTROL, and it is the one that matters for every existing caller.

    Nobody sends this field today. If declaring it broke the un-declared case, every
    browser transition and every MCP `task_transition` would start failing — and the two
    parametrized tests above would still be perfectly green.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value     = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=MANAGER,
        transition=f"{approval.NOT_APPROVED_STATUS}->queued", authority="standing",
    )

    assert _post( client, item ).status_code != 422


def test_an_unknown_field_is_still_forbidden( client, repo ):
    """
    THIRD CONTROL: `extra="forbid"` still holds after adding a field to the model.

    It is what protected this endpoint before `asynchronous` existed, and a reader should
    be able to see that adding one named field did not open the model generally.
    """
    item = _item()
    repo.get_by_id_for_update.return_value = item

    assert _post( client, item, asynchronous_typo=True ).status_code == 422


# ---------------------------------------------------------------------------
# The decision function: both gates, and the caller's is the load-bearing one
# ---------------------------------------------------------------------------

def test_the_operator_flag_defaults_OFF_so_an_absent_config_stays_synchronous():
    """
    An absent or unreadable key must land on TODAY's behaviour.

    ⚠️ This is the OPPOSITE of `get_enforcement_active`'s fail-open, deliberately: that
    one must not start refusing promotions when its config vanishes; this one must not
    start handing out a status code existing callers misread as success.
    """
    assert gate.FALLBACK_ASYNCHRONOUS is False
    assert gate.promotion_is_asynchronous( True, enabled_fn=lambda: False ) is False


def test_both_gates_are_required_and_neither_alone_suffices():
    """
    Flag AND caller. Four combinations, and exactly one of them is asynchronous.
    """
    on, off = ( lambda: True ), ( lambda: False )

    assert gate.promotion_is_asynchronous( True,  enabled_fn=on  ) is True
    assert gate.promotion_is_asynchronous( True,  enabled_fn=off ) is False
    assert gate.promotion_is_asynchronous( False, enabled_fn=on  ) is False
    assert gate.promotion_is_asynchronous( False, enabled_fn=off ) is False


def test_a_caller_that_said_nothing_gets_the_synchronous_path():
    """`None` is what every caller sends today, and it must not opt anyone in."""
    assert gate.promotion_is_asynchronous( None, enabled_fn=lambda: True ) is False


@pytest.mark.parametrize( "value", [ "true", "True", "1", 1, "yes", "on", [ 1 ], { "a": 1 } ] )
def test_a_non_boolean_reaching_the_decision_anyway_is_NOT_a_request( value ):
    """
    DEFENCE IN DEPTH, and it is not redundant with the model.

    `promotion_is_asynchronous` is a public function; the model is not the only thing
    that can call it. If it tested truthiness, a caller passing the string "true" — the
    exact value `StrictBool` exists to refuse — would be opted in one layer down, and the
    wire-level guard above would still be perfectly green.

    ⚠️ The truthy AND the falsy cases are both here on purpose: `[1]` and `{"a": 1}` are
    truthy non-booleans, and they are the ones a truthiness test would let through.
    """
    assert gate.promotion_is_asynchronous( value, enabled_fn=lambda: True ) is False
