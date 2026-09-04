#!/usr/bin/env python3
"""
THE BROWSER'S ACTOR, DRIVEN AT THE DOOR IT WAS REFUSED AT.

Row 9d3a975e (P0). Rick clicked Approve on a holding-area row on 2026-09-03 at
23:24 and got:

    'operator foolish goat' is not an approver — admitting a row out of
    'not_approved' is limited to ['cheech', 'maria', 'mr radio', 'rick'].

The browser builds that actor per WEBSOCKET SESSION, so no fixed allowlist entry
can ever match it and no session id is derivable from it. Rick ruled 2026-09-04
that the browser MUST be able to satisfy this gate.

WHY THIS FILE EXISTS ALONGSIDE THE THREE THAT ALREADY TOUCH THIS DOOR.
`test_task_approval_gate.py` proves the PREDICATE refuses a non-approver.
`test_the_transition_door_calls_the_approval_gate.py` proves the CALL SITE is
wired. Both are correct and both stay green while Rick cannot approve, because
neither one asks the only question the incident asked: **does the string the
BROWSER actually sends get through this door?** They supply their own actors
("somebody else 9999", "maria 611e3c47"). This file supplies the client's.

⇒ So the actor here is not hand-written. It is READ OUT OF THE SHIPPED CLIENT on
every run (`src/lupin_app/static/js/notifications.js`), which is what makes this
a guard rather than a restatement: change the client's identity story and this
file follows it, or says out loud that it cannot.

🔴 HOW IT REDDENS, AND IT IS DELIBERATELY NOT ONE WAY.
  · the client keeps sending a per-session string  → the door 403s → RED here
  · the client starts sending something this file cannot render → RED, naming
    the expression, because a guard that silently stops evaluating the real
    actor is worse than no guard (§A CLEAN EXIT IS NOT EVIDENCE THE WORK
    HAPPENED — a step that cannot finish must decline and say what it did not do)

⚠️ WHAT THIS FILE DOES NOT COVER, said plainly. It asserts NOTHING about
manager-hood: the promotion gate is a second door on this route and is stood
down here exactly as `test_the_transition_door_calls_the_approval_gate.py`
stands it down, for the same reason and with the same seam. A reader who takes
this file as evidence the whole door works is reading one leg. It also asserts
nothing about the BROADCAST leg of row 9d3a975e — that one is a browser-side
credential defect and is guarded in
`src/tests/unit/nav/the_logged_in_indicator_must_not_accept_a_token_the_server_refuses.test.ts`.
"""
import json
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime   import datetime, timezone
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

NOW = datetime( 2026, 9, 4, 0, 0, tzinfo=timezone.utc )

# The client file, resolved from LUPIN_ROOT at CALL time so a worktree reads its OWN
# tree (§A TIER RUN FROM A WORKTREE). Never from __file__ chains.
CLIENT_JS = os.path.join(
    os.environ.get( "LUPIN_ROOT", os.getcwd() ),
    "src", "lupin_app", "static", "js", "notifications.js",
)

# The `${...}` holes this file knows how to fill, and the value it fills each with.
# A hole that is NOT in here is a client change this guard has not been taught —
# it fails loudly rather than guessing (§a pointer that cannot fail is a pointer
# that silently lands in the wrong place).
RENDERABLE_HOLES = {
    # notifications.js assigns queueSessionId an "adjective noun" websocket session
    # name. "foolish goat" is the one Rick's browser held at 23:24 on 2026-09-03 —
    # the actual value from the incident, not an invented one.
    'this.queueSessionId || "browser"' : "foolish goat",
    "this.queueSessionId || 'browser'" : "foolish goat",
    "this.queueSessionId"              : "foolish goat",
}


def actor_the_client_sends():
    """
    The actor string the shipped browser client puts on POST /api/tasks/{id}/transition.

    Requires:
        - notifications.js is readable at CLIENT_JS

    Ensures:
        - returns the rendered actor string
        - raises AssertionError naming what it found when the client's `_transitionTask`
          body carries zero or more than one `actor` field, or when the expression
          contains a `${...}` hole this guard has not been taught
        - never returns a value it had to guess at
    """
    source = open( CLIENT_JS, encoding="utf-8" ).read()

    # Narrow to the one method, so an `actor` field on some OTHER request cannot be
    # mistaken for this one (§A HIT IS NOT A USE — the name travels further than the use).
    start = source.find( "async _transitionTask(" )
    assert start != -1, (
        f"{CLIENT_JS} no longer defines `_transitionTask`. This guard reads the "
        f"browser's actor out of that method; teach it the new call site."
    )
    end = source.find( "\n    }", start )
    body = source[ start : end if end != -1 else start + 4000 ]

    hits = re.findall( r"^\s*actor\s*:\s*(.+?),\s*$", body, re.MULTILINE )
    assert len( hits ) == 1, (
        f"expected EXACTLY ONE `actor:` field inside _transitionTask, found "
        f"{len( hits )}: {hits!r}. Two actor sources means this guard is reporting "
        f"on one of them and the door may be reached by the other."
    )
    expr = hits[ 0 ].strip()

    # A bare quoted string needs no rendering.
    if ( expr.startswith( '"' ) and expr.endswith( '"' ) ) or ( expr.startswith( "'" ) and expr.endswith( "'" ) ):
        return expr[ 1:-1 ]

    assert expr.startswith( "`" ) and expr.endswith( "`" ), (
        f"the client's actor expression is {expr!r}, which this guard cannot render. "
        f"It is NOT asserting anything about the real actor right now. Teach "
        f"RENDERABLE_HOLES how to evaluate it, or replace this extractor."
    )
    rendered = expr[ 1:-1 ]
    for hole in re.findall( r"\$\{([^}]*)\}", rendered ):
        key = hole.strip()
        assert key in RENDERABLE_HOLES, (
            f"the client's actor expression contains ${{{key}}}, which this guard has "
            f"not been taught to fill. It is NOT asserting anything about the real "
            f"actor right now. Add it to RENDERABLE_HOLES with the value a logged-in "
            f"operator would carry."
        )
        rendered = rendered.replace( "${" + hole + "}", RENDERABLE_HOLES[ key ] )
    return rendered


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "bug",
        title               = "a row waiting in the holding area",
        body                = None,
        project             = "lupin",
        owner_persona       = "maria",
        accountable_manager = "maria",
        created_by          = "maria 4f98d12f",
        status              = "not_approved",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P0",
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
    """The router's db seams, faked."""
    fake = MagicMock()
    fake.statuses_for_ids.return_value = { }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def client( repo, monkeypatch ):
    """
    ⚠️ THE PROMOTION GATE IS STOOD DOWN, AND THAT IS NOT THIS FILE'S SUBJECT.
    It is a SECOND door on this route which asks Rick by voice. A unit test must not
    reach a live ask, and manager-hood is guarded in `test_manager_figure.py`. The
    stand-down is conditional on the seam EXISTING and says so, rather than hiding
    behind raising=False, which would no-op silently if the seam were renamed.
    """
    gate = getattr( tasks, "promotion_gate", None )
    if gate is not None:
        from cosa.rest.task_promotion_gate import PromotionApproval
        monkeypatch.setattr( gate, "approval_for_promotion",
                             lambda *a, **k: PromotionApproval( allowed=True,
                                                               approval_source="stubbed-for-this-file" ) )
    app = FastAPI()
    app.include_router( tasks.router )
    # A LOGGED-IN OPERATOR. This is the whole premise of Rick's report: the request
    # authenticates, and is then refused on identity anyway.
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"
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


def _post( client, item, actor, to_status="queued" ):
    return client.post( f"/api/tasks/{item.id}/transition",
                        json={ "to_status": to_status, "actor": actor, "authority": "user_direct" } )


def test_the_isolation_actually_isolates( settings ):
    """Runs first. Without it a green file is also consistent with reading the real fleet settings."""
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()


def test_the_guard_can_read_the_clients_actor_at_all( ):
    """
    The positive control on the EXTRACTOR, and it is not optional: every assertion
    below is about a string this function produced, so a function that quietly
    returned nothing useful would make the rest of the file vacuous
    (§AN EMPTY RESULT IS TWO DIFFERENT FAILURES WEARING ONE FACE).
    """
    actor = actor_the_client_sends()
    assert isinstance( actor, str ) and actor.strip(), f"extractor produced {actor!r}"
    assert len( actor ) >= 3, f"extractor produced an implausibly short actor: {actor!r}"


def test_the_browser_actor_is_not_refused_by_the_approver_gate( client, repo, settings ):
    """
    🔴 THE ONE THIS FILE EXISTS FOR — Rick's click, at the layer it entered at.

    A request, not a function call. The actor is the shipped client's own, and the
    caller is authenticated. Under Rick's 2026-09-04 ruling this MUST get through.
    """
    _write( settings, approvers=[ "cheech", "maria", "mr radio", "rick" ], enforcement_active=True )
    item = _item( status="not_approved" )
    repo.get_by_id_for_update.return_value = item

    actor = actor_the_client_sends()
    r     = _post( client, item, actor )

    assert not ( r.status_code == 403 and "not an approver" in str( r.json().get( "detail", "" ) ) ), (
        f"THE BROWSER STILL CANNOT APPROVE FROM THE HOLDING AREA (row 9d3a975e). "
        f"An authenticated operator's request carrying the client's own actor "
        f"{actor!r} was refused: {r.json().get( 'detail' )}"
    )


def test_the_gate_still_refuses_somebody_who_is_genuinely_not_an_approver( client, repo, settings ):
    """
    🔴 THE DISCRIMINATOR, AND WITHOUT IT THE TEST ABOVE IS WORTHLESS. Deleting the
    gate entirely, or emptying the allowlist, makes the test above pass. This is the
    arm that says the door still refuses somebody — one variable changes, the actor.
    """
    _write( settings, approvers=[ "cheech", "maria", "mr radio", "rick" ], enforcement_active=True )
    item = _item( status="not_approved" )
    repo.get_by_id_for_update.return_value = item

    r = _post( client, item, "some worker 9999" )

    assert r.status_code == 403, f"the door admitted a non-approver — the gate is not being called. Got {r.status_code}."
    assert "not an approver" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()
