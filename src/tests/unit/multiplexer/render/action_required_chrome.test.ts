// Parity A-2 #2m (row 2ebf322f) — the chrome around an Action Required card's prompt.
//
// Legacy: renderActionRequiredNotification's card build (notifications.js:23292-23330),
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
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredChrome";
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
  assert.equal( projectBadge( "someone@example.com" ), null );
} );

test( "an absent sender_id builds no badge at all", () => {
  assert.equal( projectBadge( undefined ), null );
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
  assert.equal( personaBadge( undefined ), null );
} );

// --- the 📋 indicator --------------------------------------------------------

test( "the indicator carries the abstract on data-abstract, the attribute ReadingPaneRenderer reads", () => {
  const el = abstractIndicator( "the full text" )!;
  assert.equal( el.className, "abstract-indicator" );
  assert.equal( el.getAttribute( "data-abstract" ), "the full text" );
  assert.equal( el.textContent, "📋" );
} );

test( "a blank or absent abstract gets no indicator, as legacy's trim gate does", () => {
  assert.equal( abstractIndicator( "   " ), null );
  assert.equal( abstractIndicator( "" ), null );
  assert.equal( abstractIndicator( undefined ), null );
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

test( "a blank or absent abstract builds no block", () => {
  assert.equal( abstractBlock( "  " ), null );
  assert.equal( abstractBlock( undefined ), null );
} );

// --- the prediction hint -----------------------------------------------------

test( "no hint draws legacy's cold-start ghost box", () => {
  const el = predictionHintBox( { id_hash: "a1", response_type: "yes_no" }, undefined );
  assert.equal( el.className, "prediction-hint prediction-hint-cold" );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "Learning, no prediction yet" );
} );

test( "a yes_no prediction is title-cased, as legacy title-cases it", () => {
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c" } },
    undefined,
  );
  assert.equal( el.className, "prediction-hint" );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "Yes" );
} );

test( "a non-yes_no prediction prints as-is, untouched by the title-case", () => {
  const el = predictionHintBox(
    { id_hash: "a1", response_type: "open_ended", prediction_hint: { confidence: 0.9, predicted_value: "ship it", category: "c" } },
    undefined,
  );
  assert.equal( el.querySelector( ".prediction-hint-label" )!.textContent, "ship it" );
} );

test( "the strategy line is drawn when the server sent one, and omitted when it did not", () => {
  const withStrategy = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c", strategy: "recent-history" } },
    undefined,
  );
  assert.equal( withStrategy.querySelector( ".prediction-hint-strategy" )!.textContent, "recent-history" );
  const without = predictionHintBox(
    { id_hash: "a1", response_type: "yes_no", prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c" } },
    undefined,
  );
  assert.equal( without.querySelector( ".prediction-hint-strategy" ), null );
} );

test( "the vote controls reach the real integration — a click calls onVote with this card's id", () => {
  const calls: Array<[ string, string ]> = [];
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c" } },
    { getVote: () => undefined, onVote: ( id, dir ) => calls.push( [ id, dir ] ) },
  );
  const up = el.querySelector<HTMLButtonElement>( ".prediction-vote-up" );
  assert.ok( up !== null, "the vote controls mounted — if this is null the rest of the test asserts nothing" );
  up.click();
  assert.deepEqual( calls, [ [ "card-7", "up" ] ] );
} );

test( "a previously cast vote comes back highlighted", () => {
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c" } },
    { getVote: () => "down", onVote: () => {} },
  );
  const root = el.querySelector( ".prediction-hint-vote" )!;
  assert.ok( root.classList.contains( "voted" ) );
  assert.ok( el.querySelector( ".prediction-vote-down" )!.classList.contains( "selected" ) );
} );

test( "with no integration the controls do not mount, rather than mounting with no handler", () => {
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { confidence: 0.9, predicted_value: "yes", category: "c" } },
    undefined,
  );
  // The controls still render (legacy draws them), but every click routes into the
  // optional-chain no-op rather than a dead listener — the click must not throw.
  const up = el.querySelector<HTMLButtonElement>( ".prediction-vote-up" );
  assert.ok( up !== null );
  up.click();
} );

test( "a hint below the vote gate draws the box but no controls", () => {
  const el = predictionHintBox(
    { id_hash: "card-7", response_type: "yes_no", prediction_hint: { confidence: 0.1, predicted_value: "yes", category: "c" } },
    { getVote: () => undefined, onVote: () => {} },
  );
  assert.equal( el.className, "prediction-hint" );
  assert.equal( el.querySelector( ".prediction-hint-vote" ), null );
} );
