// Focus-bar selection survives a page refresh even when the focused session
// hydrates LATE (Tiffany 2026-06-17).
//
// Bug (Rick, TOP priority): the focus-bar toggle "loses its selection on page
// refresh — the user must reselect focus every reload." The selection IS
// persisted to localStorage (_saveCcFocusState) and there is a restore pass
// (_restoreCcUiAfterLoad) — BUT when the focused sender has no card at restore
// time, restore reverts the IN-MEMORY focus to default via _exitFocusMode(false)
// (keeping only the localStorage intent). The late-arrival re-apply in
// _addStripIcon then consulted only the now-false in-memory ccFocusState, so when
// the focused session arrived later via async WS nothing re-read the persisted
// intent → focus silently dropped. Focused sessions are frequently the
// late-arriving ones (an active worker that first reports via WS), so the symptom
// hit nearly every reload.
//
// Fix: _maybeReapplyPersistedFocus(senderId), called from the top of _addStripIcon,
// re-reads localStorage and re-enters focus mode the moment the persisted focused
// session's icon/card hydrates. These tests reproduce the drop and prove the
// self-restore, plus the guard branches (non-focused arrival, no/disabled persisted
// focus, already-active idempotency, corrupt localStorage, missing senderId).
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/focus_persist_late_hydration.test.ts

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
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

const FOCUS_KEY = "notifications_cc_focus_state";
const SENDER_A  = "claude.code@lupin.deepily.ai#aaaa1111";   // the focused session
const SENDER_B  = "claude.code@lupin.deepily.ai#bbbb2222";   // a non-focused session
const PERSONA   = { name: "Rachel", display_name: "Rachel", color: "#CE93D8" };

type FocusUI = Record<string, unknown> & {
  _addStripIcon: ( a: string, b: string, c: unknown, d: string ) => void;
  _maybeReapplyPersistedFocus: ( s: string | null ) => void;
  _stripIconIdFor: ( s: string ) => string;
  ccFocusState: { enabled: boolean; focused_sender_id: string | null };
};

function cardIdFor( senderId: string ): string {
  return `sender-card-${ senderId.replace( /[@.#]/g, "-" ) }`;
}

function addSenderCard( senderId: string ): HTMLElement {
  const list = document.getElementById( "notifications-list" )!;
  const card = document.createElement( "div" );
  card.className = "sender-card";
  card.id = cardIdFor( senderId );
  list.appendChild( card );
  return card;
}

function makeUI( reverted = true ): FocusUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as FocusUI;
  ui.debug = false;
  ui.log = (): void => {};
  ui.error = (): void => {};
  ui.CC_FOCUS_STATE_KEY = FOCUS_KEY;
  // Simulate the post-restore IN-MEMORY state: _restoreCcUiAfterLoad reverted
  // focus to default because SENDER_A's card was absent at restore time, but the
  // localStorage intent is still set (see beforeEach / per-test seeding).
  ui.ccFocusState = reverted
    ? { enabled: false, focused_sender_id: null }
    : { enabled: true,  focused_sender_id: SENDER_A };
  ui.managerPersonaMap = new Map();
  ui.conversationModes = {};
  ui.ccHideInactiveStrip = false;
  ui.ccStripUnreadCounts = {};

  document.body.replaceChildren();
  const strip = document.createElement( "div" );
  strip.id = "cc-session-strip"; strip.setAttribute( "hidden", "" );
  const icons = document.createElement( "div" ); icons.id = "cc-strip-icons";
  strip.appendChild( icons );
  const toggle = document.createElement( "button" );
  toggle.id = "cc-strip-toggle"; toggle.setAttribute( "data-focus-active", "false" ); toggle.textContent = "👁 Focus";
  const list = document.createElement( "div" ); list.id = "notifications-list";
  document.body.append( strip, toggle, list );
  return ui;
}

beforeEach( () => {
  localStorage.clear();
  document.body.replaceChildren();
} );

test( "FIX: focused session hydrating LATE re-applies focus from localStorage (no reselect)", () => {
  // Persisted intent = focus on A; in-memory reverted to default (the post-restore state).
  localStorage.setItem( FOCUS_KEY, JSON.stringify( { enabled: true, focused_sender_id: SENDER_A } ) );
  const ui = makeUI();
  // A non-focused session B already rendered and visible (arrived before A).
  const cardB = addSenderCard( SENDER_B );
  ui._addStripIcon( SENDER_B, "LUPIN", PERSONA, "bbbb2222" );
  // A's card now hydrates too (e.g. its first WS notification), then its icon.
  const cardA = addSenderCard( SENDER_A );

  ui._addStripIcon( SENDER_A, "LUPIN", PERSONA, "aaaa1111" );   // ← late arrival triggers the fix

  assert.equal( ui.ccFocusState.enabled, true, "focus re-enabled from persisted intent" );
  assert.equal( ui.ccFocusState.focused_sender_id, SENDER_A, "focused session restored to A" );
  const toggle = document.getElementById( "cc-strip-toggle" )!;
  assert.equal( toggle.getAttribute( "data-focus-active" ), "true", "toggle pill shows active" );
  assert.equal( toggle.textContent, "👁 Focus: ON" );
  const iconA = document.getElementById( ui._stripIconIdFor( SENDER_A ) )!;
  assert.equal( iconA.getAttribute( "data-focused" ), "true", "A's strip icon marked focused" );
  assert.equal( cardA.getAttribute( "data-focus-hidden" ), null, "focused card A is visible" );
  assert.equal( cardB.getAttribute( "data-focus-hidden" ), "true", "non-focused card B hidden" );
} );

test( "a NON-focused session arriving late does not steal focus", () => {
  localStorage.setItem( FOCUS_KEY, JSON.stringify( { enabled: true, focused_sender_id: SENDER_A } ) );
  const ui = makeUI();
  addSenderCard( SENDER_B );
  ui._addStripIcon( SENDER_B, "LUPIN", PERSONA, "bbbb2222" );
  // A never arrives; B is not the persisted focus → in-memory stays default.
  assert.equal( ui.ccFocusState.enabled, false, "B is not the focused session — focus not applied" );
} );

test( "no persisted focus (disabled) → late arrival does nothing", () => {
  localStorage.setItem( FOCUS_KEY, JSON.stringify( { enabled: false, focused_sender_id: null } ) );
  const ui = makeUI();
  addSenderCard( SENDER_A );
  ui._addStripIcon( SENDER_A, "LUPIN", PERSONA, "aaaa1111" );
  assert.equal( ui.ccFocusState.enabled, false, "disabled persisted focus stays disabled" );
} );

test( "absent localStorage key → late arrival does nothing (no throw)", () => {
  const ui = makeUI();   // localStorage cleared in beforeEach
  addSenderCard( SENDER_A );
  ui._addStripIcon( SENDER_A, "LUPIN", PERSONA, "aaaa1111" );
  assert.equal( ui.ccFocusState.enabled, false );
} );

test( "already-active focus is idempotent (guard short-circuits, no re-apply)", () => {
  localStorage.setItem( FOCUS_KEY, JSON.stringify( { enabled: true, focused_sender_id: SENDER_A } ) );
  const ui = makeUI( /* reverted */ false );   // in-memory focus ALREADY active on A
  addSenderCard( SENDER_A );
  ui._addStripIcon( SENDER_A, "LUPIN", PERSONA, "aaaa1111" );
  assert.equal( ui.ccFocusState.enabled, true, "stays focused" );
  assert.equal( ui.ccFocusState.focused_sender_id, SENDER_A );
} );

test( "corrupt localStorage is swallowed (no throw, focus stays default)", () => {
  localStorage.setItem( FOCUS_KEY, "{not valid json" );
  const ui = makeUI();
  addSenderCard( SENDER_A );
  assert.doesNotThrow( () => ui._addStripIcon( SENDER_A, "LUPIN", PERSONA, "aaaa1111" ) );
  assert.equal( ui.ccFocusState.enabled, false, "corrupt persisted state ignored" );
} );

test( "missing senderId is a no-op (guard)", () => {
  localStorage.setItem( FOCUS_KEY, JSON.stringify( { enabled: true, focused_sender_id: SENDER_A } ) );
  const ui = makeUI();
  assert.doesNotThrow( () => ui._maybeReapplyPersistedFocus( null ) );
  assert.equal( ui.ccFocusState.enabled, false );
} );
