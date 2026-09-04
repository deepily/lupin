// The row mic dictates into ITS OWN pane's reason box — never another pane's.
//
// Rick asked for a small speech-to-text control beside the reason field on the third
// row of the action dropdown, across the task list, the holding area and the epic
// board. Row 35404747.
//
// 🔴 THE ONE THING THIS FILE EXISTS TO PROVE IS THE SCOPE, NOT THE MIC. A row carrying
// an epic key renders in TWO panes at once with the same `data-task-id` on both copies,
// deliberately — that duplication is the feature. So "the mic works" is not the claim
// worth guarding; "the mic filled the box the operator was looking at" is.
//
// ⚠️ MEASURED, NOT HYPOTHETICAL. 2026-09-02: Rick pressed Won't-fix on bc77cd79 and
// nothing happened. A bare `document.querySelector` returned the FIRST match — always
// the task list — so his epic-board reason was read from the other pane's empty box,
// the blank-reason guard fired, and the request never left the browser. Zero wont_fix
// events in the store; no PATCH in thirty minutes of server log.
//
// 🔴 A UNIQUE-ID GUARD WOULD ASSERT THE WRONG THING AND PASS WHILE THE BUG IS LIVE.
// The row filing suggested guarding against duplicate ids. That makes the BUTTON unique
// and leaves the LOOKUP free to pick the wrong copy — two separate problems, and only
// the second one bites. Hence the two-pane fixture below rather than an id assertion.
//
// Run: npx tsx --test src/tests/unit/notifications_js/the_row_mic_fills_its_own_panes_reason_box.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

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

type MicUI = Record<string, unknown> & {
  _taskActionsCell: ( task: Record<string, unknown> ) => string;
  _handleRowControlClick: ( target: unknown ) => boolean;
  _handleReasonSttClick: ( button: unknown ) => Promise<void>;
  _wireTaskListAccordion: () => void;
  _wireHoldingAreaControls: () => void;
  _wireEpicBoardAccordion: () => void;
};

// What the recorder was actually handed. `inputElement` is the whole point: the
// recorder writes into the ELEMENT it is given, so capturing it captures the answer to
// "which copy of this row did the click resolve to".
type Started = { contextId: string; button: unknown; inputElement: unknown };

let started: Started[] = [];
let stopped  = 0;
let recording = false;
let processing = false;

function newUI(): MicUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as MicUI;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui.queueSessionId            = "test-session";
  ui._holdingAreaControlsWired = false;
  ui._taskListAccordionWired   = false;
  ui._epicBoardAccordionWired  = false;
  // A stub that RECORDS rather than one that ignores its input. A `lambda *a, **k`
  // fake would return the same thing whichever pane was clicked, so every assertion
  // written over it would be unfalsifiable — the exact defect CLAUDE.md documents as
  // "coverage measures whether a line RAN, never whether the test could have NOTICED
  // it running wrong".
  ui.recordingManager = {
    isRecording  : (): boolean => recording,
    isProcessing : (): boolean => processing,
    stopRecording: async (): Promise<void> => { stopped += 1; },
    startRecording: async ( contextId: string, button: unknown, inputElement: unknown ): Promise<void> => {
      started.push( { contextId, button, inputElement } );
    }
  };
  return ui;
}

const ROW_ID = "bbbbbbbb-1111-2222-3333-444444444444";

function row( over: Record<string, unknown> = {} ): Record<string, unknown> {
  return {
    id: ROW_ID, title: "a row on two boards", status: "queued", item_class: "task",
    created_by: "maya b7114f78", priority: "P2", project: "lupin", ...over
  };
}

// 🔴 THE FIXTURE IS THE TEST. The SAME task id is rendered into the task list AND the
// epic board, which is what the page really does for a row carrying an epic key. A
// single-pane fixture cannot fail the way bc77cd79 failed — there is no second copy for
// a lookup to pick wrongly — so it would pass against the defect.
function twoPanesWithTheSameRow( ui: MicUI, task: Record<string, unknown> ): void {
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

  const cell = ui._taskActionsCell( task );
  const table = ( id: string ): string => `
    <table id="${id}"><tbody>
      <tr><td>${cell}</td></tr>
      <tr class="task-row-error-stripe" data-error-for="${task.id}" hidden><td></td></tr>
    </tbody></table>`;

  ( document.getElementById( "task-list-container" ) as HTMLElement ).innerHTML  = table( "task-list-table" );
  ( document.getElementById( "epic-board-container" ) as HTMLElement ).innerHTML = table( "epic-board-table" );

  ui._taskListAccordionWired   = false;
  ui._holdingAreaControlsWired = false;
  ui._epicBoardAccordionWired  = false;
  ui._wireTaskListAccordion();
  ui._wireHoldingAreaControls();
  ui._wireEpicBoardAccordion();
}

function micIn( containerId: string ): HTMLElement {
  const el = document
    .getElementById( containerId )!
    .querySelector( `.task-reason-stt[data-task-id="${ROW_ID}"]` ) as HTMLElement;
  assert.ok( el, `no mic rendered in #${containerId} — this test cannot speak to scoping` );
  return el;
}

function reasonIn( containerId: string ): HTMLElement {
  return document
    .getElementById( containerId )!
    .querySelector( `.task-reason-input[data-task-id="${ROW_ID}"]` ) as HTMLElement;
}

beforeEach( () => { started = []; stopped = 0; recording = false; processing = false; } );

// ── The positive control ────────────────────────────────────────────────────────
// Without this, every per-pane assertion below could be passing over an empty DOM.

test( "the fixture really does render the same row in two panes", () => {
  const ui = newUI();
  twoPanesWithTheSameRow( ui, row() );

  const all = document.querySelectorAll( `.task-reason-input[data-task-id="${ROW_ID}"]` );
  assert.equal( all.length, 2, "the two-pane fixture must produce TWO copies of the row's reason box" );
  assert.ok( reasonIn( "task-list-container" ) !== reasonIn( "epic-board-container" ),
             "the two copies must be distinct elements, or the discriminating test below is vacuous" );
} );

// ── The discriminating pair — one variable: which pane was clicked ──────────────

test( "clicking the EPIC BOARD mic hands the recorder the EPIC BOARD's reason box", async () => {
  const ui = newUI();
  twoPanesWithTheSameRow( ui, row() );

  const consumed = ui._handleRowControlClick( micIn( "epic-board-container" ) );
  assert.equal( consumed, true, "the dispatcher must consume a mic click" );
  await Promise.resolve();

  assert.equal( started.length, 1, "exactly one recording must start" );
  // ⚠️ `assert.ok( a === b )`, NEVER `assert.equal`. On failure node:assert
  // serialises both operands to build a diff, and a happy-dom element is deeply
  // self-referential — the process is SIGKILLed at ~12s building the message. The
  // mutation is caught either way, but the run reports `0 passed` with no named test,
  // which reads as the file failing to load rather than as the guard firing.
  assert.ok( started[ 0 ].inputElement === reasonIn( "epic-board-container" ),
             "the recorder must be handed the clicked pane's own reason box, not another pane's" );
  assert.ok( started[ 0 ].inputElement !== reasonIn( "task-list-container" ),
             "THIS is bc77cd79: dictating on the epic board must not fill the task list's box" );
} );

test( "clicking the TASK LIST mic hands the recorder the TASK LIST's reason box", async () => {
  const ui = newUI();
  twoPanesWithTheSameRow( ui, row() );

  ui._handleRowControlClick( micIn( "task-list-container" ) );
  await Promise.resolve();

  assert.equal( started.length, 1 );
  assert.ok( started[ 0 ].inputElement === reasonIn( "task-list-container" ),
             "the recorder must be handed the task list's own reason box" );
} );

// ⚠️ THE MIRROR IS NOT DECORATION. A handler that always returned the FIRST match would
// pass the task-list case on its own — the task list is the first match. Only the pair
// discriminates, and only because the two cases differ in exactly one thing.

// ── Placement, as Rick described it ────────────────────────────────────────────

test( "the mic sits immediately before the reason field it fills", () => {
  const ui = newUI();
  const html = ui._taskActionsCell( row() );

  const mic    = html.indexOf( "task-reason-stt" );
  const reason = html.indexOf( "task-reason-input" );
  const submit = html.indexOf( "task-submit-button" );

  assert.ok( mic > 0, "the cell must render a mic" );
  assert.ok( mic < reason, "the mic must come BEFORE the reason field" );
  assert.ok( reason < submit, "the reason field must still come before Submit" );

  const host = document.createElement( "div" );
  host.innerHTML = html;
  const micEl = host.querySelector( ".task-reason-stt" )!;
  assert.ok( micEl.nextElementSibling?.classList.contains( "task-reason-input" ),
             "the mic must be the reason field's immediate previous sibling — adjacent, not merely earlier" );
} );

test( "the mic carries the shared stt-button class so it inherits the recording states", () => {
  const ui = newUI();
  const host = document.createElement( "div" );
  host.innerHTML = ui._taskActionsCell( row() );
  const mic = host.querySelector( ".task-reason-stt" )!;
  // `.recording` and `.processing` are painted on `.stt-button` and nowhere else, so a
  // mic that drops the shared class looks fine at rest and goes dead mid-recording.
  assert.ok( mic.classList.contains( "stt-button" ),
             "the row mic must keep the shared .stt-button class" );
} );

// ── Toggle and refusal ─────────────────────────────────────────────────────────

test( "a click while already recording STOPS instead of starting a second recording", async () => {
  const ui = newUI();
  twoPanesWithTheSameRow( ui, row() );
  recording = true;

  ui._handleRowControlClick( micIn( "task-list-container" ) );
  await Promise.resolve();

  assert.equal( stopped, 1, "the second click must stop the recording" );
  assert.equal( started.length, 0, "and must not start another one" );
} );

test( "a click while transcribing is ignored rather than queued", async () => {
  const ui = newUI();
  twoPanesWithTheSameRow( ui, row() );
  processing = true;

  ui._handleRowControlClick( micIn( "task-list-container" ) );
  await Promise.resolve();

  assert.equal( started.length, 0 );
  assert.equal( stopped, 0 );
} );

test( "a terminal row's mic is disabled along with the rest of the cell", () => {
  const ui = newUI();
  const host = document.createElement( "div" );
  host.innerHTML = ui._taskActionsCell( row( { status: "done" } ) );
  const mic = host.querySelector( ".task-reason-stt" ) as HTMLButtonElement;
  assert.equal( mic.disabled, true,
                "a done row takes no transitions, so there is no reason to dictate into" );
} );

test( "a mic with no reason box beside it refuses in words instead of recording", async () => {
  const ui = newUI();
  twoPanesWithTheSameRow( ui, row() );

  let complaint = "";
  ui._renderTaskRowError = ( _id: string, message: string ): void => { complaint = message; };

  const mic = micIn( "task-list-container" );
  reasonIn( "task-list-container" ).remove();

  await ui._handleReasonSttClick( mic );

  assert.equal( started.length, 0, "nothing may be recorded into a box that is not there" );
  assert.match( complaint, /reason box/i, "the operator must be told, in their own pane" );
} );
