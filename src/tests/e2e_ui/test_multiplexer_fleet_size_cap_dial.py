#!/usr/bin/env python3
"""
E2E — the multiplexer Fleet Status pane's fleet-size-cap dial (Parity A-2 #5, row 18d06df7).

Ported from legacy notifications.js `fetchFleetSizeCap` (:9205) and `setFleetSizeCap` (:9311),
wired by `_wireFleetSizeCap` (:9351). Two behaviours the unit tier checks in happy-dom and this
file checks on the SERVED page:
    - a save repaints from the SERVER's answer, never the value sent
      (legacy `setFleetSizeCap` :9323-9326; `_wireFleetSizeCap` :9381, :9383-9388)
    - a refused save re-reads the dial, so the handle snaps back to the enforced cap, and the
      server's `detail` is reported (legacy `setFleetSizeCap` :9335-9339)

Every coordinate above names the method that encloses it, which is what the strong citation
guard requires beyond the line resolving: `fetchFleetSizeCap` :9205-9229, `setFleetSizeCap`
:9311-9350, `_wireFleetSizeCap` :9351-9395. A6.md names the same six dial methods.

WHAT IS REAL AND WHAT IS STUBBED: the login, the page, the bundle and the store are real.
`/api/arbiter/fleet-size-cap` and `/api/arbiter/fleet-state` are routed, because the dial's
numbers live in the arbiter's config file and a real PUT would change the fleet's cap.

Venue: :8000 (scheduled) — `logged_in_page` resets lupin_db_test and registers a user. Select with
`-k fleet_size_cap_dial`.
"""

from __future__ import annotations

import json

from playwright.sync_api import expect

from .conftest import BASE_URL


CAP_ROUTE   = "**/api/arbiter/fleet-size-cap"
FLEET_ROUTE = "**/api/arbiter/fleet-state"

SLIDER = '[data-testid="multiplexer-fleet-size-cap"]'
VALUE  = '[data-testid="multiplexer-fleet-size-cap-value"]'
STATUS = '[data-testid="multiplexer-fleet-size-cap-status"]'

CEILING      = 10
START_CAP    = 5
LIVE         = { "total": 3, "managers": 1, "workers": 2 }
EMPTY_FLEET  = { "app_timezone": "UTC", "fleet_arbiter": { "sessions": [ ] } }
REFUSAL_TEXT = "e2e: fleet size cap is defined twice in the arbiter config"
PAINT_MS     = 10_000


def _cap_body( cap ):
    return { "cap": cap, "ceiling": CEILING, "live": LIVE }


def _route_dial( page, put_status, put_body ):
    """
    Route the dial's endpoint: GET answers the cap the stub holds, PUT answers put_status/put_body.

    Ensures:
        - returns a dict whose "puts" list collects each PUT's parsed JSON body and whose
          "gets" counts the GETs
        - the held cap starts at START_CAP and moves only when a PUT succeeds, to put_body["cap"]
    """
    seen = { "puts": [ ], "gets": 0, "cap": START_CAP }

    def _handler( route ):
        req = route.request
        if req.method == "PUT":
            seen[ "puts" ].append( json.loads( req.post_data or "{}" ) )
            if put_status == 200: seen[ "cap" ] = put_body[ "cap" ]
            route.fulfill( status=put_status, content_type="application/json", body=json.dumps( put_body ) )
            return
        seen[ "gets" ] += 1
        route.fulfill( status=200, content_type="application/json", body=json.dumps( _cap_body( seen[ "cap" ] ) ) )

    page.route( CAP_ROUTE, _handler )
    page.route( FLEET_ROUTE, lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps( EMPTY_FLEET ) ) )
    return seen


def _open_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook && window.__multiplexerTestHook.stores",
        timeout=15000,
    )


def _dial_painted_at_start( page ):
    expect( page.locator( VALUE ) ).to_have_text( f"{START_CAP} / {CEILING}", timeout=PAINT_MS )
    slider = page.locator( SLIDER )
    expect( slider ).to_have_value( str( START_CAP ) )
    expect( slider ).to_have_attribute( "max", str( CEILING ) )
    expect( page.locator( STATUS ) ).to_have_text( "3 live — 1 manager(s), 2 worker(s)" )
    return slider


def drive_save_repaints_the_servers_answer( page ):
    """The body of the save test, split out so it can run against a page opened any way."""
    seen   = _route_dial( page, 200, _cap_body( 8 ) )
    _open_multiplexer( page )
    slider = _dial_painted_at_start( page )

    slider.fill( "7" )

    # The server answered 8 to a request for 7. The dial must show 8, the value it holds.
    expect( page.locator( VALUE ) ).to_have_text( f"8 / {CEILING}", timeout=PAINT_MS )
    expect( slider ).to_have_value( "8" )
    expect( slider ).to_be_enabled()
    assert seen[ "puts" ] == [ { "cap": 7 } ], f"the dial should PUT exactly once, with the dragged value: {seen[ 'puts' ]}"


def drive_refused_save_snaps_back( page ):
    """The body of the refusal test, split out so it can run against a page opened any way."""
    errors = [ ]
    page.on( "console", lambda m: errors.append( m.text ) if m.type == "error" else None )
    seen   = _route_dial( page, 409, { "detail": REFUSAL_TEXT } )
    _open_multiplexer( page )
    slider = _dial_painted_at_start( page )
    gets_before = seen[ "gets" ]

    slider.fill( "9" )

    # Refused: the dial re-reads and snaps back to the cap in force, and says why.
    expect( slider ).to_have_value( str( START_CAP ), timeout=PAINT_MS )
    expect( page.locator( VALUE ) ).to_have_text( f"{START_CAP} / {CEILING}" )
    expect( slider ).to_be_enabled()
    assert seen[ "puts" ] == [ { "cap": 9 } ], f"the dial should PUT exactly once: {seen[ 'puts' ]}"
    assert seen[ "gets" ] > gets_before, "a refused save must re-read the dial, not repaint the value it sent"
    assert any( REFUSAL_TEXT in e for e in errors ), f"the server's detail must be reported; console errors: {errors}"


def test_fleet_size_cap_dial_save_repaints_the_servers_answer( logged_in_page ):
    drive_save_repaints_the_servers_answer( logged_in_page )


def test_fleet_size_cap_dial_refused_save_snaps_back( logged_in_page ):
    drive_refused_save_snaps_back( logged_in_page )
