#!/usr/bin/env python3
"""
THE REFUSAL NOBODY HAD WATCHED — the approval gate exercised through the HTTP door
against the LIVE configuration.

WHY THIS FILE EXISTS. Row `8af64f5a` has carried the same undischarged sentence since
it was written: **"Armed config is NOT a demonstrated refusal."** Its own condition on
Phase 3 was María's, and it is the right one — *an authorization check nobody has
watched refuse is not a control.* Every existing test of this gate
(`src/tests/unit/test_task_approval_gate.py`, 58 of them) proves the POLICY FUNCTION in
isolation, with the settings module pointed at a `tmp_path` and its INI keys blanked by
a fixture. Not one of them sends a request. So the suite could be entirely green while
the gate was never wired to the endpoint, or wired and unreachable, and the coverage
number would be true the whole time.

⚠️ WHAT MAKES THIS DIFFERENT FROM THE UNIT SUITE, precisely: this test does NOT patch
the settings module. It reads whatever the fleet actually ships — `get_enforcement_active()`,
`get_approvers()`, `default_mint_status()` — and skips itself, loudly and with the values
printed, if enforcement is off. **A test that silently passes because the feature is
disabled is worse than no test**, so the skip names the reason rather than reporting green.

🔴 AND WHAT IT IS NOT PROOF OF. The gate is a POLICY control, not a security boundary —
the endpoint's own comment says so (`routers/tasks.py`): `payload.actor` is
caller-DECLARED and every seat carries the same fleet credential, so this refuses an
HONEST non-approver and cannot stop a dishonest one. This file proves the refusal
happens and is reachable. It does not, and cannot, prove anybody is prevented.

VENUE: :7999-eligible, by the same reasoning as `test_task_reassign_parity_e2e.py` —
real Postgres round-trip inside an outer transaction that is rolled back at teardown, so
no row written here outlives the test. No server, no network.
"""
import os
import sys
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Bootstrap (conftest also does this; kept for direct-invocation parity)
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db import database as db_module
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest import task_approval_settings as approval


# A persona that is NOT on the approver list. Asserted below rather than assumed —
# the list is configuration and an editor could add this name tomorrow, at which point
# this test must fail loudly instead of quietly proving nothing.
NON_APPROVER = "rio 87e08fee"


@pytest.fixture
def txn_session( monkeypatch ):
    """
    A real Postgres Session joined to an OUTER transaction rolled back at teardown, so
    the create and transition seams see each other's writes yet NOTHING persists.

    Same pattern as `test_task_reassign_parity_e2e.py` — deliberately copied rather than
    re-invented, because a bespoke isolation fixture is how a test ends up writing to the
    live fleet's board.
    """
    connection = db_module.engine.connect()
    outer      = connection.begin()
    session    = Session( bind=connection, join_transaction_mode="create_savepoint" )

    @contextmanager
    def _shared_get_db():
        try:
            yield session
            session.commit()             # → RELEASE SAVEPOINT; visible within the outer txn
        except Exception:
            session.rollback()           # → ROLLBACK TO SAVEPOINT only
            raise
        # deliberately NOT closed — the next get_db() block reuses this session

    monkeypatch.setattr( tasks, "get_db", _shared_get_db )
    yield session

    session.close()
    outer.rollback()                     # discard every savepoint — zero persistent state
    connection.close()


@pytest.fixture
def client( txn_session ):
    """TestClient over the real tasks router, auth overridden (this tests policy, not auth)."""
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


@pytest.fixture
def live_config():
    """
    The SHIPPED values, unpatched — and a skip that names them if the gate is off.

    ⇒ This fixture is the whole point of the file. The unit suite controls these values;
    this one reports them.
    """
    enforcing = approval.get_enforcement_active()
    approvers = sorted( approval.get_approvers() )
    if not enforcing:
        pytest.skip(
            f"approval enforcement is OFF in the live config (approvers={approvers}) — "
            f"a refusal cannot be demonstrated against a disabled gate, and reporting "
            f"green here would be the exact false comfort this file exists to remove"
        )
    # PRECONDITION, not an assumption: the persona this test refuses must actually be
    # off the list. If somebody adds it, this fails here with a clear cause rather than
    # further down as a mysterious 200.
    assert not approval.is_approver( NON_APPROVER ), (
        f"'{NON_APPROVER}' is ON the approver list {approvers} — this test can no longer "
        f"demonstrate a refusal. Pick a persona that is genuinely not an approver."
    )
    return { "enforcing": enforcing, "approvers": approvers }


def _create_row( client, **overrides ):
    """Mint a row through the real endpoint. P0 so the flow-ratio gate cannot refuse it."""
    body = {
        "item_class" : "task",
        "title"      : "approval-gate refusal probe (e2e)",
        "project"    : "lupin",
        "created_by" : NON_APPROVER,
        "priority"   : "P0",
    }
    body.update( overrides )
    r = client.post( "/api/tasks", json=body )
    assert r.status_code == 201, f"{r.status_code}: {r.text}"
    return r.json()


def _transition( client, task_id, to_status, actor, **extra ):
    body = { "to_status": to_status, "actor": actor, "authority": "standing" }
    body.update( extra )
    return client.post( f"/api/tasks/{task_id}/transition", json=body )


def test_a_create_that_names_no_status_lands_in_the_HOLDING_AREA( client, live_config ):
    """
    Phase 4's flip, observed through the door instead of read off a config line.

    The row body's ordering rule was "do not ship the writer before the reader"; this is
    the writer, live. `default_mint_status()` is read at CALL time, so this asserts the
    behaviour of the running process rather than a value frozen at import.
    """
    if approval.default_mint_status() != "not_approved":
        pytest.skip( "the holding-area default is OFF in the live config — nothing to observe" )

    item = _create_row( client )
    assert item[ "status" ] == "not_approved", (
        f"a create naming no status minted '{item['status']}' — the holding-area default "
        f"is on in config but the create path is not honouring it"
    )


def test_a_NON_APPROVER_IS_ACTUALLY_REFUSED_through_the_HTTP_door( client, live_config ):
    """
    🔴 THE LOAD-BEARING TEST IN THIS FILE. A real request, the live approver list, and a
    403 nobody had ever watched arrive.

    Everything else here exists to stop this one passing for the wrong reason: the
    positive control below proves the same request SUCCEEDS for an approver, so the 403
    cannot be coming from a malformed payload, an illegal transition, or a missing row.
    """
    item = _create_row( client, status="not_approved" )

    # ── THE REFUSAL ──────────────────────────────────────────────────────────────
    r = _transition( client, item[ "id" ], "queued", NON_APPROVER )
    assert r.status_code == 403, (
        f"expected 403, got {r.status_code}: {r.text}\n"
        f"a non-approver was NOT refused — the gate is armed in config "
        f"(approvers={live_config['approvers']}) but is not stopping this request"
    )
    detail = r.json()[ "detail" ]
    assert "is not an approver" in detail
    # The refusal must say WHERE the list lives, or an operator has a 403 and no recourse.
    assert "task approval approver personas" in detail

    # The row did NOT move. A 403 that still applied the transition would be worse than
    # no gate at all, and nothing above this line would have noticed.
    after = client.get( f"/api/tasks/{item['id']}" )
    assert after.status_code == 200, f"{after.status_code}: {after.text}"
    assert after.json()[ "status" ] == "not_approved", (
        "the request was refused with 403 but the status moved anyway"
    )

    # ── POSITIVE CONTROL: the same request, an approver, must SUCCEED ─────────────
    approver = live_config[ "approvers" ][ 0 ]
    r = _transition( client, item[ "id" ], "queued", approver,
                     reason="admitted by the e2e positive control" )
    assert r.status_code == 200, (
        f"approver '{approver}' was refused ({r.status_code}: {r.text}) — without this "
        f"leg the 403 above proves nothing, since a gate that refuses EVERYBODY would "
        f"pass the first half of this test"
    )


def test_WONT_FIX_is_refused_from_an_ordinary_status_too_not_just_the_holding_area( client, live_config ):
    """
    Won't-fix is approver-only from EVERY source status, and that breadth is the control
    rather than tidiness: `wont_fix` counts toward the create/close ratio where `dropped`
    does not, so a seat able to close rows this way would hold both halves of a
    mint-by-deletion loop — close to raise the closed count, then create against the
    headroom it just manufactured.

    The unit suite asserts this on the policy function. This asserts it on the endpoint.
    """
    item = _create_row( client, status="queued" )

    r = _transition( client, item[ "id" ], "wont_fix", NON_APPROVER,
                     reason="probing the gate from an ordinary status" )
    assert r.status_code == 403, (
        f"expected 403, got {r.status_code}: {r.text}\n"
        f"won't-fix was NOT gated from 'queued' — the mint-by-deletion loop is open"
    )
    assert "closing a row as 'wont_fix'" in r.json()[ "detail" ]

    after = client.get( f"/api/tasks/{item['id']}" )
    assert after.json()[ "status" ] == "queued", "refused with 403 but the row closed anyway"


def test_an_ordinary_transition_is_NOT_gated( client, live_config ):
    """
    THE NEGATIVE CONTROL FOR THE WHOLE FILE. A non-approver moving a row queued →
    in_progress must still work.

    Without this, every assertion above is consistent with the gate refusing every
    transition from everybody — which would be a broken board, not a working control,
    and all three tests would still be green.
    """
    item = _create_row( client, status="queued" )

    r = _transition( client, item[ "id" ], "in_progress", NON_APPROVER,
                     reason="ordinary work, no approval required" )
    assert r.status_code == 200, (
        f"a non-approver was refused an ORDINARY transition ({r.status_code}: {r.text}) — "
        f"the gate is over-broad and the board is closed to everyone but approvers"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# THE HOLDING AREA IS A GATE, AND A GATE THAT LEAKS INTO THE BOARD IS NOT A GATE
# ═══════════════════════════════════════════════════════════════════════════════
#
# P0 46799ba3, reported by Rick 2026-09-03: ticket 0ab1a095 appeared in BOTH the
# holding area and the live queue. One row, one status — so no pane was rendering a
# duplicate; the BOARD QUERY ITSELF returned it, measured against the live server.
#
# 🔴 THE MECHANISM, and it is not a missing filter. `_apply_owed_filter` excludes
# BOARD_INVISIBLE_STATUSES and then deliberately RE-ADMITS
# `and_( status == NOT_APPROVED_STATUS, ~holding_is_active_clause( ... ) )` — Rick's
# 2026-09-02 self-expiry ruling: a held row hides only while its triage chase is
# still in the future. `holding_is_active_clause` requires `next_chase_ts IS NOT NULL
# AND > now`, so a row with NO chase is "not actively holding" and comes straight back
# onto the board.
#
# ⚠️ AND NOTHING SETS A CHASE WHEN A ROW IS MINTED INTO HOLDING — on create,
# `next_chase_ts` comes only from the payload and defaults to None. So this is not one
# unlucky row: EVERY held row is born chase-less, and the gate is inert by construction.
#
# ⚠️ WHY THESE ARMS LIVE HERE AND NOT IN THE UNIT SUITE. `test_tasks_router.py` covers
# this endpoint well and CANNOT see this defect: it mocks the repository and asserts
# which flags reach it. The bug is in the SQL predicate BELOW that mock. These arms
# drive the real filter against a real session, which is the layer the incident
# entered at.
#
# ⚠️ AND THE PAIR IS THE POINT — one variable, nothing else. A single chase-less arm
# would also pass against a board query that had simply stopped returning anything.

def _board( client ):
    """The board query the dashboard actually polls — see shared/task-list-query.js."""
    r = client.get( "/api/tasks?limit=500&unscoped_audit=true&hide_parked=false&char_budget=0" )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    payload = r.json()
    return payload.get( "tasks", payload if isinstance( payload, list ) else [] )


def _holding( client ):
    r = client.get( "/api/tasks?limit=500&unscoped_audit=true&status=not_approved&char_budget=0" )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    payload = r.json()
    return payload.get( "tasks", payload if isinstance( payload, list ) else [] )


def test_a_held_row_with_NO_triage_chase_stays_OFF_the_live_board( client ):
    """
    🔴 RICK'S ROW, REDUCED TO ITS ONE VARIABLE. This is the arm that was RED when the
    P0 was filed, and it is the whole finding: a held row carrying no chase was being
    served to the board, so unapproved work appeared where people look for approved
    work and could be started by someone who never saw the gate.
    """
    held = _create_row( client, status="not_approved", title="held, NO chase" )

    board_ids = { t[ "id" ] for t in _board( client ) }

    assert held[ "id" ] not in board_ids, (
        f"a not_approved row with no triage chase was returned by the BOARD query. "
        f"The holding area is the gate for all new work; a board that shows held rows "
        f"presents unapproved work as live work."
    )


def test_the_same_held_row_IS_in_the_holding_area( client ):
    """
    POSITIVE CONTROL, and the arm above is unreadable without it. 'Absent from the
    board' is satisfied perfectly by a row that was never stored, by a broken query,
    and by a fix that hides held rows everywhere — which would lose them.
    """
    held = _create_row( client, status="not_approved", title="held, NO chase" )

    holding_ids = { t[ "id" ] for t in _holding( client ) }

    assert held[ "id" ] in holding_ids, (
        "the held row is missing from the HOLDING AREA — it has not been gated, it has "
        "been lost, which is worse than the defect this file is about"
    )


def test_a_held_row_WITH_A_FUTURE_CHASE_is_also_off_the_board( client ):
    """
    THE SECOND MEMBER OF THE PAIR — the same assertion with the one variable flipped.

    This arm ALREADY PASSED before the fix, and saying so is the point: it is what
    proves the filter was never broken. The re-admission branch works exactly as
    designed whenever a chase exists; what was missing was any chase at all.
    """
    future = ( datetime.now( timezone.utc ) + timedelta( days=3 ) ).isoformat()
    held   = _create_row( client, status="not_approved", title="held, FUTURE chase",
                          next_chase_ts=future )

    assert held[ "id" ] not in { t[ "id" ] for t in _board( client ) }
    assert held[ "id" ] in     { t[ "id" ] for t in _holding( client ) }


def test_an_ORDINARY_queued_row_IS_on_the_board( client ):
    """
    🔴 THE ARM THAT MAKES THE OTHER THREE MEAN ANYTHING. Every assertion above is
    'not on the board', and a board query returning nothing at all satisfies all of
    them. This one fails if the fix hides more than it should.
    """
    ordinary = _create_row( client, status="queued", title="ordinary queued row" )

    assert ordinary[ "id" ] in { t[ "id" ] for t in _board( client ) }, (
        "an ordinary queued row vanished from the board — the holding filter is now "
        "excluding work that was never held"
    )
