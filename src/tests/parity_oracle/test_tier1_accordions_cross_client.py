"""
Layout-Parity Oracle, Tier 1 — INNER ACCORDIONS, BOTH CLIENTS, ONE FIXTURE.

`test_tier1_accordions.py` asks whether the MUX emits the contract. This module
asks the question that one cannot: **does legacy emit the same thing, and does a
real click do the same thing on both?** One fixture, one walker, two clients —
"the same" is defined by ONE referee rather than by two hand-written checks.

WHAT IT COMPARES — the 13 inner-accordion rows of the Layout Contract: the task
owner groups, the epic sections and the holding-area filer groups, with their
ids, keys, collapse state, aria affordance, chevron glyphs and counts. The
SECTION-LEVEL chrome is not walked: five measured divergences on it are with
Rick and its predicate is still open.

🔴 THE CLICK MUST BE ASKED AT THE LAYER THAT CARRIES THE WIRING. The mux's
accordion listener is a DELEGATED listener on the renderer's container
(`TaskListRenderer.ts:204`, `EpicBoardRenderer.ts:138`), NOT anything the
templates install. So the component-isolation harness — which mounts templates —
CANNOT toggle, and its silence is an instrument artifact rather than a finding
about the client. Measured 2026-09-06: the harness reported the mux as inert
through two clicks while the real page toggled correctly. The click tests here
therefore drive the REAL PAGES.

⚠️ WHICH TREE EACH SIDE COMES FROM, SAID OUT LOUD. The dev container bind-mounts
`./src` from the MAIN CHECKOUT (`docker-compose.yml:169`), so a page served by
:7999 is not necessarily this worktree's code. Two guards below make that
assumption FAIL LOUDLY instead of silently measuring somebody else's tree:
`test_the_served_legacy_renderer_is_this_tree_s` hashes the served
`notifications.js` against this tree's, and
`test_the_mux_click_path_is_unmodified_in_this_tree` pins the seven files on the
mux click path against the main checkout. If either goes red, the cross-client
claim is about a tree you are not editing and must not be reported.

🔴 THE MUX SIDE IS THE HARNESS, AND THE HARNESS IS NOT THE PRODUCT. THIS IS A
KNOWN FALSE GREEN ON ONE FIELD TODAY, NOT A THEORETICAL LIMIT. The equality test
below takes legacy from the SERVED page and the mux from `_walk_mux_harness`.
Krishna 🦚 measured all three venues over ONE fixture in COMMIT `aa9851bc`,
and they do not agree. ⚠️ That commit is in this repo but is NOT an ancestor of
this branch, so `git show aa9851bc` resolves it while its doc
`src/rnd/2026.09.06-live-mux-drops-the-epic-story-row.md` is NOT yet on disk here —
cite the commit, not the path, until the branches meet:

    LIVE legacy   /app/notifications?classic=1   epic:alpha story rows = 1
    LIVE mux      /app/multiplexer               epic:alpha story rows = 0   <- the product
    HARNESS mux   this module's venue            epic:alpha story rows = 1   <- what we compare

`epic_groups` carries `story_rows` (`parity_oracle.py:355`, a count of
`tr.epic-story-row`), and the loop below asserts that family cell for cell. So
**this test passes on `story_rows` ONLY BECAUSE the mux side is the harness** —
sourced from the live mux, on his measurement, it would go red. Every other field
he walked was identical across all three venues, so the divergence is currently
known to be this one field; nobody has swept the rest.

⚠️ Whose measurement is whose: the three-venue table is HIS, not re-derived here.
The `story_rows` walk and the cell-for-cell assertion are MINE. The MECHANISM is
measured by NOBODY — he ruled his instrument out (both clients were served his
stub) and then explicitly declined to name a cause, listing a store parse, an
ordering race and a composition path as all consistent with the four facts.
`multiplexer/boot.ts:624` fires `stores.epicStories.load()` UNAWAITED and its own
comment names "no story rows" as the pre-load render state — that is a LEAD
consistent with one of his three, and it rules out neither of the others. Do not
promote it to a cause in this file or on any row.

⇒ A HARNESS CAN DIVERGE FROM THE PRODUCT IN BOTH DIRECTIONS, and this module has
now been bitten each way: the component harness reported the mux INERT through two
real clicks (below), and this renderer harness reports a row the user never sees.
A cross-client green taken here carries that caveat in both directions.

Venue: :7999-eligible — every API is route-stubbed so nothing is written, the
run is seconds, and it needs no monopoly. It DOES need a reachable :7999 and the
test credentials; both are skips, not failures.

    bash src/scripts/build-parity-harness.sh   # (the conftest does this too)
    pytest src/tests/parity_oracle/test_tier1_accordions_cross_client.py -v
"""

from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

import pytest
import requests

from tests.e2e_ui.parity_oracle import (
    ACCORDION_CLICK_PATH_RELPATHS,
    ACCORDION_HARNESS_URL_PATH,
    ACCORDION_SKELETON_JS,
    LEGACY_ACCORDION_URL_PATH,
    LEGACY_RENDERER_HREF,
    LEGACY_RENDERER_RELPATH,
    MUX_ACCORDION_URL_PATH,
    accordion_composite,
    accordion_stories_body,
    load_accordion_scenario,
    repo_root,
)

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )

# The three families the walker returns; `panes` is harness-only and deliberately
# excluded — legacy has no such wrapper and its absence is not a divergence.
CONTRACT_FAMILIES = ( "task_groups", "epic_groups", "holding_groups" )


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


@pytest.fixture( scope="module" )
def static_origin():
    """This repo's own `src/lupin_app/` over loopback — the MUX side's venue, so
    the structural comparison reads the tree under edit rather than the served one."""
    directory = str( repo_root() / "src" / "lupin_app" )
    handler   = functools.partial( http.server.SimpleHTTPRequestHandler, directory=directory )
    server    = http.server.ThreadingHTTPServer( ( "127.0.0.1", 0 ), handler )
    thread    = threading.Thread( target=server.serve_forever, daemon=True )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[ 1 ]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join( timeout=5 )


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


def _authed_page( page, tokens ):
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( tokens[ 'access_token' ] )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( tokens[ 'refresh_token' ] )});"
    )


def _walk_live_page( page, tokens, scenario, path ) -> dict:
    """Drive a REAL client page over the fixture and walk its accordions."""
    _authed_page( page, tokens )
    _stub_pane_apis( page, scenario )
    page.goto( f"{BASE_URL}{path}", wait_until="networkidle", timeout=30_000 )
    page.wait_for_selector( "tbody.task-group", timeout=20_000 )
    page.wait_for_timeout( 1_500 )   # let the epic + holding panes finish painting
    return page.evaluate( ACCORDION_SKELETON_JS, "body" )


def _mount_mux_renderers( page, static_origin, scenario ) -> None:
    """Mount the REAL renderers — the layer the delegated click listener lives on.

    ⚠️ The viewer's recorded epic choices live in localStorage, so the first-load
    default is only the default on a tree with nothing recorded. Cleared here so
    the assertion is about `epicDefaultExpanded()` and not about a leftover.
    """
    page.goto( f"{static_origin}{ACCORDION_HARNESS_URL_PATH}", wait_until="networkidle", timeout=20_000 )
    page.evaluate( "() => { try { window.localStorage.clear(); } catch ( e ) { /* private mode */ } }" )
    page.wait_for_function( "() => window.__accordionHarnessReady === true", timeout=10_000 )
    mounted = page.evaluate( "( s ) => window.__accordionMountRenderers( s )", scenario )
    assert mounted == 3, f"the renderer harness must mount 3 panes; got {mounted}"


def _walk_mux_harness( page, static_origin, scenario ) -> dict:
    page.goto( f"{static_origin}{ACCORDION_HARNESS_URL_PATH}", wait_until="networkidle", timeout=20_000 )
    page.wait_for_function( "() => window.__accordionHarnessReady === true", timeout=10_000 )
    page.evaluate( "( s ) => window.__accordionMount( s )", scenario )
    return page.evaluate( ACCORDION_SKELETON_JS, "body" )


# ---------------------------------------------------------------------------
# PROVENANCE GUARDS — these make the venue assumption fail loudly.
# ---------------------------------------------------------------------------

def test_the_served_legacy_renderer_is_this_tree_s():
    """The legacy side is measured on :7999, whose container may mount another
    tree. Hash what is actually SERVED against this tree's file; anything else
    means the comparison below is about code you are not editing."""
    try:
        served = requests.get( f"{BASE_URL}{LEGACY_RENDERER_HREF}", timeout=10 )
    except requests.RequestException as exc:
        pytest.skip( f"{BASE_URL} unreachable: {exc}" )
    assert served.status_code == 200, f"legacy renderer not served: {served.status_code}"
    mine = ( repo_root() / LEGACY_RENDERER_RELPATH ).read_bytes()
    assert _sha( served.content ) == _sha( mine ), (
        "the served notifications.js is NOT this tree's — the cross-client result would "
        "describe a different checkout. Bounce the dev server onto this tree, or read the "
        "legacy side as somebody else's."
    )


def test_the_mux_click_path_is_unmodified_in_this_tree():
    """The click tests drive the SERVED mux page, so they only speak for this
    tree while this tree has not changed the click path. Pin all seven files
    against the main checkout; a red here means the click result no longer
    transfers and the venue must change before it is reported."""
    # `--git-common-dir` resolves to the MAIN checkout's .git from inside any
    # worktree, so its parent is the main checkout — no hardcoded path, and it
    # works from the main tree too (where it degrades to a no-op comparison).
    resolved = subprocess.run(
        [ "git", "rev-parse", "--path-format=absolute", "--git-common-dir" ],
        cwd=repo_root(), capture_output=True, text=True, timeout=30 )
    assert resolved.returncode == 0, f"git rev-parse failed: {resolved.stderr.strip()}"
    main = Path( resolved.stdout.strip() ).parent
    assert ( main / LEGACY_RENDERER_RELPATH ).exists(), (
        f"the main checkout resolved to {main}, which does not hold {LEGACY_RENDERER_RELPATH} — "
        "the venue assumption cannot be checked, so do not report a click result from here"
    )
    if main == repo_root():
        pytest.skip( "running in the main checkout — there is no second tree to drift from" )

    drifted = [ rel for rel in ACCORDION_CLICK_PATH_RELPATHS
                if _sha( ( repo_root() / rel ).read_bytes() ) != _sha( ( main / rel ).read_bytes() ) ]
    assert drifted == [], (
        "this tree has changed the mux accordion click path, so a click measured on the "
        f"SERVED page no longer describes it: {drifted}"
    )


# ---------------------------------------------------------------------------
# THE COMPARISON
# ---------------------------------------------------------------------------

def test_both_clients_emit_the_same_inner_accordions_over_one_fixture( page, tokens, scenario, static_origin ):
    """🔴 THE CROSS-CLIENT CLAIM. One fixture, one walker, two renderers — the
    13 contract rows must agree cell for cell: ids, keys, collapse state, the
    full aria affordance, the chevron glyphs and the counts.

    The mux side is this tree's own harness; the legacy side is the served page,
    guarded above to be this tree's `notifications.js`.

    🔴 READ THE MODULE DOCSTRING BEFORE QUOTING THIS TEST'S GREEN. The
    `epic_groups` family includes `story_rows`, and the harness emits that row
    where the LIVE mux does not (Krishna 🦚, `aa9851bc`, three venues over
    one fixture). On `story_rows` this assertion is green because of the venue,
    not because the clients agree."""
    mux    = _walk_mux_harness( page, static_origin, scenario )
    legacy = _walk_live_page( page, tokens, scenario, LEGACY_ACCORDION_URL_PATH )

    # A positive control: an empty walk agrees with an empty walk, and would pass
    # every per-item assertion below while measuring nothing at all.
    assert len( legacy[ "task_groups" ] ) >= 3, "legacy rendered no owner groups — the walk found nothing"
    assert len( legacy[ "epic_groups" ] ) >= 3, "legacy rendered no epic sections"
    assert len( legacy[ "holding_groups" ] ) >= 3, "legacy rendered no filer groups"

    for family in CONTRACT_FAMILIES:
        assert legacy[ family ] == mux[ family ], (
            f"{family} DIVERGE between the clients:\n"
            f"  legacy: {json.dumps( legacy[ family ], ensure_ascii=False )}\n"
            f"  mux   : {json.dumps( mux[ family ], ensure_ascii=False )}"
        )


@pytest.mark.parametrize( "client_path", [ LEGACY_ACCORDION_URL_PATH, MUX_ACCORDION_URL_PATH ] )
@pytest.mark.parametrize(
    "family,group_sel,header_sel,key_attr,starts_collapsed",
    [
        ( "task", "tbody.task-group", "tr.task-group-header", "data-owner", False ),
        ( "epic", "tbody.epic-group", "tr.epic-group-header", "data-epic",  True  ),
    ],
)
def test_a_real_click_toggles_and_a_second_click_restores( page, tokens, scenario, client_path,
                                                           family, group_sel, header_sel,
                                                           key_attr, starts_collapsed ):
    """Click the first group's header on a REAL page, then click it back.

    ⚠️ THE NODE IS REPLACED BY THE REPAINT, so every reading re-queries the live
    DOM by the group's KEY rather than holding the element across the click — a
    stale handle reports the pre-click node forever and reads as an inert client.

    The SECOND click is not ceremony: a toggle that fires and a toggle that
    fires CORRECTLY are different claims, and only the restore separates them."""
    _authed_page( page, tokens )
    _stub_pane_apis( page, scenario )
    page.goto( f"{BASE_URL}{client_path}", wait_until="networkidle", timeout=30_000 )
    page.wait_for_selector( group_sel, timeout=20_000 )
    page.wait_for_timeout( 1_500 )

    key = page.evaluate( "( s ) => document.querySelector( s[0] ).getAttribute( s[1] )",
                         [ group_sel, key_attr ] )
    assert key, f"{family}: the group carries no {key_attr}"

    read = """( a ) => {
        const [ sg, sh, ka, key ] = a;
        const g = document.querySelector( sg + '[' + ka + '="' + key + '"]' );
        if ( !g ) return null;
        const h = g.querySelector( sh );
        const c = h.querySelector( "span[class$='-chevron']" );
        return { collapsed: g.classList.contains( "collapsed" ),
                 aria: h.getAttribute( "aria-expanded" ),
                 glyph: c ? c.textContent.trim() : null };
    }"""
    click = """( a ) => {
        const [ sg, sh, ka, key ] = a;
        document.querySelector( sg + '[' + ka + '="' + key + '"]' ).querySelector( sh ).click();
    }"""
    args = [ group_sel, header_sel, key_attr, key ]

    before = page.evaluate( read, args )
    assert before[ "collapsed" ] is starts_collapsed, f"{family}: unexpected first-load state {before}"

    page.evaluate( click, args ); page.wait_for_timeout( 400 )
    after1 = page.evaluate( read, args )
    assert after1[ "collapsed" ] is not starts_collapsed, f"{family}: the click did not toggle ({after1})"
    assert after1[ "aria" ] == ( "true" if not after1[ "collapsed" ] else "false" ), \
        f"{family}: aria-expanded disagrees with the class referee ({after1})"
    assert after1[ "glyph" ] == ( "▸" if after1[ "collapsed" ] else "▾" ), \
        f"{family}: the chevron glyph did not follow the state ({after1})"

    page.evaluate( click, args ); page.wait_for_timeout( 400 )
    after2 = page.evaluate( read, args )
    assert after2 == before, f"{family}: a second click did not restore — {before} -> {after2}"


@pytest.mark.parametrize(
    "family,group_sel,header_sel,key_attr,starts_collapsed",
    [
        ( "task", "tbody.task-group", "tr.task-group-header", "data-owner", False ),
        ( "epic", "tbody.epic-group", "tr.epic-group-header", "data-epic",  True  ),
    ],
)
def test_the_mux_click_is_falsifiable_from_this_tree( page, scenario, static_origin,
                                                      family, group_sel, header_sel,
                                                      key_attr, starts_collapsed ):
    """🔴 THE SAME CLICK CLAIM, ASKED WHERE A MUTATION IN THIS WORKTREE CAN KILL IT.

    The parametrized test above drives the SERVED pages, which is the honest
    end-to-end venue and is also unfalsifiable from here — the server may be
    running another tree's code, so no edit of mine can redden it. This one
    mounts THIS tree's renderers in the harness, so the mux half of the click
    claim finally has a guard somebody can break on purpose.

    ⚠️ It is NOT a replacement for the served-page test. That one answers "does
    the shipped page work"; this one answers "does this tree's code work". Two
    different questions, and dropping either leaves a real gap.
    """
    _mount_mux_renderers( page, static_origin, scenario )

    key = page.evaluate( "( s ) => document.querySelector( s[0] ).getAttribute( s[1] )",
                         [ group_sel, key_attr ] )
    assert key, f"{family}: the group carries no {key_attr}"

    read = """( a ) => {
        const [ sg, sh, ka, key ] = a;
        const g = document.querySelector( sg + '[' + ka + '="' + key + '"]' );
        if ( !g ) return null;
        const h = g.querySelector( sh );
        const c = h.querySelector( "span[class$='-chevron']" );
        return { collapsed: g.classList.contains( "collapsed" ),
                 aria: h.getAttribute( "aria-expanded" ),
                 glyph: c ? c.textContent.trim() : null };
    }"""
    click = """( a ) => {
        const [ sg, sh, ka, key ] = a;
        document.querySelector( sg + '[' + ka + '="' + key + '"]' ).querySelector( sh ).click();
    }"""
    args = [ group_sel, header_sel, key_attr, key ]

    before = page.evaluate( read, args )
    assert before[ "collapsed" ] is starts_collapsed, f"{family}: unexpected first-load state {before}"

    page.evaluate( click, args ); page.wait_for_timeout( 300 )
    after1 = page.evaluate( read, args )
    assert after1[ "collapsed" ] is not starts_collapsed, f"{family}: the click did not toggle ({after1})"
    assert after1[ "aria" ] == ( "true" if not after1[ "collapsed" ] else "false" ), \
        f"{family}: aria-expanded disagrees with the class referee ({after1})"
    assert after1[ "glyph" ] == ( "▸" if after1[ "collapsed" ] else "▾" ), \
        f"{family}: the chevron glyph did not follow the state ({after1})"

    page.evaluate( click, args ); page.wait_for_timeout( 300 )
    after2 = page.evaluate( read, args )
    assert after2 == before, f"{family}: a second click did not restore — {before} -> {after2}"
