// Worker-badge silencing on the legacy focus bar (Rick 2026-06-24).
//
// Keystone predicate: a MANAGED worker is a sender whose manager lineage is
// known (managerPersonaMap holds a non-null persona). Managed workers keep the
// faint activity pulse but NEVER surface a numeric count — neither the strip
// icon's `data-unread-count` ::after circle nor the per-card `.sender-new-count`
// "N new" badge. Unmanaged / manager / root sessions keep their count as today.
//
// Covered surfaces:
//   - `_isWorkerSender(senderId)`            — the predicate
//   - `_applyManagerBadge(icon, mgr)`        — sets/clears `data-worker` on the strip icon
//   - `_addStripIcon(...)`                   — stamps `data-worker` at creation
//   - `_markStripIconActivity(...)`          — pulse kept, count suppressed for workers
//   - `_applyCardWorkerFlag(card, id)`       — sets/clears `data-worker` on the card
//   - `updateSenderCardHeader(senderId)`     — suppresses `.sender-new-count` for workers
//
// happy-dom has no layout engine, so we assert the DOM/attributes the methods
// build — the CSS carve (notifications.css strip ::after + the shared
// notifications-surface.css card rule) is visually confirmed by the Playwright
// E2E on :8000. Mirrors manager_badge_strip.test.ts's harness.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/worker_badge_silencing.test.ts

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
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );
} );

type SilencingUI = Record<string, unknown> & {
  managerPersonaMap   : Map<string, unknown>;
  ccFocusState        : { enabled: boolean; focused_sender_id: string | null };
  ccStripUnreadCounts : Record<string, number>;
  senderGroups        : Map<string, unknown>;
  _isWorkerSender       : ( senderId: string ) => boolean;
  _applyManagerBadge    : ( icon: Element | null, managerPersona: unknown ) => void;
  _applyCardWorkerFlag  : ( card: Element | null, senderId: string ) => void;
  _addStripIcon         : ( senderId: string, project: string, persona: unknown, sessionId: string ) => void;
  _markStripIconActivity: ( senderId: string, options?: Record<string, unknown> ) => void;
  _stripIconIdFor       : ( senderId: string ) => string;
  updateSenderCardHeader: ( senderId: string ) => void;
  getSenderStatusIndicator: ( ts: unknown ) => string;
  formatRelativeTime      : ( ts: unknown ) => string;
};

function newUI(): SilencingUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as SilencingUI;
  ui.debug                = false;
  ui.log                  = (): void => {};
  ui.managerPersonaMap    = new Map();
  ui.ccFocusState         = { enabled: false, focused_sender_id: null };
  ui.conversationModes    = {};
  ui.ccHideInactiveStrip  = false;
  ui.ccStripUnreadCounts  = {};
  ui.senderGroups         = new Map();
  return ui;
}

function buildStripDOM(): void {
  document.body.replaceChildren();
  const strip = document.createElement( "div" );
  strip.id = "cc-session-strip";
  strip.setAttribute( "hidden", "" );
  const icons = document.createElement( "div" );
  icons.id = "cc-strip-icons";
  strip.appendChild( icons );
  document.body.appendChild( strip );
}

// Minimal `.sender-card` with the header spans updateSenderCardHeader reads/writes.
function buildSenderCard( senderId: string ): HTMLElement {
  const cardId = `sender-card-${senderId.replace( /[@.#]/g, "-" )}`;
  const card = document.createElement( "div" );
  card.id        = cardId;
  card.className = "sender-card";
  card.innerHTML = `
    <div class="sender-card-header">
      <span class="sender-status"></span>
      <span class="sender-stats-group">
        <span class="sender-new-count"></span>
        <span class="sender-message-count">(0)</span>
        <span class="sender-last-activity">Last: --</span>
      </span>
    </div>`;
  document.body.appendChild( card );
  return card;
}

beforeEach( () => { document.body.replaceChildren(); } );

const WORKER = "claude.code@lupin.deepily.ai#worker01";
const ROOT   = "claude.code@lupin.deepily.ai#root01";

// ── _isWorkerSender predicate ────────────────────────────────────────────────

test( "_isWorkerSender: true when managerPersonaMap holds a non-null persona", () => {
  const ui = newUI();
  ui.managerPersonaMap.set( WORKER, { icon: "👑", initial: "T", color: "#3F51B5", name: "Tiberius" } );
  assert.equal( ui._isWorkerSender( WORKER ), true );
} );

test( "_isWorkerSender: false for an unmanaged/root sender (no map entry)", () => {
  const ui = newUI();
  assert.equal( ui._isWorkerSender( ROOT ), false );
} );

test( "_isWorkerSender: false when managerPersonaMap is absent (defensive)", () => {
  const ui = newUI();
  ( ui as Record<string, unknown> ).managerPersonaMap = null;
  assert.equal( ui._isWorkerSender( WORKER ), false );
} );

// ── _applyManagerBadge sets/clears data-worker on the strip icon ─────────────

test( "_applyManagerBadge sets data-worker='true' when a manager persona is present", () => {
  const ui = newUI();
  buildStripDOM();
  ui._addStripIcon( WORKER, "LUPIN", { name: "Rio", color: "#28a745" }, "worker01" );
  const icon = document.getElementById( ui._stripIconIdFor( WORKER ) ) as HTMLElement;
  ui._applyManagerBadge( icon, { initial: "T", color: "#3F51B5", name: "Tiberius" } );
  assert.equal( icon.getAttribute( "data-worker" ), "true" );
} );

test( "_applyManagerBadge( icon, null ) clears data-worker (re-parented session)", () => {
  const ui = newUI();
  buildStripDOM();
  ui.managerPersonaMap.set( WORKER, { initial: "T", color: "#3F51B5", name: "Tiberius" } );
  ui._addStripIcon( WORKER, "LUPIN", { name: "Rio" }, "worker01" );
  const icon = document.getElementById( ui._stripIconIdFor( WORKER ) ) as HTMLElement;
  assert.equal( icon.getAttribute( "data-worker" ), "true", "worker flag set at creation" );
  ui._applyManagerBadge( icon, null );
  assert.equal( icon.getAttribute( "data-worker" ), null, "flag cleared when lineage removed" );
} );

test( "_addStripIcon stamps data-worker at creation when the sender has a manager", () => {
  const ui = newUI();
  buildStripDOM();
  ui.managerPersonaMap.set( WORKER, { initial: "T", color: "#3F51B5", name: "Tiberius" } );
  ui._addStripIcon( WORKER, "LUPIN", { name: "Rio", color: "#28a745" }, "worker01" );
  const icon = document.getElementById( ui._stripIconIdFor( WORKER ) ) as HTMLElement;
  assert.equal( icon.getAttribute( "data-worker" ), "true" );
} );

test( "_addStripIcon leaves a root session WITHOUT data-worker", () => {
  const ui = newUI();
  buildStripDOM();
  ui._addStripIcon( ROOT, "LUPIN", { name: "Rio", color: "#28a745" }, "root01" );
  const icon = document.getElementById( ui._stripIconIdFor( ROOT ) ) as HTMLElement;
  assert.equal( icon.getAttribute( "data-worker" ), null );
} );

// ── _markStripIconActivity: pulse kept, count suppressed for workers ─────────

test( "_markStripIconActivity: WORKER keeps data-unread pulse but gets NO data-unread-count", () => {
  const ui = newUI();
  buildStripDOM();
  ui.managerPersonaMap.set( WORKER, { initial: "T", color: "#3F51B5", name: "Tiberius" } );
  ui._addStripIcon( WORKER, "LUPIN", { name: "Rio" }, "worker01" );
  ui.ccFocusState = { enabled: true, focused_sender_id: "someone.else" };

  ui._markStripIconActivity( WORKER );

  const icon = document.getElementById( ui._stripIconIdFor( WORKER ) ) as HTMLElement;
  assert.equal( icon.getAttribute( "data-unread" ), "true", "pulse kept (sign of life)" );
  assert.equal( icon.getAttribute( "data-unread-count" ), null, "numeric count suppressed for worker" );
  assert.equal( ui.ccStripUnreadCounts[ WORKER ], 1, "internal counter still advances (parity-neutral)" );
} );

test( "_markStripIconActivity: ROOT keeps both the pulse AND the numeric count", () => {
  const ui = newUI();
  buildStripDOM();
  ui._addStripIcon( ROOT, "LUPIN", { name: "Rio" }, "root01" );
  ui.ccFocusState = { enabled: true, focused_sender_id: "someone.else" };

  ui._markStripIconActivity( ROOT );
  ui._markStripIconActivity( ROOT );

  const icon = document.getElementById( ui._stripIconIdFor( ROOT ) ) as HTMLElement;
  assert.equal( icon.getAttribute( "data-unread" ), "true" );
  assert.equal( icon.getAttribute( "data-unread-count" ), "2", "count rendered for non-worker" );
} );

// ── _applyCardWorkerFlag sets/clears data-worker on the card ─────────────────

test( "_applyCardWorkerFlag sets data-worker on a worker card and clears it on a root card", () => {
  const ui = newUI();
  ui.managerPersonaMap.set( WORKER, { initial: "T", name: "Tiberius" } );
  const workerCard = buildSenderCard( WORKER );
  const rootCard   = buildSenderCard( ROOT );

  ui._applyCardWorkerFlag( workerCard, WORKER );
  ui._applyCardWorkerFlag( rootCard, ROOT );
  assert.equal( workerCard.getAttribute( "data-worker" ), "true" );
  assert.equal( rootCard.getAttribute( "data-worker" ), null );

  // Re-parent: WORKER loses its manager → flag must clear.
  ui.managerPersonaMap.delete( WORKER );
  ui._applyCardWorkerFlag( workerCard, WORKER );
  assert.equal( workerCard.getAttribute( "data-worker" ), null );
} );

test( "_applyCardWorkerFlag is a no-op on a null card (defensive)", () => {
  const ui = newUI();
  assert.doesNotThrow( () => ui._applyCardWorkerFlag( null, WORKER ) );
} );

// ── updateSenderCardHeader: suppress .sender-new-count for workers ───────────

test( "updateSenderCardHeader: WORKER card shows NO 'N new' count and carries data-worker", () => {
  const ui = newUI();
  ui.managerPersonaMap.set( WORKER, { initial: "T", name: "Tiberius" } );
  const card = buildSenderCard( WORKER );
  ui.senderGroups.set( WORKER, { totalCount: 9, newCount: 4, lastActivity: Date.now() } );

  ui.updateSenderCardHeader( WORKER );

  assert.equal( card.getAttribute( "data-worker" ), "true", "card flagged worker" );
  const newCount = card.querySelector( ".sender-new-count" ) as HTMLElement;
  assert.equal( newCount.textContent, "", "no 'N new' text written for worker" );
  assert.equal( newCount.style.display, "none", "count badge hidden for worker" );
  // The rest of the header still renders (number-only suppression).
  assert.equal( ( card.querySelector( ".sender-message-count" ) as HTMLElement ).textContent, "(9)" );
} );

test( "updateSenderCardHeader: ROOT card DOES show the 'N new' count", () => {
  const ui = newUI();
  const card = buildSenderCard( ROOT );
  ui.senderGroups.set( ROOT, { totalCount: 9, newCount: 4, lastActivity: Date.now() } );

  ui.updateSenderCardHeader( ROOT );

  assert.equal( card.getAttribute( "data-worker" ), null, "root card not flagged" );
  const newCount = card.querySelector( ".sender-new-count" ) as HTMLElement;
  assert.equal( newCount.textContent, "4 new", "count rendered for non-worker" );
  assert.equal( newCount.style.display, "inline-block" );
} );

test( "updateSenderCardHeader: ROOT card with zero newCount hides the badge", () => {
  const ui = newUI();
  const card = buildSenderCard( ROOT );
  ui.senderGroups.set( ROOT, { totalCount: 3, newCount: 0, lastActivity: Date.now() } );

  ui.updateSenderCardHeader( ROOT );

  const newCount = card.querySelector( ".sender-new-count" ) as HTMLElement;
  assert.equal( newCount.style.display, "none", "no new activity → hidden even for non-worker" );
} );

if ( typeof process !== "undefined" && process.argv.includes( "--run" ) ) { /* node --test entry */ }
