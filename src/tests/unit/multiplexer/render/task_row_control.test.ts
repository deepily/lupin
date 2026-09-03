// Guard — the multiplexer's Actions cell, converted to the one-select row
// control (2026.09.02). Rick ruled the shape for the notifications board and
// then ruled it again here: one select carrying all five verbs, one shared
// reason field, one Submit.
//
// THIS SURFACE IS AN ADDITION, NOT A MERGE. The notifications board had five
// verbs in five buttons and the work was folding them together. This cell had
// ONE verb — Drop, a bare input and a button — so four verbs, the legality that
// decides which of them a row may take, and the date affordance all arrive here
// for the first time. A guard written as if this were the same job would pin the
// merge and miss the addition.
//
// EVERY SWEEP STATES ITS DENOMINATOR. A loop over an empty corpus passes every
// assertion inside it; a querySelectorAll that finds nothing reads exactly like
// a control that behaved. So each sweep says how many it found and asserts that
// count against a floor measured off the tree.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderTaskRow } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskListTable";
import { TASK_VERBS, verbLegality, verbNeeds } from "../../../../lupin_app/static/js/multiplexer/render/taskVerbs";

// Denominators, measured off the tree rather than chosen:
//   VERB_FLOOR   — notifications.js `_verbNeeds` carries five verbs; this is its port.
//   OPTION_FLOOR — five verbs plus the "Choose an action…" placeholder.
before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const VERB_FLOOR   = 5;
const OPTION_FLOOR = VERB_FLOOR + 1;

const STATUS_CORPUS: ReadonlyArray<string> = [
  "queued", "in_progress", "claimed", "review", "blocked",
  "parked", "not_approved", "done", "dropped", "wont_fix",
];

function cellFor( status: string, id: string = "t1" ): HTMLElement {
  const tr = renderTaskRow( { id, title: "t", status }, undefined );
  const cell = tr.querySelector<HTMLElement>( ".task-col-actions" );
  assert.ok( cell, `every row must render an actions cell; status=${status} rendered none` );
  return cell;
}

// ---------------------------------------------------------------------------
// The three controls replace the one
// ---------------------------------------------------------------------------

test("Actions cell: one verb select, one shared reason input, one Submit", () => {
  const cell = cellFor( "queued" );
  assert.equal( cell.querySelectorAll( ".task-verb-select" ).length, 1, "exactly one verb select" );
  assert.equal( cell.querySelectorAll( ".task-reason-input" ).length, 1, "exactly one reason input" );
  assert.equal( cell.querySelectorAll( ".task-submit-button" ).length, 1, "exactly one Submit" );
  const btn = cell.querySelector<HTMLButtonElement>( ".task-submit-button" );
  assert.equal( btn?.type, "button" );
  assert.equal( btn?.textContent, "Submit", "Rick's ruling: the button reads Submit, not the verb" );
});

test("Actions cell: the single-verb Drop control is GONE from every status", () => {
  // The retired shape, swept rather than spot-checked — a leftover on one status
  // is exactly the kind of thing a single-status check walks past.
  let swept = 0;
  for ( const s of STATUS_CORPUS ) {
    const cell = cellFor( s );
    assert.equal( cell.querySelectorAll( ".task-drop-reason" ).length, 0, `${s}: retired drop input still rendered` );
    assert.equal( cell.querySelectorAll( ".task-drop-button" ).length, 0, `${s}: retired Drop button still rendered` );
    swept += 1;
  }
  assert.equal( swept, STATUS_CORPUS.length, `swept ${swept} of ${STATUS_CORPUS.length} statuses` );
  assert.ok( swept >= 10, `positive control: the corpus must not have collapsed; ${swept} statuses swept` );
});

test("Actions cell: the priority and owner selects are untouched by the conversion", () => {
  const cell = cellFor( "queued" );
  assert.equal( cell.querySelectorAll( ".task-priority-select" ).length, 1 );
  assert.equal( cell.querySelectorAll( ".task-owner-select" ).length, 1 );
});

// ---------------------------------------------------------------------------
// The select's options — the sweep with the real denominator
// ---------------------------------------------------------------------------

test("verb select: a placeholder plus all five verbs, in TASK_VERBS order", () => {
  const sel = cellFor( "queued" ).querySelector<HTMLSelectElement>( ".task-verb-select" )!;
  const opts = Array.from( sel.options );
  assert.ok( opts.length >= OPTION_FLOOR,
    `positive control: ${VERB_FLOOR} verbs + one placeholder = ${OPTION_FLOOR} options; found ${opts.length}` );
  assert.equal( opts.length, OPTION_FLOOR );
  assert.equal( opts[ 0 ]!.value, "", "the leading option is the un-chosen placeholder" );
  assert.match( opts[ 0 ]!.textContent ?? "", /choose an action/i );
  assert.deepEqual( opts.slice( 1 ).map( ( o ) => o.value ), Array.from( TASK_VERBS ) );
});

test("verb select: no verb is preselected — the operator must choose", () => {
  const sel = cellFor( "queued" ).querySelector<HTMLSelectElement>( ".task-verb-select" )!;
  assert.equal( sel.value, "", "a preselected verb turns one stray click into a transition" );
});

test("verb select: EVERY status renders all five verbs, live or greyed", () => {
  // The count is invariant across statuses on purpose: legality greys an option,
  // it never removes one. A row that silently drops an option teaches the
  // operator that the verb does not exist rather than that it is not allowed.
  let swept = 0, optionsSeen = 0;
  for ( const s of STATUS_CORPUS ) {
    const sel = cellFor( s ).querySelector<HTMLSelectElement>( ".task-verb-select" )!;
    assert.equal( sel.options.length, OPTION_FLOOR, `${s}: expected ${OPTION_FLOOR} options` );
    optionsSeen += sel.options.length;
    swept += 1;
  }
  assert.equal( swept, STATUS_CORPUS.length, `swept ${swept} of ${STATUS_CORPUS.length}` );
  assert.equal( optionsSeen, STATUS_CORPUS.length * OPTION_FLOOR,
    `positive control: ${STATUS_CORPUS.length * OPTION_FLOOR} options expected across the corpus; saw ${optionsSeen}` );
});

test("verb select: the rendered enabled/greyed split matches verbLegality exactly, on every status", () => {
  // The cell must not carry its own second opinion about legality. Two
  // derivations of one rule agree until the day they do not, and the disagreement
  // shows up as a control offering a move the server refuses.
  let pairs = 0, enabledSeen = 0, greyedSeen = 0;
  for ( const s of STATUS_CORPUS ) {
    const sel = cellFor( s ).querySelector<HTMLSelectElement>( ".task-verb-select" )!;
    for ( const entry of verbLegality( s ) ) {
      const opt = Array.from( sel.options ).find( ( o ) => o.value === entry.verb );
      assert.ok( opt, `${s}: no option rendered for ${entry.verb}` );
      assert.equal( opt!.disabled, !entry.enabled, `${s}/${entry.verb}: rendered state disagrees with verbLegality` );
      if ( entry.enabled ) enabledSeen += 1; else greyedSeen += 1;
      pairs += 1;
    }
  }
  assert.equal( pairs, STATUS_CORPUS.length * VERB_FLOOR, `${pairs} status×verb pairs checked` );
  assert.ok( enabledSeen > 0 && greyedSeen > 0,
    `both arms must fire: ${enabledSeen} enabled, ${greyedSeen} greyed — an all-one-way corpus asserts nothing` );
});

test("verb select: a greyed option says WHY, in its own label, and carries the a11y markers", () => {
  // The reason rides the option's own text because there is nowhere else for it
  // to go: a disabled <option> has no tooltip and no hover in most browsers.
  const sel = cellFor( "blocked" ).querySelector<HTMLSelectElement>( ".task-verb-select" )!;
  const park = Array.from( sel.options ).find( ( o ) => o.value === "park" )!;
  assert.ok( park.disabled );
  assert.match( park.textContent ?? "", /Park — only from queued or in progress/ );
  assert.equal( park.getAttribute( "aria-disabled" ), "true",
    "`disabled` alone tells the mouse and nobody else" );
  assert.ok( park.classList.contains( "task-action-disabled" ),
    "the class is what the stylesheet greys" );
});

test("verb select: a LIVE option carries the bare label and none of the greyed markers", () => {
  const sel = cellFor( "queued" ).querySelector<HTMLSelectElement>( ".task-verb-select" )!;
  const park = Array.from( sel.options ).find( ( o ) => o.value === "park" )!;
  assert.equal( park.disabled, false );
  assert.equal( park.textContent, "Park", "a live option must not carry an explanation" );
  assert.equal( park.getAttribute( "aria-disabled" ), null );
  assert.equal( park.classList.contains( "task-action-disabled" ), false );
});

// ---------------------------------------------------------------------------
// Terminal rows
// ---------------------------------------------------------------------------

test("terminal row: the select and Submit are themselves disabled, not merely their options", () => {
  const TERMINAL = [ "done", "dropped", "wont_fix" ];
  assert.equal( TERMINAL.length, 3, "positive control: three terminal statuses" );
  let checked = 0;
  for ( const s of TERMINAL ) {
    const cell = cellFor( s );
    const sel  = cell.querySelector<HTMLSelectElement>( ".task-verb-select" )!;
    const box  = cell.querySelector<HTMLInputElement>( ".task-reason-input" )!;
    const btn  = cell.querySelector<HTMLButtonElement>( ".task-submit-button" )!;
    assert.equal( sel.disabled, true, `${s}: select still live` );
    assert.equal( box.disabled, true, `${s}: reason box still live` );
    assert.equal( btn.disabled, true, `${s}: Submit still live` );
    assert.equal( sel.getAttribute( "aria-disabled" ), "true", `${s}: select missing aria-disabled` );
    assert.equal( Array.from( sel.options ).filter( ( o ) => !o.disabled && o.value !== "" ).length, 0,
      `${s}: a terminal row offered a live verb` );
    checked += 1;
  }
  assert.equal( checked, 3, `checked ${checked} of 3 terminal statuses` );
});

test("open row: nothing is disabled at rest", () => {
  const cell = cellFor( "queued" );
  assert.equal( cell.querySelector<HTMLSelectElement>( ".task-verb-select" )!.disabled, false );
  assert.equal( cell.querySelector<HTMLInputElement>( ".task-reason-input" )!.disabled, false );
  assert.equal( cell.querySelector<HTMLButtonElement>( ".task-submit-button" )!.disabled, false );
});

// ---------------------------------------------------------------------------
// The reason field, and what is deliberately absent
// ---------------------------------------------------------------------------

test("reason input: a text box with a generic resting placeholder the verb change replaces", () => {
  const box = cellFor( "queued" ).querySelector<HTMLInputElement>( ".task-reason-input" )!;
  assert.equal( box.type, "text" );
  assert.equal( box.getAttribute( "placeholder" ), "reason…" );
  assert.equal( box.getAttribute( "aria-label" ), "Reason" );
});

test("no date input renders until a verb asks for one", () => {
  // A date box standing beside a verb that does not want a date is the control
  // Rick could not read the purpose of. It is inserted by the verb-change
  // handler, so a row shows one only when a date is the thing being asked for.
  let swept = 0;
  for ( const s of STATUS_CORPUS ) {
    assert.equal( cellFor( s ).querySelectorAll( ".task-chase-input" ).length, 0, `${s}: a date box at rest` );
    swept += 1;
  }
  assert.equal( swept, STATUS_CORPUS.length, `swept ${swept} of ${STATUS_CORPUS.length} statuses` );
  // Positive control on the OTHER side: two verbs really do want one, so this
  // absence is a state the code chose and not a table with no dated verbs in it.
  const dated = TASK_VERBS.filter( ( v ) => verbNeeds( v )!.date );
  assert.equal( dated.length, 2, `two dated verbs must exist for this absence to mean anything; found ${dated.length}` );
});

// ---------------------------------------------------------------------------
// Row identity — every control must resolve back to its own row
// ---------------------------------------------------------------------------

test("every control carries the row's task id, and it is the row's OWN id", () => {
  const tr = renderTaskRow( { id: "abc-123", title: "t", status: "queued" }, undefined );
  const cell = tr.querySelector<HTMLElement>( ".task-col-actions" )!;
  const carriers = cell.querySelectorAll<HTMLElement>( "[data-task-id]" );
  assert.ok( carriers.length >= 3,
    `the select, the reason box and Submit must each carry the id; ${carriers.length} elements did` );
  for ( const el of Array.from( carriers ) ) {
    assert.equal( el.dataset.taskId, "abc-123", `${el.className} carries the wrong id` );
  }
  assert.equal( tr.getAttribute( "data-task-id" ), "abc-123" );
});

test("an idless row still renders the controls, carrying an empty id", () => {
  // The renderer no-ops on an empty id; the cell's job is to render something
  // shaped like every other row rather than a hole in the column.
  const tr = renderTaskRow( { title: "t", status: "queued" }, undefined );
  const cell = tr.querySelector<HTMLElement>( ".task-col-actions" )!;
  assert.equal( cell.querySelectorAll( ".task-verb-select" ).length, 1 );
  assert.equal( cell.querySelector<HTMLSelectElement>( ".task-verb-select" )!.dataset.taskId, "" );
});
