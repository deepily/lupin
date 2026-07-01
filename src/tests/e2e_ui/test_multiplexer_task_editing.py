#!/usr/bin/env python3
"""
E2E — Multiplexer Phase 2: per-worker task EDITING in the task-list card.

Exercises the Phase-2 editing surface end-to-end in a real browser: the per-row
priority dropdown (P0–P3), the owner-reassignment dropdown (active personas,
'Sam' overflow INCLUDED per Rick's Q5), and the inline drop-with-reason control
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
      uses, with the 'Sam' overflow persona included (Q5)
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
# (which the owner roster MUST include per Q5 — same roster the fleet card shows).
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


def _open_card( page, tasks: dict | None = None ) -> dict:
    """
    Seed auth, stub list/fleet/patch/transition, navigate, wait for boot hook.

    `tasks` overrides the list-endpoint payload (defaults to `_TASKS`); the
    F1 copy-ID tests inject a full-uuid task so the clipboard assertion can
    distinguish the FULL id from the 8-char displayed prefix.

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
    page.route( TASKS_LIST_ROUTE,  _fulfill( tasks or _TASKS ) )
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


def test_owner_roster_includes_sam( page ):
    _open_card( page )
    options = _row( page, "t1" ).locator( ".task-owner-select option" ).all_text_contents()
    # Current owner amy + live targets bob/carol/Sam; Sam INCLUDED (Q5 — same
    # roster the fleet-status card shows, which carries Sam as a live persona).
    assert "amy" in options
    assert "bob" in options
    assert "carol" in options
    assert "Sam" in options


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

def test_task_editing_controls_visual( page, assert_snapshot_structure_only ):
    """
    Baseline the task-list card WITH the Phase-2 editing controls rendered —
    STRUCTURE-ONLY (width + height-tolerance), PIXEL-BLIND BY DESIGN.

    Snapshot scope is the whole card container so the priority/owner selects +
    drop affordance are all in frame. Run #1 with `--update-snapshots` establishes
    the PNG (used as a SIZE reference only); later runs assert structural size.

    Resolution D for straggler bug 660d02b4 (ratified by Tiberius 2026-07-01):
    this is the most glyph-dense of the 37 mux visual snapshots (a full task-list
    data table of 11-13px text). Its per-pixel glyph anti-aliasing is
    non-deterministic run-to-run — HIGH-VARIANCE, up to ~3800 scattered mismatched
    px — EVEN WITH the suite-wide deterministic-font launch args already applied
    (`--font-render-hinting=none` / `--disable-lcd-text` / `--force-color-profile=srgb`
    / `--force-device-scale-factor=1`, see conftest `browser_type_launch_args`).
    No pixel/count budget can forgive ~3800 benign px without also masking a real
    <2000px regression (a recolored pill), which would cross the never-false-green
    line. So the exact-pixel assertion is DROPPED: FUNCTIONAL coverage of these
    controls lives in the sibling E2E tests above
    (`test_actions_column_and_controls_render`, the priority/owner PATCH-body
    tests, the drop-reason/blank-reason tests). What is RETAINED is a deterministic
    STRUCTURAL gate — `assert_snapshot_structure_only` (width exact + height ±1px)
    — plus two genuine render-determinism improvements kept because they help
    regardless: the Actions-column control-height pin (task-list.css, fixed the
    original 169↔170 flap) and the settle below. Restoring pixel coverage is
    deferred to the P3 (C) deterministic-font / sub-pixel-positioning follow-on
    (the existing font flags are already present + insufficient for THIS card).
    """
    _open_card( page )
    container = page.locator( ".task-list-container" )
    # Deterministic pre-snapshot settle (kept as a genuine improvement): wait for
    # the network to idle, web fonts to finish, and two full animation frames
    # (layout + paint committed) so the captured frame is the final one. This
    # reduced but did NOT eliminate the glyph-AA jitter (hence resolution D above);
    # it still stabilises the card SIZE the structural gate checks.
    page.wait_for_load_state( "networkidle" )
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    assert_snapshot_structure_only( container, name="multiplexer_task_editing_controls.png" )
    print( "✓ multiplexer_task_editing_controls: structural snapshot verified (width + height-tolerance; pixel-blind by design — bug 660d02b4 D)" )


# ---------------------------------------------------------------------------
# F2 (task fdfb5b05) — Detail column repositioned 10 → 3 (after Title, before
# Class). Verified in the REAL page: the served bundle actually paints the
# Detail header + cell in slot 3, which the render-unit tests cannot confirm
# (they assert the DOM the template BUILDS, not the DOM the browser SERVES).
# ---------------------------------------------------------------------------

# Target L→R order (0-based) after the F2 reposition — Detail at index 2.
_EXPECTED_COL_ORDER = [
    "task-col-id", "task-col-title", "task-col-detail", "task-col-class",
    "task-col-status", "task-col-blocked", "task-col-chase",
    "task-col-accountable", "task-col-priority", "task-col-project",
    "task-col-actions",
]


def _classes( locator ) -> list[ str ]:
    """First class token of each element under `locator`, in DOM order."""
    out: list[ str ] = []
    for i in range( locator.count() ):
        cls = locator.nth( i ).get_attribute( "class" ) or ""
        out.append( cls.split()[ 0 ] if cls.split() else "" )
    return out


def test_detail_header_in_position_three( page ):
    _open_card( page )
    # Scope to the task-list table — the multiplexer page ALSO renders a
    # fleet-status table whose <thead th> would otherwise collide.
    order = _classes( page.locator( ".task-list-table thead th" ) )
    assert order == _EXPECTED_COL_ORDER, f"header order drifted: { order }"
    # Detail sits in slot 3 (index 2), directly between Title and Class.
    assert order[ 1 ] == "task-col-title"
    assert order[ 2 ] == "task-col-detail"
    assert order[ 3 ] == "task-col-class"


def test_detail_cell_in_position_three_in_row( page ):
    _open_card( page )
    row_cells = _row( page, "t1" ).locator( "td" )
    order = _classes( row_cells )
    assert order == _EXPECTED_COL_ORDER, f"row cell order drifted: { order }"
    # Detail affordance (📄) survives the move — the emoji still renders in the
    # repositioned cell (renderDetailCell unchanged, only its append site moved).
    assert _row( page, "t1" ).locator( "td.task-col-detail .task-detail-emoji" ).count() == 1
    # Actions remains the trailing column (no regression to the edit controls).
    assert order[ -1 ] == "task-col-actions"


# ---------------------------------------------------------------------------
# F1 (task fdfb5b05) — Click-to-copy the FULL task id. Verified end-to-end
# against the REAL browser clipboard (permission-granted context): the cell
# DISPLAYS the 8-char prefix but the clipboard receives the FULL uuid. The
# render-unit tests mock `navigator.clipboard.writeText`; only this E2E proves
# the affordance drives the actual OS clipboard through the delegated handler.
# ---------------------------------------------------------------------------

_FULL_UUID = "fdfb5b05-aaaa-bbbb-cccc-0123456789ab"

# A single task whose id is a full uuid → the displayed label is the 8-char
# prefix, so copy-full-vs-display-prefix is observable.
_TASKS_UUID = {
    "tasks" : [
        { "id": _FULL_UUID, "item_class": "task", "title": "Copyable row",
          "status": "in_progress", "owner_persona": "amy",
          "accountable_manager": "tiberius", "priority": "P2",
          "project": "lupin", "blocked_by": None, "next_chase_ts": None,
          "body": "some detail body" },
    ],
    "count" : 1,
}


def test_id_cell_carries_copy_affordance( page ):
    _open_card( page, tasks=_TASKS_UUID )
    id_cell = _row( page, _FULL_UUID ).locator( "td.task-col-id" )
    # a11y affordance: keyboard-operable button semantics + hint.
    assert id_cell.get_attribute( "role" ) == "button"
    assert id_cell.get_attribute( "tabindex" ) == "0"
    assert id_cell.get_attribute( "title" ) == "Click to copy ID"
    # Cell DISPLAYS only the 8-char prefix (the full uuid lives on the row).
    assert id_cell.text_content().strip() == _FULL_UUID[ :8 ]


def test_id_cell_click_copies_full_uuid_to_clipboard( page ):
    page.context.grant_permissions( [ "clipboard-read", "clipboard-write" ] )
    _open_card( page, tasks=_TASKS_UUID )
    id_cell = _row( page, _FULL_UUID ).locator( "td.task-col-id" )
    id_cell.click()
    # Transient no-reflow "copied" flash appears...
    page.wait_for_selector( "td.task-col-id.task-id-copied", timeout=2000 )
    # ...and the FULL uuid (not the 8-char prefix) landed on the real clipboard.
    clip = page.evaluate( "() => navigator.clipboard.readText()" )
    assert clip == _FULL_UUID, f"clipboard has { clip!r }, expected full uuid"


def test_id_cell_keyboard_enter_copies_full_uuid( page ):
    page.context.grant_permissions( [ "clipboard-read", "clipboard-write" ] )
    _open_card( page, tasks=_TASKS_UUID )
    id_cell = _row( page, _FULL_UUID ).locator( "td.task-col-id" )
    id_cell.focus()
    page.keyboard.press( "Enter" )
    page.wait_for_selector( "td.task-col-id.task-id-copied", timeout=2000 )
    assert page.evaluate( "() => navigator.clipboard.readText()" ) == _FULL_UUID


def test_id_cell_copied_flash_does_not_reflow_row( page ):
    """The copied state is a same-width color/overlay change (absolutely-positioned
    ✓ badge) — the row width MUST be byte-identical copied vs. not (F1 acceptance:
    row width unchanged; keeps the visual snapshot stable)."""
    page.context.grant_permissions( [ "clipboard-read", "clipboard-write" ] )
    _open_card( page, tasks=_TASKS_UUID )
    row     = _row( page, _FULL_UUID )
    id_cell = row.locator( "td.task-col-id" )
    width_before = row.bounding_box()[ "width" ]
    id_cell.click()
    page.wait_for_selector( "td.task-col-id.task-id-copied", timeout=2000 )
    width_after = row.bounding_box()[ "width" ]
    assert width_after == width_before, f"row reflowed on copy: { width_before } → { width_after }"
