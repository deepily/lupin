#!/usr/bin/env python3
"""
E2E — the multiplexer Holding Area's flow-ratio gate and truncation banner (Parity A-2 #8, row c1bb2be7).

Ported from legacy notifications.js _paintFlowRatioVerdict (:11527), saveFlowRatioSettings (:11649),
initFlowRatioControls (:11799) and _renderTaskListTruncationBanner (:12328); spec io/phase2/A9.md
rows B7, H11, H12. Checked here on the SERVED page:
    - the header readout: counts, percent, and the gate's verdict as a class — red when the gate
      would refuse, including before the settings load (legacy defect 5, fixed)
    - the threshold slider writes on `change`, and repaints from the SERVER's answer
    - a refused write keeps its message and snaps the slider back (legacy defect 1, fixed)
    - the truncation banner: the ✂️ line and the server's warning verbatim (defect 7, left by ruling)

WHAT IS REAL AND WHAT IS STUBBED: the login, the page, the bundle and the stores are real. The
flow-ratio, settings and manager-pull endpoints and `/api/tasks` are routed: a real PATCH would move
the fleet's create gate, and a row-cap page needs more than 500 held rows.

Venue: :8000 (scheduled) — `logged_in_page` resets lupin_db_test and registers a user. Select with
`-k holding_area_flow_ratio`.
"""

from __future__ import annotations

import json

from playwright.sync_api import expect

from .conftest import BASE_URL
from .task_panes import EMPTY_TASKS, MUX_HOLDING_AREA_PANE, tasks_route_handler


TASKS_ROUTE    = "**/api/tasks*"
RATIO_ROUTE    = "**/api/tasks/flow-ratio"
SETTINGS_ROUTE = "**/api/tasks/flow-ratio/settings"
PULL_ROUTE     = "**/api/tasks/manager-pull"

READOUT         = '[data-testid="multiplexer-flow-ratio"]'
CONTROLS        = '[data-testid="multiplexer-flow-ratio-controls"]'
THRESHOLD       = '[data-testid="multiplexer-flow-ratio-threshold"]'
THRESHOLD_VALUE = '[data-testid="multiplexer-flow-ratio-threshold-value"]'
STATUS          = '[data-testid="multiplexer-flow-ratio-controls-status"]'
BANNER_LINES    = f"{MUX_HOLDING_AREA_PANE} .task-list-truncated"
PAINT_MS        = 10_000

# 30 created, 20 closed = 150%, against a 110% threshold: the gate refuses.
RATIO    = { "created": 30, "closed": 20, "ratio": 1.5, "allow_below": 1.1, "window_hours": 168,
             "close_needed": 3, "room_for": 0, "verdict": "deny" }
SETTINGS = { "allow_below": 1.1, "window_hours": 168, "window_source": "config", "threshold_source": "config" }
PULL     = { "disabled": False, "source": "config" }
ROW_CAP  = ( "row-cap truncation — 500 of 800 matching rows returned (limit=500, offset=0); "
             "300 rows not shown. Ordering is newest-first, so the omitted rows are the OLDEST "
             "matches. Page with offset, or narrow the filter" )


def _json( route, status, body ):
    route.fulfill( status=status, content_type="application/json", body=json.dumps( body ) )


def _route_gate( page, settings_gets=( 200, ), patch_status=200, patch_body=None, holding_body=None ):
    """
    Route the three flow-ratio endpoints and `/api/tasks`.

    Requires:
        - settings_gets lists the status of each settings GET in order; the last one repeats
        - holding_body is the holding-area query's answer, or None for no rows

    Ensures:
        - returns a dict collecting "patches" (parsed PATCH bodies), "ratio_gets" and "settings_gets"
        - a settings GET answered 200 carries the settings the stub holds, which move to patch_body
          only when a PATCH succeeds
    """
    seen = { "patches": [ ], "ratio_gets": 0, "settings_gets": 0, "settings": dict( SETTINGS ) }

    def _settings( route ):
        req = route.request
        if req.method == "PATCH":
            seen[ "patches" ].append( json.loads( req.post_data or "{}" ) )
            if patch_status == 200: seen[ "settings" ] = patch_body
            _json( route, patch_status, patch_body if patch_status == 200 else { "detail": "admin only" } )
            return
        status = settings_gets[ min( seen[ "settings_gets" ], len( settings_gets ) - 1 ) ]
        seen[ "settings_gets" ] += 1
        _json( route, status, seen[ "settings" ] if status == 200 else { "detail": "e2e: unavailable" } )

    def _ratio( route ):
        seen[ "ratio_gets" ] += 1
        _json( route, 200, RATIO )

    page.route( TASKS_ROUTE, tasks_route_handler( EMPTY_TASKS, holding_body=holding_body ) )
    page.route( RATIO_ROUTE, _ratio )
    page.route( SETTINGS_ROUTE, _settings )
    page.route( PULL_ROUTE, lambda route: _json( route, 200, PULL ) )
    return seen


def _open_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook && window.__multiplexerTestHook.stores",
        timeout=15000,
    )


def _readout_shows_the_refusing_gate( page ):
    readout = page.locator( READOUT )
    expect( readout ).to_contain_text( "30 created / 20 closed", timeout=PAINT_MS )
    expect( readout ).to_contain_text( "150%" )
    expect( readout ).to_have_class( "task-list-flow-ratio flow-ratio-closed" )


def drive_readout_and_cluster( page ):
    _route_gate( page )
    _open_multiplexer( page )
    _readout_shows_the_refusing_gate( page )
    expect( page.locator( CONTROLS ) ).to_be_visible( timeout=PAINT_MS )
    expect( page.locator( THRESHOLD ) ).to_have_value( "110" )
    expect( page.locator( THRESHOLD_VALUE ) ).to_have_text( "110%" )
    expect( page.locator( STATUS ) ).to_have_text( "from config" )


def drive_readout_is_red_before_the_settings_load( page ):
    seen = _route_gate( page, settings_gets=( 500, ) )
    _open_multiplexer( page )
    # Legacy painted this green: no settings, so no threshold, so "open". The ratio's own
    # allow_below says the gate refuses, and the colour must say so too.
    _readout_shows_the_refusing_gate( page )
    expect( page.locator( CONTROLS ) ).to_be_hidden()
    assert seen[ "settings_gets" ] >= 1, "the settings endpoint was never asked, so this test measured nothing"


def drive_threshold_writes_on_change_and_repaints_the_server( page ):
    answer = dict( SETTINGS, allow_below=1.4, threshold_source="override" )
    seen   = _route_gate( page, patch_body=answer )
    _open_multiplexer( page )
    expect( page.locator( CONTROLS ) ).to_be_visible( timeout=PAINT_MS )
    ratio_gets_before = seen[ "ratio_gets" ]

    page.locator( THRESHOLD ).fill( "150" )

    # Asked for 150%, the server kept 140%. The slider must show what the gate uses.
    expect( page.locator( THRESHOLD ) ).to_have_value( "140", timeout=PAINT_MS )
    expect( page.locator( THRESHOLD_VALUE ) ).to_have_text( "140%" )
    expect( page.locator( STATUS ) ).to_have_text( "saved override" )
    assert seen[ "patches" ] == [ { "allow_below": 1.5 } ], f"one PATCH, as a fraction: {seen[ 'patches' ]}"
    assert seen[ "ratio_gets" ] > ratio_gets_before, "a write must re-read the ratio its verdict depends on"


def drive_refused_threshold_keeps_its_message_and_snaps_back( page ):
    seen = _route_gate( page, patch_status=403 )
    _open_multiplexer( page )
    expect( page.locator( CONTROLS ) ).to_be_visible( timeout=PAINT_MS )

    page.locator( THRESHOLD ).fill( "150" )

    expect( page.locator( STATUS ) ).to_have_text( "not saved — admin only", timeout=PAINT_MS )
    expect( page.locator( THRESHOLD ) ).to_have_value( "110" )
    expect( page.locator( THRESHOLD_VALUE ) ).to_have_text( "110%" )
    # The drag's preview must not outlive the refusal.
    expect( page.locator( READOUT ) ).to_have_class( "task-list-flow-ratio flow-ratio-closed" )
    assert seen[ "patches" ] == [ { "allow_below": 1.5 } ], f"one PATCH: {seen[ 'patches' ]}"


def drive_truncation_banner( page ):
    holding = { "tasks": [ ], "count": 0, "total": 800, "has_more": True, "warnings": [ ROW_CAP ] }
    _route_gate( page, holding_body=holding )
    _open_multiplexer( page )
    lines = page.locator( BANNER_LINES )
    expect( lines ).to_have_count( 2, timeout=PAINT_MS )
    expect( lines.nth( 0 ) ).to_have_text( "✂️ Board truncated: showing 0 of 800 — 800 not displayed." )
    expect( lines.nth( 1 ) ).to_have_text( f"⚠️ Server: {ROW_CAP}" )


def test_holding_area_flow_ratio_readout_and_cluster( logged_in_page ):
    drive_readout_and_cluster( logged_in_page )


def test_holding_area_flow_ratio_readout_is_red_before_the_settings_load( logged_in_page ):
    drive_readout_is_red_before_the_settings_load( logged_in_page )


def test_holding_area_flow_ratio_threshold_writes_on_change( logged_in_page ):
    drive_threshold_writes_on_change_and_repaints_the_server( logged_in_page )


def test_holding_area_flow_ratio_refused_threshold_snaps_back( logged_in_page ):
    drive_refused_threshold_keeps_its_message_and_snaps_back( logged_in_page )


def test_holding_area_truncation_banner( logged_in_page ):
    drive_truncation_banner( logged_in_page )
