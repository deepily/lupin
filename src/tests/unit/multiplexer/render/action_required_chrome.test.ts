// Parity A-2 #2m (row 2ebf322f) — the chrome around an Action Required card's prompt.
//
// Legacy: `renderActionRequiredNotification`'s card build (notifications.js),
// plus buildPredictionHintSection (:23581-23656).
//   - [PROJECT] badge from sender_id via getProjectFromSenderId (:23299-23303), and
//     legacy suppresses it when the parse yields "UNKNOWN" (:23301)
//   - persona badge off the envelope, first child of .action-required-timer-controls (:23310)
//   - 📋 abstract indicator, gated on a non-blank abstract (:23315)
//   - the inline .action-required-abstract block, markdown-rendered (:23293-23295)
//   - the prediction hint: a cold ghost box with no hint (:23583-23589), else the
//     predicted value + strategy, yes_no title-cased (:23597-23600)
//
// Guard: every case below reads a behaviour legacy has and the multiplexer lacked at
// efea9dc8 — `action-required-abstract` and `mc-project-badge` both measured 0 across
// the whole multiplexer at HEAD bf9b78c0 while legacy carried 2 of each.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/action_required_chrome.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  projectBadge,
  personaBadge,
  abstractIndicator,
  abstractBlock,
  predictionHintBox,
  contextForecastLine,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredChrome";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createPredictionVoteStore } from "../../../../lupin_app/static/js/multiplexer/stores/PredictionVoteStore";
import type { VoicePersona } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

// `renderMarkdown` reads window.marked + window.DOMPurify, which production loads as
// vendor bundles and which are NOT installed in this test environment — every
// multiplexer markdown test shims them (markdown.test.ts:28-42). So the sanitiser
// itself is NOT under test here and no assertion below claims it is: a shim that
// stripped a <script> would be asserting the shim, not DOMPurify. What IS asserted is
// the seam — that the abstract goes THROUGH the sanitiser rather than into innerHTML.
// `sanitizeCalls` records every payload handed to sanitize so that claim is checkable.
const sanitizeCalls: string[] = [];

beforeEach( () => {
  const w = globalThis as unknown as {
    marked   ?: { parse: ( s: string, opts?: unknown ) => string };
    DOMPurify?: { sanitize: ( s: string, cfg?: unknown ) => string };
  };
  sanitizeCalls.length = 0;
  w.marked    = { parse: ( s ) => `<p>${ s.replace( /\*\*([^*]+)\*\*/g, "<strong>$1</strong>" ) }</p>` };
  w.DOMPurify = { sanitize: ( s ) => { sanitizeCalls.push( s ); return s; } };
} );

// A null-check that stays SCOREABLE when it fails. `assert.equal( <element>, null )`
// builds a diff of the two values, and in this file's context that SIGKILLs the test
// runner instead of reporting — measured 2026-09-19, two arms: the element form dies,
// the boolean form below reports the same failure cleanly. A mutation arm that reddens
// an un-scoreable assertion scores nothing, which is exactly how one arm was lost.
function assertAbsent( value: unknown, message: string ): void {
  assert.equal( value === null, true, message );
}

const persona: VoicePersona = {
  name: "Maya", voice_id: "v1", icon: "🌻", color: "#8E24AA", borrowed: false,
};

// --- the [PROJECT] badge -----------------------------------------------------

test( "the project badge carries the upper-cased project in legacy's brackets", () => {
  const el = projectBadge( "claude.code@lupin.deepily.ai#a74c8168" );
  assert.equal( el!.className, "mc-project-badge" );
  assert.equal( el!.textContent, "[LUPIN]" );
} );

test( "a sender id that does not parse is suppressed, as legacy suppresses UNKNOWN", () => {
  assertAbsent( projectBadge( "someone@example.com" ), "an unparseable sender id builds no badge" );
} );

test( "an absent sender_id builds no badge at all", () => {
  assertAbsent( projectBadge( undefined ), "an absent sender id builds no badge" );
} );

// --- the persona badge -------------------------------------------------------

test( "the persona badge carries the icon and name in separate spans", () => {
  const el = personaBadge( persona )!;
  assert.equal( el.querySelector( ".persona-badge-icon" )!.textContent, "🌻" );
  assert.equal( el.querySelector( ".persona-badge-name" )!.textContent, "Maya" );
} );

test( "a borrowed persona is marked, matching senderCard's borrowed class", () => {
  assert.equal( personaBadge( { ...persona, borrowed: true } )!.className, "persona-badge borrowed" );
  assert.equal( personaBadge( persona )!.className, "persona-badge" );
} );

test( "an absent persona builds no badge", () => {
  assertAbsent( personaBadge( undefined ), "an absent persona builds no badge" );
} );

// 🔴 NULL, NOT undefined — this is the case that shipped broken, and the case above could
// never have caught it. The server spells "no persona" as JSON `null`
// (notification_fifo_queue.py sends `self.voice_persona`, None when the sender-id suffix has
// no session-bridge entry). The old guard tested `persona === undefined`, so `null` sailed
// through it and `persona.borrowed` threw. EventBus swallowed the throw into a
// `listener_error`, killing ActionRequiredRenderer.reconcile() AFTER the header count was
// written and BEFORE any paint — the operator saw "⚠️ Action Required 1" over an empty
// panel. Measured 2026-09-22 on :7999; it reddened three ask/audio E2E tests.
//
// Keep BOTH cases. `undefined` alone passed the whole time the defect was live, which is
// the point: a test that cannot fail on the broken input is not a guard.
test( "a NULL persona builds no badge either — the absence the server actually sends", () => {
  assertAbsent( personaBadge( null ), "a null persona builds no badge" );
} );

// --- the 📋 indicator --------------------------------------------------------

test( "the indicator carries the abstract on data-abstract, the attribute ReadingPaneRenderer reads", () => {
  const el = abstractIndicator( "the full text" )!;
  assert.equal( el.className, "abstract-indicator" );
  assert.equal( el.getAttribute( "data-abstract" ), "the full text" );
  assert.equal( el.textContent, "📋" );
} );

test( "a blank or absent abstract gets no indicator, as legacy's trim gate does", () => {
  assertAbsent( abstractIndicator( "   " ), "a blank abstract gets no indicator" );
  assertAbsent( abstractIndicator( "" ), "an empty abstract gets no indicator" );
  assertAbsent( abstractIndicator( undefined ), "an absent abstract gets no indicator" );
} );

// --- the inline abstract block ----------------------------------------------

test( "the abstract block renders markdown under legacy's class name", () => {
  const el = abstractBlock( "**bold** text" )!;
  assert.equal( el.className, "action-required-abstract" );
  assert.equal( el.querySelector( "strong" )!.textContent, "bold" );
} );

test( "the abstract goes through the sanitiser seam, not into innerHTML", () => {
  // The guard: replace abstractBlock's `renderMarkdown` call with a raw innerHTML
  // assignment and sanitize is never reached, so this reddens. It does NOT assert
  // that DOMPurify is correct — that is the vendor's test, and the real bundle is
  // not installed here (see the beforeEach note).
  abstractBlock( "before <script>alert(1)</script> after" );
  assert.equal( sanitizeCalls.length, 1, "sanitize ran exactly once for the abstract" );
  assert.ok( sanitizeCalls[ 0 ]!.includes( "<script>alert(1)</script>" ),
    "the raw abstract reached the sanitiser — if this fails the text bypassed it" );
} );

test( "it is the sanitiser's OUTPUT that lands in the DOM, not the input it was handed", () => {
  // Calling sanitize and then rendering the unsanitised text would satisfy the test
  // above — one call, right payload, wrong element content. So this arm makes the
  // shim REWRITE its input: only code that uses the return value can show the marker.
  const w = globalThis as unknown as { DOMPurify?: { sanitize: ( s: string ) => string } };
  w.DOMPurify = { sanitize: () => "<em>SANITISER-OUTPUT</em>" };
  const el = abstractBlock( "whatever the author typed" )!;
  assert.equal( el.textContent, "SANITISER-OUTPUT",
    "the block rendered what sanitize RETURNED — if this reads the author's text, the return value was discarded" );
  assert.equal( el.querySelector( "em" )!.tagName, "EM", "and it was parsed as markup, not escaped text" );
} );

test( "a blank or absent abstract builds no block", () => {
  assertAbsent( abstractBlock( "  " ), "a blank abstract builds no block" );
  assertAbsent( abstractBlock( undefined ), "an absent abstract builds no block" );
} );

// --- the prediction hint -----------------------------------------------------

test( "no hint draws legacy's cold-start ghost box", () => {
  const el = predictionHintBox( { id_hash: "a1", response_type: "yes_no" }, undefined );
  assert.equal( el.className, "prediction-hint prediction-hint-cold" );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "Learning, no prediction yet" );
} );

test( "a yes_no prediction is title-cased, as legacy title-cases it", () => {
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c" } },
    undefined,
  );
  assert.equal( el.className, "prediction-hint" );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "Yes" );
} );

test( "a non-yes_no prediction prints as-is, untouched by the title-case", () => {
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "open_ended", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "ship it", category: "c" } },
    undefined,
  );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "ship it" );
} );

test( "a non-string prediction is JSON-rendered rather than printed as [object Object]", () => {
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "open_ended_batch", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: { answers: { q: "a" } }, category: "c" } },
    undefined,
  );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, '{"answers":{"q":"a"}}' );
} );

test( "a yes_no prediction that is not a string falls through the title-case", () => {
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: 42, category: "c" } },
    undefined,
  );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "42" );
} );

test( "an empty-string yes_no prediction does not title-case an empty string", () => {
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "", category: "c" } },
    undefined,
  );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "" );
} );

test( "an undefined prediction value renders empty, never the string \"undefined\"", () => {
  // JSON.stringify(undefined) is undefined, not a string — the `?? ""` arm.
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "open_ended", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: undefined, category: "c" } },
    undefined,
  );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "" );
} );

test( "the strategy line is drawn when the server sent one, and omitted when it did not", () => {
  const withStrategy = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c", strategy: "recent-history" } },
    undefined,
  );
  assert.equal( withStrategy.querySelector( ".prediction-hint-strategy" )!.textContent, "recent-history" );
  const without = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c" } },
    undefined,
  );
  assertAbsent( without.querySelector( ".prediction-hint-strategy" ), "no strategy line without a strategy" );
} );

test( "the vote controls reach the real integration — a click calls onVote with this card's id", () => {
  const calls: Array<[ string, string ]> = [];
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c" } },
    { getVote: () => undefined, onVote: ( id, dir ) => calls.push( [ id, dir ] ) },
  );
  const up = el.querySelector<HTMLButtonElement>( ".prediction-vote-up" );
  assert.ok( up !== null, "the vote controls mounted — if this is null the rest of the test asserts nothing" );
  up.click();
  assert.deepEqual( calls, [ [ "card-7", "up" ] ] );
} );

test( "a previously cast vote comes back highlighted", () => {
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c" } },
    { getVote: () => "down", onVote: () => {} },
  );
  const root = el.querySelector( ".prediction-hint-vote" )!;
  assert.ok( root.classList.contains( "voted" ) );
  assert.ok( el.querySelector( ".prediction-vote-down" )!.classList.contains( "selected" ) );
} );

test( "with no integration the controls do not mount, rather than mounting with no handler", () => {
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c" } },
    undefined,
  );
  // The box itself is still drawn (predicted value in it); only the controls are skipped.
  assert.ok( el.querySelector( ".prediction-hint-label" ) !== null, "the box was drawn — otherwise the absence below is vacuous" );
  assertAbsent( el.querySelector( ".prediction-hint-vote" ), "no vote controls without an integration" );
  assertAbsent( el.querySelector( ".prediction-vote-up" ), "no up button without an integration" );
  assertAbsent( el.querySelector( ".prediction-vote-down" ), "no down button without an integration" );
} );

test( "with the real vote store the controls mount and a click POSTs this card's vote", async () => {
  const bus   = createEventBusForTesting();
  const posts: Array<{ path: string; body: unknown }> = [];
  const store = createPredictionVoteStore( {
    bus,
    api: { post: async <T,>( path: string, body: unknown ): Promise<T> => { posts.push( { path, body } ); return {} as T; } },
  } );
  store.setContext( "card-9", { question: "Ship it?", predicted_value: "yes", category: "c", response_type: "yes_no" } );
  const el = predictionHintBox(
    { id_hash: "card-9", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.9, predicted_value: "yes", category: "c" } },
    { getVote: ( id ) => store.getVote( id ), onVote: ( id, dir ) => { void store.vote( id, dir ); } },
  );
  const down = el.querySelector<HTMLButtonElement>( ".prediction-vote-down" );
  assert.ok( down !== null, "the vote controls mounted — if this is null the rest of the test asserts nothing" );
  down.click();
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.equal( posts.length, 1 );
  assert.equal( posts[ 0 ]!.path, "/api/notify/prediction-vote/card-9" );
  assert.equal( ( posts[ 0 ]!.body as { vote: string } ).vote, "down" );
  assert.equal( store.getVote( "card-9" ), "down" );
} );

test( "a hint below the vote gate draws the box but no controls", () => {
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { state: "ready", retrieval_metric: "dot", confidence: 0.1, predicted_value: "yes", category: "c" } },
    { getVote: () => undefined, onVote: () => {} },
  );
  assert.equal( el.className, "prediction-hint" );
  assertAbsent( el.querySelector( ".prediction-hint-vote" ), "no vote controls below the gate" );
} );

// --- Phase 5: the fold and the four states ---------------------------------

type Hint = NonNullable<Parameters<typeof predictionHintBox>[ 0 ][ "prediction_hint" ]>;
const ready: Hint = { state: "ready", retrieval_metric: "cosine", confidence: 0.87, predicted_value: "yes", category: "c" };
const box = ( hint: Hint | null | undefined, rt = "yes_no", fold?: Parameters<typeof predictionHintBox>[ 2 ] ) =>
  predictionHintBox( { id_hash: "f1", response_type: rt, prediction_hint: hint }, undefined, fold );

test( "every hint is wrapped in a details fold that starts closed", () => {
  for ( const hint of [ ready, { state: "unavailable", retrieval_metric: "dot", category: "c" } as Hint, null, undefined ] ) {
    const el = box( hint ) as HTMLDetailsElement;
    assert.equal( el.tagName, "DETAILS" );
    assert.equal( el.getAttribute( "data-testid" ), "prediction-hint-fold" );
    assert.equal( el.open, false, "the fold must start closed" );
    assert.equal( el.querySelector( "summary" ) !== null, true, "a keyboard-operable summary is the fold's handle" );
  }
} );

test( "each state renders its own text", () => {
  const text = ( s: string ) => box( { state: s, retrieval_metric: "dot", category: "c" } as Hint ).querySelector( ".prediction-hint-label" )!.textContent;
  assert.equal( text( "insufficient_evidence" ), "Learning, no prediction yet" );
  assert.equal( text( "below_threshold" ), "Forecast too uncertain to show" );
  assert.equal( text( "unavailable" ), "Forecast unavailable" );
  assert.equal( text( "not_a_state" ), "Forecast unavailable", "an unknown state falls back to unavailable" );
  for ( const inherited of [ "toString", "constructor", "hasOwnProperty" ] ) {
    assert.equal( text( inherited ), "Forecast unavailable", `${ inherited } is inherited from Object.prototype, not a state` );
  }
  assert.equal( box( ready ).querySelector( ".prediction-hint-label" )!.textContent, "Yes" );
  assert.equal( box( null ).getAttribute( "data-hint-state" ), "insufficient_evidence" );
} );

test( "only a ready hint shows a confidence, and it names the metric beside it", () => {
  assert.equal( box( ready ).querySelector( ".prediction-hint-confidence" )!.textContent, "Confidence 87% (cosine similarity)" );
  assertAbsent( box( { state: "below_threshold", retrieval_metric: "dot", category: "c" } ).querySelector( ".prediction-hint-confidence" ), "no confidence outside ready" );
  const noConf = box( { state: "ready", retrieval_metric: "dot", category: "c" } );
  assert.equal( noConf.querySelector( ".prediction-hint-confidence" )!.textContent, "Confidence 0% (dot similarity)" );
} );

test( "the always-yes line appears with its denominator, in every state, and only when sent", () => {
  const rate = { yes: 52, n: 59, rate: 0.8814 };
  assert.equal( box( { ...ready, always_yes_rate: rate } ).querySelector( ".prediction-hint-always-yes" )!.textContent, "Always yes would be right 52 of 59 times" );
  const cold = box( { state: "insufficient_evidence", retrieval_metric: "dot", category: "c", always_yes_rate: rate } );
  assert.equal( cold.querySelector( ".prediction-hint-always-yes" )!.textContent, "Always yes would be right 52 of 59 times" );
  assertAbsent( box( ready ).querySelector( ".prediction-hint-always-yes" ), "no line without a rate" );
} );

test( "a yes/no qualifier shows beside the forecast", () => {
  assert.equal( box( { ...ready, predicted_qualifier: "but only on weekdays" } ).querySelector( ".prediction-hint-label" )!.textContent, 'Yes — "but only on weekdays"' );
  assert.equal( box( { ...ready, predicted_qualifier: "" } ).querySelector( ".prediction-hint-label" )!.textContent, "Yes" );
} );

test( "the fold integration reopens a fold that was opened and hears each open", async () => {
  const opened: string[] = [];
  const closed = box( ready, "yes_no", { isOpen: () => false, onOpen: ( id ) => opened.push( id ) } ) as HTMLDetailsElement;
  assert.equal( closed.open, false );
  // The DOM fires `toggle` itself when `open` changes, so the test only changes `open` and waits.
  closed.open = true;
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( opened, [ "f1" ] );
  closed.open = false;
  await new Promise( ( r ) => setTimeout( r, 0 ) );
  assert.deepEqual( opened, [ "f1" ], "closing the fold is not reported" );
  const reopened = box( ready, "yes_no", { isOpen: ( id ) => id === "f1", onOpen: () => {} } ) as HTMLDetailsElement;
  assert.equal( reopened.open, true );
} );

test( "the indicator takes an extra class, a test id and a title from its options, and the title can be left off", () => {
  const custom = abstractIndicator( "details", { className: "jobs-abstract", title: "View details", testid: "jobs-abstract" } )!;
  assert.equal( custom.className, "abstract-indicator jobs-abstract" );
  assert.equal( custom.getAttribute( "title" ), "View details" );
  assert.equal( custom.getAttribute( "data-testid" ), "jobs-abstract" );
  const plain = abstractIndicator( "details" )!;
  assert.equal( plain.getAttribute( "title" ), "View full abstract", "the default title stays" );
  assert.equal( plain.getAttribute( "data-testid" ), null, "no test id unless asked" );
  const untitled = abstractIndicator( "details", { title: null } )!;
  assert.equal( untitled.getAttribute( "title" ), null, "title: null leaves the attribute off" );
} );

// --- A neither forecast (row 321105e7): the lookup arm can forecast "neither", and the card must say so -----

test( "a neither forecast shows as Neither, with its qualifier, and never as yes or no", () => {
  const neither: Hint = { ...ready, predicted_value: "neither" };
  assert.equal( box( neither ).querySelector( ".prediction-hint-label" )!.textContent, "Neither" );
  assert.equal( box( { ...neither, predicted_qualifier: "re-frame it" } ).querySelector( ".prediction-hint-label" )!.textContent, 'Neither — "re-frame it"' );
  assert.equal( box( neither ).querySelector( ".prediction-hint-confidence" )!.textContent, "Confidence 87% (cosine similarity)" );
} );

test( "a ready context forecast of neither reads Haiku forecast: Neither", () => {
  const line = contextForecastLine( "yes_no", { state: "ready", predicted_value: "neither", confidence: 0.6 } );
  assert.equal( line!.textContent, "Haiku forecast: Neither (60%)" );
} );
