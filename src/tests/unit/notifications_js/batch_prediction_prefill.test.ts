// Option D (row bd0ce120) — open_ended_batch prefill from a high-confidence
// prediction. Verifies the server-stamped auto-submit gate (`_batchPredictedAnswers`)
// and that `renderOpenEndedBatchUI` fills each input from the PREDICTION when the
// gate opens, and from the expeditor's weaker `default_value` when it does not.
//
// Same constructor-bypass pattern as session_reaped_handler.test.ts: slice OFF the
// bottom-of-file init block, load the class into a vm context, build an instance via
// Object.create() so the heavy constructor never runs.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/batch_prediction_prefill.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  const classOnly  = fullSource.slice( 0, initIdx );
  vm.runInThisContext( classOnly + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal( typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function", "NotificationsUI loaded" );
} );

type UI = Record<string, unknown> & {
  _batchPredictedAnswers: ( n: unknown ) => Record<string, unknown> | null;
  renderOpenEndedBatchUI: ( n: unknown ) => string;
};

function makeUI(): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as UI;
  ui.debug = false;
  ui.log   = (): void => {};
  return ui;
}

// A batch notification with two questions whose expeditor defaults are the WEAK
// values (query default = the vague sentence). The prediction holds the RIGHT ones.
function batchNotification( hint: unknown ): unknown {
  return {
    id            : "n1",
    response_type : "open_ended_batch",
    message       : "I need a few details",
    response_options : { questions: [
      { header: "query",  question: "What topic?", default_value: "make me a podcast" },
      { header: "budget", question: "Budget?",     default_value: "" },
    ] },
    prediction_hint : hint,
  };
}

const OPEN_HINT = {
  auto_submit_enabled                  : true,
  auto_submit_min_confidence_threshold : 0.9,
  confidence                           : 1.0,
  predicted_value : { answers: { query: "the KISS explainer in docs/explainer", budget: "no limit" } },
};

// ---- _batchPredictedAnswers gate ----

test( "gate OPENS and returns the predicted answers when all conditions hold", () => {
  const ui = makeUI();
  const answers = ui._batchPredictedAnswers( batchNotification( OPEN_HINT ) );
  assert.deepEqual( answers, { query: "the KISS explainer in docs/explainer", budget: "no limit" } );
} );

test( "gate CLOSED — wrong response_type", () => {
  const ui = makeUI();
  const n  = batchNotification( OPEN_HINT ) as Record<string, unknown>;
  n.response_type = "open_ended";
  assert.equal( ui._batchPredictedAnswers( n ), null );
} );

test( "gate CLOSED — no prediction hint (cold start)", () => {
  const ui = makeUI();
  assert.equal( ui._batchPredictedAnswers( batchNotification( null ) ), null );
} );

test( "gate CLOSED — auto_submit disabled by config", () => {
  const ui = makeUI();
  const hint = { ...OPEN_HINT, auto_submit_enabled: false };
  assert.equal( ui._batchPredictedAnswers( batchNotification( hint ) ), null );
} );

test( "gate CLOSED — confidence below the floor", () => {
  const ui = makeUI();
  const hint = { ...OPEN_HINT, confidence: 0.89 };
  assert.equal( ui._batchPredictedAnswers( batchNotification( hint ) ), null );
} );

test( "gate OPENS at exactly the floor (>= is inclusive)", () => {
  const ui = makeUI();
  const hint = { ...OPEN_HINT, confidence: 0.9 };
  assert.ok( ui._batchPredictedAnswers( batchNotification( hint ) ) );
} );

test( "gate CLOSED — floor not stamped as a number", () => {
  const ui = makeUI();
  const hint = { ...OPEN_HINT, auto_submit_min_confidence_threshold: undefined };
  assert.equal( ui._batchPredictedAnswers( batchNotification( hint ) ), null );
} );

test( "gate CLOSED — hint carries no answers map", () => {
  const ui = makeUI();
  const hint = { ...OPEN_HINT, predicted_value: { value: "yes" } };
  assert.equal( ui._batchPredictedAnswers( batchNotification( hint ) ), null );
} );

test( "gate CLOSED — null notification", () => {
  const ui = makeUI();
  assert.equal( ui._batchPredictedAnswers( null ), null );
} );

// ---- renderOpenEndedBatchUI prefill ----

test( "render fills each input from the PREDICTION when the gate opens", () => {
  const ui   = makeUI();
  const html = ui.renderOpenEndedBatchUI( batchNotification( OPEN_HINT ) );
  assert.ok( html.includes( 'value="the KISS explainer in docs/explainer"' ),
    "query input must be prefilled from the prediction, not the vague default" );
  assert.ok( html.includes( 'value="no limit"' ), "budget input must be prefilled from the prediction" );
  assert.ok( !html.includes( 'value="make me a podcast"' ),
    "the weak expeditor default must be overridden by the prediction" );
} );

test( "render falls back to the expeditor default_value when the gate is closed", () => {
  const ui   = makeUI();
  const html = ui.renderOpenEndedBatchUI( batchNotification( null ) );
  assert.ok( html.includes( 'value="make me a podcast"' ),
    "with no prediction, the legacy default_value must stand" );
} );

// ---- regression guard: the prediction PREFILLS, it must NEVER auto-submit ----
// Row a89026bd: the standing risk is a client proxy answering Rick's gate before
// he sees it. The gate opening (even at confidence 1.0) is allowed to prefill the
// inputs — it must NOT call submitResponse. That call is the human's, made by
// clicking "Submit All ✓". This pins the boundary so a future change cannot wire
// the confidence gate into an auto-answer without turning this test red.

test( "gate OPEN at confidence 1.0 PREFILLS but NEVER calls submitResponse (a89026bd)", () => {
  const ui = makeUI();
  let submitCalls = 0;
  ( ui as Record<string, unknown> ).submitResponse = (): void => { submitCalls += 1; };

  // The full render path a card takes when the gate is wide open.
  const answers = ui._batchPredictedAnswers( batchNotification( OPEN_HINT ) );
  const html    = ui.renderOpenEndedBatchUI( batchNotification( OPEN_HINT ) );

  assert.deepEqual( answers, { query: "the KISS explainer in docs/explainer", budget: "no limit" },
    "control: the gate really did open at confidence 1.0 (else this proves nothing)" );
  assert.equal( submitCalls, 0,
    "prediction must NOT auto-answer the gate — no submitResponse during gate/render" );
  assert.ok( html.includes( 'class="response-submit-button batch-submit-all"' ),
    "the human's Submit-All button must still be present and unpressed — Rick's gate is intact" );
} );

// ---- row 922b2db9: refuse a non-scalar answer at the gate, never coerce ----
// A non-scalar predicted answer (object / array / null) must NOT prefill or arm
// auto-submit. String()-coercing it would launder "[object Object]" into a
// >=floor-confidence answer. The gate refuses the whole map; the expeditor
// default stands and the user is asked.

function nonScalarHint( badValue: unknown ): unknown {
  return { ...OPEN_HINT, predicted_value: { answers: { query: badValue, budget: "no limit" } } };
}

test( "gate CLOSED — an object-valued answer is refused (922b2db9)", () => {
  const ui = makeUI();
  assert.equal( ui._batchPredictedAnswers( batchNotification( nonScalarHint( { x: 1 } ) ) ), null );
} );

test( "gate CLOSED — an array-valued answer is refused (922b2db9)", () => {
  const ui = makeUI();
  assert.equal( ui._batchPredictedAnswers( batchNotification( nonScalarHint( [ 1, 2 ] ) ) ), null );
} );

test( "gate CLOSED — a null-valued answer is refused (922b2db9)", () => {
  const ui = makeUI();
  assert.equal( ui._batchPredictedAnswers( batchNotification( nonScalarHint( null ) ) ), null );
} );

test( "gate OPENS — number and boolean answers are scalars, kept (922b2db9)", () => {
  const ui = makeUI();
  const hint = { ...OPEN_HINT, predicted_value: { answers: { query: 42, budget: true } } };
  assert.deepEqual( ui._batchPredictedAnswers( batchNotification( hint ) ), { query: 42, budget: true } );
} );

test( "render falls back to default_value and never prints [object Object] on a non-scalar (922b2db9)", () => {
  const ui   = makeUI();
  const html = ui.renderOpenEndedBatchUI( batchNotification( nonScalarHint( { x: 1 } ) ) );
  assert.ok( !html.includes( "[object Object]" ),
    "a non-scalar prediction must never render as [object Object]" );
  assert.ok( html.includes( 'value="make me a podcast"' ),
    "the gate refused, so the expeditor default_value must stand" );
} );
