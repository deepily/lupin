// Sender text reaches the LEGACY page as text, never as markup — row 6ce9f4a1.
//
// The census in src/rnd/2026.09.11-legacy-action-required-escaping-plan.md found 14 places in
// notifications.js that wrote a sender-supplied string into innerHTML unescaped (4 of them, in
// addNotificationToList, are row-split), plus the operator's own text and the TTS error modal.
// Every site that is fixed here gets its OWN test, so a revert of one wrap reddens one named test.
//
// 🔴 WHAT THE ASSERTION MEASURES. happy-dom parses markup the way a browser does but does not run
// event handlers, so "no script ran" is not observable here. What IS observable, and what an
// unescaped interpolation changes, is the PARSE: a payload that becomes an element or an attribute
// was markup; a payload that survives as textContent / .value was text. The positive control at the
// bottom renders the pre-fix line in the same harness and watches it produce the element — without
// that arm, a harness that could not parse would pass every test in this file.
// The real-browser layer (script does not execute) is the Playwright file named in the plan.
//
// Harness: the established one — notifications.js sliced before its DOM-ready init, loaded with
// vm.runInThisContext, a UI made with Object.create( prototype ), collaborators stubbed.
//
// Run: npx tsx --test src/tests/unit/notifications_js/sender_text_is_escaped_in_the_legacy_page.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

// Element-shaped payload: unescaped, it parses to an <img>.
const TAG_PAYLOAD  = `<img src=x onerror="globalThis.__xss=1">`;
// Attribute-shaped payload: unescaped inside value="…", it closes the attribute and adds onfocus.
const ATTR_PAYLOAD = `x" autofocus onfocus="globalThis.__xss=1`;

type UI = Record<string, any>;

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

beforeEach( () => {
  document.body.innerHTML = "";
} );

function newUI(): UI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui   = Object.create( Ctor.prototype ) as UI;
  ui.debug   = false;
  ui.log     = (): void => {};
  ui.error   = (): void => {};
  ui.actionRequiredNotifications = new Map();
  return ui;
}

function mount( id: string ): HTMLElement {
  const el = document.createElement( "div" );
  el.id = id;
  document.body.appendChild( el );
  return el;
}

// ⚠️ EVERY ASSERTION BELOW COMPARES A BOOLEAN OR A STRING, NEVER A DOM NODE. A failing assert that
// holds a happy-dom element makes node inspect the whole document for its message, and the jstest
// lane's RSS watchdog kills the run at 2 GB before any result prints (measured on this file's first
// revert arm, 2026-09-11; rows f5768ee4 / 32c58572). A test that cannot report its own failure is
// not a guard.

/** The two facts that tell text from markup, for an element-shaped payload. */
function assertRenderedAsText( root: Element | null, where: string ): void {
  assert.equal( root !== null, true, `${where}: nothing rendered` );
  assert.equal( root!.querySelector( "img" ) !== null, false, `${where}: the payload parsed into an <img>` );
  assert.equal( root!.textContent!.includes( TAG_PAYLOAD ), true, `${where}: the payload is not in the text` );
}

/** For an attribute-shaped payload: the value round-trips and no handler attribute appeared. */
function assertValueRoundTrips( input: HTMLInputElement | null, where: string ): void {
  assert.equal( input !== null, true, `${where}: input not rendered` );
  assert.equal( input!.getAttribute( "onfocus" ), null, `${where}: the payload broke out of value="…"` );
  assert.equal( input!.value, ATTR_PAYLOAD, `${where}: the value did not round-trip` );
}

function mcNotification( question: Record<string, unknown> ): Record<string, unknown> {
  return {
    id               : "n-mc-1",
    sender_id        : "claude.code@lupin.deepily.ai#abcdef12",
    response_type    : "multiple_choice",
    response_options : { questions: [ question ] },
  };
}

function renderMC( ui: UI, notification: Record<string, unknown> ): HTMLElement {
  const host = document.createElement( "div" );
  host.innerHTML = ui.renderMultipleChoiceUI( notification, 0 );
  return host;
}

// ── TTS error modal (server text, one-line wraps) ───────────────────────────────────────────

test( "TTS error modal: the error TEXT renders as text", () => {
  const ui = newUI();
  ui.showTTSErrorModal( "E1", TAG_PAYLOAD, "" );
  assertRenderedAsText( document.querySelector( ".tts-error-message" ), "tts-error-message" );
} );

test( "TTS error modal: the error CODE renders as text", () => {
  const ui = newUI();
  ui.showTTSErrorModal( TAG_PAYLOAD, "boom", "" );
  assertRenderedAsText( document.querySelector( ".tts-error-code" ), "tts-error-code" );
} );

// ── Sender card: session name ───────────────────────────────────────────────────────────────

test( "sender card: a session name renders as text", () => {
  const ui       = newUI();
  const senderId = "claude.code@lupin.deepily.ai#abcdef12";
  mount( "notifications-list" );
  ui.senderGroups      = new Map();
  ui.sessionNames      = { abcdef12: TAG_PAYLOAD };
  ui.conversationModes = {};
  ui.senderPersonaMap  = new Map();
  // Decorators that run AFTER the card's innerHTML is written; the claim is about that write.
  ui._applyFocusHiddenToCard = (): void => {};
  ui._applyCardWorkerFlag    = (): void => {};
  ui._addStripIcon           = (): void => {};
  ui.ccFocusState            = { enabled: false, focused_sender_id: null };
  ui.createSenderCard( senderId );
  assertRenderedAsText( document.querySelector( ".sender-session-name" ), "sender-session-name" );
} );

// ── Minimized action-required card ─────────────────────────────────────────────────────────

test( "minimized action-required card: the message renders as text", () => {
  const ui = newUI();
  mount( "action-required-pending-queue" );
  ui.renderMinimizedNotificationDOM( { id: "n-min-1", message: TAG_PAYLOAD, response_type: "yes_no", timeout_seconds: 30 }, 1 );
  assertRenderedAsText( document.querySelector( ".minimized-message" ), "minimized-message" );
} );

// ── The active action-required card ────────────────────────────────────────────────────────

function renderActive( ui: UI, notification: Record<string, unknown> ): HTMLElement {
  mount( "action-required-active-slot" );
  ui.renderActionRequiredNotification( notification );
  return document.getElementById( `action-required-${notification.id}` ) as HTMLElement;
}

test( "action-required card: the TITLE renders as text", () => {
  const ui   = newUI();
  const card = renderActive( ui, { id: "n-title-1", title: TAG_PAYLOAD, message: "m", response_type: "yes_no", sender_id: "claude.code@lupin.deepily.ai#abcdef12" } );
  assertRenderedAsText( card.querySelector( ".action-required-title" ), "action-required-title" );
} );

test( "action-required card: an open-ended response_default stays inside value=\"…\"", () => {
  const ui   = newUI();
  const card = renderActive( ui, { id: "n-oe-1", title: "t", message: "m", response_type: "open_ended", response_default: ATTR_PAYLOAD, sender_id: "claude.code@lupin.deepily.ai#abcdef12" } );
  assertValueRoundTrips( card.querySelector( ".response-text-input" ), "response-text-input" );
} );

// ── Multiple choice ────────────────────────────────────────────────────────────────────────

test( "multiple choice: the QUESTION renders as text", () => {
  const ui   = newUI();
  const host = renderMC( ui, mcNotification( { question: TAG_PAYLOAD, header: "H", options: [ { label: "a" } ] } ) );
  assertRenderedAsText( host.querySelector( ".mc-question-text" ), "mc-question-text" );
} );

test( "multiple choice: an option LABEL renders as text", () => {
  const ui   = newUI();
  const host = renderMC( ui, mcNotification( { question: "q", header: "H", options: [ { label: TAG_PAYLOAD } ] } ) );
  assertRenderedAsText( host.querySelector( ".mc-option-label" ), "mc-option-label" );
} );

test( "multiple choice: an option LABEL stays inside the input's value=\"…\"", () => {
  const ui   = newUI();
  const host = renderMC( ui, mcNotification( { question: "q", header: "H", options: [ { label: ATTR_PAYLOAD } ] } ) );
  assertValueRoundTrips( host.querySelector( "input.mc-input:not(.mc-other-radio)" ), "mc-input" );
} );

test( "multiple choice: an option DESCRIPTION renders as text", () => {
  const ui   = newUI();
  const host = renderMC( ui, mcNotification( { question: "q", header: "H", options: [ { label: "a", description: TAG_PAYLOAD } ] } ) );
  assertRenderedAsText( host.querySelector( ".mc-option-desc" ), "mc-option-desc" );
} );

test( "multiple choice: the operator's saved 'Other' answer stays inside value=\"…\"", () => {
  const ui           = newUI();
  const notification = mcNotification( { question: "q", header: "H", options: [ { label: "a" } ] } );
  ui.actionRequiredNotifications.set( notification.id, { collectedAnswers: { H: ATTR_PAYLOAD } } );
  const host = renderMC( ui, notification );
  assertValueRoundTrips( host.querySelector( ".mc-other-input" ), "mc-other-input" );
} );

test( "multiple choice: a label carrying \" and & is the ANSWER read back, and a re-render re-ticks it", () => {
  // The escape must not change what the operator's click submits. The browser decodes the
  // entities when it parses value="…", so .value is the sender's label byte for byte, and the
  // saved answer still matches the option list on the next render.
  const label        = `Yes "definitely" & now`;
  const ui           = newUI();
  const notification = mcNotification( { question: "q", header: "H", options: [ { label }, { label: "No" } ] } );
  const first        = renderMC( ui, notification );
  const input        = first.querySelector( "input.mc-input:not(.mc-other-radio)" ) as HTMLInputElement;
  assert.equal( input.value, label );

  ui.actionRequiredNotifications.set( notification.id, { collectedAnswers: { H: input.value } } );
  const again   = renderMC( ui, notification );
  const checked = again.querySelector( "input.mc-input:checked" ) as HTMLInputElement | null;
  assert.equal( checked !== null, true, "the saved answer did not re-tick an option" );
  assert.equal( checked!.value, label );
  assert.equal( ( again.querySelector( ".mc-other-input" ) as HTMLInputElement ).value, "", "the label was mistaken for a custom answer" );
} );

// ── Prediction hint ────────────────────────────────────────────────────────────────────────

test( "prediction hint: a predicted answer's header renders as text", () => {
  const ui   = newUI();
  const html = ui.buildPredictionHintSection( {
    id            : "n-pred-1",
    response_type : "multiple_choice",
    prediction_hint : { confidence: 0.9, strategy: "cbr_retrieval", predicted_value: { answers: { [ TAG_PAYLOAD ]: "a" } } },
  } );
  const host = document.createElement( "div" );
  host.innerHTML = html;
  assertRenderedAsText( host.querySelector( ".prediction-hint-label" ), "prediction-hint-label" );
} );

// ── Badges written into a card that already exists ─────────────────────────────────────────

function cardWithButtons( id: string ): HTMLElement {
  const card = document.createElement( "div" );
  card.id = `action-required-${id}`;
  card.innerHTML = `<div class="response-buttons"></div>`;
  document.body.appendChild( card );
  return card;
}

test( "expired badge: the sender's response_default renders as text", () => {
  const ui = newUI();
  const id = "n-exp-1";
  const card = cardWithButtons( id );
  ui.actionRequiredNotifications.set( id, { notification: { id, response_type: "yes_no", response_default: TAG_PAYLOAD, sender_id: "claude.code@lupin.deepily.ai#abcdef12" } } );
  ui.calculateDestination     = (): null => null;
  ui.updateActionRequiredCount = (): void => {};
  ui.saveActionRequiredState   = (): void => {};
  ui.handleLocalTimeout( id );
  assertRenderedAsText( card.querySelector( ".notification-status-badge.expired" ), "expired badge" );
} );

test( "responded-in-another-session badge: the response renders as text", () => {
  const ui = newUI();
  const id = "n-other-1";
  const card = cardWithButtons( id );
  ui.actionRequiredNotifications.set( id, { notification: { id, response_type: "yes_no", sender_id: "claude.code@lupin.deepily.ai#abcdef12" } } );
  ui.stopCountdownTimer            = (): void => {};
  ui.addNotificationToSenderGroup  = (): void => {};
  ui.updateTotalNotificationsCount = (): void => {};
  ui.updateActionRequiredCount     = (): void => {};
  ui.saveActionRequiredState       = (): void => {};
  ui.handleNotificationResponded( { notification_id: id, response_value: TAG_PAYLOAD } );
  assertRenderedAsText( card.querySelector( ".notification-status-badge.responded" ), "responded badge" );
} );

// ── Positive control ───────────────────────────────────────────────────────────────────────

test( "CONTROL: the pre-fix line, rendered in this harness, DOES parse the payload into markup", () => {
  // Without this arm every test above could pass on a harness that never parses HTML.
  const host = document.createElement( "div" );
  host.innerHTML = `<div class="mc-question-text">${TAG_PAYLOAD}</div><input class="x" value="${ATTR_PAYLOAD}">`;
  assert.equal( host.querySelector( ".mc-question-text img" ) !== null, true, "the harness did not parse an <img> from raw markup" );
  assert.notEqual( ( host.querySelector( "input.x" ) as HTMLElement ).getAttribute( "onfocus" ), null, "the harness did not parse the attribute break-out" );
} );
