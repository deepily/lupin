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

from .task_panes import (
    MUX_TASK_LIST_PANE, MUX_HOLDING_AREA_PANE, is_holding_area_query,
    tasks_route_handler, disclose_row, disclosed_value,
)

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


def _open_with_tasks( page, tasks_body: dict ) -> dict:
    """
    Seed auth, stub the tasks endpoint, navigate, wait for the boot test-hook.

    The stub answers the holding area's own query with an empty body, as the real server
    would for these fixtures (row 1657a852 — see task_panes.py). Returns the URLs it saw,
    split into "board" and "holding".
    """
    seen = { "board": [ ], "holding": [ ] }
    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( TASKS_ROUTE, tasks_route_handler( tasks_body, seen=seen ) )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    return seen


def _pane( page ):
    """The task-list pane. The Epic Board renders the same rows, so every locator is scoped."""
    return page.locator( MUX_TASK_LIST_PANE )


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
    pane = _pane( page )
    pane.locator( ".task-list-table" ).wait_for( timeout=3000 )

    # Open-only count: done excluded → 3 of 4.
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "3"

    # Owner group header for amy + the Unassigned bucket.
    headers = pane.locator( ".task-group-header" )
    texts = " ".join( headers.all_text_contents() )
    assert "amy" in texts
    assert "(Unassigned)" in texts

    # The blocked row surfaces blocked_by + next_chase (the differentiator). Both live in
    # the disclosed controls row now; read the VALUE spans, since each field's label alone
    # would satisfy "not the em dash".
    blocked = pane.locator( "tr.task-row.task-status-blocked" )
    assert blocked.count() == 1
    controls = disclose_row( pane, "2" )
    assert disclosed_value( controls, "task-col-blocked" ) == "task-1"
    assert disclosed_value( controls, "task-col-chase" ) not in ( "", "—" )
    # Class badge color-keyed to item_class (bug).
    assert blocked.locator( ".task-class-badge.task-class-bug" ).count() == 1
    # Status-dot present in the status cell.
    assert blocked.locator( ".task-col-status .task-status-dot" ).count() == 1
    # P0 priority → high heat-tint class (presence, not pixels).
    assert blocked.locator( ".task-col-priority.task-prio-high" ).count() == 1

    # An "updated HH:MM:SS" stamp is set on a real fetch. It sits in the card's header,
    # OUTSIDE the pane container, and is unique on the page — so it is not pane-scoped
    # (ts-37979ae6 timed out when it was).
    assert page.locator( ".task-list-updated" ).text_content().startswith( "updated " )


def test_the_holding_area_is_answered_by_its_own_query( page ):
    """
    GUARDS THE FIXTURE, NOT THE PRODUCT (row 1657a852, María's review).

    Every other test here scopes its locators to the task-list pane, so a stub that
    answered the holding area's `status=not_approved` query with the BOARD's rows would
    leave them all green — the doubled rows would sit in a pane nobody reads. This test is
    the one that reads it. The real server returns disjoint sets, so the holding area
    must show none of the board fixture's rows, and the page must have asked it exactly
    one holding-shaped question on load.
    """
    seen = _open_with_tasks( page, _POPULATED )
    _pane( page ).locator( ".task-list-table" ).wait_for( timeout=3000 )

    assert len( seen[ "board" ] ) >= 1, "the board query never arrived, so nothing below is measured"
    assert len( seen[ "holding" ] ) == 1, f"expected one holding-area query on load, saw { seen[ 'holding' ] }"
    assert all( is_holding_area_query( u ) for u in seen[ "holding" ] )

    holding = page.locator( MUX_HOLDING_AREA_PANE )
    assert holding.count() == 1, "the holding-area pane is not mounted, so its emptiness proves nothing"
    board_ids = [ t[ "id" ] for t in _POPULATED[ "tasks" ] ]

    def _leaked():
        return [ i for i in board_ids if holding.locator( f'tr.task-row[data-task-id="{ i }"]' ).count() > 0 ]

    assert _leaked() == [ ], f"board rows rendered in the holding area: { _leaked() }"

    # ── POSITIVE CONTROL: the instrument can see a leak ───────────────────────────
    # The :8000 runner reads the main tree, so this guard cannot be proven with an on-disk
    # mutation arm without editing the shared checkout. The mutation lives here instead:
    # reload with the OLD stub's behaviour — the board's rows answered to BOTH queries — and
    # the same reading must now find them. Without this leg, "nothing leaked" is also what a
    # holding pane that never renders rows would report.
    page.unroute( TASKS_ROUTE )
    page.route( TASKS_ROUTE, tasks_route_handler( _POPULATED, holding_body=_POPULATED ) )
    page.reload( wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    page.wait_for_function(
        "() => document.querySelectorAll( '[data-testid=\"multiplexer-holding-area-container\"] tr.task-row' ).length > 0",
        timeout=5000,
    )
    assert _leaked(), "a stub answering the holding query with the board's rows was NOT detected — this guard is blind"


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

    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    page.route( TASKS_ROUTE, tasks_route_handler(
        lambda: _POPULATED if state[ "mode" ] == "good" else _UNREACHABLE ) )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    pane = _pane( page )
    pane.locator( ".task-list-table" ).wait_for( timeout=3000 )
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "3"

    # Flip to unreachable, click refresh → indicator appears BUT last-known rows
    # remain (graceful degradation — never blank).
    state[ "mode" ] = "unreachable"
    # The refresh button is in the card's header, outside the pane container, and unique.
    page.locator( ".task-list-refresh" ).click()
    pane.locator( ".task-list-unreachable" ).wait_for( timeout=3000 )
    time.sleep( 0.2 )
    assert pane.locator( ".task-list-table" ).count() == 1, "last-known rows still rendered"
    assert page.locator( '[data-testid="multiplexer-task-list-count"]' ).text_content() == "3", "count holds at last-known"


# ---------------------------------------------------------------------------
# Row redesign 2026.06.29 — leading ID column + title truncation/tooltip +
# 📄 body-overlay (AUGMENT: added alongside the existing columns + Actions).
# ---------------------------------------------------------------------------

def test_mux_id_column_shows_first_8_chars( page ):
    """The NEW leftmost ID column renders the first 8 chars of the row id."""
    _open_with_tasks( page, _POPULATED )
    pane = _pane( page )
    pane.locator( ".task-list-table" ).wait_for( timeout=3000 )
    ids = [ t.strip() for t in pane.locator( ".task-row .task-col-id" ).all_text_contents() ]
    assert "1" in ids, f"id column missing first-8 id; got {ids}"   # id '1' → '1'


def test_mux_title_cell_carries_full_title_tooltip( page ):
    """The Title cell carries the FULL title in a `title=` hover-tooltip attr."""
    _open_with_tasks( page, _POPULATED )
    pane = _pane( page )
    pane.locator( ".task-list-table" ).wait_for( timeout=3000 )
    cell = pane.locator( ".task-row .task-col-title", has_text="Live task" ).first
    assert cell.get_attribute( "title" ) == "Live task"


def _open_live_detail( page ):
    """
    Open the live 📄 for row "1" (the only fixture row with a body) and wait for the overlay.

    The 📄 lives in the row's disclosed controls row, hidden until the row is disclosed
    (row 1657a852) — clicking it without disclosing times out on "element is not visible".
    """
    pane = _pane( page )
    pane.locator( ".task-list-table" ).wait_for( timeout=3000 )
    disclose_row( pane, "1" ).locator( ".task-detail-emoji:not(.task-detail-empty)" ).click()
    page.wait_for_selector( "#task-body-overlay", state="attached", timeout=3000 )


def test_mux_live_detail_emoji_opens_body_overlay( page ):
    """Clicking a LIVE 📄 opens an overlay rendering the task `body`; Esc dismisses."""
    _open_with_tasks( page, _POPULATED )
    _open_live_detail( page )
    body = page.locator( "#task-body-overlay .task-body-overlay-body" ).text_content()
    assert "Full detail for the live task" in body

    page.keyboard.press( "Escape" )
    page.wait_for_selector( "#task-body-overlay", state="detached", timeout=3000 )


def test_mux_body_overlay_dismisses_on_backdrop_click( page ):
    """A click on the overlay backdrop (outside the panel) dismisses it."""
    _open_with_tasks( page, _POPULATED )
    _open_live_detail( page )
    page.locator( "#task-body-overlay" ).click( position={ "x": 5, "y": 5 } )
    page.wait_for_selector( "#task-body-overlay", state="detached", timeout=3000 )


def test_mux_empty_body_emoji_is_dimmed_in_place( page ):
    """A row with no body keeps its 📄 in the column but DIMMED (disabled)."""
    _open_with_tasks( page, _POPULATED )
    pane = _pane( page )
    pane.locator( ".task-list-table" ).wait_for( timeout=3000 )
    dimmed = pane.locator( ".task-detail-emoji.task-detail-empty" )
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
    _open_live_detail( page )

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
