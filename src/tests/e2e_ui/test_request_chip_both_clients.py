#!/usr/bin/env python3
"""
E2E — a manager's pending request on BOTH boards, and the verdict door refusing a non-operator.

Row c9fafb9d. A real pending `admit` request on a real `not_approved` row, read by the real
`GET /api/tasks`, rendered by the shipped bundle (multiplexer) and the shipped
`notifications.js` (legacy), answered through the real `POST /api/tasks/{id}/request-verdict`.
Nothing is intercepted.

WHAT THIS MEASURES, AND WHAT IT DOES NOT:
    - the chip shows on the holding-area row, with its move, its filer and its reason
    - the holding-area request badge counts it
    - Approve and Deny from a login that is not Rick's each reach the verdict door, come
      back 403 with the operator-alone refusal, and paint that refusal on the chip
    - neither click moves the row or answers the request

    It does NOT measure an approval performing the move. The verdict door answers only the
    account `task approval approver accounts` maps to an approver, and on :8000 that is
    Rick's email alone. Widening that list for a test was ruled out (Mr. Radio, 2026-09-10
    22:46), so the move-on-approval half stays with the unit and TS tiers.

⚠️ THE REQUEST IS SEEDED THROUGH THE STORE'S OWN WRITE PATH, NOT THE FILING DOOR. The filing
door's manager check resolves the caller through a live session bridge, and a scheduled run
has none of its own; borrowing a live manager's session id would stamp that seat's identity
on test rows. So the fixture runs the lifecycle's own filing refusals and then
`TaskRepository.apply_request_filing` — the call the door makes after its checks — with a
plain actor string. The DB columns are never written by hand (Mr. Radio, 22:50).

Venue: :8000 (scheduled) — seeds and deletes rows in lupin_db_test. Select with
`-k request_chip`.
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from playwright.sync_api import expect

from .conftest import BASE_URL

# Every row this file creates carries this created_by, so teardown deletes exactly these.
REQUEST_CHIP_MARKER = "e2e-request-chip@chloe"
REQUEST_FILER       = "e2e request filer"
REQUEST_REASON      = "E2E: a pending admit request shows its chip on both boards"
REQUEST_MOVE        = "admit"

# Pinned as a LITERAL, not imported from task_request_lifecycle: this is the text Rick reads,
# and an import would follow a rewording instead of noticing it.
OPERATOR_ALONE = (
    "recording a verdict on a promote/demote request is the operator's alone "
    "(Rick, 2026-09-08). A manager may FILE a request and read its state; the "
    "answer is his. Nothing about this request has changed."
)

CHIP_TIMEOUT_MS = 20_000


# ---------------------------------------------------------------------------
# Seeding — a real row, a real pending request, through the store's write path
# ---------------------------------------------------------------------------

def _require_test_db():
    from cosa.rest.db import database as db_module

    db_url = str( db_module.engine.url )
    assert "lupin_db_test" in db_url, \
        f"SAFETY: the request-chip E2E must only seed lupin_db_test, got: {db_url}"


def _delete_request_chip_rows():
    """
    Delete every task row this file created (its events cascade).

    Ensures:
        - no task_items row with created_by == REQUEST_CHIP_MARKER remains
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        for item in session.query( TaskItem ).filter( TaskItem.created_by == REQUEST_CHIP_MARKER ).all():
            session.delete( item )


def _seed_pending_admit_request():
    """
    Create a not_approved row and file a pending admit request on it.

    Requires:
        - the process's DB is lupin_db_test
        - no other row in the store carries a pending request, so the badge count is ours

    Ensures:
        - one TaskItem, status not_approved, request_state pending, request_move admit
        - one request_filed event whose actor is REQUEST_FILER and whose reason carries
          REQUEST_REASON
        - returns the row id as a string

    Raises:
        - AssertionError when the lifecycle refuses the filing, or another pending request
          exists — named, so a red here is not read as a rendering failure
    """
    import cosa.rest.task_request_lifecycle as request_lifecycle
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.task_repository import TaskRepository
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        others = session.query( TaskItem ).filter( TaskItem.request_state == "pending" ).count()
        assert others == 0, \
            f"PRECONDITION: {others} other row(s) already carry a pending request, so the badge count would not be this test's"

        item = TaskItem(
            item_class          = "task",
            title               = f"E2E request chip {uuid.uuid4().hex[ :8 ]}",
            project             = "lupin",
            created_by          = REQUEST_CHIP_MARKER,
            owner_persona       = None,
            accountable_manager = None,
            status              = "not_approved",
            blocked_by          = [ ],
            next_chase_ts       = datetime.now( timezone.utc ) + timedelta( days=2 ),
            priority            = "P3",
        )
        session.add( item )
        session.flush()
        task_id = item.id

    with get_db() as session:
        repo = TaskRepository( session )
        item = repo.get_by_id_for_update( task_id )
        assert request_lifecycle.refusal_for_filing( REQUEST_MOVE, item.status ) is None
        assert request_lifecycle.refusal_for_refiling( item.request_state, item.request_move ) is None
        repo.apply_request_filing(
            item      = item,
            move      = REQUEST_MOVE,
            actor     = REQUEST_FILER,
            authority = "standing",
            reason    = REQUEST_REASON,
        )

    return str( task_id )


def _row_state( task_id ):
    """The row's (status, request_state, request_move), read fresh from the DB."""
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        item = session.get( TaskItem, uuid.UUID( task_id ) )
        return ( item.status, item.request_state, item.request_move )


@pytest.fixture( scope="function" )
def pending_admit_request():
    """Seed one pending admit request; delete it afterwards, including after a crash."""
    _require_test_db()
    _delete_request_chip_rows()
    task_id = _seed_pending_admit_request()
    yield task_id
    _delete_request_chip_rows()


# ---------------------------------------------------------------------------
# The shared assertions — one body, so both clients are held to the same bar
# ---------------------------------------------------------------------------

def _assert_chip_and_badge( chip, badge ):
    expect( chip ).to_have_count( 1, timeout=CHIP_TIMEOUT_MS )
    expect( chip ).to_have_attribute( "data-request-move", REQUEST_MOVE )
    expect( chip.locator( ".task-request-text" ) ).to_contain_text( "Promote requested" )
    expect( chip.locator( ".task-request-detail" ) ).to_have_text(
        f"by {REQUEST_FILER} — {REQUEST_REASON}", timeout=CHIP_TIMEOUT_MS
    )
    expect( badge ).to_be_visible( timeout=CHIP_TIMEOUT_MS )
    expect( badge ).to_have_text( "1 request" )


def _assert_verdict_refused( page, chip, task_id, button_class, verdict ):
    """
    Click one verdict button and prove THIS click was refused.

    ⚠️ THE NETWORK ASSERTION IS THE DISCRIMINATING ONE. After Approve, the chip already reads
    the refusal, so a status assertion alone would pass for a Deny that never sent anything.
    The status line is blanked before the click to narrow that further, but a poll repaint
    can restore a remembered refusal — so the response is what names the path: a POST to this
    row's verdict door, carrying this verdict, answered 403 with this text.
    """
    status = chip.locator( ".task-request-status" )
    status.evaluate( "el => { el.textContent = '' }" )

    verdict_path = f"/api/tasks/{task_id}/request-verdict"
    with page.expect_response(
        lambda r: r.url.endswith( verdict_path ) and r.request.method == "POST",
        timeout = CHIP_TIMEOUT_MS,
    ) as answer:
        chip.locator( button_class ).click()

    response = answer.value
    assert response.status == 403, f"{verdict}: expected 403, got {response.status} {response.text()}"
    assert response.request.post_data_json[ "verdict" ] == verdict
    assert response.json()[ "detail" ] == OPERATOR_ALONE

    expect( status ).to_have_text( OPERATOR_ALONE, timeout=CHIP_TIMEOUT_MS )
    expect( chip.locator( ".task-request-approve" ) ).to_be_enabled()
    expect( chip.locator( ".task-request-deny" ) ).to_be_enabled()
    assert _row_state( task_id ) == ( "not_approved", "pending", REQUEST_MOVE ), \
        f"{verdict}: a refused verdict moved the row or answered the request"


# ---------------------------------------------------------------------------
# Legacy notifications page
# ---------------------------------------------------------------------------

def test_request_chip_legacy_board_shows_the_request_and_refuses_a_non_operator_verdict(
    logged_in_page, pending_admit_request
):
    page    = logged_in_page
    task_id = pending_admit_request

    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )

    chip  = page.locator( f'#holding-area-container .task-request-chip[data-task-id="{task_id}"]' )
    badge = page.locator( "#holding-area-request-badge" )
    _assert_chip_and_badge( chip, badge )

    _assert_verdict_refused( page, chip, task_id, ".task-request-approve", "approved" )
    _assert_verdict_refused( page, chip, task_id, ".task-request-deny",    "denied" )


# ---------------------------------------------------------------------------
# Multiplexer
# ---------------------------------------------------------------------------

def _multiplexer_login_tokens():
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def test_request_chip_multiplexer_board_shows_the_request_and_refuses_a_non_operator_verdict(
    page, pending_admit_request
):
    task_id         = pending_admit_request
    access, refresh = _multiplexer_login_tokens()

    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( access )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( refresh )});"
    )
    page.goto( f"{BASE_URL}/app/multiplexer", wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )

    chip  = page.locator(
        f'[data-testid="multiplexer-holding-area-container"] .task-request-chip[data-task-id="{task_id}"]'
    )
    badge = page.locator( '[data-testid="multiplexer-holding-area-request-badge"]' )
    _assert_chip_and_badge( chip, badge )

    _assert_verdict_refused( page, chip, task_id, ".task-request-approve", "approved" )
    _assert_verdict_refused( page, chip, task_id, ".task-request-deny",    "denied" )
