// EVERY PANE OFFERS AND ROUTES EVERY VERB — the 15-cell walk (3 panes x 5 verbs).
//
// 🔴 THE ORACLE IS THE SOURCE MODULE; THE DOM IS ONLY EVER THE OBSERVATION.
// María's ruling, 2026-09-04, and it is the whole design of this file:
//
//     ORACLE   (expected)  shared/task-verbs.js — TASK_VERB_SPECS
//     OBSERVED             what each pane actually renders and routes
//     assert               observed ⊇ oracle, PER PANE
//
// Reading the expected set off the DOM was proposed and REFUSED. A pane that stops
// rendering `approve` would stop being expected to render it, and the guard would go
// green on precisely the defect it exists to catch — the three-arm blindness rebuilt
// in a more convincing costume. So a verb added to the module below is what forces
// every pane to be asked about it; nothing here re-types the list.
//
// WHY IT IS PER PANE AND NOT PER RENDERER. All three panes share `_taskActionsCell`,
// so a shared-suite arm cannot tell you whether a given pane ROUTES the click. That
// distinction is not theoretical here: when the blank-reason guard was deleted on
// 2026-09-04, the shared suite scored four kills and the epic board scored ZERO, and
// a comfortable total hid a pane that could not see the guard at all.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/every_pane_offers_and_routes_every_verb.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { TASK_LIST_QUERY } from "../../../lupin_app/static/js/shared/task-list-query.js";
import { TASK_VERB_SPECS, TASK_VERBS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const w = window as unknown as Record<string, unknown>;
  w.LUPIN_TASK_LIST_QUERY  = TASK_LIST_QUERY;
  w.LUPIN_TASK_VERB_SPECS  = TASK_VERB_SPECS;
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const i   = src.indexOf( "// Initialize when DOM is ready" );
  assert.ok( i > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( src.slice( 0, i ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
                       { filename: NOTIFICATIONS_JS } );
} );


// ─────────────────────────── THE ORACLE, AND ITS OWN CONTROL ───────────────────────────
//
// 🔴 A LOOP OVER AN EMPTY ORACLE PASSES EVERY ASSERTION INSIDE IT. If the import ever
// yields {} — a rename, a bad path, a module that stops publishing — every per-verb
// test below would be generated ZERO times and this file would report a perfect green
// while measuring nothing. So the oracle asserts its own size before anything uses it.

// 🔴 HAND-WRITTEN, AND THAT IS THE ENTIRE POINT. Every other expectation in this file is
// DERIVED from the module, which is correct for the walk — it is how a sixth verb forces
// every pane to be asked about it. But a walk whose corpus comes from the thing under test
// cannot notice the corpus CHANGING IDENTITY: rename `park` to `hold` in the module and in
// the cell, and the walk still generates fifteen cells and still passes all fifteen.
//
// MEASURED 2026-09-04, both directions, one variable:
//     rename park   -> hold      : this file 31/31 GREEN (the store parity guard caught it,
//                                  and ONLY because park is the one verb whose legality the
//                                  store publishes)
//     rename demote -> sendback  : this file 31/31 GREEN, store parity guard 5/5 GREEN.
//                                  NOTHING here saw a verb disappear from the product.
//
// So one side of one comparison has to be something the client cannot edit. This is it.
// 🔴 DO NOT "DE-DUPLICATE" THIS INTO AN IMPORT FROM THE MODULE. The duplication IS the
// control — importing it would make both sides of the comparison move together, which is
// the exact blindness measured above.
// `fixed` added at the rebase onto dcb8daa3 — john's sixth verb. This literal going
// red is the review step this control exists for, exactly as its message says.
const VERBS_AS_OF_2026_09_04 = [ "park", "drop", "demote", "wont_fix", "fixed", "approve" ];

test( "ORACLE CONTROL: the source module's vocabulary is EXACTLY the expected membership", () => {
  assert.ok( Array.isArray( TASK_VERBS ), "TASK_VERBS is not an array — the oracle is unusable" );

  // Membership, not just size. A count alone passes a rename, which is a verb vanishing
  // from the operator's reach with the arithmetic undisturbed.
  assert.deepEqual( [ ...TASK_VERBS ].sort(), [ ...VERBS_AS_OF_2026_09_04 ].sort(),
    `the oracle's vocabulary is [${ TASK_VERBS }] and this test expects ` +
    `[${ VERBS_AS_OF_2026_09_04 }].\n` +
    `  · a verb ADDED here is the intended workflow — add it to the list above and the ` +
    `walk below will start asking every pane about it\n` +
    `  · a verb RENAMED or REMOVED is the case this assertion exists for: the walk cannot ` +
    `see it, because the walk takes its corpus from the same module` );

  for ( const verb of TASK_VERBS ) {
    const spec = TASK_VERB_SPECS[ verb as keyof typeof TASK_VERB_SPECS ];
    assert.ok( spec && typeof spec.status === "string" && spec.status,
      `verb "${ verb }" carries no target status — the oracle cannot say what it should post` );
  }
} );


// ─────────────────────────────── THE THREE PANES ───────────────────────────────
//
// Each pane is described by how it is PAINTED and how it is WIRED — never by calling
// `_taskActionsCell` directly, which is the layer the shared suite already covers and
// the layer that cannot answer "does this pane route a click".

type UI = Record<string, any>;

function newUI(): UI {
  const Ctor = ( globalThis as Record<string, any> ).NotificationsUI;
  const ui = Object.create( Ctor.prototype );
  ui.debug = false; ui.log = () => {}; ui.error = () => {};
  ui.EPIC_KEY_PREFIX = "epic:"; ui.EPIC_UNASSIGNED_KEY = "epic:unassigned";
  ui.EPIC_ON_RICK_KEY = "__on_rick__"; ui.EPIC_DRIFT_KEY = "__drift__";
  ui.EPIC_BLOCKER_OF_INTEREST = "rick";
  ui.EPIC_BOARD_STATE_KEY = "lupin.epicBoard.groupState";
  ui.TASK_TITLE_TRUNCATE_LEN = 60;
  ui.TASK_LIST_COLLAPSED_KEY = "lupin.taskList.collapsedOwners";
  ui.TASK_LIST_UNASSIGNED_KEY = "__unassigned__";
  ui._epicBoardAccordionWired = false; ui._epicStories = {}; ui._epicStoriesFetched = false;
  ui._taskListAccordionWired = false; ui._taskListFetchInFlight = false;
  ui._taskListLastGoodTasks = null;
  ui._holdingAreaControlsWired = false; ui._holdingAreaFetchInFlight = false;
  return ui;
}

// The page skeleton every pane needs. One DOM for all three, so a pane cannot pass by
// being the only thing on the page — the "ellipsis opens ITS OWN pane" defect.
function pageDOM(): void {
  document.body.replaceChildren();
  const root = document.createElement( "div" );
  root.innerHTML = `
    <div class="collapsible-section" id="section-task-list">
      <div class="section-content"><div id="task-list-container"></div></div>
    </div>
    <div class="collapsible-section" id="section-holding-area">
      <div class="section-content" id="holding-area-section">
        <div id="holding-area-container"></div>
      </div>
    </div>
    <div class="collapsible-section" id="section-epic-board">
      <h3><span id="epic-board-count">0</span><span id="epic-board-updated"></span></h3>
      <div id="epic-board-container"></div>
    </div>`;
  document.body.appendChild( root );
}

const ROW_ID = "cell-probe-1";

function row( status: string ): Record<string, unknown> {
  return { id: ROW_ID, title: "a row under the 15-cell walk", status,
           owner_persona: "maya", correlation_key: "epic:cell-walk", priority: "P2" };
}

type Pane = {
  name: string;
  // Paint one row at `status` into this pane, through the pane's REAL render path,
  // with the pane's REAL listeners installed. Returns the pane's container.
  paint: ( ui: UI, status: string ) => HTMLElement;
};

const PANES: Pane[] = [
  {
    name: "task list",
    paint: ( ui, status ) => {
      pageDOM();
      ui._taskListAccordionWired = false;
      ui._wireTaskListAccordion();
      const c = document.getElementById( "task-list-container" )!;
      c.innerHTML = ui.renderTaskListTable( ui.groupTasksByOwner( [ row( status ) ] ),
                                            undefined, ui.loadCollapsedTaskOwners() );
      return c;
    }
  },
  {
    name: "holding area",
    paint: ( ui, status ) => {
      pageDOM();
      ui._holdingAreaControlsWired = false;
      const c = document.getElementById( "holding-area-container" )!;
      c.innerHTML = ui._renderHoldingAreaGroup( "maya", [ row( status ) ] );
      ui._wireHoldingAreaControls();
      return c;
    }
  },
  {
    name: "epic board",
    paint: ( ui, status ) => {
      pageDOM();
      ui._epicBoardAccordionWired = false;
      ui._wireEpicBoardAccordion();
      const c = document.getElementById( "epic-board-container" )!;
      const model = ui.groupTasksByEpic( [ row( status ) ] );
      c.innerHTML = ui.renderEpicBoardTable( model, ui.loadEpicGroupState() );
      return c;
    }
  }
];

// The status a verb is legal FROM, derived from the oracle rather than chosen here.
function aStatusThatOffers( verb: string ): string {
  const spec = TASK_VERB_SPECS[ verb as keyof typeof TASK_VERB_SPECS ] as Record<string, any>;
  if ( spec.legalFrom && spec.legalFrom.length ) return spec.legalFrom[ 0 ];
  const illegal: string[] = spec.illegalFrom || [];
  for ( const candidate of [ "queued", "in_progress", "blocked" ] ) {
    if ( !illegal.includes( candidate ) ) return candidate;
  }
  throw new Error( `the oracle offers no legal source status for "${ verb }"` );
}

beforeEach( () => pageDOM() );


// ═══════════════ CELL 1 of 2: the pane OFFERS the verb, enabled ═══════════════

for ( const pane of PANES ) {
  for ( const verb of TASK_VERBS ) {
    test( `OFFERED — ${ pane.name } offers "${ verb }" enabled on a row it is legal from`, () => {
      const ui     = newUI();
      const status = aStatusThatOffers( verb );
      const c      = pane.paint( ui, status );

      const select = c.querySelector( ".task-verb-select" ) as HTMLSelectElement | null;
      assert.ok( select,
        `the ${ pane.name } rendered no verb select at all on a ${ status } row — every ` +
        `assertion about "${ verb }" below would be vacuous` );

      const option = select!.querySelector( `option[value="${ verb }"]` ) as HTMLOptionElement | null;
      assert.ok( option,
        `the ${ pane.name } does not offer "${ verb }" at all. The oracle says this verb exists; ` +
        `this pane has never heard of it, so an operator cannot reach it here however correct ` +
        `the handler is` );
      assert.equal( option!.disabled, false,
        `the ${ pane.name } offers "${ verb }" GREYED on a ${ status } row, which the oracle says ` +
        `it is legal from. A disabled control and an absent one look identical to an operator` );
    } );
  }
}


// ═══════════ CELL 2 of 2: the pane ROUTES a Submit for that verb ═══════════
//
// The refusal path is the one driven, because it is observable without a server and it
// proves the whole chain: the click reached a listener, the listener found THIS row's
// inputs, and the verb's own obligation was enforced. A verb needing no reason is driven
// through to the transition instead.

for ( const pane of PANES ) {
  for ( const verb of TASK_VERBS ) {
    test( `ROUTED — ${ pane.name } routes a Submit for "${ verb }" to the handler`, async () => {
      const ui     = newUI();
      const status = aStatusThatOffers( verb );
      const c      = pane.paint( ui, status );
      const spec   = TASK_VERB_SPECS[ verb as keyof typeof TASK_VERB_SPECS ] as Record<string, any>;

      const calls: unknown[] = [];
      ui._transitionTask   = async ( id: string, to: string, extras: unknown ) => {
        calls.push( [ id, to, extras ] ); return { ok: true };
      };
      ui.refreshTaskList   = async () => {};
      ui.fetchHoldingArea  = async () => {};

      const select = c.querySelector( ".task-verb-select" ) as HTMLSelectElement;
      select.value = verb;
      select.dispatchEvent( new window.Event( "change", { bubbles: true } ) );

      const button = c.querySelector( ".task-submit-button" ) as HTMLButtonElement;
      assert.ok( button, `the ${ pane.name } rendered no Submit for "${ verb }"` );

      // Prove the CLICK reaches a handler, rather than calling the handler ourselves —
      // a dead pane and a correct handler are indistinguishable without this.
      const original = ui._handleTaskSubmitClick;
      let   ran: unknown = null;
      ui._handleTaskSubmitClick = ( b: unknown ) => { ran = original.call( ui, b ); return ran; };
      button.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
      ui._handleTaskSubmitClick = original;

      assert.ok( ran !== null,
        `a Submit for "${ verb }" on the ${ pane.name } reached NO handler — this pane does not ` +
        `route its row controls, so every control on it is dead on screen` );
      await ran;

      if ( spec.reason ) {
        // A verb that requires a reason, submitted blank, must refuse locally and say so.
        assert.equal( calls.length, 0,
          `"${ verb }" reached the server from the ${ pane.name } with a BLANK reason — the ` +
          `client-side guard is the only thing between an empty reason and a changed row` );
        const stripe = c.querySelector( ".task-row-error-stripe" ) as HTMLElement | null;
        assert.ok( stripe && !stripe.hidden,
          `"${ verb }" was refused on the ${ pane.name } and the operator was told nothing — a ` +
          `control that declines in silence reads as broken` );
        assert.equal( ( stripe!.textContent || "" ).trim(), ( spec.complaint || "" ).trim(),
          `the ${ pane.name } refused "${ verb }" with someone else's complaint. One shared box ` +
          `must not mean one shared obligation` );
      } else {
        // 🔴 A NO-REASON VERB THAT ARMS TWICE IS A COMBINATION THIS WALK NEVER HAD
        // UNTIL `fixed`. Before it, no-reason meant approve (one click) and two-click
        // meant won't-fix (which needs a reason), so this branch could assume one click
        // reached the server. `fixed` is both, and the first click correctly posts
        // NOTHING — it arms. Asserting the arm before the second click is stronger than
        // the old single-click assumption, not a concession to it: a verb that armed
        // when it should not have would now be caught here rather than read as success.
        if ( spec.armsTwice ) {
          assert.equal( calls.length, 0,
            `"${ verb }" arms twice, so the FIRST click must reach no server at all — a ` +
            `terminal verb that commits on one click is a misclick away from an ` +
            `append-only row the operator cannot undo` );
          button.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
          await Promise.resolve();
        }
        // A verb needing no reason should have gone all the way through.
        assert.equal( calls.length, 1,
          `"${ verb }" needs no reason, yet nothing reached the server from the ${ pane.name }` );
        assert.deepEqual( ( calls[ 0 ] as unknown[] ).slice( 0, 2 ), [ ROW_ID, spec.status ],
          `"${ verb }" posted the wrong row or the wrong target status from the ${ pane.name }` );
      }
    } );
  }
}
