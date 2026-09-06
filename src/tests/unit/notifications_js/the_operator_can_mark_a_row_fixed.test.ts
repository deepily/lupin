// THE VERB RICK COULD NOT REACH — "Fixed", the missing opposite of "Won't fix".
//
// Rick, 2026-09-04, by voice (row 1e12cc08): "when it's in the holding pane or when
// it's in the epic area I can mark something as won't fix. I think the asymmetry
// should very simply be: I see something's fixed, I'm going to mark it as fixed. I'm
// not waiting around for you guys to do proper task list hygiene."
//
// 🔴 WHY A CONTROL-EXISTS TEST IS NOT ENOUGH, and it is this repo's own receipt: on
// 2026-09-02 the Won't-fix control was PRESENT, CORRECT and DEAD — a bare
// `document.querySelector` read the FIRST match, so Rick's epic-board click sent the
// task list's empty box. Zero events, no PATCH, the request never left the browser,
// and every rendering test stayed green. So these arms drive REAL bubbling clicks
// through the delegated listeners and read the REQUEST BODY at `authedFetch`.
//
// ⚠️ AND `->done` IS THE ONE VERB WHERE "IT REACHED THE SERVER" IS NOT THE WHOLE
// CLAIM. `validate_transition` refuses a close carrying no receipt that can carry it,
// so a Fixed button that posts a bare `to_status: "done"` renders as a control that
// does nothing — reaching the server and being refused looks, from where Rick sits,
// exactly like the dead button above. The receipt arm is therefore the load-bearing
// one here, not a detail.
//
// WHAT THIS FILE DOES NOT COVER, said plainly: the SERVER's enforcement. Nothing in
// the browser is the control — an agent posting this exact body is refused 403 on
// `account_email`, and that is guarded in
// `src/tests/unit/test_only_a_logged_in_operator_can_mint_an_attestation.py`.
//
// Run: npx tsx --test src/tests/unit/notifications_js/the_operator_can_mark_a_row_fixed.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

// The page loads shared/task-verbs.js as a MODULE before notifications.js, and the
// harness has to do the same. Added at the rebase onto dcb8daa3: this file was
// written against the inline verb TABLE that used to live in notifications.js, so it
// needed no setup. That table is now one shared vocabulary and `_verbNeeds` reads it
// from `window`, so without this line every lookup returns null and `fixed` is a live
// <option> whose Submit answers "Choose an action first" — the verb reads as dead.
import { TASK_VERB_SPECS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  ( window as unknown as Record<string, unknown> ).LUPIN_TASK_VERB_SPECS = TASK_VERB_SPECS;
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
  _wireTaskListAccordion: () => void;
  _wireHoldingAreaControls: () => void;
  _wireEpicBoardAccordion: () => void;
  refreshTaskList: () => Promise<void>;
  authedFetch: ( url: string, init: Record<string, unknown> ) => Promise<unknown>;
};

const ROW_ID = "aaaaaaaa-1111-2222-3333-444444444444";

interface Seen { url: string; body: Record<string, unknown>; }

function newUI( seen: Seen[] ): RowUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as RowUI;
  ui.debug                     = false;
  ui.log                       = (): void => {};
  ui.error                     = (): void => {};
  ui._taskListFetchInFlight    = false;
  ui._holdingAreaFetchInFlight = false;
  ui._taskListLastGoodTasks    = null;
  ui.TASK_TITLE_TRUNCATE_LEN   = 60;
  ui.queueSessionId            = "wise-penguin";
  ui._holdingAreaControlsWired = false;
  ui._taskListAccordionWired   = false;
  // The pane repaints on success; nothing here is about the repaint.
  ui.refreshTaskList = async (): Promise<void> => {};
  ui.authedFetch = async ( url: string, init: Record<string, unknown> ) => {
    seen.push( { url, body: JSON.parse( String( init.body ) ) } );
    return { ok: true, status: 200 };
  };
  return ui;
}

function row( over: Record<string, unknown> = {} ): Record<string, unknown> {
  return {
    id: ROW_ID, title: "a row an operator can see is fixed", status: "in_progress",
    item_class: "bug", created_by: "maria 21979045", priority: "P1", project: "lupin", ...over
  };
}

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

// 🔴 FILLING AND WIRING ARE SEPARATE, AND THE FIRST CUT OF THIS FILE CONFLATED THEM.
// A combined helper re-wires every pane on each call, so a two-pane test attaches TWO
// delegated listeners to each container and one click posts TWICE. That is a FIXTURE
// defect and it wore the costume of the defect under test: the scoping arm below failed
// with a message about pane scoping while the product code was correct.
//
// ⚠️ The tell was the DIRECTION. An unscoped read finds the other pane's empty select
// and sends NOTHING — 0 requests. Double-wiring sends 2. The number said fixture, not
// product, and a reader who only saw red would have gone looking in the wrong file.
//
// The page itself wires each container ONCE and remembers it, because the container
// outlives every repaint and only its innerHTML is replaced. Wiring once here is the
// faithful model, not a convenience.
function fillPane( ui: RowUI, task: Record<string, unknown>, paneId = "task-list-container" ): HTMLElement {
  const host = document.getElementById( paneId ) as HTMLElement;
  host.innerHTML = `
    <table><tbody>
      <tr><td>${ui._taskActionsCell( task )}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${task.id}" hidden><td></td></tr>
    </tbody></table>`;
  return host;
}

function wireOnce( ui: RowUI ): void {
  ui._taskListAccordionWired   = false;
  ui._holdingAreaControlsWired = false;
  ui._epicBoardAccordionWired  = false;
  ui._wireTaskListAccordion();
  ui._wireHoldingAreaControls();
  ui._wireEpicBoardAccordion();
}

function paneWithCell( ui: RowUI, task: Record<string, unknown>, paneId = "task-list-container" ): HTMLElement {
  const host = fillPane( ui, task, paneId );
  wireOnce( ui );
  return host;
}

async function clickThrough( ui: RowUI, el: Element | null, what: string ): Promise<void> {
  assert.ok( el, `${what} did not render at all — this test cannot speak to wiring` );
  const target   = ui as unknown as Record<string, ( b: unknown ) => unknown >;
  const original = target._handleTaskSubmitClick;
  let   ran: unknown = null;
  target._handleTaskSubmitClick = ( b: unknown ) => { ran = original.call( ui, b ); return ran; };
  el!.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
  target._handleTaskSubmitClick = original;
  assert.ok( ran !== null,
    `${what} reached NO handler — the control is dead on screen however correct the handler is` );
  await ran;
}

function chooseFixed( host: HTMLElement ): void {
  const sel = host.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  assert.ok( sel, "the row renders no verb select at all" );
  sel.value = "fixed";
  assert.equal( sel.value, "fixed",
    "the select REFUSED the value 'fixed' — the option is not in the list, so every arm below would be vacuous" );
  sel.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
}

function submitButton( host: HTMLElement ): HTMLButtonElement {
  return host.querySelector( ".task-submit-button" ) as HTMLButtonElement;
}

beforeEach( () => realPageDOM() );


// ════════════════════════ the control is on screen ════════════════════════

test( "an open row offers Fixed, enabled, beside Won't fix", () => {
  const seen: Seen[] = [];
  const host = paneWithCell( newUI( seen ), row() );
  const opts = Array.from( ( host.querySelector( ".task-verb-select" ) as HTMLSelectElement ).options );

  const fixed = opts.find( o => o.value === "fixed" );
  assert.ok( fixed, "there is no Fixed option — the asymmetry Rick named is still here" );
  assert.equal( fixed!.disabled, false, "Fixed renders disabled on an open row" );
  assert.equal( fixed!.textContent, "Fixed" );

  // The positive control: Won't fix is its live sibling, so a cell that greyed
  // EVERYTHING would not satisfy the arm above by accident.
  const wontFix = opts.find( o => o.value === "wont_fix" );
  assert.equal( wontFix!.disabled, false, "Won't fix is disabled too — this row is not the open row it claims to be" );
} );

test( "a terminal row offers Fixed disabled, and says why", () => {
  const seen: Seen[] = [];
  const host = paneWithCell( newUI( seen ), row( { status: "done" } ) );
  const fixed = Array.from( ( host.querySelector( ".task-verb-select" ) as HTMLSelectElement ).options )
    .find( o => o.value === "fixed" )!;

  assert.equal( fixed.disabled, true, "a done row still offers Fixed — done is append-only" );
  assert.match( fixed.textContent!, /terminal rows are append-only/ );
} );


// ═══════════════════ it reaches the server, and with a receipt ═══════════════════

test( "Fixed takes two clicks, and the arm names FIXED rather than won't-fix", async () => {
  const seen: Seen[] = [];
  const ui   = newUI( seen );
  const host = paneWithCell( ui, row() );
  chooseFixed( host );

  await clickThrough( ui, submitButton( host ), "the first Submit click" );

  assert.equal( seen.length, 0, "Fixed posted on the FIRST click — a terminal verb must arm first" );
  assert.equal( submitButton( host ).textContent, "Confirm fixed",
    "the armed button names the wrong verb; an operator reading 'Confirm won't-fix' after choosing Fixed is being told the control misheard them" );
} );

test( "the second click posts ->done CARRYING AN OPERATOR ATTESTATION", async () => {
  const seen: Seen[] = [];
  const ui   = newUI( seen );
  const host = paneWithCell( ui, row() );
  chooseFixed( host );

  await clickThrough( ui, submitButton( host ), "the first Submit click" );
  await clickThrough( ui, submitButton( host ), "the confirming Submit click" );

  assert.equal( seen.length, 1, "the confirmed Fixed click never reached the server" );
  assert.equal( seen[ 0 ].url, `/api/tasks/${ROW_ID}/transition` );
  assert.equal( seen[ 0 ].body.to_status, "done" );

  // 🔴 THE ARM THIS FILE EXISTS FOR. Without a receipt the server refuses the close,
  // and a refused close is indistinguishable on screen from a dead button.
  const receipts = seen[ 0 ].body.receipt_refs as Record<string, unknown> | undefined;
  assert.ok( receipts, "the Fixed request carries NO receipt_refs — the server will refuse this close and the button will look dead" );
  assert.ok( receipts!.operator_attestation,
    `receipt_refs carries no operator_attestation: ${JSON.stringify( receipts )}` );
} );

test( "Fixed asks for no reason — a blank box does not stop it", async () => {
  const seen: Seen[] = [];
  const ui   = newUI( seen );
  const host = paneWithCell( ui, row() );
  chooseFixed( host );

  const box = host.querySelector( ".task-reason-input" ) as HTMLInputElement;
  assert.equal( box.value, "", "the fixture pre-filled the reason box — this arm cannot speak to a blank one" );

  await clickThrough( ui, submitButton( host ), "the first Submit click" );
  await clickThrough( ui, submitButton( host ), "the confirming Submit click" );

  assert.equal( seen.length, 1,
    "a blank reason blocked Fixed. Rick ruled his click IS the receipt; option (b) — make him type something — was put to him and rejected as friction" );
} );


// ═════════════════════════ negative controls ═════════════════════════

test( "Won't-fix is UNCHANGED by the new verb, arm label included", async () => {
  const seen: Seen[] = [];
  const ui   = newUI( seen );
  const host = paneWithCell( ui, row() );
  const sel  = host.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  sel.value  = "wont_fix";
  sel.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "nobody is going to do this";

  await clickThrough( ui, submitButton( host ), "the first Submit click" );
  assert.equal( submitButton( host ).textContent, "Confirm won't-fix" );

  await clickThrough( ui, submitButton( host ), "the confirming Submit click" );
  assert.equal( seen.length, 1 );
  assert.equal( seen[ 0 ].body.to_status, "wont_fix" );
  assert.equal( seen[ 0 ].body.reason, "nobody is going to do this" );
  assert.equal( seen[ 0 ].body.receipt_refs, undefined,
    "won't-fix now carries an attestation — the receipt was attached to every verb rather than to Fixed" );
} );

test( "a NON-terminal verb still posts on ONE click and carries no attestation", async () => {
  const seen: Seen[] = [];
  const ui   = newUI( seen );
  const host = paneWithCell( ui, row() );
  const sel  = host.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  sel.value  = "drop";
  sel.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
  ( host.querySelector( ".task-reason-input" ) as HTMLInputElement ).value = "not worth doing";

  await clickThrough( ui, submitButton( host ), "the Submit click" );

  assert.equal( seen.length, 1, "Drop stopped posting on the first click — the arming leaked onto a non-terminal verb" );
  assert.equal( seen[ 0 ].body.to_status, "dropped" );
  assert.equal( seen[ 0 ].body.receipt_refs, undefined );
} );


// ══════════ the pane-scoping incident, re-run against the new verb ══════════

test( "Fixed clicked on the SECOND pane posts for that pane's row", async () => {
  // The bc77cd79 shape, 2026-09-02: a row renders DELIBERATELY in two panes, and a
  // bare `document.querySelector` reads the first match — always the task list. Rick's
  // epic-board click sent the other pane's state and the request never left the
  // browser. A new verb inherits that hazard unless it reads from the clicked pane.
  const seen: Seen[] = [];
  const ui = newUI( seen );
  // BOTH panes filled, THEN wired once — see the note on `fillPane`.
  fillPane( ui, row(), "task-list-container" );
  const epic = fillPane( ui, row(), "epic-board-container" );
  wireOnce( ui );

  assert.equal( document.querySelectorAll( ".task-verb-select" ).length, 2,
    "the row did not render in two panes — this arm cannot see the defect it exists for" );

  // ONLY the epic-board copy is set to Fixed. The task-list copy is left untouched, so
  // an unscoped read finds "" and the submit refuses with "Choose an action first".
  chooseFixed( epic );

  await clickThrough( ui, submitButton( epic ), "the first Submit click in the epic pane" );
  await clickThrough( ui, submitButton( epic ), "the confirming click in the epic pane" );

  assert.equal( seen.length, 1,
    "the epic-board Fixed click sent nothing — the verb was read from the OTHER pane's select, which is the 2026-09-02 defect exactly" );
  assert.equal( seen[ 0 ].body.to_status, "done" );
} );
