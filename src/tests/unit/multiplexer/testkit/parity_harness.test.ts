// WS3 — component-isolation harness entry tests (happy-dom).
//
// Drives parityHarness.ts to c8 100%: importing the module wires the window
// test surface; __parityMount mounts one .sender-card per scenario sender from
// the real canonical fixture (validating the harness end-to-end off-browser).

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

interface HarnessWindow {
  __parityHarnessReady?: boolean;
  __parityMount?: ( s: unknown ) => number;
  __parityModel?: { senders: unknown[]; directions: Record<string, string> };
}

let scenario: unknown;

before( async () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  scenario = JSON.parse(
    readFileSync(
      new URL( "../../../e2e_ui/fixtures/notifications-parity-scenario.json", import.meta.url ),
      "utf-8",
    ),
  );
} );

beforeEach(() => {
  ( globalThis as { marked?: { parse: ( s: string ) => string } } ).marked = {
    parse: ( s: string ) => `<p>${s}</p>`,
  };
  ( globalThis as { DOMPurify?: { sanitize: ( s: string ) => string } } ).DOMPurify = {
    sanitize: ( s: string ) => s,
  };
  document.body.innerHTML = '<main class="container"><div id="sender-cards-container"></div></main>';
} );

test( "parityHarness: import wires the window test surface", async () => {
  await import( "../../../../lupin_app/static/js/multiplexer/testkit/parityHarness" );
  const w = window as unknown as HarnessWindow;
  assert.equal( w.__parityHarnessReady, true );
  assert.equal( typeof w.__parityMount, "function" );
} );

test( "parityHarness: __parityMount renders one .sender-card per sender + exposes the model", async () => {
  await import( "../../../../lupin_app/static/js/multiplexer/testkit/parityHarness" );
  const w = window as unknown as HarnessWindow;

  const count = w.__parityMount!( scenario );
  assert.equal( count, 2 );

  const cards = document.querySelectorAll( "#sender-cards-container .sender-card" );
  assert.equal( cards.length, 2 );

  // The responded-split is visible: Tiberius card holds 5 message rows.
  const tib = document.querySelector(
    '.sender-card[data-sender-id="claude.code@lupin.deepily.ai#parity01"]',
  )!;
  assert.equal( tib.querySelectorAll( ".sender-message" ).length, 5 );

  // Model exposed for the oracle (directions map present).
  assert.equal( w.__parityModel!.directions[ "parity-responded-1-response" ], "outgoing" );

  // Idempotent re-mount — clears and re-renders without duplicating.
  const again = w.__parityMount!( scenario );
  assert.equal( again, 2 );
  assert.equal( document.querySelectorAll( "#sender-cards-container .sender-card" ).length, 2 );
} );
