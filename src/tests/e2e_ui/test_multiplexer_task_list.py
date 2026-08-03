#!/usr/bin/env python3
"""
E2E — Multiplexer Step 4: read-only Task-List card (store-canonical task mgmt).

Exercises the TaskListStore (poll/fetch) + TaskListRenderer (4 render states +
count + graceful degradation) end-to-end in a real browser. The `/api/tasks`
endpoint is STUBBED via `page.route` so each render state is driven
deterministically without a live task-store; the renderer runs the real
store.refresh() -> fetchState() -> render path.

The card is a read-only consumer of the EXISTING `GET /api/tasks` endpoint
(routers/tasks.py) — it does NOT touch tasks.py. The full-row response shape
mirrors the server `_serialize_item` wire shape.

COLOR: the status-based scheme (status-dot + row left-accent + priority
heat-tint) is asserted by CLASS PRESENCE — the class is the WCAG-1.4.1
redundancy carrier (always paired with the status WORD / priority text), so a
class assertion is exactly the right check, not a brittle computed-pixel read.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Uses
page.route stubs (no real state mutation) but runs via the manager's :8000
Playwright batch per the venue rubric. Authored by the task-list-card lane;
RUN by the manager. Per CLAUDE.local.md "USER IS NEVER A TESTER": every
assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_task_list.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_task_list.py -v
"""

from __future__ import annotations

import json
import os
import time

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

# Glob matches the store's `/api/tasks?limit=500` (query has no slash → `*` covers it).
TASKS_ROUTE = "**/api/tasks*"


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


def _fulfill_tasks( body: dict ):
    """Build a page.route handler that fulfills the tasks endpoint with `body`."""
    def _handler( route ):
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )
    return _handler


def _open_with_tasks( page, tasks_body: dict ):
    """Seed auth, stub the tasks endpoint, navigate, wait for the boot test-hook."""
    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( TASKS_ROUTE, _fulfill_tasks( tasks_body ) )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )


# ---------------------------------------------------------------------------
# Fixtures (response shapes returned by GET /api/tasks)
# ---------------------------------------------------------------------------

_POPULATED = {
    "tasks" : [
        { "id": "1", "item_class": "task", "title": "Live task", "status": "in_progress",
          "owner_persona": "amy", "accountable_manager": "tiberius", "priority": "P1",
          "project": "lupin", "blocked_by": None, "next_chase_ts": None,
          # A non-empty body drives the LIVE (clickable) 📄 detail affordance
          # (row redesign 2026.06.29 — the overlay renders THIS field).
          "body": "Full detail for the live task lives here." },
        { "id": "2", "item_class": "bug", "title": "Blocked bug", "status": "blocked",
          "owner_persona": "amy", "accountable_manager": "tiberius", "priority": "P0",
          "project": "lupin", "blocked_by": "task-1", "next_chase_ts": "2026-06-16T14:30:00-04:00" },
        { "id": "3", "item_class": "task", "title": "Done task", "status": "done",
          "owner_persona": "zoe", "priority": "P2", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None },   # terminal → filtered out
        { "id": "4", "item_class": "task", "title": "Orphan queued", "status": "queued",
          "owner_persona": None, "priority": "P3", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None },    # no owner → Unassigned
    ],
    "count" : 4,
}

_ALL_TERMINAL = {
    "tasks" : [
        { "id": "1", "item_class": "task", "title": "Done one", "status": "done",
          "owner_persona": "amy", "priority": "P2", "project": "lupin" },
        { "id": "2", "item_class": "task", "title": "Dropped one", "status": "dropped",
          "owner_persona": "amy", "priority": "P2", "project": "lupin" },
    ],
    "count" : 2,
}

_UNREACHABLE = { "status": "unreachable", "tasks": None }


# ---------------------------------------------------------------------------
# Render states
# ---------------------------------------------------------------------------

def test_task_list_populated_renders_grouped_table( page ):
    _open_with_tasks( page, _POPULATED )
    page.wait_for_selector( ".task-list-table", timeout=3000 )

    # Open-only count: done excluded → 3 of 4.
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "3"

    # Owner group header for amy + the Unassigned bucket.
    headers = page.locator( ".task-group-header" )
    texts = " ".join( headers.all_text_contents() )
    assert "amy" in texts
    assert "(Unassigned)" in texts

    # The blocked row surfaces blocked_by + next_chase (the differentiator).
    blocked = page.locator( "tr.task-status-blocked" )
    assert blocked.count() == 1
    assert blocked.locator( ".task-col-blocked" ).text_content() == "task-1"
    assert blocked.locator( ".task-col-chase" ).text_content() != "—"
    # Class badge color-keyed to item_class (bug).
    assert blocked.locator( ".task-class-badge.task-class-bug" ).count() == 1
    # Status-dot present in the status cell.
    assert blocked.locator( ".task-col-status .task-status-dot" ).count() == 1
    # P0 priority → high heat-tint class (presence, not pixels).
    assert blocked.locator( ".task-col-priority.task-prio-high" ).count() == 1

    # An "updated HH:MM:SS" stamp is set on a real fetch.
    assert page.locator( ".task-list-updated" ).text_content().startswith( "updated " )


def test_task_list_all_terminal_shows_no_open_tasks( page ):
    _open_with_tasks( page, _ALL_TERMINAL )
    el = page.wait_for_selector( ".task-list-container .task-list-empty", timeout=3000 )
    assert el.text_content() == "✅ No open tasks."
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "0"


def test_task_list_unreachable_shows_indicator_not_blank( page ):
    _open_with_tasks( page, _UNREACHABLE )
    # Never blank: the unreachable indicator is shown.
    page.wait_for_selector( ".task-list-container .task-list-unreachable", timeout=3000 )
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "0"


def test_task_list_auth_required_shows_signin_banner( page ):
    def _handler( route ):
        route.fulfill( status=401, content_type="application/json", body=json.dumps( { "detail": "unauthorized" } ) )

    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( TASKS_ROUTE, _handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    page.wait_for_selector( ".task-list-container .task-list-signin", timeout=3000 )


# ---------------------------------------------------------------------------
# Graceful degradation — good fetch then unreachable replays last-known rows
# ---------------------------------------------------------------------------

def test_task_list_degrades_to_last_known_on_unreachable( page ):
    # A mutable route: first response populated, then unreachable on the next call.
    state = { "mode": "good" }

    def _handler( route ):
        body = _POPULATED if state[ "mode" ] == "good" else _UNREACHABLE
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )

    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( TASKS_ROUTE, _handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    page.wait_for_selector( ".task-list-table", timeout=3000 )
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "3"

    # Flip to unreachable, click refresh → indicator appears BUT last-known rows
    # remain (graceful degradation — never blank).
    state[ "mode" ] = "unreachable"
    page.locator( ".task-list-refresh" ).click()
    page.wait_for_selector( ".task-list-unreachable", timeout=3000 )
    time.sleep( 0.2 )
    assert page.locator( ".task-list-table" ).count() == 1, "last-known rows still rendered"
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "3", "count holds at last-known"


# ---------------------------------------------------------------------------
# Row redesign 2026.06.29 — leading ID column + title truncation/tooltip +
# 📄 body-overlay (AUGMENT: added alongside the existing columns + Actions).
# ---------------------------------------------------------------------------

def test_mux_id_column_shows_first_8_chars( page ):
    """The NEW leftmost ID column renders the first 8 chars of the row id."""
    _open_with_tasks( page, _POPULATED )
    page.wait_for_selector( ".task-list-table", timeout=3000 )
    ids = [ t.strip() for t in page.locator( ".task-row .task-col-id" ).all_text_contents() ]
    assert "1" in ids, f"id column missing first-8 id; got {ids}"   # id '1' → '1'


def test_mux_title_cell_carries_full_title_tooltip( page ):
    """The Title cell carries the FULL title in a `title=` hover-tooltip attr."""
    _open_with_tasks( page, _POPULATED )
    page.wait_for_selector( ".task-list-table", timeout=3000 )
    cell = page.locator( ".task-row .task-col-title", has_text="Live task" ).first
    assert cell.get_attribute( "title" ) == "Live task"


def test_mux_live_detail_emoji_opens_body_overlay( page ):
    """Clicking a LIVE 📄 opens an overlay rendering the task `body`; Esc dismisses."""
    _open_with_tasks( page, _POPULATED )
    page.wait_for_selector( ".task-list-table", timeout=3000 )

    page.locator( ".task-detail-emoji:not(.task-detail-empty)" ).first.click()
    page.wait_for_selector( "#task-body-overlay", state="attached", timeout=3000 )
    body = page.locator( "#task-body-overlay .task-body-overlay-body" ).text_content()
    assert "Full detail for the live task" in body

    page.keyboard.press( "Escape" )
    page.wait_for_selector( "#task-body-overlay", state="detached", timeout=3000 )


def test_mux_body_overlay_dismisses_on_backdrop_click( page ):
    """A click on the overlay backdrop (outside the panel) dismisses it."""
    _open_with_tasks( page, _POPULATED )
    page.wait_for_selector( ".task-list-table", timeout=3000 )
    page.locator( ".task-detail-emoji:not(.task-detail-empty)" ).first.click()
    page.wait_for_selector( "#task-body-overlay", state="attached", timeout=3000 )
    page.locator( "#task-body-overlay" ).click( position={ "x": 5, "y": 5 } )
    page.wait_for_selector( "#task-body-overlay", state="detached", timeout=3000 )


def test_mux_empty_body_emoji_is_dimmed_in_place( page ):
    """A row with no body keeps its 📄 in the column but DIMMED (disabled)."""
    _open_with_tasks( page, _POPULATED )
    page.wait_for_selector( ".task-list-table", timeout=3000 )
    dimmed = page.locator( ".task-detail-emoji.task-detail-empty" )
    assert dimmed.count() >= 1
    assert dimmed.first.get_attribute( "data-task-body" ) is None


# Measures the open #task-body-overlay's computed position + geometry vs the
# viewport (the f7486a9d fixed-centered-modal regression guard — mux parity).
_OVERLAY_METRICS_JS = """() => {
    const o = document.getElementById( "task-body-overlay" );
    const p = o.querySelector( ".task-body-overlay-content" );
    const cs = getComputedStyle( o );
    const orect = o.getBoundingClientRect();
    const prect = p.getBoundingClientRect();
    return {
        position : cs.position,
        vw       : window.innerWidth,
        vh       : window.innerHeight,
        o_left   : orect.left,
        o_top    : orect.top,
        o_width  : orect.width,
        o_height : orect.height,
        panel_cx : prect.left + prect.width / 2,
    };
}"""


def test_mux_body_overlay_computes_fixed_centered_modal( page ):
    """
    REGRESSION GUARD (bug f7486a9d), MUX PARITY: the opened 📄 overlay must
    COMPUTE position:fixed, cover the full viewport, and center its content
    panel — NOT flow to the page foot as a position:static block. This is the
    computed-style assertion the open/dismiss tests above omit (they pass even
    when the overlay is dumped at page-foot). Locks the mux to the same
    centered-modal contract Rick wants for both clients.
    """
    _open_with_tasks( page, _POPULATED )
    page.wait_for_selector( ".task-list-table", timeout=3000 )

    page.locator( ".task-detail-emoji:not(.task-detail-empty)" ).first.click()
    page.wait_for_selector( "#task-body-overlay", state="attached", timeout=3000 )

    metrics = page.evaluate( _OVERLAY_METRICS_JS )

    assert metrics[ "position" ] == "fixed", \
        f"mux overlay must be position:fixed (regression: stale CSS → static); got {metrics[ 'position' ]!r}"
    # inset:0 → the fixed overlay anchors at the origin (NOT below page content)
    assert abs( metrics[ "o_left" ] ) <= 1 and abs( metrics[ "o_top" ] ) <= 1, \
        f"mux fixed overlay must anchor at viewport origin, not page-foot; got left={metrics[ 'o_left' ]} top={metrics[ 'o_top' ]}"
    assert abs( metrics[ "o_width" ] - metrics[ "vw" ] ) <= 2 and abs( metrics[ "o_height" ] - metrics[ "vh" ] ) <= 2, \
        "mux fixed overlay must span the full viewport (inset:0)"
    # flex centering → the content panel sits at the horizontal center
    assert abs( metrics[ "panel_cx" ] - metrics[ "vw" ] / 2 ) <= 2, \
        "mux overlay content panel must be horizontally centered"

    page.keyboard.press( "Escape" )
    page.wait_for_selector( "#task-body-overlay", state="detached", timeout=3000 )
