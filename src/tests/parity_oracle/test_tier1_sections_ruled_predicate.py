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
from tests.helpers import app_login

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
    return app_login.login( BASE_URL, email, password )[ "tokens" ]


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


# ---------------------------------------------------------------------------
# THE GUARD OVER THE WALKER ITSELF — here rather than in a unit test because the
# defect it names is only observable in a laid-out page.
# ---------------------------------------------------------------------------

# Every `.section-content` in a section with its OWN height, walked
# INDEPENDENTLY of SECTION_APPEARANCE_JS so the guard below is not the walker
# agreeing with itself.
SECTION_BODIES_JS = r"""
( rootSel ) => {
    const root = document.querySelector( rootSel );
    if ( !root ) return null;
    return [ ...root.querySelectorAll( ".section-header" ) ].map( ( h ) => (
        // `:scope >` for the same reason the walker uses it: a
        // `.section-content` may CONTAIN another (legacy's job-submit cards),
        // and an inner one belongs to the card, not to the section.
        [ ...h.parentElement.querySelectorAll( ":scope > .section-content" ) ]
            .map( ( b ) => Math.round( b.getBoundingClientRect().height ) )
    ) );
}
"""


def test_the_walker_measures_every_body_in_a_section_not_just_the_first( page, static_origin, scenario ):
    """🔴 THE WALKER'S OWN GUARD. A section is allowed MORE THAN ONE
    `.section-content`, and the mux's Task List has two: an empty
    `task-list-notices` banner mount FIRST, then `task-list-container`. The
    notices div carries the class deliberately, so the shared
    `[data-collapsed="true"] > .section-content` rule hides it with the pane.

    A `querySelector` in the walker therefore measured the EMPTY banner and
    reported the Task List body as 0px on first load — an instrument artifact
    that reads exactly like a client defect, and it cost a real triage
    (bisected to bf12ace35, 2026-09-23; row 08b0e669).

    WOULD HAVE FAILED BEFORE THE FIX: the first body measures 0 and the walker
    returned exactly that, so `walked > first` was false.

    The denominator is asserted, not assumed — if the Task List ever drops back
    to one body this test fails loudly rather than passing vacuously over a
    population it never checked."""
    sections = _mux_sections( page, static_origin, scenario )
    bodies   = page.evaluate( SECTION_BODIES_JS, "#accordion-panes-container" )
    assert bodies, "the independent body walk found no sections — an empty walk agrees with anything"
    assert len( bodies ) == len( sections ), (
        f"the two walks disagree on the section count: {len(sections)} vs {len(bodies)}" )

    # The Task List is the multi-body section, and it is FIRST in the harness mount.
    assert sections[ 0 ][ "title" ].startswith( "📋" ), f"expected the Task List first: {sections[0]}"
    assert len( bodies[ 0 ] ) == 2, (
        f"the Task List is expected to carry TWO .section-content bodies (the notices banner "
        f"and the container); it carries {len(bodies[0])}: {bodies[0]}. If the renderer changed, "
        "this guard needs re-reading — do not simply relax the number." )
    assert sections[ 0 ][ "body_count" ] == 2, (
        f"the walker did not report the denominator it summed over: {sections[0]}" )

    # 🔴 THE TRAP, NAMED: the FIRST body is the empty banner and measures 0. A
    # walker that reads only the first reports the whole pane as 0px.
    assert bodies[ 0 ][ 0 ] == 0, (
        f"the notices banner is expected to be empty and 0px on first load; got {bodies[0][0]}px. "
        "If it is no longer 0 this test can no longer tell a summing walker from a "
        "first-child walker, and it must be rewritten rather than retargeted." )
    assert sections[ 0 ][ "body_height" ] > bodies[ 0 ][ 0 ], (
        f"the walker returned the FIRST body ({bodies[0][0]}px) rather than the section's "
        f"bodies: {sections[0]}" )
    assert sections[ 0 ][ "body_height" ] == sum( bodies[ 0 ] ), (
        f"the walker did not sum the section's bodies: {sections[0]['body_height']} != {sum(bodies[0])}" )

    # And the single-body sections are untouched: a sum over one element is that element.
    for i, walked in enumerate( sections[ 1: ], start=1 ):
        assert len( bodies[ i ] ) == 1, f"section {i} unexpectedly has {len(bodies[i])} bodies: {bodies[i]}"
        assert walked[ "body_height" ] == bodies[ i ][ 0 ], (
            f"a one-body section must measure exactly that body: {walked} vs {bodies[i]}" )


# Per legacy section: how many `.section-content` are DIRECT CHILDREN, and how
# many are descendants at any depth. The two numbers differ exactly where a
# section holds a job-submit card, which is what `:scope >` exists to exclude.
LEGACY_NESTED_BODIES_JS = r"""
() => [ ...document.querySelectorAll( ".section-header" ) ].map( ( h ) => {
    const sec = h.parentElement;
    return {
        direct     : sec.querySelectorAll( ":scope > .section-content" ).length,
        descendant : sec.querySelectorAll( ".section-content" ).length,
    };
} )
"""


def test_the_walker_counts_a_sections_own_bodies_not_a_cards_nested_one( page, tokens, scenario ):
    """⚠️ MARÍA'S REVIEW POINT, AS A GUARD. A `.section-content` MAY CONTAIN
    ANOTHER. On the legacy page `#job-submit-section` holds
    `#claude-code-section`, `#research-submit-section` and
    `#test-suite-submit-section`; `#notifications-section` holds
    `#broadcast-submit-section` (notifications.html). Those inner bodies belong
    to job-submit CARDS — they sit under `.job-submit-card-header`, not
    `.section-header`, so nothing walks them as sections of their own.

    A bare descendant `querySelectorAll` would fold a card's height into its
    section's, and would count a `.collapsed` card as part of an expanded
    section. WOULD HAVE FAILED WITHOUT `:scope >`: the nesting section's walked
    `body_count` would be its descendant count, not 1.

    The denominator is asserted rather than assumed — if legacy ever stops
    nesting, this guard fails loudly instead of passing over a page that no
    longer contains the case it was written for."""
    walked = _legacy_sections( page, tokens, scenario )
    shapes = page.evaluate( LEGACY_NESTED_BODIES_JS )
    assert walked and shapes, "legacy rendered no section headers — an empty walk agrees with anything"
    assert len( walked ) == len( shapes ), (
        f"the two walks disagree on the legacy section count: {len(walked)} vs {len(shapes)}" )

    nesting = [ i for i, s in enumerate( shapes ) if s[ "descendant" ] > s[ "direct" ] ]
    assert nesting, (
        "no legacy section carries a NESTED .section-content, so this guard cannot tell a "
        "`:scope >` walk from a descendant walk. If the job-submit cards stopped nesting, "
        "rewrite this test rather than deleting it." )

    for i in nesting:
        assert shapes[ i ][ "direct" ] == 1, (
            f"legacy section {i} is expected to own exactly one body; it has "
            f"{shapes[i]['direct']} direct and {shapes[i]['descendant']} descendant: {walked[i]}" )
        assert walked[ i ][ "body_count" ] == 1, (
            f"the walker counted a CARD's nested body as the section's: {walked[i]} "
            f"(direct={shapes[i]['direct']}, descendant={shapes[i]['descendant']})" )
