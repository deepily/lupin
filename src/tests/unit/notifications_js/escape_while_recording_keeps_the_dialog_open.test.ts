// Escape that stops a recording must not cancel the action-required dialog.
//
// The card's document-level keydown handler only stood down when focus sat in a text
// field; a recording
// started from the 🎤 button leaves focus on the button, so Escape reached
// cancelActionRequired as well as the recorder.
//
// Fix: while a recording is active the dialog's Escape handler does nothing.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/escape_while_recording_keeps_the_dialog_open.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

let ui: Record<string, any>;

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;" );

  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  ui = Object.create( Ctor.prototype ) as Record<string, any>;
  ui.log                       = (): void => {};
  ui.keyboardListenerActive    = false;
  ui.actionRequiredNotifications = new Map( [ [ "ar1", {} ] ] );
  ui.activeActionRequiredId    = "ar1";
  ui.cancelled                 = [] as string[];
  ui.cancelActionRequired      = function ( id: string ): void { this.cancelled.push( id ); };
  ui.recordingManager          = { activeRecording: null, audioRecorder: null };
  ui.attachKeyboardListener();
} );

beforeEach( () => {
  ui.cancelled.length = 0;
  ui.recordingManager.activeRecording = null;
  document.body.replaceChildren();
} );

function escape(): KeyboardEvent {
  const e = new KeyboardEvent( "keydown", { key: "Escape", bubbles: true, cancelable: true } );
  document.dispatchEvent( e );
  return e;
}

test( "Escape cancels the dialog when nothing is recording (positive control)", () => {
  escape();
  assert.deepEqual( ui.cancelled, [ "ar1" ] );
} );

test( "Escape while a recording is active does not cancel the dialog, even with focus on the mic button", () => {
  const btn = document.createElement( "button" );
  document.body.appendChild( btn );
  btn.focus();
  assert.ok( document.activeElement === btn, "focus is on a button, not an input — the case that leaked" );
  ui.recordingManager.activeRecording = { contextId: "ar1-other" };
  const e = escape();
  assert.deepEqual( ui.cancelled, [], "the dialog stays open" );
  assert.equal( e.defaultPrevented, false, "the handler left the key alone for the recorder" );
} );

test( "once the recording has stopped, Escape cancels again", () => {
  ui.recordingManager.activeRecording = { contextId: "x" };
  escape();
  assert.deepEqual( ui.cancelled, [] );
  ui.recordingManager.activeRecording = null;
  escape();
  assert.deepEqual( ui.cancelled, [ "ar1" ] );
} );
