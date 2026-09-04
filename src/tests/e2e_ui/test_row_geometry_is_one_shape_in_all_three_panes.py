"""
E2E UI guard for the ROW's GEOMETRY in all three panes — real browser, real layout.

WHY THIS EXISTS, AND WHY 575 GREEN UNIT TESTS DID NOT CLOSE IT.
`the_row_is_one_shape_in_all_three_panes.test.ts` runs under happy-dom, which
has NO LAYOUT ENGINE: every geometry value reads back `0` while computed
styles return the DECLARATION verbatim (`display "flow-root"`, `width
"3.71%"` — never resolved). On 2026-09-03 that produced 574 green tests over
a visibly broken page three separate times in one evening. A unit guard here
can pin DECLARATIONS and can never pin GEOMETRY.

⇒ SO THIS SUITE ENTERS AT THE LAYER THE INCIDENT ENTERED AT, and it is the
same reasoning as `test_holding_area_per_row_editor.py`: the defect that cost
an evening was a control rendered 108px outside a 916px pane, and from a
chair `unreachable` and `absent` are one observation.

WHAT IS PINNED — four arms, each over all three panes:

  1. THE SIX COLUMNS ARE ONE SCHEMA. Every column occupies the same fraction
     of its own table in the task list, the holding area and the epic board.
     🔴 THIS IS RICK'S ACTUAL REQUIREMENT AND NOTHING GUARDED IT BEFORE THIS
     FILE. `task-list.css` says so in its own comment: "Fitting the pane was
     never the requirement; being IDENTICAL was."
  2. NO HORIZONTAL SCROLL, with a row CLOSED and again with it OPEN. Opening
     the disclosure injects a full-width spanning row; a colspan that has
     drifted from the header count widens the table and the pane clips it.
  3. THE TOGGLE IS INSIDE ITS PANE AND IS WHAT A CLICK THERE REACHES.
  4. THE TITLE IS BOUND TO TWO LINES — `clientHeight < scrollHeight` on a
     title long enough to overflow. EQUAL MEANS INERT, and inert is exactly
     how the clamp shipped the first time.

⚠️ ARM 4 SEEDS ITS OWN OVERFLOWING TITLE ON PURPOSE. Measured 2026-09-03:
no live row on the real board exercises the clamp — every real title fits
two lines — so a guard reading production data would assert nothing and
report a pass. A clamp is unfalsifiable against content that never overflows.

⚠️ ARM 1 IS NOT KILLED BY CHANGING A WIDTH. The six percentages are shared by
`.task-list-table` and `.epic-board-table` in one rule each, so editing a
VALUE moves all three panes together and this arm stays green — correctly.
What arm 1 catches is a rule that becomes PANE-SCOPED: dropping one selector
from the pair. That is the general form of the sticky-pin defect (row
7bacb4ab), where a rule scoped to `.task-list-table` styled the same element
two ways depending on the view — unifying the MARKUP does not unify the
STYLING, and a pane-scoped rule is a second schema no renderer guard can see.

THE INSTRUMENT CARRIES THE THREE LIES, forward from
`src/rnd/2026.09.04-row-display-progressive-disclosure.md` (commit 9e7eda24).
Hit-testing a control lies three ways and ALL THREE READ AS UNREACHABLE:
off-viewport returns null; a node under the fixed nav (`.lupin-nav`,
z-index 9999) returns `.lupin-nav-inner`; and a node DETACHED by a background
re-render answers every geometric question with an all-zero rect, which
arithmetic renders as "1226.5px outside the pane". Nothing in that output
says the element left the document. Hence: re-query by index immediately
before measuring, assert `document.contains`, clear the fixed nav, report
SKIPPED as SKIPPED, and refuse a verdict when nothing was judgeable.

PROVEN, NOT ASSERTED — two mutation arms plus a restore control, 2026-09-04.
Baseline `cf722c8a` (working tip), run on :8000, tree-state sha `5087b139`,
`tracked-dirty=0`. Every arm mutated the SERVED stylesheet by Playwright
route-interception rather than on disk: `task-list.css` belongs to Pocholo and
this is the shared main checkout, so an in-place edit would race a live peer.

  arm  what it changes                          columns guard   title guard
  C0   nothing — real css, same interception    PASS            PASS
  M1   splits the disclose width pair so only    🔴 RED          PASS
       `.epic-board-table` carries 11%
  M2   `-webkit-line-clamp: 2` -> `none`         PASS            🔴 RED

Each arm reddens ITS OWN guard and leaves the other GREEN, so the two
discriminate rather than merely fail together; C0 rules out the interception
itself as the cause. M1's readout: epic board title .5593 vs .5906, disclose
.1042 vs .0557. M2's: clientHeight 78 == scrollHeight 78 on a 260-char title,
in all three panes — which is the `51/51` shape the clamp originally shipped as.

🔴 M1'S FIRST CUT WAS A NO-OP THAT READ AS APPLIED, and it is recorded because
the next person will reach for the same edit. Replacing the value on the second
line of the comma-joined pair leaves ONE rule with a new number, so all three
panes move together and nothing breaks — while the harness reports `hits == 1,
applied = True`. A break that repairs its own damage is indistinguishable from a
weak guard. The real break is SPLITTING the pair, which is what "a pane-scoped
rule is a second schema" means in the file.

Requires:
    - Test server on the :8000 venue with Testing config
    - Clean test database (via logged_in_page)

Venue: :8000 scheduled — `./src/scripts/run-e2e-ui-tests.sh -k row_geometry`.
"""

import json

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Seed payloads — one set feeds all three panes
# ---------------------------------------------------------------------------

# Long enough to overflow two lines at any plausible title-column width. Arm 4
# is the reason it exists: with a title that fits, clientHeight == scrollHeight
# whether the clamp binds or not, and the arm cannot fail.
LONG_TITLE = (
    "A title long enough to overflow two lines at any plausible column width, "
    "because a clamp measured against content that fits is a clamp that cannot "
    "be observed to bind, and an arm that cannot fail is not a guard at all "
    "however carefully its assertion is worded."
)

EPIC_KEY = "epic:row-display"

OPEN_TASKS = [
    {
        "id"                  : "a0000000-0000-0000-0000-00000000000a",
        "title"               : LONG_TITLE,
        "body"                : "",
        "owner_persona"       : "maya",
        "status"              : "in_progress",
        "item_class"          : "task",
        "blocked_by"          : [],
        "next_chase_ts"       : None,
        "accountable_manager" : "maria",
        "created_by"          : "maria 4f98d12f",
        "priority"            : "P1",
        "project"             : "lupin",
        "correlation_key"     : EPIC_KEY,
    },
    {
        "id"                  : "a0000000-0000-0000-0000-00000000000b",
        "title"               : "A short one, so the pane holds more than a single row",
        "body"                : "",
        "owner_persona"       : "maya",
        "status"              : "queued",
        "item_class"          : "bug",
        "blocked_by"          : [],
        "next_chase_ts"       : None,
        "accountable_manager" : "maria",
        "created_by"          : "maria 4f98d12f",
        "priority"            : "P3",
        "project"             : "lupin",
        "correlation_key"     : EPIC_KEY,
    },
]

# The holding area asks a DIFFERENT question of the same endpoint, so it needs
# its own rows. The long title is repeated deliberately: arm 4 must be able to
# judge every pane, not two of them.
HELD_TASKS = [
    {
        "id"                  : "b0000000-0000-0000-0000-00000000000a",
        "title"               : LONG_TITLE,
        "body"                : "",
        "owner_persona"       : "maya",
        "status"              : "not_approved",
        "item_class"          : "task",
        "blocked_by"          : [],
        "next_chase_ts"       : None,
        "accountable_manager" : "maria",
        "created_by"          : "maria 4f98d12f",
        "priority"            : "P2",
        "project"             : "lupin",
        "correlation_key"     : EPIC_KEY,
    },
]

EPIC_STORIES = {
    "_README" : "Hand-maintained.",
    EPIC_KEY  : { "title": "Row display", "story": "One renderer, three panes." },
}

# Container id, the row class the pane renders, and a human name for failures.
PANES = [
    ( "task list",    "#task-list-container",    "task-row"  ),
    ( "holding area", "#holding-area-container", "task-row"  ),
    ( "epic board",   "#epic-board-container",   "epic-row"  ),
]

COLUMNS = [ "id", "title", "class", "status", "priority", "disclose" ]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def _route_tasks( page ):
    """
    Serve all three panes from fixtures, keyed on the query each pane sends.

    ⚠️ ONE ENDPOINT SERVES TWO QUESTIONS. The task list and the epic board read
    the open rows; only the holding area names `status=not_approved`. Keying on
    the query string is what keeps the held row out of the board above, where
    the same id rendered twice would make every scoped lookup ambiguous.

    Requires:
        - page is a Playwright page, routed BEFORE navigation so the first
          paint is intercepted too

    Ensures:
        - the holding query returns HELD_TASKS; every other returns OPEN_TASKS
        - /api/epic-stories returns EPIC_STORIES
    """
    def tasks_handler( route ):
        held = "status=not_approved" in route.request.url
        rows = HELD_TASKS if held else OPEN_TASKS
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "tasks": rows, "count": len( rows ) } )
        )

    def stories_handler( route ):
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "stories": EPIC_STORIES, "count": len( EPIC_STORIES ) } )
        )

    page.route( "**/api/tasks*", tasks_handler )
    page.route( "**/api/epic-stories*", stories_handler )


def _seeded_page( page ):
    """
    Route-seed, navigate, expand every group, and wait for all three panes.

    Ensures:
        - all three pane containers hold at least one rendered row
        - collapsed groups are opened where the pane offers an expand-all, so
          arm 3 is not reduced to skips (a collapsed row has zero width and
          would satisfy every per-cell assertion trivially)
    """
    _route_tasks( page )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )

    for testid in ( "task-list-expand-all-btn", "epic-board-expand-all-btn" ):
        button = page.get_by_test_id( testid )
        if button.count() > 0:
            button.first.click()

    for _, container, row_class in PANES:
        page.wait_for_selector( f"{container} tr.{row_class}", state="attached" )

    page.wait_for_timeout( 250 )
    return page


# ---------------------------------------------------------------------------
# The instrument
# ---------------------------------------------------------------------------

# Measure one pane's six header columns against its own table.
#
# Fractions, not pixels: the columns are declared as percentages under
# `table-layout: fixed`, so two panes of different WIDTH must still agree on
# the SHAPE. Comparing raw pixels would flag a pane that is legitimately a few
# px narrower, and comparing nothing at all is what we had.
_COLUMN_GEOMETRY_JS = """
( args ) => {
    const pane = document.querySelector( args.container );
    if ( !pane ) return { found: false, why: "pane missing" };
    const table = pane.querySelector( "table" );
    if ( !table ) return { found: false, why: "table missing" };

    const tableWidth = table.getBoundingClientRect().width;
    if ( !( tableWidth > 0 ) ) return { found: false, why: "table has no width" };

    const cols = args.columns.map( name => {
        const th = table.querySelector( "thead th.task-col-" + name );
        if ( !th ) return { name: name, present: false };
        const r = th.getBoundingClientRect();
        return { name: name, present: true, px: r.width, fraction: r.width / tableWidth };
    } );

    return {
        found      : true,
        tableWidth : tableWidth,
        paneWidth  : pane.getBoundingClientRect().width,
        columns    : cols
    };
}
"""

# Horizontal overflow, read on the pane AND on the table's own scroll box.
_OVERFLOW_JS = """
( container ) => {
    const pane = document.querySelector( container );
    if ( !pane ) return { found: false };
    pane.scrollLeft = 0;
    const table = pane.querySelector( "table" );
    const boxes = [ pane ];
    // The nearest scrollable ancestor of the table, if it is not the pane
    // itself — a clip can live on an inner wrapper, and a pane that fits
    // while its wrapper scrolls is still a page the operator must scroll.
    let node = table ? table.parentElement : null;
    while ( node && node !== pane ) { boxes.push( node ); node = node.parentElement; }
    return {
        found : true,
        worst : Math.max( ...boxes.map( b => b.scrollWidth - b.clientWidth ) ),
        table : table ? table.getBoundingClientRect().width : null,
        pane  : pane.getBoundingClientRect().width
    };
}
"""

# Reachability of every disclosure toggle in a pane.
#
# 🔴 EVERY CLAUSE HERE IS A RECEIPT — each one is present because that exact
# false reading was produced on the live page on 2026-09-03, and all three
# false readings looked like "unreachable".
_TOGGLE_REACH_JS = """
async ( container ) => {
    const SEL   = "button.task-disclose-button";
    const sleep = ms => new Promise( r => setTimeout( r, ms ) );
    const pane  = document.querySelector( container );
    if ( !pane ) return { judged: [], skipped: [ "pane missing" ] };

    const judged = [], skipped = [];
    const n = pane.querySelectorAll( SEL ).length;

    for ( let i = 0; i < n; i++ ) {
        // LIE 3 — never hold a node across an await. Re-query by index.
        let btns = [ ...document.querySelector( container ).querySelectorAll( SEL ) ];
        if ( i >= btns.length ) { skipped.push( "re-rendered, fewer rows" ); continue; }
        if ( btns[ i ].getBoundingClientRect().width === 0 ) { skipped.push( "collapsed group" ); continue; }

        btns[ i ].scrollIntoView( { block: "center", inline: "nearest" } );
        await sleep( 180 );

        btns = [ ...document.querySelector( container ).querySelectorAll( SEL ) ];
        if ( i >= btns.length || !document.contains( btns[ i ] ) ) {
            skipped.push( "detached mid-measure" ); continue;
        }

        const paneRect = document.querySelector( container ).getBoundingClientRect();
        document.querySelector( container ).scrollLeft = 0;
        const r  = btns[ i ].getBoundingClientRect();
        const cx = ( r.left + r.right ) / 2, cy = ( r.top + r.bottom ) / 2;

        // LIE 1 (off-viewport -> null) and LIE 2 (the fixed nav at z-index
        // 9999 wins every hit-test under it) are both refusals, not failures.
        if ( !( cy > 60 && cy < window.innerHeight - 10 ) ) {
            skipped.push( "could not clear the fixed nav" ); continue;
        }

        const hit = document.elementFromPoint( cx, cy );
        judged.push( {
            insidePane  : r.left >= paneRect.left - 1 && r.right <= paneRect.right + 1,
            hitIsToggle : !!hit && !!hit.closest && !!hit.closest( SEL ),
            right       : r.right,
            paneRight   : paneRect.right
        } );
    }
    return { judged: judged, skipped: skipped, total: n };
}
"""

# The clamp, read as GEOMETRY.
#
# 🔴 A COMPUTED `display` STRING IS NOT EVIDENCE ABOUT A CLAMP. The `td` and
# the `span` BOTH compute `flow-root` in Chrome, and only the span clamps — so
# the display value was constant across the two cases while the behaviour was
# not, and could never have been the discriminator. The false mechanism
# ("the cell computes flow-root, so the clamp cannot apply") is retracted in
# `src/rnd/2026.09.04-row-display-progressive-disclosure.md`. The geometry
# below is what actually discriminates, and it was available the whole time.
_TITLE_CLAMP_JS = """
( args ) => {
    const pane = document.querySelector( args.container );
    if ( !pane ) return { found: false };
    const spans = [ ...pane.querySelectorAll( "tr." + args.rowClass + " .task-col-title .task-title" ) ];
    const rows  = spans.map( s => ( {
        client : s.clientHeight,
        scroll : s.scrollHeight,
        text   : ( s.textContent || "" ).length
    } ) );
    // Only a span whose content OVERFLOWS can tell a bound clamp from an inert
    // one; a title that fits reads client == scroll either way.
    const overflowing = rows.filter( r => r.scroll > r.client );
    return { found: true, rows: rows, overflowingCount: overflowing.length };
}
"""


def _column_geometry( page, container ):
    return page.evaluate( _COLUMN_GEOMETRY_JS, { "container": container, "columns": COLUMNS } )


# ---------------------------------------------------------------------------


class TestTheSixColumnsAreOneSchema:
    """Rick's actual requirement: identical across the panes, not merely fitting."""

    def test_every_column_occupies_the_same_fraction_in_all_three_panes( self, logged_in_page ):
        """
        The six columns hold the same share of their table in every pane.

        🔴 THIS IS THE ARM NOTHING GUARDED BEFORE THIS FILE. It is killed by a
        rule becoming PANE-SCOPED — dropping `.epic-board-table` from one of
        the six width pairs in task-list.css — which is the general form of
        the sticky-pin defect and the one thing a renderer guard cannot see.

        ⚠️ It is NOT killed by changing a percentage: the pairs move all three
        panes together, which is correct and is named here rather than left to
        inflate the arm count.
        """
        page  = _seeded_page( logged_in_page )
        panes = { name: _column_geometry( page, container ) for name, container, _ in PANES }

        for name, geo in panes.items():
            assert geo[ "found" ], f"{name}: {geo.get( 'why' )}"
            missing = [ c[ "name" ] for c in geo[ "columns" ] if not c[ "present" ] ]
            assert not missing, f"{name} is missing header columns {missing}"

        reference = panes[ "task list" ]
        ref_by    = { c[ "name" ]: c[ "fraction" ] for c in reference[ "columns" ] }

        drift = []
        for name, geo in panes.items():
            if name == "task list":
                continue
            for col in geo[ "columns" ]:
                delta = abs( col[ "fraction" ] - ref_by[ col[ "name" ] ] )
                if delta > 0.005:
                    drift.append(
                        f"{name}.{col[ 'name' ]}: {col[ 'fraction' ]:.4f} "
                        f"vs task list {ref_by[ col[ 'name' ] ]:.4f} (delta {delta:.4f})"
                    )

        assert not drift, (
            "The six columns are NOT one schema across the panes:\n  "
            + "\n  ".join( drift )
            + "\n\nTable widths: "
            + ", ".join( f"{n}={g[ 'tableWidth' ]:.1f}" for n, g in panes.items() )
        )


class TestThePaneNeverScrollsSideways:
    """A row that overflows its pane is the defect that cost the evening."""

    @pytest.mark.parametrize( "opened", [ False, True ], ids=[ "row_closed", "row_open" ] )
    def test_no_pane_scrolls_horizontally( self, logged_in_page, opened ):
        """
        Every pane fits its own width, with the disclosure closed AND open.

        ⚠️ THE OPEN CASE IS NOT PADDING. Opening injects a spanning row whose
        colspan is derived from `_rowWidth()`; a colspan that drifts from the
        header count widens the table under a `table-layout: fixed` and the
        pane clips it. The closed case cannot see that.
        """
        page = _seeded_page( logged_in_page )

        if opened:
            for _, container, _ in PANES:
                toggles = page.locator( f"{container} button.task-disclose-button" )
                if toggles.count() > 0:
                    toggles.first.click()
            page.wait_for_timeout( 250 )

        overflow = []
        for name, container, _ in PANES:
            box = page.evaluate( _OVERFLOW_JS, container )
            assert box[ "found" ], f"{name}: pane missing"
            if box[ "worst" ] > 1:
                overflow.append(
                    f"{name}: {box[ 'worst' ]}px of horizontal overflow "
                    f"(table {box[ 'table' ]:.1f} in a pane of {box[ 'pane' ]:.1f})"
                )

        assert not overflow, (
            f"Panes scroll sideways with the row {'OPEN' if opened else 'CLOSED'}:\n  "
            + "\n  ".join( overflow )
        )


class TestTheToggleIsReachable:
    """`absent` and `off-screen` are one observation from a chair."""

    def test_every_disclosure_toggle_is_inside_its_pane_and_hit_testable( self, logged_in_page ):
        """
        Each ⋯ sits within its pane's box and is what a click there reaches.

        🔴 THIS ARM REFUSES RATHER THAN GUESSES. A toggle that could not be
        cleared of the fixed nav, that belongs to a collapsed group, or that
        was detached by a background repaint is SKIPPED — never counted as a
        pass. And a pane with nothing judgeable FAILS: "all toggles reachable"
        over an empty judged set is the emptiest true sentence in this repo.
        """
        page = _seeded_page( logged_in_page )

        problems = []
        for name, container, _ in PANES:
            result = page.evaluate( _TOGGLE_REACH_JS, container )
            judged = result[ "judged" ]

            if not judged:
                problems.append(
                    f"{name}: NO JUDGEABLE TOGGLE — refusing to report a pass "
                    f"({result[ 'total' ]} present, skipped: {result[ 'skipped' ]})"
                )
                continue

            for i, j in enumerate( judged ):
                if not j[ "insidePane" ]:
                    problems.append(
                        f"{name}[{i}]: toggle runs to x={j[ 'right' ]:.1f} "
                        f"against a pane edge of {j[ 'paneRight' ]:.1f}"
                    )
                if not j[ "hitIsToggle" ]:
                    problems.append( f"{name}[{i}]: something else answers a click at its centre" )

        assert not problems, "Toggle reachability:\n  " + "\n  ".join( problems )


class TestTheTitleIsBoundToTwoLines:
    """EQUAL MEANS INERT — the clamp shipped that way once already."""

    def test_an_overflowing_title_is_clamped_rather_than_merely_declared( self, logged_in_page ):
        """
        A title long enough to overflow reads clientHeight < scrollHeight.

        🔴 THE ONLY DISCRIMINATOR IS THE GEOMETRY. `51/51` was the defect and
        `39/78` is the fix; the computed `display` string is identical in both
        and proves nothing (see the module docstring and 9e7eda24).

        ⚠️ THE SEEDED LONG TITLE IS LOAD-BEARING. Against a title that fits,
        client == scroll whether the clamp binds or not, so this arm would
        pass over a completely inert clamp.
        """
        page = _seeded_page( logged_in_page )

        problems = []
        for name, container, row_class in PANES:
            result = page.evaluate( _TITLE_CLAMP_JS, { "container": container, "rowClass": row_class } )
            assert result[ "found" ], f"{name}: pane missing"

            rows = result[ "rows" ]
            if not rows:
                problems.append( f"{name}: NO TITLE SPAN — refusing to report a pass" )
                continue

            tall = [ r for r in rows if r[ "text" ] >= len( LONG_TITLE ) ]
            if not tall:
                problems.append(
                    f"{name}: the seeded long title did not render — "
                    f"nothing here can exercise the clamp (rows: {rows})"
                )
                continue

            for r in tall:
                if r[ "scroll" ] <= r[ "client" ]:
                    problems.append(
                        f"{name}: clamp is INERT — clientHeight {r[ 'client' ]} "
                        f"== scrollHeight {r[ 'scroll' ]} on a {r[ 'text' ]}-char title"
                    )
                elif r[ "client" ] > 60:
                    problems.append(
                        f"{name}: bound, but not at TWO lines — clientHeight "
                        f"{r[ 'client' ]}px is more than two 19.5px lines plus slack"
                    )

        assert not problems, "Title clamp:\n  " + "\n  ".join( problems )
