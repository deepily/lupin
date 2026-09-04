"""
E2E UI guard for the holding area's PER-ROW editor (Rick's P0, row 267acbca).

WHAT WENT WRONG, and why every unit test we had was green through it.
The per-row editor was fully rendered and fully wired in the holding area
from the day the pane shipped: `_renderTaskRow` emits `_disclosureToggle`
plus a `.task-controls-row` carrying `_taskActionsCell`, and
`_wireHoldingAreaControls` delegates the clicks. Measured in the live
browser 2026-09-03, the DOM held one row, one disclosure button, one
controls row and one verb select — exactly what a jsdom assertion would
demand, and it passed.

It was 108 pixels off the right-hand edge of the world. The twelve-column
task table is 1065px wide, the pane is 916px, and `.section-content` clips
at `overflow-x: hidden`. The ellipsis sat at x=1519 against a container
edge of x=1411, and `document.elementFromPoint` over its centre returned
null. Rick saw the group header's Approve-all / Won't-fix-all — which fit
— and nothing else, and reported that the per-row editor did not exist.
From a chair, unreachable and absent are the same observation.

The epic board escaped it by being NARROWER, not by being different:
`_renderEpicRow` emits five columns to `_renderTaskRow`'s twelve, fits its
pane, and reaches the SAME `_disclosureToggle` and the SAME
`_taskActionsCell`. Nothing about the editor itself ever differed, which is
why "reuse the epic board's editor" was already true and still left Rick
unable to use it.

⇒ SO THIS SUITE ENTERS AT THE LAYER THE INCIDENT ENTERED AT: geometry in a
real browser. A DOM-presence assertion cannot see this defect — it is the
assertion that was already passing. Every check below reads a bounding box
or a hit-test, or watches the wire.

What is pinned:
  1. The ellipsis is INSIDE the pane's box and is the element the browser
     hands back at its own centre. This is the one that goes red on the
     regression that happened.
  2. The controls row starts HIDDEN, so (3) cannot pass vacuously.
  3. Clicking the ellipsis opens it, and EVERY editor control — verb
     select, reason, Submit, priority Update — lands inside the pane.
  4. The per-row path REACHES THE STORE: Submit POSTs to
     /api/tasks/{id}/transition naming THAT ONE id, with the operator's
     verb and reason. This is Rick's "arm that goes RED if the per-row path
     stops reaching the store".
  5. The BULK control survives. Rick kept it on purpose — "I just told you
     that you could keep the bulk approval. I'm just not gonna use it" —
     so deleting it is a regression in the opposite direction, and a suite
     that only guards the new thing would never notice.

⚠️ (5) IS NOT PADDING. Two of these tests would pass if the pane rendered
ONLY per-row controls and none would notice the bulk buttons had gone.

Requires:
    - Dev server running on the test venue (:8000) with Testing config
    - Clean test database (via logged_in_page fixture)

Venue: :8000 scheduled — submit via POST /api/test-suite/submit.
"""

import json

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Seed payloads — REAL /api/tasks shapes for a HELD row
# ---------------------------------------------------------------------------

HELD_ID = "0ab1a095-1eed-4e7e-be83-aa7c43b8be59"

# Two filers, so the pane renders more than one group and a per-row control
# cannot be confused with a group-level one that happens to sit near it.
HELD_TASKS = [
    {
        "id"                  : HELD_ID,
        "title"               : "Fleet size limiter — configurable cap with a slider, enforced at spawn",
        "body"                : "Filed by Maria at Rick's direct instruction.",
        "owner_persona"       : "maria",
        "status"              : "not_approved",
        "item_class"          : "task",
        "blocked_by"          : [],
        "next_chase_ts"       : None,
        "accountable_manager" : "maria",
        "created_by"          : "maria 4f98d12f",
        "priority"            : "P1",
        "project"             : "lupin"
    },
    {
        "id"                  : "bbbbbbbb-0000-0000-0000-00000000000b",
        "title"               : "A second held row, filed by somebody else",
        "body"                : "",
        "owner_persona"       : "pocholo",
        "status"              : "not_approved",
        "item_class"          : "bug",
        "blocked_by"          : [],
        "next_chase_ts"       : None,
        "accountable_manager" : "pocholo",
        "created_by"          : "pocholo 0e61abe3",
        "priority"            : "P3",
        "project"             : "lupin"
    }
]


def _route_tasks( page, state ):
    """
    Serve the holding area's query from a fixture, and record transitions.

    ⚠️ ONE ENDPOINT SERVES TWO PANES AND THEY ASK DIFFERENT QUESTIONS. The
    task list and the holding area both GET /api/tasks; only the holding
    area names `status=not_approved`. Keying on the query string is what
    keeps the held rows out of the board above, which would otherwise
    render the same ids twice and make a scoped lookup ambiguous.

    Requires:
        - page is a Playwright page (routed BEFORE navigation, so the pane's
          first paint is intercepted too)
        - state is a mutable dict; "transitions" collects every POST body
          together with the id it was addressed to

    Ensures:
        - the holding query returns HELD_TASKS; the board query returns none
        - every POST /api/tasks/{id}/transition is recorded and answered 200
        - state["transitions"] is a list of { "id", "body" }
    """
    def tasks_handler( route ):
        url  = route.request.url
        held = "status=not_approved" in url
        rows = HELD_TASKS if held else []
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "tasks": rows, "count": len( rows ) } )
        )

    def transition_handler( route ):
        request = route.request
        task_id = request.url.split( "/api/tasks/" )[ 1 ].split( "/" )[ 0 ]
        try:
            body = json.loads( request.post_data or "{}" )
        except ValueError:
            body = { "unparseable": request.post_data }
        state[ "transitions" ].append( { "id": task_id, "body": body } )
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "item": dict( HELD_TASKS[ 0 ], status="queued" ) } )
        )

    def stories_handler( route ):
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( { "stories": [], "count": 0 } ) )

    # The transition route is registered FIRST: Playwright matches most-recently
    # registered first, and "**/api/tasks*" would otherwise swallow the POST.
    page.route( "**/api/tasks/*/transition", transition_handler )
    page.route( "**/api/tasks*", tasks_handler )
    page.route( "**/api/epic-stories*", stories_handler )


def _seeded_page( page ):
    """Route-seed, navigate, and wait for the holding area's first paint."""
    state = { "transitions": [] }
    _route_tasks( page, state )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_selector( "#holding-area-container .holding-area-group", state="attached" )
    return state


def _pane_and_box( page, selector ):
    """
    One element's bounding box together with its pane's, plus a hit test.

    🔴 `inPane` IS THE DISCRIMINATING FIELD AND `hitsSelf` IS NOT — measured,
    not assumed. Two arms were driven on the live page, one variable (the
    three CSS rules of the fix), each arm with the pane's `scrollLeft` forced
    to 0 so neither inherited the other's scroll position:

        arm            ellipsis   Submit    Update
        pre-fix        inPane F   inPane F  inPane F
        post-fix       inPane T   inPane T  inPane T

    `hitsSelf` came back TRUE in BOTH arms, so it catches nothing about this
    incident. It is kept because it guards a DIFFERENT regression — an overlay
    covering a control that is correctly placed — and it is named here as the
    weak arm rather than left to inflate the count.

    ⚠️ AND "NEAREST CLIPPING ANCESTOR" WAS TRIED AND IS VACUOUS. The control
    strip itself carries `overflow-x: auto`, so that walk stops at
    `.task-actions`, which contains its own children by construction and
    returns TRUE in both arms. Containment must be measured against the PANE.

    Ensures:
        - returns { "found", "width", "inPane", "hitsSelf" }; "found" false
          when the selector matches nothing, so a typo cannot read as a pass
        - the pane's horizontal scroll is zeroed before AND after
          scrollIntoView, so a measurement can never be rescued by a scroll
          position some earlier assertion left behind
    """
    return page.evaluate(
        """(sel) => {
            const pane = document.getElementById( "holding-area-container" );
            const el   = pane ? pane.querySelector( sel ) : null;
            if ( !pane || !el ) return { found: false };
            pane.scrollLeft = 0;
            el.scrollIntoView( { block: "center", inline: "nearest" } );
            pane.scrollLeft = 0;
            const p = pane.getBoundingClientRect();
            const r = el.getBoundingClientRect();
            const hit = document.elementFromPoint( r.left + r.width / 2, r.top + r.height / 2 );
            return {
                found    : true,
                width    : Math.round( r.width ),
                inPane   : r.left >= p.left - 1 && r.right <= p.right + 1,
                hitsSelf : !!hit && !!hit.closest && !!hit.closest( sel )
            };
        }""",
        selector
    )


# ---------------------------------------------------------------------------


class TestTheEllipsisIsReachable:
    """The regression that happened: rendered, wired, and off-screen."""

    def test_the_disclosure_ellipsis_lands_inside_its_pane( self, logged_in_page ):
        """
        The ⋯ is within the pane's box AND is what a click there would reach.

        🔴 `inPane` IS THE ARM FOR THE ORIGINAL DEFECT. Before the fix the
        button's box ran 1499..1530 against a pane edge of 1391 and a
        `.section-content` clip edge of 1431 — painted nowhere. The two-arm
        measurement behind that claim is in `_pane_and_box`.

        ⚠️ `hitsSelf` DID NOT DISCRIMINATE and is asserted anyway, for the
        different regression of a control that is placed correctly and
        covered. Saying so is the point: a reader who counts four assertions
        here should know only one of them catches what actually happened.
        """
        _seeded_page( logged_in_page )

        probe = _pane_and_box( logged_in_page, ".task-disclose-button" )

        assert probe[ "found" ],    "no disclosure ellipsis in the holding area at all"
        assert probe[ "width" ] > 0, "the ellipsis has no box"
        assert probe[ "inPane" ],   "the ellipsis is outside its pane — clipped, exactly as in the original defect"
        assert probe[ "hitsSelf" ], "a click at the ellipsis's own centre does not reach it"

    def test_every_held_row_has_one( self, logged_in_page ):
        """
        Two seeded rows, two ellipses — not one shared control near the top.

        ⚠️ THE COUNT IS THE ASSERTION. Rick's complaint was that the pane
        offered one blanket control for everything in it; a single ellipsis
        serving both rows would be that same defect wearing the fix's
        clothes.
        """
        _seeded_page( logged_in_page )

        rows     = logged_in_page.locator( "#holding-area-container tr.task-row" ).count()
        ellipses = logged_in_page.locator( "#holding-area-container .task-disclose-button" ).count()

        assert rows == len( HELD_TASKS ), f"expected {len( HELD_TASKS )} held rows, saw {rows}"
        assert ellipses == rows, f"{rows} rows but {ellipses} disclosure controls"


class TestTheEditorOpensAndFits:
    """Rick's ask, literally: pick an action, type a reason, submit."""

    def test_the_controls_row_starts_hidden( self, logged_in_page ):
        """
        The negative control for the test below.

        Without this, "the controls are visible after clicking" would pass
        on a pane that never hid them, and the disclosure would be pinned
        by nothing.
        """
        _seeded_page( logged_in_page )

        hidden = logged_in_page.eval_on_selector_all(
            "#holding-area-container .task-controls-row",
            "rows => rows.map( r => r.hidden )"
        )

        assert hidden and all( hidden ), f"a controls row was already open: {hidden}"

    @pytest.mark.parametrize( "control", [
        ".task-verb-select",
        ".task-reason-input",
        ".task-submit-button",
        ".task-priority-select",
        ".task-priority-update"
    ] )
    def test_each_control_lands_inside_the_pane_once_disclosed( self, logged_in_page, control ):
        """
        Every control of the disclosed editor is reachable, one by one.

        ⚠️ PARAMETRIZED SO A FAILURE NAMES THE CONTROL. The strip is one
        flex row spanning the full table width, so it overflows the pane the
        same way the column did — and it does so from the RIGHT, meaning
        Submit and Update are the first to go. A single assertion over "the
        strip" would report a failure about the container while hiding
        which control the operator could not press.
        """
        _seeded_page( logged_in_page )
        logged_in_page.locator( "#holding-area-container .task-disclose-button" ).first.click()
        logged_in_page.wait_for_selector(
            "#holding-area-container .task-controls-row:not([hidden])", state="attached" )

        probe = _pane_and_box( logged_in_page, control )

        assert probe[ "found" ],  f"{control} is not in the holding area's disclosed editor"
        assert probe[ "inPane" ], f"{control} is clipped outside the pane and cannot be used"


class TestThePerRowPathReachesTheStore:
    """Rick's DONE MEANS, verbatim: an arm that goes RED if it stops."""

    def test_approve_posts_that_one_row_and_takes_no_reason( self, logged_in_page ):
        """
        The holding area's own exit: approve moves THAT row to queued.

        🔴 THE `len( ... ) == 1` IS THE WHOLE POINT. The control this
        replaces was a batch that moved every row a filer had put in the
        pane. A per-row editor that posted the group would satisfy every
        other assertion in this file — it would open, it would fit, it
        would reach the store — and would be the defect Rick reported.

        ⚠️ APPROVE DISABLES THE REASON BOX, AND THAT IS CORRECT. `_verbNeeds`
        gives approve `reason: false`, and the verb-change handler disables
        the field, clears it, and re-labels it "Approve needs no reason".
        The first cut of this test filled it anyway and hung for 30s on
        Playwright's editability wait — a test defect wearing the costume of
        a product defect. The assertion below pins the disabling so the next
        reader does not re-introduce the fill.
        """
        state = _seeded_page( logged_in_page )

        logged_in_page.locator(
            f'#holding-area-container .task-disclose-button[data-task-id="{HELD_ID}"]' ).click()
        logged_in_page.wait_for_selector(
            f'#holding-area-container .task-controls-row[data-controls-for="{HELD_ID}"]:not([hidden])',
            state="attached" )

        pane = f'#holding-area-container [data-task-id="{HELD_ID}"]'
        logged_in_page.select_option( f'{pane}.task-verb-select', "approve" )

        assert logged_in_page.locator( f'{pane}.task-reason-input' ).is_disabled(), \
            "approve must disable the reason box — it takes no reason"

        logged_in_page.click( f'{pane}.task-submit-button' )
        logged_in_page.wait_for_timeout( 1200 )

        posted = state[ "transitions" ]
        assert len( posted ) == 1, f"expected exactly one transition, saw {len( posted )}: {posted}"
        assert posted[ 0 ][ "id" ] == HELD_ID, f"posted against {posted[ 0 ][ 'id' ]}, not the row that was edited"
        assert posted[ 0 ][ "body" ].get( "to_status" ) == "queued", \
            f"approve must move the row to queued, sent {posted[ 0 ][ 'body' ]}"

    def test_a_reason_carrying_verb_sends_the_operator_s_own_words( self, logged_in_page ):
        """
        Rick's ask verbatim — "choose an action, submit a reason" — on the
        one verb where the reason is the whole point.

        ⚠️ APPROVE CANNOT CARRY THIS CLAIM, which is why this is a second
        test rather than a widened first one: approve takes no reason, so a
        suite that only exercised approve would never once prove the reason
        the operator typed reaches the store. Won't-fix is the verb whose
        justification is the only thing distinguishing it from work that got
        forgotten.

        ⚠️ TWO CLICKS, DELIBERATELY. Won't-fix is terminal, so the first
        click ARMS the button and the second sends it. A single click here
        would post nothing and read as the wire being broken.
        """
        state = _seeded_page( logged_in_page )

        logged_in_page.locator(
            f'#holding-area-container .task-disclose-button[data-task-id="{HELD_ID}"]' ).click()
        logged_in_page.wait_for_selector(
            f'#holding-area-container .task-controls-row[data-controls-for="{HELD_ID}"]:not([hidden])',
            state="attached" )

        pane   = f'#holding-area-container [data-task-id="{HELD_ID}"]'
        reason = "overtaken by the v2 front door"
        logged_in_page.select_option( f'{pane}.task-verb-select', "wont_fix" )
        logged_in_page.fill( f'{pane}.task-reason-input', reason )

        logged_in_page.click( f'{pane}.task-submit-button' )      # arms
        assert not state[ "transitions" ], \
            "a terminal verb must ARM on the first click, not post — the confirm step is gone"

        logged_in_page.click( f'{pane}.task-submit-button' )      # confirms
        logged_in_page.wait_for_timeout( 1200 )

        posted = state[ "transitions" ]
        assert len( posted ) == 1, f"expected exactly one transition, saw {len( posted )}: {posted}"
        assert posted[ 0 ][ "id" ] == HELD_ID
        assert posted[ 0 ][ "body" ].get( "to_status" ) == "wont_fix", \
            f"sent {posted[ 0 ][ 'body' ]}"
        assert posted[ 0 ][ "body" ].get( "reason" ) == reason, \
            f"the operator's own words did not reach the store: {posted[ 0 ][ 'body' ]}"

    def test_a_second_row_is_untouched_by_the_first_row_s_submit( self, logged_in_page ):
        """
        The other held row does not move.

        ⚠️ THIS IS A DIFFERENT CLAIM FROM THE COUNT ABOVE and both are
        needed: a control could post once and post it against the WRONG id,
        which the count alone reads as a clean pass.
        """
        state = _seeded_page( logged_in_page )

        logged_in_page.locator(
            f'#holding-area-container .task-disclose-button[data-task-id="{HELD_ID}"]' ).click()
        pane = f'#holding-area-container [data-task-id="{HELD_ID}"]'
        logged_in_page.select_option( f'{pane}.task-verb-select', "approve" )
        logged_in_page.click( f'{pane}.task-submit-button' )
        logged_in_page.wait_for_timeout( 1200 )

        other = HELD_TASKS[ 1 ][ "id" ]
        touched = [ t for t in state[ "transitions" ] if t[ "id" ] == other ]
        assert not touched, f"the second row was transitioned too: {touched}"


class TestTheBulkControlSurvives:
    """Rick kept it deliberately; removing it is the opposite regression."""

    def test_each_group_still_carries_approve_all_and_wont_fix_all( self, logged_in_page ):
        """
        "I just told you that you could keep the bulk approval. I'm just
        not gonna use it." — Rick, 2026-09-03.

        The per-row editor is an ADDITION. A suite that guarded only the new
        control would go green on a change that deleted this one.
        """
        _seeded_page( logged_in_page )

        groups   = logged_in_page.locator( "#holding-area-container .holding-area-group" ).count()
        approve  = logged_in_page.locator( "#holding-area-container .holding-approve-all" ).count()
        wont_fix = logged_in_page.locator( "#holding-area-container .holding-wont-fix-all" ).count()

        assert groups >= 2, f"expected a group per filer, saw {groups}"
        assert approve  == groups, f"{groups} groups but {approve} Approve-all buttons"
        assert wont_fix == groups, f"{groups} groups but {wont_fix} Won't-fix-all buttons"
