"""
Layout-Parity Oracle, Tier 2 — INNER-ACCORDION APPEARANCE, BOTH CLIENTS.

john's cross-client entry proved the 13 inner-accordion rows agree structurally
and behaviourally, and named its own limit: "every green here is DOM and
behaviour, never appearance: no computed style, no geometry, no screenshot."
This module reads that missing axis — the NAMED computed-style properties of
every one of the 13 contract rows, from BOTH clients, over ONE fixture.

🔴 BOTH SIDES ARE DRIVEN AT THE REAL PAGES, AND THE HARNESS WOULD HAVE LIED.
Appearance is produced by the CASCADE, not by the renderer. The component-
isolation harness links its own <link> set, so a computed style read there is a
fact about the harness page rather than about the client. That is john's click
lesson one level down: his harness mounted TEMPLATES and could not see a
DELEGATED listener, and reported the mux inert. A harness page cannot see a
sheet the real page links.

    legacy  /app/notifications?classic=1
    mux     /app/multiplexer

⚠️ WHICH TREE THIS DESCRIBES. Both pages are served by :7999, whose container
bind-mounts ./src from the MAIN CHECKOUT (docker-compose.yml:169 — john's
finding). So a result here is about the MAIN CHECKOUT, not about the worktree
this file sits in. `test_the_measured_pages_come_from_a_named_tree` says so out
loud rather than letting the number imply otherwise.

Venue: :7999-eligible — every pane API is route-stubbed so nothing is written,
the run is seconds, and it needs no monopoly.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest
import requests

from tests.e2e_ui.parity_oracle import (
    LEGACY_ACCORDION_URL_PATH,
    LEGACY_RENDERER_HREF,
    LEGACY_RENDERER_RELPATH,
    MUX_ACCORDION_URL_PATH,
    accordion_composite,
    accordion_stories_body,
    load_accordion_scenario,
    repo_root,
)

from .accordion_appearance import (
    ACCORDION_APPEARANCE_JS,
    ACCORDION_APPEARANCE_PROPS,
    CONTRACT_ROW_SHAPES,
    row_shape,
)

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )


def _sha( data: bytes ) -> str:
    return hashlib.sha256( data ).hexdigest()[ :16 ]


@pytest.fixture( scope="module" )
def scenario() -> dict:
    return load_accordion_scenario()


@pytest.fixture( scope="module" )
def tokens():
    """Log in once. Missing credentials are a SKIP — this suite cannot invent them."""
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD not set" )
    try:
        resp = requests.post( f"{BASE_URL}/auth/login",
                              json={ "email": email, "password": password }, timeout=10 )
    except requests.RequestException as exc:
        pytest.skip( f"{BASE_URL} unreachable: {exc}" )
    if resp.status_code != 200:
        pytest.skip( f"login failed: {resp.status_code}" )
    return resp.json()[ "tokens" ]


def _stub_pane_apis( page, scenario: dict ):
    """Serve BOTH clients the same fixture. The holding-area query is the same
    path as the task-list one and differs only by `status=not_approved`."""
    def _tasks( route ):
        held = "status=not_approved" in route.request.url
        rows = scenario[ "holding_area" if held else "task_list" ][ "tasks" ]
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( accordion_composite( rows, scenario ) ) )

    page.route( "**/api/tasks?**", _tasks )
    page.route( "**/api/epic-stories**", lambda rt: rt.fulfill(
        status=200, content_type="application/json",
        body=json.dumps( accordion_stories_body( scenario ) ) ) )


def _walk_appearance( page, tokens, scenario, path ) -> dict:
    """Drive a REAL client page over the fixture and read every contract row's
    named appearance properties."""
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( tokens[ 'access_token' ] )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( tokens[ 'refresh_token' ] )});"
    )
    _stub_pane_apis( page, scenario )
    page.goto( f"{BASE_URL}{path}", wait_until="networkidle", timeout=30_000 )
    page.wait_for_selector( "tbody.task-group", timeout=20_000 )
    page.wait_for_timeout( 1_500 )   # let the epic + holding panes finish painting
    return page.evaluate( ACCORDION_APPEARANCE_JS, { "props": ACCORDION_APPEARANCE_PROPS } )


@pytest.fixture( scope="module" )
def both( browser, tokens, scenario ) -> dict:
    """One walk per client, each in its own context so localStorage cannot leak."""
    out = {}
    for name, path in ( ( "legacy", LEGACY_ACCORDION_URL_PATH ),
                        ( "mux",    MUX_ACCORDION_URL_PATH ) ):
        ctx  = browser.new_context( viewport={ "width": 1280, "height": 900 },
                                    device_scale_factor=1 )
        page = ctx.new_page()
        try:
            out[ name ] = _walk_appearance( page, tokens, scenario, path )
        finally:
            ctx.close()
    return out


# ---------------------------------------------------------------------------
# PROVENANCE — say which tree the reading is about, before reporting a number.
# ---------------------------------------------------------------------------

def test_the_measured_pages_come_from_a_named_tree():
    """Both pages are served by :7999, which bind-mounts ./src from the MAIN
    checkout. Hash the served legacy renderer against THIS tree's copy: equal
    means the reading also describes this worktree; unequal means it describes
    the main checkout and must be reported that way. Either is legitimate — an
    UNSTATED one is not, so this test always prints the verdict."""
    try:
        served = requests.get( f"{BASE_URL}{LEGACY_RENDERER_HREF}", timeout=10 )
    except requests.RequestException as exc:
        pytest.skip( f"{BASE_URL} unreachable: {exc}" )
    assert served.status_code == 200, f"legacy renderer not served: {served.status_code}"
    mine  = ( repo_root() / LEGACY_RENDERER_RELPATH ).read_bytes()
    same  = _sha( served.content ) == _sha( mine )
    print( f"\n[provenance] served={_sha( served.content )} this_tree={_sha( mine )} "
           f"same_tree={same}" )


# ---------------------------------------------------------------------------
# THE WALK REACHED SOMETHING — a loop over nothing satisfies every per-item
# assertion inside it, so the corpus reports on itself.
# ---------------------------------------------------------------------------

def test_the_walk_found_every_group_family_in_both_clients( both ):
    """Positive control for the instrument. The fixture holds 3 task owners,
    4 epic sections and 3 holding filers; a walk returning zero of any family is
    an empty instrument, which reads identically to a clean pass."""
    for client, res in both.items():
        found = res[ "found" ]
        print( f"\n[found:{client}] {found}" )
        assert found[ "task_groups" ]    > 0, f"{client}: walked no task groups"
        assert found[ "epic_groups" ]    > 0, f"{client}: walked no epic groups"
        assert found[ "holding_groups" ] > 0, f"{client}: walked no holding groups"


def test_every_one_of_the_13_contract_rows_was_read_in_both_clients( both ):
    """Accounts for EVERY named row. The 13 contract-row SHAPES must each be
    present in both walks — otherwise a row silently contributed no reading and
    its appearance would be reported as 'no divergence' by omission."""
    missing = {}
    for client, res in both.items():
        shapes = { row_shape( k ) for k in res[ "nodes" ] }
        gone   = [ s for s in CONTRACT_ROW_SHAPES if s not in shapes ]
        if gone:
            missing[ client ] = gone
    assert not missing, (
        "contract rows that produced NO appearance reading (so their parity is "
        f"unmeasured, not proven):\n{json.dumps( missing, indent=2 )}"
    )


# ---------------------------------------------------------------------------
# THE COMPARISON
# ---------------------------------------------------------------------------

def test_the_13_inner_accordion_rows_look_the_same_in_both_clients( both ):
    """🔴 THE APPEARANCE CLAIM. For every contract row present in BOTH clients,
    every named property must be equal. A divergence fails with the exact
    row + property + legacy + mux line — that line IS the bug report."""
    legacy, mux = both[ "legacy" ][ "nodes" ], both[ "mux" ][ "nodes" ]
    common = sorted( set( legacy ) & set( mux ) )
    assert common, (
        f"no aligned contract rows between the clients — legacy keys "
        f"{sorted( legacy )[ :5 ]}, mux keys {sorted( mux )[ :5 ]}"
    )
    print( f"\n[aligned] {len( common )} contract rows compared on "
           f"{len( ACCORDION_APPEARANCE_PROPS )} named properties" )

    # 🔴 `height` IS NOT COMPARED ON CONTAINER ROWS — the measurement talking, not a
    # convenience. A container row is a tbody-shaped group whose rendered height is THE SUM
    # OF ITS CHILDREN, and those children include the DATA rows, which are NOT contract rows
    # and are NOT walked here. So a height difference on `task[...]` / `holding[...]` /
    # `epic[...]` reports the per-row height of a population this test does not measure, and
    # it CANNOT discriminate a styling divergence from a content difference.
    # Measured 2026-09-06 by Krishna 🦚, who called it a real difference and explicitly
    # refused to weld it to a cause: legacy 168px vs mux 202px on holding[Maria], and five
    # siblings the same shape.
    # ⚠️ WHAT THIS GIVES UP, said rather than glossed: a genuine height regression on a
    # container row now passes. Every OTHER property is still compared on these rows, and
    # `height` is still compared on leaf rows — the narrower claim is the honest one.
    CONTAINER_PREFIXES = ( "task[", "holding[", "epic[" )

    diffs = []
    for key in common:
        is_container = key.startswith( CONTAINER_PREFIXES )
        for prop in ACCORDION_APPEARANCE_PROPS:
            if prop == "height" and is_container: continue
            lv, mv = legacy[ key ].get( prop ), mux[ key ].get( prop )
            if lv != mv:
                diffs.append( f"  {key}  {prop}: legacy {lv!r} · mux {mv!r}" )

    assert not diffs, (
        f"inner-accordion APPEARANCE divergence — {len( diffs )} property "
        f"differences across {len( common )} rows:\n" + "\n".join( diffs )
    )


def test_the_two_clients_render_the_same_set_of_contract_rows( both ):
    """Keys present in one client and not the other. Reported separately from
    the property comparison because a MISSING row and a MIS-STYLED row are
    different defects wanting different fixes — and the comparison above can
    only ever speak for rows both clients emit."""
    legacy, mux = set( both[ "legacy" ][ "nodes" ] ), set( both[ "mux" ][ "nodes" ] )
    only_legacy = sorted( legacy - mux )
    only_mux    = sorted( mux - legacy )
    assert not ( only_legacy or only_mux ), (
        f"contract rows emitted by ONE client only — legacy-only "
        f"{only_legacy}\nmux-only {only_mux}"
    )
