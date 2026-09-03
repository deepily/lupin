// Row-control redesign — ONE verb select, ONE reason field, ONE Submit.
//
// Rick, 2026-09-02, in his own words: "you literally repeated similar functionality in
// drop park and demote with three different buttons and three different text fields.
// You need to overload those actions and need to be consistent from row to row."
//
// The cell being replaced grew one verb at a time — Drop, then Park, then Won't-fix,
// then Demote, then Approve — each with its own button and its own input, and nobody
// looked at all five together until Rick did. Five buttons and five text boxes for five
// moves that differ only in which word gets posted to the same endpoint.
//
// 🔴 THESE ARE WRITTEN RED, AGAINST TODAY'S CELL, ON PURPOSE. Every assertion here
// fails at the fork sha and must fail before the cell is touched — otherwise the file
// is describing what already exists rather than what is being built, and would go
// green without a line of the redesign landing. The red list is recorded in the commit.
//
// ⚠️ THIS FILE DOES NOT REPLACE holding_area_panel / task_list_panel / epic_board_panel.
// Those carry the behaviour guards Pocholo converted to real click paths tonight, at
// real cost. Reds there are the guard working and are reported, never edited to fit.
//
// Run: npx tsx --test src/tests/unit/notifications_js/row_control_redesign.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type RowUI = Record<string, unknown> & {
  _taskActionsCell: ( task: Record<string, unknown> ) => string;
  _handleTaskSubmitClick: ( button: unknown ) => Promise<void>;
  _handleVerbSelectChange: ( select: unknown ) => void;
  _handleRowControlClick: ( target: unknown ) => boolean;
  _wireTaskListAccordion: () => void;
  _wireHoldingAreaControls: () => void;
  _wireEpicBoardAccordion: () => void;
  _transitionTask: ( id: string, to: string, extras?: unknown ) => Promise<{ ok: boolean; message?: string }>;
  refreshTaskList: () => Promise<void>;
  refreshHoldingArea: () => Promise<void>;
};

function newUI(): RowUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as RowUI;
  ui.debug                     = false;
  ui.log                       = (): void => {};
  ui.error                     = (): void => {};
  ui._taskListFetchInFlight    = false;
  ui._holdingAreaFetchInFlight = false;
  ui._taskListLastGoodTasks    = null;
  ui.TASK_TITLE_TRUNCATE_LEN   = 60;
  ui.queueSessionId            = "test-session";
  ui._holdingAreaControlsWired = false;
  ui._taskListAccordionWired   = false;
  return ui;
}

const ROW_ID = "aaaaaaaa-1111-2222-3333-444444444444";

function row( over: Record<string, unknown> = {} ): Record<string, unknown> {
  return {
    id: ROW_ID, title: "a row", status: "queued", item_class: "task",
    created_by: "rio 87e08fee", priority: "P2", project: "lupin", ...over
  };
}

// The page's real three-pane shape — same fixture the sibling files use, and for the
// same reason: a nested fixture lets one pane's listener catch another pane's clicks.
function realPageDOM(): void {
  document.body.innerHTML = `
    <div class="collapsible-section" id="section-task-list">
      <div class="section-content"><div id="task-list-container"></div></div>
    </div>
    <div class="collapsible-section" id="section-holding-area">
      <div class="section-content" id="holding-area-section">
        <div id="holding-area-container"></div>
      </div>
    </div>
    <div class="collapsible-section" id="section-epic-board">
      <div class="section-content"><div id="epic-board-container"></div></div>
    </div>`;
}

// Put the cell in the live task-list pane and wire the real delegated listeners, so a
// click travels the path a browser would rather than reaching the handler by name.
function paneWithCell( ui: RowUI, task: Record<string, unknown> ): HTMLElement {
  realPageDOM();
  const host = document.getElementById( "task-list-container" ) as HTMLElement;
  host.innerHTML = `
    <table id="task-list-table"><tbody>
      <tr><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${task.id}" hidden><td></td></tr>
    </tbody></table>`;
  // ⚠️ THE WIRING GUARDS MUST BE RESET, and this is a FIXTURE concern, not a product
  // one. Each pane wires its container once and remembers it, which is correct in the
  // page — the container element outlives every repaint, only its innerHTML is
  // replaced. This helper rebuilds the whole DOM per call, so the remembered "already
  // wired" would leave the listener on a container that has been thrown away, and
  // every click after the first row would reach no handler. That reads exactly like a
  // dead control and is not one.
  ui._taskListAccordionWired   = false;
  ui._holdingAreaControlsWired = false;
  ui._epicBoardAccordionWired  = false;
  ui._wireTaskListAccordion();
  ui._wireHoldingAreaControls();
  ui._wireEpicBoardAccordion();
  return host;
}

// Dispatch a REAL bubbling event and assert a handler was reached, then hand back its
// promise. Copied deliberately from holding_area_panel's `clickThrough`: at the fork,
// 0 of 20 row-control tests reached a real event, which is why three panes of dead
// controls stayed invisible to 484 passing tests.
async function clickThrough( ui: RowUI, method: string, el: Element | null, what: string ): Promise<void> {
  assert.ok( el, `${ what } did not render at all — this test cannot speak to wiring` );
  const target   = ui as unknown as Record<string, ( b: unknown ) => unknown >;
  const original = target[ method ];
  let   ran: unknown = null;
  target[ method ] = ( b: unknown ) => { ran = original.call( ui, b ); return ran; };
  el!.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
  target[ method ] = original;
  assert.ok( ran !== null,
    `${ what } reached NO handler — the control is dead on screen however correct the handler is` );
  await ran;
}

function selectVerb( host: HTMLElement, verb: string ): HTMLSelectElement {
  const sel = host.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  assert.ok( sel, "the row renders no verb select at all" );
  sel.value = verb;
  sel.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
  return sel;
}

const VERBS = [ "park", "drop", "demote", "wont_fix", "approve" ];

beforeEach( () => realPageDOM() );


// ════════════════════ one select, one field, one button ════════════════════

test( "all five verbs live on ONE select, and the row renders no per-verb buttons", () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );

  const selects = host.querySelectorAll( ".task-verb-select" );
  assert.equal( selects.length, 1, "the row does not carry exactly one verb select" );

  const values = Array.from( ( selects[ 0 ] as HTMLSelectElement ).options )
    .map( o => o.value ).filter( v => v !== "" );
  assert.deepEqual( values, VERBS,
    "the select does not carry all five verbs in the settled order" );

  // ⚠️ THE ABSENCE HALF IS THE POINT OF THE REDESIGN and is asserted separately from
  // the presence half: a select that renders ALONGSIDE the five old buttons satisfies
  // every assertion above and changes nothing Rick complained about.
  for ( const dead of [ "task-drop-button", "task-park-button", "task-wont-fix-button",
                        "task-demote-button", "task-approve-button" ] ) {
    assert.equal( host.querySelectorAll( `.${dead}` ).length, 0,
      `${dead} still renders — the verbs were added to a select without the buttons leaving` );
  }
} );

test( "the row renders ONE reason field, not one per verb", () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );

  assert.equal( host.querySelectorAll( ".task-reason-input" ).length, 1,
    "the row does not carry exactly one shared reason field" );
  for ( const dead of [ "task-drop-reason", "task-park-reason", "task-wont-fix-reason",
                        "task-demote-reason" ] ) {
    assert.equal( host.querySelectorAll( `.${dead}` ).length, 0,
      `${dead} still renders — the fields were not actually merged` );
  }
} );

test( "the one action button reads Submit", () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );

  const buttons = host.querySelectorAll( "button.task-action-btn" );
  assert.equal( buttons.length, 1, "the row does not carry exactly one action button" );
  // Rick: "It's probably submit right? That sounds better than go."
  assert.equal( ( buttons[ 0 ].textContent ?? "" ).trim(), "Submit" );
} );


// ════════════════════ the field follows the verb ════════════════════

test( "choosing Approve DISABLES the shared reason field", () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "not_approved" } ) );
  const box  = host.querySelector( ".task-reason-input" ) as HTMLInputElement;

  selectVerb( host, "drop" );
  assert.equal( box.disabled, false, "the reason field is dead for a verb that requires one" );

  selectVerb( host, "approve" );
  // Rick: "let's do all 5 on the drop-down and the field disables for approved."
  // Disabled rather than merely ignored — a live box beside a verb that discards its
  // contents invites the operator to type a justification nothing will ever read.
  assert.equal( box.disabled, true, "Approve leaves the reason field live" );

  selectVerb( host, "wont_fix" );
  assert.equal( box.disabled, false, "the field stays dead after leaving Approve" );
} );

test( "the date input appears only for a verb that needs one, and says what it is for", () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );

  const dateNow = () => host.querySelector( ".task-chase-input" ) as HTMLInputElement | null;

  assert.equal( dateNow(), null, "a date input renders before any verb is chosen" );
  selectVerb( host, "drop" );
  assert.equal( dateNow(), null, "Drop takes no date and renders one anyway" );

  selectVerb( host, "park" );
  const shown = dateNow();
  assert.ok( shown, "Park renders no date input" );
  assert.equal( shown!.type, "date" );
  // 🔴 THE RELABEL IS THE WHOLE ANSWER TO RICK'S QUESTION. He said "I really have no
  // idea what the date chooser is for". A control whose purpose the operator cannot
  // infer is a defect in the CONTROL, not in the operator — so the label states the
  // thing the date does rather than naming the field the server stores it in.
  assert.equal( shown!.getAttribute( "aria-label" ), "Chase me again on" );
  assert.equal( host.textContent?.includes( "Chase date" ), false,
    "the old unguessable label survives somewhere in the cell" );
} );


// ════════════════════ legality, in the option's own label ════════════════════

function optionFor( host: HTMLElement, verb: string ): HTMLOptionElement {
  const opt = host.querySelector( `.task-verb-select option[value="${verb}"]` ) as HTMLOptionElement;
  assert.ok( opt, `no option for ${verb}` );
  return opt;
}

test( "an illegal verb is greyed out AND says why, in the option's own label", () => {
  const ui   = newUI();
  // `blocked` is outside PARK_LEGAL_FROM_STATUSES = ( queued, in_progress ).
  const host = paneWithCell( ui, row( { status: "blocked" } ) );

  const park = optionFor( host, "park" );
  assert.equal( park.disabled, true, "Park is offered from a status the server refuses" );
  // 🔴 AN <option> HAS NOWHERE TO PUT A TOOLTIP. The five buttons carried their legality
  // in `title`, which a disabled option cannot show — so the explanation moves INTO the
  // label rather than being quietly dropped in the redesign.
  assert.match( park.textContent ?? "", /only from queued or in progress/i );

  const drop = optionFor( host, "drop" );
  assert.equal( drop.disabled, false, "Drop is legal from every non-terminal status" );
  assert.equal( ( drop.textContent ?? "" ).trim(), "Drop",
    "a legal verb carries an explanation it does not need" );
} );

test( "a terminal row offers every verb greyed, with the terminal reason on each", () => {
  const ui = newUI();
  for ( const status of [ "done", "dropped", "wont_fix" ] ) {
    const host = paneWithCell( ui, row( { status } ) );
    for ( const verb of VERBS ) {
      const opt = optionFor( host, verb );
      assert.equal( opt.disabled, true,
        `${verb} is live on a ${status} row — terminal rows are append-only` );
      assert.match( opt.textContent ?? "", /terminal/i,
        `${verb} is greyed on a ${status} row without saying why` );
    }
  }
} );

test( "Approve and Demote are still never both live on one row", () => {
  const ui = newUI();
  for ( const [ status, live ] of [ [ "not_approved", "approve" ], [ "queued", "demote" ] ] ) {
    const host = paneWithCell( ui, row( { status } ) );
    const dead = live === "approve" ? "demote" : "approve";
    assert.equal( optionFor( host, live ).disabled, false, `${live} is greyed on a ${status} row` );
    assert.equal( optionFor( host, dead ).disabled, true,
      `${dead} is live on a ${status} row — a no-op edge the store rejects as a failure` );
  }
} );


// ════════════════════ Submit dispatches by the chosen verb ════════════════════

test( "Submit posts the verb the select names — a real click, all four reversible verbs", async () => {
  const ui = newUI();
  // Won't-fix is deliberately absent: it takes TWO clicks now and has its own test
  // below. Folding it in here would need a branch inside the loop, and a loop with a
  // branch in it stops being one assertion repeated and starts being two tests wearing
  // one name.
  const expected: Record<string, string> = {
    park: "parked", drop: "dropped", demote: "not_approved", approve: "queued"
  };

  for ( const verb of [ "park", "drop", "demote", "approve" ] ) {
    // Each verb needs a row it is legal on: approve only from not_approved, demote
    // only from anything else.
    const host = paneWithCell( ui, row( { status: verb === "approve" ? "not_approved" : "queued" } ) );
    const calls: Array<[ string, string ]> = [];
    ui._transitionTask   = async ( i, to ) => { calls.push( [ i, to ] ); return { ok: true }; };
    ui.refreshTaskList   = async () => {};
    ui.refreshHoldingArea = async () => {};

    selectVerb( host, verb );
    const box = host.querySelector( ".task-reason-input" ) as HTMLInputElement;
    if ( !box.disabled ) box.value = "a reason that is not blank";
    const date = host.querySelector( ".task-chase-input" ) as HTMLInputElement | null;
    if ( date ) date.value = "2026-09-09";

    await clickThrough( ui, "_handleTaskSubmitClick",
      host.querySelector( ".task-submit-button" ), `Submit for ${verb}` );

    assert.equal( calls.length, 1, `Submit sent nothing for ${verb}` );
    assert.equal( calls[ 0 ][ 1 ], expected[ verb ],
      `Submit posted the wrong status for ${verb}` );
    assert.equal( calls[ 0 ][ 0 ], ROW_ID );
  }
} );

test( "Submit with no verb chosen refuses in words instead of posting", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  const calls: string[] = [];
  ui._transitionTask = async ( _i, to ) => { calls.push( to ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  await clickThrough( ui, "_handleTaskSubmitClick",
    host.querySelector( ".task-submit-button" ), "Submit with nothing chosen" );

  assert.equal( calls.length, 0, "Submit posted a transition with no verb selected" );
  const stripe = host.querySelector( ".task-row-error-stripe" ) as HTMLElement;
  assert.equal( stripe.hidden, false, "the refusal is invisible — the button reads as dead" );
  assert.match( stripe.textContent ?? "", /choose an action/i );
} );

test( "the blank-reason refusal survives the merge, for every verb that requires one", async () => {
  const ui = newUI();
  for ( const verb of [ "park", "drop", "demote", "wont_fix" ] ) {
    const host = paneWithCell( ui, row( { status: "queued" } ) );
    const calls: string[] = [];
    ui._transitionTask = async ( _i, to ) => { calls.push( to ); return { ok: true }; };
    ui.refreshTaskList = async () => {};

    selectVerb( host, verb );
    const date = host.querySelector( ".task-chase-input" ) as HTMLInputElement | null;
    if ( date ) date.value = "2026-09-09";     // isolate the reason as the only thing missing

    await clickThrough( ui, "_handleTaskSubmitClick",
      host.querySelector( ".task-submit-button" ), `Submit for ${verb} with a blank reason` );

    assert.equal( calls.length, 0, `${verb} posted with a blank reason` );
    const stripe = host.querySelector( ".task-row-error-stripe" ) as HTMLElement;
    assert.equal( stripe.hidden, false, `${verb} refused without showing the refusal` );
    assert.match( stripe.textContent ?? "", /reason/i );
  }
} );


// ════════════════════ the terminal verb keeps its own step ════════════════════
//
// 🔴 THE STEP IS A SECOND CLICK IN THE PAGE, NOT A BROWSER `confirm()`. Rick's ruling,
// 2026-09-02, relayed by María: with Won't-fix chosen, Submit relabels to "Confirm
// won't-fix" and fires only on the next click.
//
// ⚠️ AND THE STEP IS NOT A CARRY-OVER — THE OLD CELL HAD NO CONFIRMATION AT ALL.
// Measured before building: 11 `confirm(` calls in the file, exactly one inside the five
// row handlers, and it is a COMMENT at :11854 saying there is no dialog. What that
// comment gives as the reason is the thing this redesign destroys — "the reversible
// sibling is one button to the left", i.e. Demote. Once five verbs share one Submit
// there is no button to the left, so the safeguard stops existing at precisely the
// moment the terminal verb moves behind a shared control. The risk does not persist
// across the redesign; it GROWS, and the comment would have gone on reassuring readers
// that an arrangement still held after it was gone.

test( "🔴 the FIRST click on Won't-fix arms the button and sends nothing", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  const calls: string[] = [];
  ui._transitionTask = async ( _i, to ) => { calls.push( to ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  selectVerb( host, "wont_fix" );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "not doing it";
  const btn = host.querySelector( ".task-submit-button" ) as HTMLButtonElement;

  await clickThrough( ui, "_handleTaskSubmitClick", btn, "the first Submit for wont_fix" );

  assert.equal( calls.length, 0,
    "one click closed the row permanently — the terminal verb has no step of its own" );
  assert.equal( ( btn.textContent ?? "" ).trim(), "Confirm won't-fix",
    "the button did not say that it is now armed, so the second click is a surprise" );
} );

test( "🔴 the SECOND click is what closes the row", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  const calls: Array<[ string, string ]> = [];
  ui._transitionTask = async ( i, to ) => { calls.push( [ i, to ] ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  selectVerb( host, "wont_fix" );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "not doing it";
  const btn = host.querySelector( ".task-submit-button" ) as HTMLButtonElement;

  await clickThrough( ui, "_handleTaskSubmitClick", btn, "the first Submit for wont_fix" );
  await clickThrough( ui, "_handleTaskSubmitClick", btn, "the second Submit for wont_fix" );

  assert.deepEqual( calls, [ [ ROW_ID, "wont_fix" ] ],
    "the armed button did not fire on the second click — the verb is unreachable" );
} );

test( "🔴 changing the verb DISARMS the button", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  const calls: string[] = [];
  ui._transitionTask = async ( _i, to ) => { calls.push( to ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  selectVerb( host, "wont_fix" );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "not doing it";
  const btn = host.querySelector( ".task-submit-button" ) as HTMLButtonElement;
  await clickThrough( ui, "_handleTaskSubmitClick", btn, "the first Submit for wont_fix" );

  // ⚠️ AN ARMED BUTTON THAT SURVIVES A CHANGE OF VERB IS WORSE THAN NO ARMING AT ALL:
  // the operator changes their mind to Drop, clicks once expecting the usual single
  // click, and the click is consumed by a confirmation for a verb they have left.
  selectVerb( host, "drop" );
  assert.equal( ( btn.textContent ?? "" ).trim(), "Submit",
    "the button still reads as armed after the verb changed" );

  await clickThrough( ui, "_handleTaskSubmitClick", btn, "Submit for drop after re-choosing" );
  assert.deepEqual( calls, [ "dropped" ],
    "the first click after changing the verb did not post the new verb" );
} );

test( "🔴 the four reversible verbs never arm — one click is one action", async () => {
  const ui = newUI();
  for ( const verb of [ "park", "drop", "demote", "approve" ] ) {
    const host = paneWithCell( ui, row( { status: verb === "approve" ? "not_approved" : "queued" } ) );
    const calls: string[] = [];
    ui._transitionTask    = async ( _i, to ) => { calls.push( to ); return { ok: true }; };
    ui.refreshTaskList    = async () => {};
    ui.refreshHoldingArea = async () => {};

    selectVerb( host, verb );
    const box = host.querySelector( ".task-reason-input" ) as HTMLInputElement;
    if ( !box.disabled ) box.value = "a reason that is not blank";
    const date = host.querySelector( ".task-chase-input" ) as HTMLInputElement | null;
    if ( date ) date.value = "2026-09-09";

    await clickThrough( ui, "_handleTaskSubmitClick",
      host.querySelector( ".task-submit-button" ), `Submit for ${verb}` );

    assert.equal( calls.length, 1,
      `${verb} needed a second click — the confirmation guards more than the terminal verb` );
  }
} );

test( "🔴 a blank reason is refused BEFORE the button arms", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  ui._transitionTask = async () => ( { ok: true } );
  ui.refreshTaskList = async () => {};

  selectVerb( host, "wont_fix" );
  const btn = host.querySelector( ".task-submit-button" ) as HTMLButtonElement;
  await clickThrough( ui, "_handleTaskSubmitClick", btn, "Submit for wont_fix with a blank reason" );

  // ⚠️ ORDER MATTERS AND IS NOT ARBITRARY. Arm first and the operator's second click —
  // the one they believe is the confirmation — lands on a refusal for a blank field
  // instead, so the confirmation they gave was never asked for and the row is one more
  // click from closing than they think.
  assert.equal( ( btn.textContent ?? "" ).trim(), "Submit",
    "the button armed on a submission that was going to be refused anyway" );
  const stripe = host.querySelector( ".task-row-error-stripe" ) as HTMLElement;
  assert.equal( stripe.hidden, false );
  assert.match( stripe.textContent ?? "", /reason/i );
} );


// ════════════════════ consistency, which is what Rick actually asked for ════════════════════

test( "every non-terminal row renders the SAME controls whatever its status", () => {
  const ui = newUI();
  // Rick: "you need to ... be consistent from row to row." The five-button cell rendered
  // a different NUMBER of controls per status — park's two inputs appeared and vanished,
  // demote's date came and went — so no two rows lined up and the eye had to re-find the
  // control it wanted on every line.
  const shapes = new Set<string>();
  for ( const status of [ "queued", "in_progress", "blocked", "review", "not_approved", "parked" ] ) {
    const host = paneWithCell( ui, row( { status } ) );
    shapes.add( [
      host.querySelectorAll( ".task-verb-select" ).length,
      host.querySelectorAll( ".task-reason-input" ).length,
      host.querySelectorAll( "button.task-action-btn" ).length
    ].join( "/" ) );
  }
  assert.deepEqual( Array.from( shapes ), [ "1/1/1" ],
    `rows of different statuses render different control shapes: ${Array.from( shapes ).join( " vs " )}` );
} );


// ═══════════ properties the retired per-verb guards were holding ═══════════
//
// 🔴 THESE EXIST BECAUSE OF WHAT THE REDESIGN COSTS, and they were written after
// measuring it rather than in anticipation. Six assertions in the Python guard
// `test_task_row_state_controls.py` went red on this change. All six pin the OLD
// SHAPE'S NAMES — `_handleTaskDropClick`, `task-wont-fix-button`, `task-demote-chase`
// — and every underlying property survives. But three of them were the ONLY guard on
// their property, so retiring them on the strength of "the name moved" would drop real
// coverage silently. The name is replaceable; the property is not.
//
// ⚠️ AND ONE OF THE SIX IS A SOURCE-TEXT CHECK THAT CANNOT SEE A COMPUTED STRING:
// `assert "Approve refused: " in client_src`. The client still shows exactly that to
// the operator — it is now built as `${this._verbLabel( verb )} refused: ...`, so the
// literal never appears in the file while the behaviour is unchanged. A test that reads
// source can tell neither an implementation from its explanation nor a literal from an
// expression, which is the same limit that file documents about itself.

test( "Approve surfaces the server's own refusal, verbatim and unedited", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "not_approved" } ) );
  // The 403 the store actually sends names the actor and the allowlist. The client must
  // not pre-empt it: the approver list is server-side configuration Rick called
  // provisional, and a client-side copy would refuse people the server would allow.
  ui._transitionTask = async () => ( { ok: false, message: "rio is not an approver; allowlist is managers + rick" } );
  ui.refreshTaskList = async () => {};

  selectVerb( host, "approve" );
  await clickThrough( ui, "_handleTaskSubmitClick",
    host.querySelector( ".task-submit-button" ), "Submit for approve" );

  const stripe = host.querySelector( ".task-row-error-stripe" ) as HTMLElement;
  assert.equal( stripe.hidden, false, "the refusal is invisible — the button reads as dead" );
  assert.match( stripe.textContent ?? "", /^Approve refused: /,
    "the stripe does not name the verb that was refused" );
  assert.match( stripe.textContent ?? "", /allowlist is managers \+ rick/,
    "the server's own words were summarised away — the operator cannot act on a paraphrase" );
} );

test( "Demote stamps a triage-by date, converted through the browser's own zone", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  const sent: Array<Record<string, string>> = [];
  ui._transitionTask = async ( _i, _to, extras ) => {
    sent.push( extras as Record<string, string> ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  selectVerb( host, "demote" );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "back to triage";
  const date = host.querySelector( ".task-chase-input" ) as HTMLInputElement;
  assert.ok( date, "Demote collects no triage-by date — a held row would be unbounded" );
  date.value = "2026-09-09";

  await clickThrough( ui, "_handleTaskSubmitClick",
    host.querySelector( ".task-submit-button" ), "Submit for demote" );

  // 🔴 THE CONVERSION IS THE ASSERTION, not the presence of a field. `<input type="date">`
  // yields a bare calendar day; posted as-is it reads as midnight UTC, which lands the
  // chase on the PREVIOUS EVENING for every zone west of Greenwich — all of ours. The
  // client stamps 09:00 local and converts, so the instant must equal what this browser
  // means by 09:00 on that day, and must NOT be the bare date.
  assert.equal( sent.length, 1 );
  assert.equal( sent[ 0 ].next_chase_ts, new Date( "2026-09-09T09:00:00" ).toISOString() );
  assert.notEqual( sent[ 0 ].next_chase_ts, "2026-09-09" );
  assert.equal( sent[ 0 ].reason, "back to triage" );
} );

test( "Park stamps its chase the same way, under its own field name", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  const sent: Array<Record<string, string>> = [];
  ui._transitionTask = async ( _i, _to, extras ) => {
    sent.push( extras as Record<string, string> ); return { ok: true }; };
  ui.refreshTaskList = async () => {};

  selectVerb( host, "park" );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "NOT TO BE WORKED per Rick";
  ( host.querySelector( ".task-chase-input" ) as HTMLInputElement ).value = "2026-09-09";
  await clickThrough( ui, "_handleTaskSubmitClick",
    host.querySelector( ".task-submit-button" ), "Submit for park" );

  // ⚠️ ONE BOX, TWO FIELD NAMES. The store takes `park_reason` for a park and `reason`
  // for everything else, so the merge of the INPUTS must not become a merge of the
  // PAYLOADS — that would post a park with no park_reason and be refused server-side
  // for a field the operator did fill in.
  assert.equal( sent.length, 1 );
  assert.equal( sent[ 0 ].park_reason, "NOT TO BE WORKED per Rick" );
  assert.equal( sent[ 0 ].reason, undefined, "a park posted its reason under the wrong key" );
  assert.equal( sent[ 0 ].next_chase_ts, new Date( "2026-09-09T09:00:00" ).toISOString() );
} );

test( "the park field still asks for a QUOTE, and each verb keeps its own complaint", () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  const box  = host.querySelector( ".task-reason-input" ) as HTMLInputElement;

  // ⚠️ MERGING THE CONTROLS WAS THE ASK; MERGING WHAT THEY MEAN WAS NOT. `park_reason`
  // must carry the row's OWN decisive sentence — that quote is what lets the next reader
  // refute the park row-by-row instead of re-deriving the board — and a bare "reason…"
  // placeholder produces paraphrases.
  selectVerb( host, "park" );
  assert.match( box.placeholder, /quote the sentence that decided this/ );
  selectVerb( host, "demote" );
  assert.match( box.placeholder, /triage/i );
  assert.notEqual( box.placeholder, "quote the sentence that decided this…",
    "every verb inherited park's placeholder — the field says the same thing five times" );
} );


// ═══════════ what the merge BREAKS elsewhere, found by running the tier ═══════════
//
// 🔴 BOTH OF THESE ARE DEFECTS THE REDESIGN INTRODUCED, not name-pins on the old shape.
// They were found by running the three sibling test files and refusing to read 33 reds
// as one thing: most were the guard reporting a changed shape, and two were the guard
// reporting a change that BROKE something. Sorting them was the work; a blanket "the
// shape moved" would have shipped both.

test( "🔴 the batch still finds its rows after the per-verb buttons left", () => {
  const ui = newUI();
  realPageDOM();
  ui._taskListAccordionWired   = false;
  ui._holdingAreaControlsWired = false;
  ui._epicBoardAccordionWired  = false;
  ui._wireHoldingAreaControls();
  ui.renderHoldingArea( { status: "ok", tasks: [
    row( { id: "h1", status: "not_approved", created_by: "krishna 420f5ec9" } ),
    row( { id: "h2", status: "not_approved", created_by: "krishna 420f5ec9" } )
  ] } );

  // ⚠️ THE BATCH READ ITS ROW IDS OFF `.task-approve-button`, which this redesign
  // deletes. Nothing failed loudly: the selector simply matched nothing, so batch
  // approve and batch won't-fix would have reported success over ZERO rows — a button
  // that works, on an empty list, silently. The ids must come off a control that still
  // exists on every row.
  // ⚠️ THE GROUP IS KEYED BY THE DISPLAY FILER, NOT BY `created_by`. The pane derives
  // "Krishna" from "krishna 420f5ec9", so a lookup with the raw field finds no group and
  // returns [] — indistinguishable from the defect this test is about. Measured while
  // writing it: the first version passed the raw value and went red for the wrong reason.
  assert.equal(
    ( document.querySelector( ".holding-area-group[data-filer]" ) as HTMLElement ).dataset.filer,
    "Krishna", "the group key moved; this test would go red without the batch being broken" );
  const ids = ui._heldRowIdsForFiler( "Krishna" );
  assert.deepEqual( ids.sort(), [ "h1", "h2" ],
    "the batch finds no rows — it would act on nothing and say it succeeded" );
} );

test( "🔴 a repaint keeps the CHOSEN VERB, not only the typed reason", () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );

  selectVerb( host, "park" );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "the sentence that decided it";
  ( host.querySelector( ".task-chase-input" ) as HTMLInputElement ).value = "2026-09-09";

  // The 60s poll replaces the pane's innerHTML. Rick's bug was that everything typed
  // and unsubmitted lived in that markup; the fix captures and restores it.
  const saved = ui._captureOperatorState( host );
  const task  = row( { status: "queued" } );
  host.innerHTML = `
    <table id="task-list-table"><tbody>
      <tr><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${ROW_ID}" hidden><td></td></tr>
    </tbody></table>`;
  ui._restoreOperatorState( host, saved );

  // 🔴 THE VERB IS OPERATOR STATE TOO, and it is the piece the redesign ADDED. Restoring
  // the reason without the verb leaves the operator's words attached to no action: the
  // select falls back to "Choose an action…", their next click is refused for having
  // chosen nothing, and the text they can still see makes the refusal look wrong.
  assert.equal( ( host.querySelector( ".task-verb-select" ) as HTMLSelectElement ).value, "park",
    "the chosen verb was lost in the repaint" );
  assert.equal( ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value,
    "the sentence that decided it" );
  // ⚠️ AND THE DATE BOX ONLY EXISTS BECAUSE PARK IS CHOSEN, so restoring its value
  // requires rebuilding the control first. Restore the text before the verb and the
  // field it belongs in has not been created yet.
  const date = host.querySelector( ".task-chase-input" ) as HTMLInputElement | null;
  assert.ok( date, "Park's date box was not rebuilt, so its value had nowhere to go" );
  assert.equal( date!.value, "2026-09-09" );
} );

test( "🔴 a repaint DISARMS won't-fix — the confirmation does not survive it", async () => {
  const ui   = newUI();
  const host = paneWithCell( ui, row( { status: "queued" } ) );
  ui._transitionTask = async () => ( { ok: true } );
  ui.refreshTaskList = async () => {};

  selectVerb( host, "wont_fix" );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "not doing it";
  await clickThrough( ui, "_handleTaskSubmitClick",
    host.querySelector( ".task-submit-button" ), "the first Submit for wont_fix" );

  const saved = ui._captureOperatorState( host );
  const task  = row( { status: "queued" } );
  host.innerHTML = `<table id="task-list-table"><tbody><tr><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${ROW_ID}" hidden><td></td></tr></tbody></table>`;
  ui._restoreOperatorState( host, saved );

  // ⚠️ THE ARMED STATE IS THE ONE PIECE THAT MUST *NOT* SURVIVE, and the direction is
  // the whole point. An arming restored across a repaint the operator did not see means
  // their next click closes the row permanently when they expected to be asked. Losing
  // it costs one click; keeping it costs a row.
  const btn = host.querySelector( ".task-submit-button" ) as HTMLButtonElement;
  assert.equal( ( btn.textContent ?? "" ).trim(), "Submit",
    "the button came back armed after a repaint nobody saw" );
  assert.notEqual( btn.dataset.armed, "1" );
} );


test( "🔴 the batch collects only rows the batch verb is LEGAL on", () => {
  const ui = newUI();
  // 🔴 THE OLD SELECTOR WAS NARROWER THAN IT LOOKED, and the narrowing was invisible.
  // `.task-approve-button[data-task-id]` matched only rows where Approve was ENABLED,
  // because the disabled form of that button was rendered WITHOUT a data-task-id at all.
  // So the batch silently acted on approvable rows only. Porting it to
  // `.task-verb-select[data-task-id]` — which every row carries — widens the batch to
  // every row in the group, and nothing about the change says so.
  //
  // ⚠️ TODAY THE TWO ARE EQUIVALENT because the pane is fed a held-rows-only query, so
  // this cannot be caught by rendering the real pane. It is a latent widening: the day a
  // non-held row reaches this pane, batch approve posts `queued` for a row already queued
  // and the store refuses a no-op edge as a failure.
  document.body.innerHTML = `<div id="holding-area-container"><div class="holding-area-group" data-filer="alice"></div></div>`;
  const group = document.querySelector( ".holding-area-group" ) as HTMLElement;
  group.innerHTML =
    ui._taskActionsCell( row( { id: "held-1", status: "not_approved" } ) ) +
    ui._taskActionsCell( row( { id: "live-2", status: "queued" } ) ) +
    ui._taskActionsCell( row( { id: "dead-3", status: "wont_fix" } ) );

  assert.deepEqual( ui._heldRowIdsForFiler( "alice" ), [ "held-1" ],
    "the batch reaches rows Approve is not legal on — it would post a no-op edge the store rejects as a failure" );
} );
