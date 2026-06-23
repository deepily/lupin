#!/usr/bin/env python3
"""
E2E — Multiplexer Phase 2: per-worker task EDITING in the task-list card.

Exercises the Phase-2 editing surface end-to-end in a real browser: the per-row
priority dropdown (P0–P3), the owner-reassignment dropdown (active personas,
'Sam' overflow EXCLUDED per Rick's Q5), and the inline drop-with-reason control
(Q4 — inline row input, not a modal). The store's optimistic patchTask/dropTask
fire the real HTTP PATCH / transition calls; those endpoints are STUBBED via
`page.route` so the request bodies can be asserted deterministically without
mutating a live task-store.

What this verifies that the unit tests cannot:
    - the controls render + dispatch in a real browser (delegated change/click)
    - the PATCH body carries `actor` (derived from the authenticated user — Q1)
      + `authority='user_direct'`, and the transition body carries
      `to_status='dropped'` + the inline reason
    - the owner roster is sourced from the SAME fleet-state feed the fleet card
      uses, with the 'Sam' overflow persona excluded (Q5)
    - a blank drop reason surfaces the inline error stripe and fires NO request

COLOR / class-presence: like the read-only card E2E, the redundancy carriers are
CLASS names (WCAG 1.4.1), so class assertions are the right check.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Uses
page.route stubs (no real state mutation) but runs via the manager's :8000
Playwright batch per the venue rubric. Per CLAUDE.local.md "USER IS NEVER A
TESTER": every assertion is AI. Authored by the task-reassign Phase-2 lane
(Clayton); RUN by the manager via `POST /api/test-suite/submit` (NEVER
side-door curl/inject).

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_task_editing.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_task_editing.py -v
"""

from __future__ import annotations

import json
import os
import time

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

# `*` is single-segment in Playwright globs, so these three are disjoint:
#   list      : /api/tasks?limit=500     (query, no extra path segment)
#   patch     : /api/tasks/<id>          (one segment)
#   transition: /api/tasks/<id>/transition
TASKS_LIST_ROUTE  = "**/api/tasks?*"
TASKS_PATCH_ROUTE = "**/api/tasks/*"
TASKS_TRANS_ROUTE = "**/api/tasks/*/transition"
FLEET_ROUTE       = "**/api/arbiter/fleet-state"


# ---------------------------------------------------------------------------
# Auth + test-hook helpers (raw lupin_access_token / lupin_refresh_token)
# ---------------------------------------------------------------------------

def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    """Login via /auth/login → (access_token, refresh_token)."""
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _seed_auth( context, access_token: str, refresh_token: str ) -> None:
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=timeout_ms,
    )


# ---------------------------------------------------------------------------
# Fixtures (response shapes)
# ---------------------------------------------------------------------------

# Two open tasks owned by amy, both editable.
_TASKS = {
    "tasks" : [
        { "id": "t1", "item_class": "task", "title": "Editable one", "status": "in_progress",
          "owner_persona": "amy", "accountable_manager": "tiberius", "priority": "P2",
          "project": "lupin", "blocked_by": None, "next_chase_ts": None },
        { "id": "t2", "item_class": "task", "title": "Editable two", "status": "queued",
          "owner_persona": "amy", "accountable_manager": "tiberius", "priority": "P1",
          "project": "lupin", "blocked_by": None, "next_chase_ts": None },
    ],
    "count" : 2,
}

# Fleet-state feed: active personas amy/bob/carol + the 'Sam' overflow persona
# (which the owner roster MUST exclude per Q5).
_FLEET = {
    "app_timezone"  : "America/New_York",
    "fleet_arbiter" : { "sessions": [
        { "persona": "amy",   "role": "worker",  "liveness": { "verdict": "live" } },
        { "persona": "bob",   "role": "manager", "liveness": { "verdict": "live" } },
        { "persona": "carol", "role": "worker",  "liveness": { "verdict": "live" } },
        { "persona": "Sam",   "role": "worker",  "liveness": { "verdict": "live" } },
    ] },
    "context_pressure" : { "personas": {} },
}


def _open_card( page ) -> dict:
    """
    Seed auth, stub list/fleet/patch/transition, navigate, wait for boot hook.

    Returns a mutable `recorded` dict capturing the PATCH / transition requests
    the controls fire, so tests can assert the wire bodies.
    """
    recorded: dict = { "patch": [], "transition": [] }

    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )

    def _fulfill( body: dict ):
        def _h( route ):
            route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )
        return _h

    def _record_patch( route ):
        req = route.request
        recorded[ "patch" ].append( { "url": req.url, "method": req.method, "body": json.loads( req.post_data or "{}" ) } )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( { "ok": True } ) )

    def _record_transition( route ):
        req = route.request
        recorded[ "transition" ].append( { "url": req.url, "method": req.method, "body": json.loads( req.post_data or "{}" ) } )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( { "ok": True } ) )

    # Most-specific (transition) registered LAST so it wins over the patch glob.
    page.route( TASKS_LIST_ROUTE,  _fulfill( _TASKS ) )
    page.route( FLEET_ROUTE,       _fulfill( _FLEET ) )
    page.route( TASKS_PATCH_ROUTE, _record_patch )
    page.route( TASKS_TRANS_ROUTE, _record_transition )

    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    page.wait_for_selector( ".task-list-table", timeout=3000 )
    return recorded


def _row( page, task_id: str ):
    return page.locator( f'tr.task-row[data-task-id="{task_id}"]' )


# ---------------------------------------------------------------------------
# Controls render
# ---------------------------------------------------------------------------

def test_actions_column_and_controls_render( page ):
    _open_card( page )
    # Actions header + per-row controls present.
    assert page.locator( "thead th.task-col-actions" ).text_content() == "Actions"
    row = _row( page, "t1" )
    assert row.locator( ".task-priority-select" ).count() == 1
    assert row.locator( ".task-owner-select" ).count() == 1
    assert row.locator( ".task-drop-reason" ).count() == 1
    assert row.locator( ".task-drop-button" ).count() == 1
    # Current priority pre-selected.
    assert row.locator( ".task-priority-select" ).input_value() == "P2"


def test_owner_roster_excludes_sam( page ):
    _open_card( page )
    options = _row( page, "t1" ).locator( ".task-owner-select option" ).all_text_contents()
    # Current owner amy + live targets bob/carol; Sam EXCLUDED (Q5).
    assert "amy" in options
    assert "bob" in options
    assert "carol" in options
    assert "Sam" not in options and "sam" not in [ o.lower() for o in options ]


# ---------------------------------------------------------------------------
# Priority edit → PATCH
# ---------------------------------------------------------------------------

def test_priority_edit_fires_patch_with_actor_and_authority( page ):
    recorded = _open_card( page )
    _row( page, "t1" ).locator( ".task-priority-select" ).select_option( "P0" )
    page.wait_for_timeout( 300 )

    assert len( recorded[ "patch" ] ) == 1, "exactly one PATCH fired"
    call = recorded[ "patch" ][ 0 ]
    assert call[ "method" ] == "PATCH"
    assert call[ "url" ].endswith( "/api/tasks/t1" )
    assert call[ "body" ][ "priority" ] == "P0"
    assert call[ "body" ][ "authority" ] == "user_direct"
    # actor derived from the authenticated user (Q1) — surface-tagged.
    assert call[ "body" ][ "actor" ].endswith( "(multiplexer)" )


# ---------------------------------------------------------------------------
# Owner reassignment → PATCH owner_persona
# ---------------------------------------------------------------------------

def test_owner_reassign_fires_patch_owner_persona( page ):
    recorded = _open_card( page )
    _row( page, "t1" ).locator( ".task-owner-select" ).select_option( "bob" )
    page.wait_for_timeout( 300 )

    assert len( recorded[ "patch" ] ) == 1
    body = recorded[ "patch" ][ 0 ][ "body" ]
    assert body[ "owner_persona" ] == "bob"
    assert body[ "authority" ] == "user_direct"
    assert body[ "actor" ].endswith( "(multiplexer)" )


# ---------------------------------------------------------------------------
# Drop-with-reason → transition→dropped
# ---------------------------------------------------------------------------

def test_drop_with_reason_fires_transition_dropped( page ):
    recorded = _open_card( page )
    row = _row( page, "t1" )
    row.locator( ".task-drop-reason" ).fill( "superseded by rewrite" )
    row.locator( ".task-drop-button" ).click()
    page.wait_for_timeout( 300 )

    assert len( recorded[ "transition" ] ) == 1, "exactly one transition fired"
    call = recorded[ "transition" ][ 0 ]
    assert call[ "method" ] == "POST"
    assert call[ "url" ].endswith( "/api/tasks/t1/transition" )
    assert call[ "body" ][ "to_status" ] == "dropped"
    assert call[ "body" ][ "reason" ] == "superseded by rewrite"
    assert call[ "body" ][ "authority" ] == "user_direct"
    assert call[ "body" ][ "actor" ].endswith( "(multiplexer)" )
    # Optimistic removal: the row leaves the open view.
    page.wait_for_timeout( 100 )
    assert _row( page, "t1" ).count() == 0


def test_drop_blank_reason_shows_inline_error_and_fires_no_request( page ):
    recorded = _open_card( page )
    row = _row( page, "t1" )
    # Leave the reason blank → click Drop.
    row.locator( ".task-drop-button" ).click()
    page.wait_for_timeout( 200 )

    # No transition fired; inline error stripe surfaced; row still present.
    assert len( recorded[ "transition" ] ) == 0
    assert row.locator( ".task-row-error-stripe" ).count() == 1
    assert "reason" in row.locator( ".task-row-error-stripe" ).text_content().lower()
    assert _row( page, "t1" ).count() == 1


# ---------------------------------------------------------------------------
# Visual regression — the editable Actions controls
# ---------------------------------------------------------------------------

def test_task_editing_controls_visual( page, assert_snapshot ):
    """
    Baseline the task-list card WITH the Phase-2 editing controls rendered.

    Run #1 with `--update-snapshots` establishes the PNG; later runs pixel-diff.
    Snapshot scope is the whole card container so the priority/owner selects +
    drop affordance are all in frame.
    """
    _open_card( page )
    # Settle layout after the table + controls paint.
    time.sleep( 0.3 )
    container = page.locator( ".task-list-container" )
    assert_snapshot( container, name="multiplexer_task_editing_controls.png" )
    print( "✓ multiplexer_task_editing_controls: visual snapshot compared" )
