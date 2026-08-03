// Legacy notifications.js — floating in-tab podcast player overlay (2026-08-03).
//
// Rick presents audio from ONE tab and cannot switch mid-demo, so a podcast
// player must live INSIDE the client tab as a floating overlay, not a new tab.
// The client intercepts a click on an `/app/audio?path=...&embed=1` link and
// shows the overlay (both layout modes); a plain `/app/audio?path=` link (no
// embed flag) is left alone and still opens a new tab. Silencing is manual
// only — the <audio controls> inside the iframe, or the ✕ dismiss button which
// removes the iframe (stopping playback). No auto-dismiss, no auto-silence.
//
// happy-dom gives us DOM + Element.closest + createElement, which is all these
// methods touch. Real audio + the ?embed=1 page are covered by Rachel's :8000
// Playwright E2E; here we pin the predicate, the click-routing branches, and
// the overlay build/dismiss DOM contract.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/podcast_overlay.test.ts

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
  const classOnly  = fullSource.slice( 0, initIdx );
  vm.runInThisContext( classOnly + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal( typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function", "NotificationsUI loaded" );
} );

type OverlayUI = Record<string, unknown> & {
  _isEmbeddedAudioHref: ( href: string | null ) => boolean;
  _handleEmbeddedAudioClick: ( ev: unknown ) => void;
  _showPodcastOverlay: ( audioUrl: string, title: string ) => HTMLElement;
  _dismissPodcastOverlay: () => void;
};

function newUI(): OverlayUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as OverlayUI;
  ui.debug = false;
  ui.log   = (): void => {};
  return ui;
}

// Minimal synthetic click event: `target` is a DOM node so the real
// Element.closest runs; `preventDefault` records that it fired.
function clickEvent( target: Element ): { target: Element; preventDefault: () => void; prevented: boolean } {
  const ev = {
    target,
    prevented: false,
    preventDefault(): void { ev.prevented = true; },
  };
  return ev;
}

function anchor( href: string | null, text = "" ): HTMLAnchorElement {
  const a = document.createElement( "a" );
  if ( href !== null ) a.setAttribute( "href", href );
  a.textContent = text;
  document.body.appendChild( a );
  return a;
}

beforeEach( () => { document.body.replaceChildren(); } );

// ── _isEmbeddedAudioHref ──────────────────────────────────────────────────────
test( "_isEmbeddedAudioHref: true for the &embed=1 audio form", () => {
  const ui = newUI();
  assert.equal( ui._isEmbeddedAudioHref( "/app/audio?path=io/podcasts/x.mp3&embed=1" ), true );
} );

test( "_isEmbeddedAudioHref: true when embed=1 is followed by another param", () => {
  const ui = newUI();
  assert.equal( ui._isEmbeddedAudioHref( "/app/audio?path=x.mp3&embed=1&t=5" ), true );
} );

test( "_isEmbeddedAudioHref: false for a plain audio link (no embed flag)", () => {
  const ui = newUI();
  assert.equal( ui._isEmbeddedAudioHref( "/app/audio?path=io/podcasts/x.mp3" ), false );
} );

test( "_isEmbeddedAudioHref: false for embed=0 and for a partial token", () => {
  const ui = newUI();
  assert.equal( ui._isEmbeddedAudioHref( "/app/audio?path=x.mp3&embed=0" ), false );
  assert.equal( ui._isEmbeddedAudioHref( "/app/audio?path=x.mp3&embed=11" ), false );
} );

test( "_isEmbeddedAudioHref: false for a non-audio link carrying embed=1", () => {
  const ui = newUI();
  assert.equal( ui._isEmbeddedAudioHref( "/app/docs?path=x.md&embed=1" ), false );
} );

test( "_isEmbeddedAudioHref: false for null / empty href", () => {
  const ui = newUI();
  assert.equal( ui._isEmbeddedAudioHref( null ), false );
  assert.equal( ui._isEmbeddedAudioHref( "" ), false );
} );

// ── _showPodcastOverlay ───────────────────────────────────────────────────────
test( "_showPodcastOverlay builds a single overlay with iframe src, title, and dismiss", () => {
  const ui = newUI();
  const url = "/app/audio?path=io/podcasts/x.mp3&embed=1";
  const el  = ui._showPodcastOverlay( url, "My Podcast" );

  assert.equal( document.querySelectorAll( "#podcast-overlay" ).length, 1, "exactly one overlay" );
  assert.equal( el.id, "podcast-overlay" );
  const frame = el.querySelector( "iframe.podcast-overlay-frame" ) as HTMLIFrameElement;
  assert.ok( frame, "iframe present" );
  assert.ok( frame.getAttribute( "src" )!.endsWith( "&embed=1" ), "iframe carries the embed URL verbatim" );
  assert.equal( el.querySelector( ".podcast-overlay-title" )!.textContent, "My Podcast" );
  assert.ok( el.querySelector( "button.podcast-overlay-dismiss" ), "dismiss button present" );
  // Stable E2E hooks for Rachel.
  assert.ok( el.querySelector( '[data-testid="podcast-overlay-frame"]' ) );
  assert.ok( el.querySelector( '[data-testid="podcast-overlay-dismiss"]' ) );
} );

test( "_showPodcastOverlay is single-instance — a second call replaces the first", () => {
  const ui = newUI();
  ui._showPodcastOverlay( "/app/audio?path=a.mp3&embed=1", "First" );
  ui._showPodcastOverlay( "/app/audio?path=b.mp3&embed=1", "Second" );
  const all = document.querySelectorAll( "#podcast-overlay" );
  assert.equal( all.length, 1, "still exactly one overlay" );
  assert.equal( document.querySelector( ".podcast-overlay-title" )!.textContent, "Second" );
} );

test( "_showPodcastOverlay falls back to a default title when none is given", () => {
  const ui = newUI();
  const el = ui._showPodcastOverlay( "/app/audio?path=a.mp3&embed=1", "" );
  assert.equal( el.querySelector( ".podcast-overlay-title" )!.textContent, "Podcast" );
} );

test( "dismiss button click removes the overlay (stops playback by removing the iframe)", () => {
  const ui = newUI();
  ui._showPodcastOverlay( "/app/audio?path=a.mp3&embed=1", "X" );
  const btn = document.querySelector( "button.podcast-overlay-dismiss" ) as HTMLButtonElement;
  btn.click();
  assert.equal( document.getElementById( "podcast-overlay" ), null, "overlay removed on dismiss" );
} );

// ── _dismissPodcastOverlay ────────────────────────────────────────────────────
test( "_dismissPodcastOverlay is a no-op when no overlay is open", () => {
  const ui = newUI();
  assert.doesNotThrow( () => ui._dismissPodcastOverlay() );
  assert.equal( document.getElementById( "podcast-overlay" ), null );
} );

// ── _handleEmbeddedAudioClick (routing branches) ──────────────────────────────
test( "click on an embed=1 audio link opens the overlay and prevents default", () => {
  const ui = newUI();
  const a  = anchor( "/app/audio?path=io/podcasts/x.mp3&embed=1", "Play Here" );
  const ev = clickEvent( a );
  ui._handleEmbeddedAudioClick( ev );
  assert.equal( ev.prevented, true, "navigation suppressed" );
  const el = document.getElementById( "podcast-overlay" );
  assert.ok( el, "overlay opened" );
  assert.equal( el!.querySelector( ".podcast-overlay-title" )!.textContent, "Play Here", "title from link text" );
} );

test( "click on a PLAIN audio link is left alone — no overlay, no preventDefault (opens a new tab)", () => {
  const ui = newUI();
  const a  = anchor( "/app/audio?path=io/podcasts/x.mp3", "Listen" );
  const ev = clickEvent( a );
  ui._handleEmbeddedAudioClick( ev );
  assert.equal( ev.prevented, false, "plain link NOT intercepted" );
  assert.equal( document.getElementById( "podcast-overlay" ), null, "no overlay for the plain link" );
} );

test( "click with no anchor in the ancestry is ignored", () => {
  const ui = newUI();
  const div = document.createElement( "div" );
  document.body.appendChild( div );
  const ev = clickEvent( div );
  ui._handleEmbeddedAudioClick( ev );
  assert.equal( ev.prevented, false );
  assert.equal( document.getElementById( "podcast-overlay" ), null );
} );

test( "click that originates inside the reading-pane iframe is ignored", () => {
  const ui = newUI();
  const pane = document.createElement( "div" );
  pane.id = "content-pane-body";
  const frame = document.createElement( "iframe" );
  const a = document.createElement( "a" );
  a.setAttribute( "href", "/app/audio?path=x.mp3&embed=1" );
  frame.appendChild( a );
  pane.appendChild( frame );
  document.body.appendChild( pane );
  const ev = clickEvent( a );
  ui._handleEmbeddedAudioClick( ev );
  assert.equal( ev.prevented, false, "iframe-internal click bailed" );
  assert.equal( document.getElementById( "podcast-overlay" ), null );
} );

test( "click on a non-audio link is ignored", () => {
  const ui = newUI();
  const a  = anchor( "/app/docs?path=x.md", "Doc" );
  const ev = clickEvent( a );
  ui._handleEmbeddedAudioClick( ev );
  assert.equal( ev.prevented, false );
  assert.equal( document.getElementById( "podcast-overlay" ), null );
} );

test( "embed link routing survives an absolute loopback-host prefix (normalized first)", () => {
  const ui = newUI();
  const a  = anchor( "http://localhost:7999/app/audio?path=x.mp3&embed=1", "Play Here" );
  const ev = clickEvent( a );
  ui._handleEmbeddedAudioClick( ev );
  assert.equal( ev.prevented, true, "absolute-form embed link still intercepted after normalization" );
  assert.ok( document.getElementById( "podcast-overlay" ), "overlay opened for absolute-form link" );
} );
