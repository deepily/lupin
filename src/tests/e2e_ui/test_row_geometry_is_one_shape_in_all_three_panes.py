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
  4a. LINE 3 IS READABLE AND ITS DETAIL CONTROL IS LIVE, IN EVERY PANE — the
     detail field is not crushed by its neighbour, the 📄 does not sit inside
     the actions block, and a real click on it OPENS THE OVERLAY.
     🔴 ADDED AFTER RICK FOUND LINE 3 UNUSABLE (P0, row 17393c56) WHILE ALL FOUR
     ARMS ABOVE WERE GREEN. Every one of them measures LINE 1; nothing opened a
     row. We built the blind spot and then reported completion through it.
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
Baseline `5087b139`, run on :8000, `tracked-dirty=0`.

🔴 THAT SHA IS A CORRECTION. The first cut of this block said "baseline
`cf722c8a`, tree-state sha `5087b139`" — reading the runner's own
`[tree-state] sha=` field as something other than the commit it names.
`cf722c8a` was HEAD when the session STARTED; two commits landed underneath
while the guard was being written, and `5087b139` is this file's own parent,
so every arm above measured `5087b139`. Both numbers were on my screen and I
named the one I remembered instead of the one that ran. Left visible rather
than quietly swapped, because a run is named by what it MEASURED. Every arm mutated the SERVED stylesheet by Playwright
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

⚠️ ARMS 2 AND 3 CARRY NO MUTATION PROOF, said here rather than left for a
reader to infer from a table that lists only two arms. C0/M1/M2 establish that
arms 1 and 4 discriminate. Arm 2 (no horizontal scroll) and arm 3 (toggle
reachable) are UNGUARDED-BY-MUTATION: they pass today, they are aimed at
defects that really happened, and nobody has yet deleted a fix and watched them
go red. Present-and-correct is not the same as watched.

⚠️ AND ARM 3's `hitIsToggle` IS INHERITED FROM A CHECK MEASURED NOT TO
DISCRIMINATE. In `test_holding_area_per_row_editor.py` the equivalent
`hitsSelf` came back TRUE in BOTH arms of the 108px incident; `insidePane` is
what caught it. `hitIsToggle` is kept because it guards a DIFFERENT regression
— an overlay covering a correctly-placed control — and is named as the thin
half rather than left to inflate the count.

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
# Line 3 shows a row's body. A row with an empty body renders a DIMMED, inert 📄
# — which is correct behaviour and would make arm 4a pass over a dead control.
# The first probe read `task-detail-empty` and that was the fixture, not a defect.
LONG_BODY = (
    "A body long enough to be worth disclosing: the relevant facts Rick says he "
    "wants to see, all of them, on the third line of the row."
)

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
        "body"                : LONG_BODY,
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
        "body"                : LONG_BODY,
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
        "body"                : LONG_BODY,
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


# ---------------------------------------------------------------------------
# ARM 4a — LINE 3
# ---------------------------------------------------------------------------

# Measure the disclosed row's action line: the detail field's box, the 📄's box
# against the actions block, and a hit test at the emoji's own centre.
#
# 🔴 THE EMOJI'S BOX, NOT THE FIELD'S. When the detail field was crushed to 9px
# the two FIELD boxes still did not intersect — they sat at 200..209 and
# 219..936, adjacent and disjoint — so a field-vs-field overlap check reported
# CLEAN through the whole defect. What actually overlapped was the 📄 itself,
# painting at 241..262 outside its own 9px parent and entirely inside the
# actions box. Measure the thing the operator is trying to click.
_LINE3_JS = """
( container ) => {
    const pane = document.querySelector( container );
    if ( !pane ) return { found: false };
    const open = [ ...pane.querySelectorAll( ".task-controls-row" ) ].filter( r => !r.hidden );
    if ( !open.length ) return { found: false, why: "no disclosed row is open" };
    const line = open[ 0 ].querySelector( ".task-disclosed-line--actions" );
    if ( !line ) return { found: false, why: "no action line on the disclosed row" };

    const field = line.querySelector( ".task-disclosed-field.task-col-detail" );
    const acts  = line.querySelector( ".task-disclosed-field.task-col-actions" );
    if ( !field || !acts ) return { found: false, why: "detail or actions field missing" };

    const emoji = field.querySelector( ".task-detail-emoji" );
    if ( !emoji ) return { found: false, why: "no detail emoji rendered" };

    emoji.scrollIntoView( { block: "center", inline: "nearest" } );
    pane.scrollLeft = 0;

    const fr = field.getBoundingClientRect();
    const er = emoji.getBoundingClientRect();
    const ar = acts.getBoundingClientRect();
    const ox = Math.min( er.right, ar.right ) - Math.max( er.left, ar.left );
    const oy = Math.min( er.bottom, ar.bottom ) - Math.max( er.top, ar.top );

    const cx = ( er.left + er.right ) / 2, cy = ( er.top + er.bottom ) / 2;
    const clear = cy > 60 && cy < window.innerHeight - 10;

    return {
        found        : true,
        dimmed       : emoji.classList.contains( "task-detail-empty" ),
        fieldWidth   : +fr.width.toFixed( 1 ),
        contentWidth : [ ...field.children ].reduce( ( t, c ) => t + c.getBoundingClientRect().width, 0 ),
        overlapPx    : ( ox > 0.5 && oy > 0.5 ) ? +ox.toFixed( 1 ) : 0,
        judgeable    : clear,
        hitIsEmoji   : clear ? !!( document.elementFromPoint( cx, cy ) || {} ).closest?.( ".task-detail-emoji" ) : null
    };
}
"""

_CLICK_DETAIL_JS = """
( container ) => {
    const d = document.querySelector( container )
        .querySelector( ".task-controls-row:not([hidden]) .task-col-detail .task-detail-emoji" );
    if ( !d ) return false;
    d.dispatchEvent( new MouseEvent( "click", { bubbles: true } ) );
    return true;
}
"""


def _open_every_pane( page ):
    """Disclose the first row of each pane, then let the repaint settle."""
    for _, container, _ in PANES:
        toggles = page.locator( f"{container} button.task-disclose-button" )
        if toggles.count() > 0:
            toggles.first.scroll_into_view_if_needed()
            toggles.first.click()
    page.wait_for_timeout( 400 )


class TestLine3IsReadableAndItsDetailControlIsLive:
    """
    Rick's P0, row 17393c56 — and the arm that would have caught it.

    🔴 TWO DEFECTS WEARING ONE SYMPTOM, WHICH IS WHY BOTH HALVES ARE HERE.
    Measured open in the browser before the fix:

        pane            detail box   📄 overlaps actions   click opens overlay
        task list         9px              21px                  yes
        holding area      9px              21px                  NO
        epic board       63px               0                    NO

    The task list and holding area were a LAYOUT defect — a `width: 1%` rule
    written for a line-1 detail column that no longer exists, still matching
    `div.task-disclosed-field.task-col-detail` on line 3 and crushing it, so
    the 📄 painted inside the actions block. The epic board's geometry was
    perfect and its 📄 reached NO handler: `_handleEpicBoardClick` had no
    detail branch, and neither did the holding area's listener.

    ⇒ Geometry alone clears the epic board. Wiring alone clears the task list.
    Only both together clear all three, which is why one arm would have shipped
    two thirds of this defect.
    """

    def test_the_detail_field_is_not_crushed_and_its_icon_clears_the_actions_block( self, logged_in_page ):
        """
        The 📄 has room of its own and does not sit inside its neighbour.

        ⚠️ ASSERTED ON THE EMOJI'S BOX, NOT THE FIELD'S — the two FIELD boxes
        stayed disjoint (200..209 against 219..936) through the entire defect,
        so a field-vs-field check reported clean while the icon it contains was
        21px deep inside the actions block.
        """
        page = _seeded_page( logged_in_page )
        _open_every_pane( page )

        problems = []
        for name, container, _ in PANES:
            r = page.evaluate( _LINE3_JS, container )
            if not r[ "found" ]:
                problems.append( f"{name}: {r.get( 'why' )}" )
                continue
            if r[ "dimmed" ]:
                problems.append( f"{name}: the seeded body did not render — a dimmed 📄 is inert "
                                 f"and would satisfy every assertion below trivially" )
                continue
            if r[ "overlapPx" ]:
                problems.append( f"{name}: the 📄 sits {r[ 'overlapPx' ]}px inside the actions block" )
            if r[ "fieldWidth" ] + 1 < r[ "contentWidth" ]:
                problems.append( f"{name}: the detail field is {r[ 'fieldWidth' ]}px holding "
                                 f"{r[ 'contentWidth' ]:.1f}px of content — its own children overflow it" )
            # 🔴 A NON-JUDGEABLE HIT IS NOT A PASS. The first cut read
            # `if judgeable and not hitIsEmoji`, which silently passed a pane
            # whose row could not be cleared of the fixed nav — my own rule 5
            # broken inside the arm written to apply it.
            if not r[ "judgeable" ]:
                problems.append( f"{name}: the 📄 could not be brought clear of the fixed nav, "
                                 f"so its reachability was NOT JUDGED — refusing to report a pass" )
            elif not r[ "hitIsEmoji" ]:
                problems.append( f"{name}: something else answers a click at the 📄's centre" )

        assert not problems, "Line 3 detail geometry:\n  " + "\n  ".join( problems )

    def test_a_real_click_on_the_detail_icon_opens_the_overlay_in_every_pane( self, logged_in_page ):
        """
        The 📄 is wired in ALL THREE panes, not just the one that had a branch.

        🔴 THIS IS THE HALF GEOMETRY CANNOT SEE. On the epic board the icon
        measured perfectly — 63px field, zero overlap, `elementFromPoint`
        returning the emoji itself — and reached no handler at all. Reachable
        and inert reads exactly like working, from a chair and from a box.
        """
        page = _seeded_page( logged_in_page )
        _open_every_pane( page )

        dead = []
        for name, container, _ in PANES:
            page.evaluate( "() => { const o = document.getElementById( 'task-body-overlay' ); if ( o ) o.remove(); }" )
            if not page.evaluate( _CLICK_DETAIL_JS, container ):
                dead.append( f"{name}: no detail 📄 to click" )
                continue
            page.wait_for_timeout( 200 )
            if not page.evaluate( "() => !!document.getElementById( 'task-body-overlay' )" ):
                dead.append( f"{name}: clicking the 📄 opened nothing — the control is dead on screen" )
        page.evaluate( "() => { const o = document.getElementById( 'task-body-overlay' ); if ( o ) o.remove(); }" )

        assert not dead, "Line 3 detail control:\n  " + "\n  ".join( dead )


# ---------------------------------------------------------------------------
# ARM 4b — THE DISCLOSED ROWS LOOK LIKE THE ROW THEY BELONG TO
# ---------------------------------------------------------------------------

_ROW_SKIN_JS = """
( container ) => {
    const pane = document.querySelector( container );
    if ( !pane ) return { found: false };
    const row1 = pane.querySelector( "tr.task-row, tr.epic-row" );
    const ctl  = [ ...pane.querySelectorAll( ".task-controls-row" ) ].filter( r => !r.hidden )[ 0 ];
    if ( !row1 || !ctl ) return { found: false, why: "no row, or no disclosed row is open" };
    const c1 = row1.querySelector( "td" ), c2 = ctl.querySelector( "td" );
    if ( !c1 || !c2 ) return { found: false, why: "a row has no first cell" };
    const s1 = getComputedStyle( c1 ), s2 = getComputedStyle( c2 );
    return { found: true,
             row1Bar: s1.boxShadow, ctlBar: s2.boxShadow,
             row1Bg : s1.backgroundColor, ctlBg: s2.backgroundColor };
}
"""


class TestTheDisclosedRowsWearTheSameSkinAsTheirRow:
    """
    Rick, row 3775155f: rows 2 and 3 carry the SAME left bar as the title row and
    the SAME background, in all three panes.

    🔴 MEASURED BEFORE THE FIX, and the epic board was worse than reported:

        pane            row 1 bar            disclosed bar   disclosed background
        task list       green, 3px inset     NONE            rgba(127,127,127,0.06)
        holding area    purple, 3px inset    NONE            rgba(127,127,127,0.06)
        epic board      NONE                 NONE            rgba(127,127,127,0.06)

    Rick asked for the bar to be carried onto rows 2 and 3 and into the epic
    board. The epic board did not have it on row 1 EITHER — the ten accent rules
    were written against `.task-row` alone. Assuming the epic board diverges was
    right for the third time tonight.

    ⚠️ THE BAR IS COMPARED TO ROW 1'S, NOT MERELY ASSERTED TO EXIST. "It has a
    bar" passes on a bar of the wrong colour, which is precisely the drift this
    whole schema exists to prevent — and a status-keyed colour has ten ways to
    be wrong and one to be right.
    """

    def test_the_disclosed_row_carries_row_ones_bar_and_row_ones_background( self, logged_in_page ):
        page = _seeded_page( logged_in_page )
        _open_every_pane( page )

        problems = []
        for name, container, _ in PANES:
            r = page.evaluate( _ROW_SKIN_JS, container )
            if not r[ "found" ]:
                problems.append( f"{name}: {r.get( 'why' )}" )
                continue
            if r[ "row1Bar" ] in ( "none", "" ):
                problems.append( f"{name}: row 1 has NO left bar at all — nothing for rows 2 and 3 to match" )
            elif r[ "ctlBar" ] != r[ "row1Bar" ]:
                problems.append( f"{name}: the disclosed row's bar is {r[ 'ctlBar' ]!r} "
                                 f"against row 1's {r[ 'row1Bar' ]!r}" )
            if r[ "ctlBg" ] != r[ "row1Bg" ]:
                problems.append( f"{name}: the disclosed row's background is {r[ 'ctlBg' ]!r} "
                                 f"against row 1's {r[ 'row1Bg' ]!r} — Rick's \"they are darker\"" )

        assert not problems, "Disclosed-row skin:\n  " + "\n  ".join( problems )


# ---------------------------------------------------------------------------
# ARM 5 — LINE 3 REACHES THE ROW'S RIGHT EDGE
# ---------------------------------------------------------------------------

# Measure how far line 3's content actually gets, against line 3's own box.
#
# 🔴 THREE BOXES, NOT ONE, AND THE FIRST TWO ALONE PASS OVER AN INVISIBLE FIX.
# Measured on the way to this fix: adding `flex: 1 1 auto` to the actions FIELD
# carried the field to 1080 — 0.0px short, every field-level assertion satisfied
# — while `.task-actions` inside it stayed at 665px ending at 990, byte-identical
# to the defect. The box reached the right edge and nothing on screen moved. So
# the strip is measured too, and the reason input's width is reported alongside
# because it is the only thing that visibly consumes the room.
#
# Against line 3's OWN right edge rather than the table's: `.task-disclosed` is
# inset 18px by its padding, line 2 sits at the same 1080, and pinning a padding
# value here would make this arm fail for a reason that is not the defect.
_LINE3_RIGHT_EDGE_JS = """
( container ) => {
    const pane = document.querySelector( container );
    if ( !pane ) return { found: false, why: "pane missing" };
    const table = pane.querySelector( "table" );
    if ( !table ) return { found: false, why: "table missing" };
    const open = [ ...pane.querySelectorAll( ".task-controls-row" ) ].filter( r => !r.hidden );
    if ( !open.length ) return { found: false, why: "no disclosed row is open" };

    const td   = open[ 0 ].querySelector( "td" );
    const line = open[ 0 ].querySelector( ".task-disclosed-line--actions" );
    if ( !td || !line ) return { found: false, why: "no action line on the disclosed row" };

    const fields = [ ...line.querySelectorAll( ".task-disclosed-field" ) ];
    if ( !fields.length ) return { found: false, why: "line 3 has no fields" };
    const strip  = line.querySelector( ".task-actions" );
    const reason = line.querySelector( ".task-reason-input" );

    const R = e => +e.getBoundingClientRect().right.toFixed( 1 );
    const L = e => +e.getBoundingClientRect().left.toFixed( 1 );
    const l2  = open[ 0 ].querySelector( ".task-disclosed-line--fields" );
    const l2f = l2 ? l2.querySelector( ".task-disclosed-field" ) : null;

    return {
        found       : true,
        headerCells : table.querySelectorAll( "thead tr th" ).length,
        colspan     : parseInt( td.getAttribute( "colspan" ), 10 ),
        tdRight     : R( td ),
        tableRight  : R( table ),
        tableLeft   : L( table ),
        lineLeft    : L( line ),
        lineRight   : R( line ),
        firstFieldL : L( fields[ 0 ] ),
        lastFieldR  : R( fields[ fields.length - 1 ] ),
        line2FirstL : l2f ? L( l2f ) : null,
        line2Right  : l2  ? R( l2 )  : null,
        stripR      : strip ? R( strip ) : null,
        reasonWidth : reason ? +reason.getBoundingClientRect().width.toFixed( 1 ) : null
    };
}
"""


class TestLine3ReachesTheRowsRightEdge:
    """
    Rick's P1, row 5f982bbd — "not expanding fully to the rightmost edge of the
    table layout area ... stopping before the priority column in all contexts."

    🔴 THE FOUR ARMS ABOVE ALL PASSED THROUGH THIS DEFECT. Arm 4a measures line
    3's detail field WIDTH, its icon's OVERLAP with the actions block, and the
    CLICK — and not one of them asks how far the line gets. A line whose content
    stops 90px short satisfies every one of them.

    MEASURED BEFORE THE FIX, at b78c7651, pane 916px, a row open in each pane:

        pane            line 3 box   content ends at   short by   reason input
        task list        200..1080        990.0          90.0px      175px
        holding area     200..1080        973.0         107.0px      175px
        epic board     201.5..1080        991.5          88.5px      175px

    ⚠️ THE COLSPAN WAS THE FIRST HYPOTHESIS AND IT WAS WRONG, which is why this
    arm checks it rather than assuming either way: six header cells and
    `colspan="6"` in all three panes, the `<td>` box identical to the table's.
    The span was complete and the CONTENT inside it stopped short. Three
    different stop positions across three panes is the tell — a short span would
    have stopped all three at one column boundary.
    """

    def test_line_3_content_reaches_the_lines_right_edge_in_every_pane( self, logged_in_page ):
        """
        The last field on line 3, and the control strip inside it, both reach the
        line's own right edge.

        ⚠️ THE STRIP IS THE HALF THAT CATCHES AN INVISIBLE FIX. Growing the field
        alone satisfies `lastFieldR` while the strip stays where the defect left
        it, and the page looks exactly as Rick reported it.
        """
        page = _seeded_page( logged_in_page )
        _open_every_pane( page )

        problems = []
        for name, container, _ in PANES:
            r = page.evaluate( _LINE3_RIGHT_EDGE_JS, container )
            if not r[ "found" ]:
                problems.append( f"{name}: {r.get( 'why' )}" )
                continue

            if r[ "colspan" ] != r[ "headerCells" ]:
                problems.append( f"{name}: the disclosed cell spans {r[ 'colspan' ]} of "
                                 f"{r[ 'headerCells' ]} header columns" )
            if abs( r[ "tdRight" ] - r[ "tableRight" ] ) > 1:
                problems.append( f"{name}: the disclosed cell ends at {r[ 'tdRight' ]} against "
                                 f"the table's {r[ 'tableRight' ]}" )

            # Both insets are measured from the TABLE's box, never from the line's.
            # Anchoring to the line alone leaves the RULER unasserted: a colspan or
            # padding drift moves the line box and its content together and this arm
            # stays green over a table that has stopped spanning.
            leftInset  = r[ "firstFieldL" ] - r[ "tableLeft" ]
            rightInset = r[ "tableRight" ]  - r[ "lastFieldR" ]

            if rightInset - leftInset > 1:
                problems.append( f"{name}: line 3's content is inset {leftInset:.1f}px from the "
                                 f"table's left and {rightInset:.1f}px from its right — it stops "
                                 f"{rightInset - leftInset:.1f}px short of where its own left edge "
                                 f"says it should reach. Rick's report" )

            if r[ "stripR" ] is None:
                problems.append( f"{name}: no .task-actions strip on line 3 — nothing to measure" )
            else:
                stripInset = r[ "tableRight" ] - r[ "stripR" ]
                if stripInset - leftInset > 1:
                    problems.append( f"{name}: the control strip is inset {stripInset:.1f}px from the "
                                     f"table's right against line 3's own {leftInset:.1f}px on the "
                                     f"left. The field box can reach the edge while the strip does "
                                     f"not, and THAT fix changes nothing on screen (reason input "
                                     f"{r[ 'reasonWidth' ]}px)" )

            # Line 2 is the sibling that was never reported broken, so it is the
            # standing answer to "how far should a disclosed line reach?". Asserting
            # the two AGREE is what makes this arm about the block rather than about
            # one line's arithmetic with itself.
            if r[ "line2Right" ] is not None and r[ "line2FirstL" ] is not None:
                l2Left  = r[ "line2FirstL" ] - r[ "tableLeft" ]
                if abs( l2Left - leftInset ) > 1:
                    problems.append( f"{name}: line 2 starts {l2Left:.1f}px inside the table and "
                                     f"line 3 starts {leftInset:.1f}px — the two disclosed lines "
                                     f"no longer share one left edge" )

        assert not problems, "Line 3 right edge:\n  " + "\n  ".join( problems )
