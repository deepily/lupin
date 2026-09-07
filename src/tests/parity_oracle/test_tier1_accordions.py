"""
Layout-Parity Oracle, Tier 1 — INNER-ACCORDION contract conformance.

Feeds the canonical accordion fixture to the MUX renderers in a component-
isolation harness, walks the produced subtree, and asserts it conforms to the
13 inner-accordion rows of the Layout Contract
(`css/shared/LAYOUT-CONTRACT.md` § "The inner accordions — IN the contract").

🔴 THE INVARIANT HALF ONLY. The SECTION-LEVEL chrome (`.section-header`,
`.toggle-button`, `.collapsed` ∪ `[data-collapsed]`) is deliberately NOT walked
here. Five measured divergences on it are with Rick, and the predicate a walker
would encode changes depending on how he rules; a walker written now would bake
in a definition of "exactly" that is still open. The 13 rows below do not move
under that ruling, which is what makes them buildable today.

🔴 THIS IS A SIBLING ENTRY, NOT A WIDENING OF `test_tier1.py`. That module
asserts `count == 2` sender cards on `#sender-cards-container`; mounting a pane
into that root would make a notifications-surface assertion answer for a
different surface, so a failure would no longer name the surface that broke.
This module owns `#accordion-panes-container` and its own harness page.

⚠️ FLEET STATUS CONTRIBUTES NO ROW. It renders a flat table with no inner
grouping in either client, so it has no inner accordion to contract — three
panes mount here, not four. Its absence is a property of the pane.

🔴 WHY THIS ENTRY SERVES ITS OWN TREE INSTEAD OF POINTING AT :7999 — MEASURED,
NOT ASSUMED. The dev container bind-mounts `./src` from the MAIN CHECKOUT
(`docker-compose.yml:169`), so a browser tier run from a worktree loads the main
tree's assets, not the author's. Measured 2026-09-06 from
`lupin-wt-cc-author-maria-1`, two independent readings agreeing:
  - `/static/dist/multiplexer/parity-harness.js` served **26,015** bytes while
    this worktree's freshly built bundle is **26,312** — different bytes for a
    file present in both trees
  - `/static/html/accordion-harness.html` answered **404** while the file exists
    on disk here
⇒ A worktree run against :7999 measures a tree the author is not editing, and
nothing in a green says so. This module therefore serves the repo's OWN static
tree over an ephemeral loopback static server: no DB, no API, no auth, no state
— the harness is pure static assets, so a file server is a complete venue.
⚠️ This does NOT establish anything about `test_tier1.py`, which still points at
`LUPIN_TEST_BASE_URL`. Whether that entry should migrate is the methodology
owner's call, not this module's.

Venue: :7999-eligible by the rubric — no persistent-state mutation, seconds, no
monopoly. It needs no server at all.

    bash src/scripts/build-parity-harness.sh     # (the conftest does this too)
    pytest src/tests/parity_oracle/test_tier1_accordions.py -v
"""

from __future__ import annotations

import functools
import http.server
import threading
from collections import Counter

import pytest

from tests.e2e_ui.parity_oracle import (
    ACCORDION_HARNESS_URL_PATH,
    ACCORDION_ROOT_SEL,
    ACCORDION_SKELETON_JS,
    load_accordion_scenario,
    repo_root,
)

# The contract's chevron glyphs — named in LAYOUT-CONTRACT.md, identical in both
# clients, and the reason a walker may read this one piece of text.
GLYPH_EXPANDED  = "▾"
GLYPH_COLLAPSED = "▸"


@pytest.fixture( scope="module" )
def static_origin():
    """Serve THIS repo's `src/lupin_app/` over loopback so `/static/...` resolves
    to the tree under test rather than to whatever the dev container mounts.

    Ensures:
        - yields an origin string like "http://127.0.0.1:38271"
        - the server is bound to 127.0.0.1 on an ephemeral port and shut down
          on teardown
    """
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


@pytest.fixture( scope="function" )
def skeleton( page, static_origin ) -> dict:
    """Mount the canonical accordion scenario and return the walked skeleton."""
    page.goto( f"{static_origin}{ACCORDION_HARNESS_URL_PATH}", wait_until="networkidle", timeout=20_000 )
    page.wait_for_function(
        "() => window.__accordionHarnessReady === true && typeof window.__accordionMount === 'function'",
        timeout=10_000,
    )
    panes = page.evaluate( "( s ) => window.__accordionMount( s )", load_accordion_scenario() )
    assert panes == 3, f"harness must mount 3 panes (fleet status has no inner accordion); got {panes}"
    walked = page.evaluate( ACCORDION_SKELETON_JS, ACCORDION_ROOT_SEL )
    assert walked is not None, "accordion skeleton walker found no root"
    return walked


# ---------------------------------------------------------------------------
# Expected values are derived from the FIXTURE by plain Python here, never read
# back off the render. The two sides must have different provenance or the
# comparison is an identity that cannot fail.
# ---------------------------------------------------------------------------

def _owner_counts() -> Counter:
    """Tasks per owner, unassigned keyed as None. Independent of the TS model."""
    return Counter( t.get( "owner_persona" ) or None for t in load_accordion_scenario()[ "task_list" ][ "tasks" ] )


def _epic_counts() -> Counter:
    """Tasks per correlation_key, epic-less keyed as None. Independent of the TS model."""
    return Counter( t.get( "correlation_key" ) or None for t in load_accordion_scenario()[ "task_list" ][ "tasks" ] )


def _filer_counts() -> Counter:
    """Held rows per created_by. Independent of the TS filer-label derivation."""
    return Counter( t.get( "created_by" ) or None for t in load_accordion_scenario()[ "holding_area" ][ "tasks" ] )


def test_the_three_panes_mount_into_their_own_root( skeleton ):
    """The harness root holds exactly the three panes that HAVE an inner
    accordion, in order — and none of them is the sender-card surface."""
    assert skeleton[ "panes" ] == [ "pane-task-list", "pane-holding-area", "pane-epic-board" ]


def test_task_groups_carry_the_contract_row_and_its_affordance( skeleton ):
    """`tbody.task-group[id][data-owner]` with a header row carrying the full
    accordion affordance and an aria-hidden chevron — one group per owner, with
    the fixture's deliberately distinct group sizes."""
    groups = skeleton[ "task_groups" ]
    assert len( groups ) == len( _owner_counts() ), "one .task-group per owner bucket"

    for g in groups:
        assert g[ "id" ],    "the tbody must carry the id its header's aria-controls names"
        assert g[ "owner" ], "the tbody must carry data-owner"
        assert g[ "has_header" ], f"group {g['owner']} has no tr.task-group-header"
        hdr = g[ "header" ]
        assert hdr[ "role" ]          == "button"
        assert hdr[ "tabindex" ]      == "0"
        assert hdr[ "aria_controls" ] == g[ "id" ], "aria-controls must name its own tbody"
        chev = g[ "chevron" ]
        assert chev is not None, f"group {g['owner']} has no span.task-group-chevron"
        assert chev[ "aria_hidden" ] == "true", "the chevron is decorative"


def test_task_groups_default_expanded_and_the_referee_is_the_container_class( skeleton ):
    """The task pane's collapse referee is a CLASS ON THE <tbody>, and its
    first-load default is EXPANDED. Both halves are asserted because a renderer
    that moved the referee to the header would still satisfy the other."""
    for g in skeleton[ "task_groups" ]:
        assert g[ "collapsed" ] is False,                  "first load: every owner group expanded"
        assert g[ "header" ][ "aria_expanded" ] == "true", "aria must agree with the class referee"
        assert g[ "chevron" ][ "glyph" ] == GLYPH_EXPANDED


def test_epic_groups_default_collapsed_and_the_referee_is_the_header_aria( skeleton ):
    """🔴 THE OPPOSITE DEFAULT TO THE TASK PANE'S, AND THAT ASYMMETRY IS REAL.
    `epicDefaultExpanded()` expands only the waiting-on-Rick highlight, so with
    no recorded viewer choice every epic section renders COLLAPSED. A walker
    keyed to one pane's idiom would report the other's groups as broken."""
    groups = skeleton[ "epic_groups" ]
    assert groups, "the epic board must render sections"
    for g in groups:
        assert g[ "collapsed" ] is True,                    f"{g['epic']}: first load is collapsed"
        assert g[ "header" ][ "aria_expanded" ] == "false", "aria must agree with the class referee"
        assert g[ "chevron" ][ "glyph" ] == GLYPH_COLLAPSED
        assert g[ "chevron" ][ "aria_hidden" ] == "true"
        assert g[ "header" ][ "aria_controls" ] == g[ "id" ]


def test_epic_sections_are_the_fixture_epics_plus_the_always_on_drift_section( skeleton ):
    """One section per epic key with its own count, plus the drift sentinel that
    renders ALWAYS — a drift section that disappeared when satisfied would be
    indistinguishable from one that failed to render."""
    counts = _epic_counts()
    by_key = { g[ "epic" ]: g for g in skeleton[ "epic_groups" ] }

    assert "__drift__" in by_key, "the drift section renders always, even at zero"
    assert by_key[ "__drift__" ][ "count" ] == str( counts[ None ] )

    for epic_key, n in counts.items():
        if epic_key is None:
            continue
        assert epic_key in by_key, f"no section for {epic_key}"
        assert by_key[ epic_key ][ "count" ] == str( n ), f"{epic_key}: count cell must equal its row count"
        assert by_key[ epic_key ][ "label" ], "every section renders a span.epic-group-label"

    # No task in this fixture is blocked on Rick, so no highlight section exists.
    assert set( by_key ) == { k for k in counts if k is not None } | { "__drift__" }


def test_the_epic_story_row_rides_inside_its_group( skeleton ):
    """`tr.epic-story-row` — the story is a CHILD OF THE GROUP, so opening an
    epic answers "what is this?" in the same gesture that reveals its rows.
    epic:alpha carries a story in the fixture; epic:beta deliberately does not."""
    by_key = { g[ "epic" ]: g for g in skeleton[ "epic_groups" ] }
    assert by_key[ "epic:alpha" ][ "story_rows" ] == 1, "the storied epic renders its story row"
    assert by_key[ "epic:beta"  ][ "story_rows" ] == 0, "an epic with no story renders no story row"


def test_holding_groups_are_keyed_by_filer_including_the_status_span( skeleton ):
    """`div.holding-area-group[data-filer]` with header, filer label and count —
    and the status span carrying data-filer too. ⚠️ EVERY control in that header
    is keyed by FILER rather than by task id, the status span included, because
    the batch handler finds a group's rows by that attribute."""
    groups = skeleton[ "holding_groups" ]
    counts = _filer_counts()
    assert len( groups ) == len( counts ), "one .holding-area-group per filer bucket"

    for g in groups:
        assert g[ "filer" ],      "the group wrapper must carry data-filer"
        assert g[ "has_header" ], f"filer {g['filer']} has no .holding-area-group-header"
        assert g[ "filer_label" ] == g[ "filer" ], "the header displays the key it is keyed by"
        assert g[ "status_filer" ] == g[ "filer" ], "the status span must carry the SAME data-filer"

    assert sorted( int( g[ "count" ] ) for g in groups ) == sorted( counts.values() ), \
        "group sizes are deliberately distinct in the fixture, so a swap is visible"
