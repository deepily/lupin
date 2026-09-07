"""
Layout-Parity Oracle, Tier 1 — the SECTION-LEVEL accordion, under RICK'S RULED
PREDICATE.

🔨 THE RULING (Rick, 2026-09-06, relayed by María 🌸). Five measured divergences
were put to him. His answer: parity is judged on RENDERED APPEARANCE AND
BEHAVIOUR, NOT NODE IDENTITY. #1-#4 stand as they are, being internal and
invisible on screen. #5 was a real regression and is fixed at `97ab72a2`: the
mux's chevron is now a `<button>` like legacy's, because a `<span
role="button">` carrying no tabindex CANNOT BE FOCUSED, so a keyboard user could
collapse legacy's sections and not the mux's.

🔴 SO THIS MODULE READS ONLY WHAT A USER SEES AND DOES — title text, count text,
chevron glyph, whether the toggle can take focus, and the body's RENDERED
HEIGHT. It asks no tag name, no class name, no id, no wrapper. The four standing
divergences therefore CANNOT fail it by construction, which is the ruling
expressed as code rather than as a promise:

    #1 collapse referee node  legacy `.collapsed` on the content
                              mux `[data-collapsed]` on the section root
    #2 count identity         legacy `span#<pane>-count` (an ID, no class)
                              mux `span.section-header-count` (a class)
    #3 actions wrapper        the mux adds `div.section-header-actions`
    #4 section root           `div.collapsible-section` vs `section#<pane>-pane`

⚠️ HEIGHT, NOT `display` — AND THE FIRST CUT OF THIS GOT IT WRONG. Legacy
collapses with max-height/overflow, so its body drops to ~1px while `display`
never changes; the mux uses `display:none`, so its body goes to 0. A predicate
keyed on either idiom reports the OTHER client as never collapsing. The
assertion is therefore a RATIO — collapsed height under a small fraction of
expanded — so neither idiom is privileged and no magic pixel is baked in.

⚠️ AND THE MUX HARNESS MUST LINK `notifications-surface.css`, WHICH IS WHERE THE
COLLAPSE RULE LIVES. Measured by runtime injection, one variable, both
directions: without the sheet a click flips `data-collapsed` and the chevron
while the body stays 487px; with it the body goes to 0px and restores. A harness
missing that sheet reports the mux as never collapsing — an instrument artifact
that reads exactly like a client defect, and the THIRD time that shape has come
up on this lane (the others: a click probe below the wiring layer, and a
bare-map epic-stories stub).

Venue: :7999-eligible — every API is route-stubbed, nothing is written, seconds.
"""


from __future__ import annotations

import functools
import http.server
import json
import os
import threading

import pytest
import requests

from tests.e2e_ui.parity_oracle import (
    ACCORDION_HARNESS_URL_PATH,
    LEGACY_ACCORDION_URL_PATH,
    SECTION_APPEARANCE_JS,
    SECTION_HEADER_CLICK_JS,
    accordion_composite,
    accordion_stories_body,
    load_accordion_scenario,
    repo_root,
)

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )

# A body is COLLAPSED when its rendered height is a small fraction of its
# expanded height. A ratio rather than a pixel, because legacy lands at ~1px
# (max-height/overflow) and the mux at 0 (display:none) — privileging either
# number would call the other client broken.
COLLAPSED_RATIO = 0.05


@pytest.fixture( scope="module" )
def scenario() -> dict:
    return load_accordion_scenario()


@pytest.fixture( scope="module" )
def tokens():
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


@pytest.fixture( scope="module" )
def static_origin():
    directory = str( repo_root() / "src" / "lupin_app" )
    handler   = functools.partial( http.server.SimpleHTTPRequestHandler, directory=directory )
    server    = http.server.ThreadingHTTPServer( ( "127.0.0.1", 0 ), handler )
    thread    = threading.Thread( target=server.serve_forever, daemon=True )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[ 1 ]}"
    finally:
        server.shutdown(); server.server_close(); thread.join( timeout=5 )


def _mux_sections( page, static_origin, scenario ) -> list:
    page.goto( f"{static_origin}{ACCORDION_HARNESS_URL_PATH}", wait_until="networkidle", timeout=20_000 )
    page.evaluate( "() => { try { window.localStorage.clear(); } catch ( e ) { /* private mode */ } }" )
    page.wait_for_function( "() => window.__accordionHarnessReady === true", timeout=10_000 )
    assert page.evaluate( "( s ) => window.__accordionMountRenderers( s )", scenario ) == 3
    page.wait_for_timeout( 400 )
    return page.evaluate( SECTION_APPEARANCE_JS, "#accordion-panes-container" )


def _legacy_sections( page, tokens, scenario ) -> list:
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( tokens[ 'access_token' ] )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( tokens[ 'refresh_token' ] )});" )
    def _tasks( route ):
        held = "status=not_approved" in route.request.url
        rows = scenario[ "holding_area" if held else "task_list" ][ "tasks" ]
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( accordion_composite( rows, scenario ) ) )
    page.route( "**/api/tasks?**", _tasks )
    page.route( "**/api/epic-stories**", lambda rt: rt.fulfill(
        status=200, content_type="application/json",
        body=json.dumps( accordion_stories_body( scenario ) ) ) )
    page.goto( f"{BASE_URL}{LEGACY_ACCORDION_URL_PATH}", wait_until="networkidle", timeout=30_000 )
    page.wait_for_selector( ".section-header", timeout=20_000 )
    page.wait_for_timeout( 2_000 )
    return page.evaluate( SECTION_APPEARANCE_JS, None )


def test_the_mux_section_headers_render_the_visible_contract( page, static_origin, scenario ):
    """Every mounted pane shows a title, a count and the expanded chevron — the
    things a user can actually see. No tag, class or id is asserted."""
    sections = _mux_sections( page, static_origin, scenario )
    assert len( sections ) == 3, f"one section header per mounted pane; got {len(sections)}"
    for s in sections:
        assert s[ "title" ],  f"a section with no visible title: {s}"
        assert s[ "count" ] is not None and s[ "count" ] != "", f"no count shown: {s}"
        assert s[ "glyph" ] == "▼", f"first load must show the expanded chevron: {s}"
        assert s[ "body_height" ] > 0, f"the body must be visible on first load: {s}"


def test_the_section_toggle_can_take_focus_on_both_clients( page, tokens, static_origin, scenario ):
    """🔴 DIVERGENCE #5 — THE ONLY ONE RICK RULED A REGRESSION. A
    `<span role="button">` with no tabindex cannot be focused, so a keyboard
    user could reach legacy's collapse and not the mux's. Asserted as a
    CAPABILITY, not as a tag name."""
    mux = _mux_sections( page, static_origin, scenario )
    assert all( s[ "toggle_focusable" ] for s in mux ), f"a mux toggle cannot take focus: {mux}"

    legacy = _legacy_sections( page, tokens, scenario )
    assert legacy, "legacy rendered no section headers — the walk found nothing"
    assert all( s[ "toggle_focusable" ] for s in legacy ), "a legacy toggle cannot take focus"


def test_a_header_click_collapses_the_body_and_a_second_restores_it( page, static_origin, scenario ):
    """The BEHAVIOUR half of the ruled predicate, on this tree's mux. Height
    rather than `display`, and a ratio rather than a pixel."""
    before = _mux_sections( page, static_origin, scenario )
    assert page.evaluate( SECTION_HEADER_CLICK_JS, [ "#accordion-panes-container", 0 ] )
    page.wait_for_timeout( 300 )
    after = page.evaluate( SECTION_APPEARANCE_JS, "#accordion-panes-container" )
    assert after[ 0 ][ "glyph" ] == "▶", f"the chevron must follow the state: {after[0]}"
    assert after[ 0 ][ "body_height" ] < before[ 0 ][ "body_height" ] * COLLAPSED_RATIO, (
        f"the body did not collapse: {before[0]['body_height']}px -> {after[0]['body_height']}px. "
        "If the attribute flipped and the height did not, this harness is missing "
        "notifications-surface.css, which is where the collapse rule lives."
    )

    assert page.evaluate( SECTION_HEADER_CLICK_JS, [ "#accordion-panes-container", 0 ] )
    page.wait_for_timeout( 300 )
    restored = page.evaluate( SECTION_APPEARANCE_JS, "#accordion-panes-container" )
    assert restored[ 0 ] == before[ 0 ], f"a second click did not restore: {before[0]} -> {restored[0]}"


def test_the_four_standing_divergences_cannot_fail_this_predicate( page, tokens, static_origin, scenario ):
    """🔨 RICK'S RULING AS AN EXECUTABLE CLAIM. #1–#4 are node-identity
    differences — the collapse referee node, the count keyed by ID vs class, the
    mux's extra actions wrapper, the section root's tag and class. This walker
    returns none of those, so the two clients' section rows must agree on the
    fields it DOES return: the chevron glyph and the toggle's focusability.

    ⚠️ Titles and counts are NOT compared across clients: the two pages carry
    different section inventories (legacy renders 15 headers, the mux's harness
    3), so an equality there would be a claim about page composition rather than
    about the accordion contract."""
    mux    = _mux_sections( page, static_origin, scenario )
    legacy = _legacy_sections( page, tokens, scenario )
    assert legacy and mux, "one side rendered nothing — an empty walk agrees with anything"

    assert { s[ "glyph" ] for s in mux } == { "▼" }
    assert "▼" in { s[ "glyph" ] for s in legacy }, "legacy shows no expanded chevron"
    assert all( s[ "toggle_focusable" ] for s in mux + legacy )
