// Multiplexer Lane C (v0.1.9 focus-bar parity) — broadcastCard template tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/templates_broadcast_card.test.ts`.
//
// Coverage target: 100% lines/branches/functions on broadcastCard.ts.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderBroadcastCard } from "../../../../lupin_app/static/js/multiplexer/render/templates/broadcastCard";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

afterEach(() => {
  if (globalThis.document !== undefined) document.body.replaceChildren();
});

function mountFragment(cardOpen: boolean): HTMLElement {
  const host = document.createElement("div");
  host.appendChild(renderBroadcastCard(cardOpen));
  return host;
}

test("renders the card scaffold with all wired elements", () => {
  const host = mountFragment(true);
  assert.ok( host.querySelector("#broadcast-submit-card") !== null );
  assert.ok( host.querySelector("#broadcast-submit-header") !== null );
  assert.ok( host.querySelector("#broadcast-submit-toggle") !== null );
  assert.ok( host.querySelector("#broadcast-submit-section") !== null );
  assert.ok( host.querySelector("#broadcast-recipients-row") !== null );
  assert.ok( host.querySelector("#broadcast-recipients-label") !== null );
  assert.ok( host.querySelector("#broadcast-recipients-refresh") !== null );
  assert.ok( host.querySelector("#broadcast-stt-button") !== null );
  assert.ok( host.querySelector("#broadcast-textarea") !== null );
  assert.ok( host.querySelector("#broadcast-send-button") !== null );
  assert.ok( host.querySelector("#broadcast-submit-status") !== null );
});

test("open state: data-card-open=true, glyph ▼ (section visibility is CSS-driven)", () => {
  const host = mountFragment(true);
  const card    = host.querySelector("#broadcast-submit-card") as HTMLElement;
  const toggle  = host.querySelector("#broadcast-submit-toggle") as HTMLElement;
  assert.equal(card.getAttribute("data-card-open"), "true");
  assert.equal(toggle.textContent, "▼");
});

test("closed state: data-card-open=false, glyph ▶ (section visibility is CSS-driven)", () => {
  const host = mountFragment(false);
  const card    = host.querySelector("#broadcast-submit-card") as HTMLElement;
  const toggle  = host.querySelector("#broadcast-submit-toggle") as HTMLElement;
  assert.equal(card.getAttribute("data-card-open"), "false");
  assert.equal(toggle.textContent, "▶");
});

test("send button starts disabled", () => {
  const host = mountFragment(true);
  const send = host.querySelector("#broadcast-send-button") as HTMLButtonElement;
  assert.equal(send.disabled, true);
});

// B1 (01-A) — commons "Recent Activity" chrome re-nested INSIDE the broadcast card.
test("B1: renders the re-nested commons Recent-Activity chrome inside the card", () => {
  const host = mountFragment(true);
  // The full chrome CommonsActivityRenderer.mount() querySelects must be present.
  assert.ok( host.querySelector("#commons-activity-pane") !== null );
  assert.ok( host.querySelector("#commons-activity-header") !== null );
  assert.ok( host.querySelector("#commons-activity-window") !== null );
  assert.ok( host.querySelector("#commons-activity-filter-direction") !== null );
  assert.ok( host.querySelector("#commons-activity-filter-kind") !== null );
  assert.ok( host.querySelector("#commons-activity-filter-persona") !== null );
  assert.ok( host.querySelector("#commons-activity-refresh") !== null );
  assert.ok( host.querySelector("#commons-activity-body") !== null );
  assert.ok( host.querySelector("#commons-activity-entries") !== null );
  assert.ok( host.querySelector("#commons-activity-empty") !== null );
});

test("B1: the commons chrome is a DESCENDANT of the broadcast card (not a sibling)", () => {
  const host = mountFragment(true);
  const card    = host.querySelector("#broadcast-submit-card") as HTMLElement;
  const commons = host.querySelector("#commons-activity-pane") as HTMLElement;
  assert.notEqual(card, null);
  assert.notEqual(commons, null);
  assert.equal(card.contains(commons), true);
});

test("B1: the commons chrome is placed OUTSIDE #broadcast-recipients-row (F-Sam-BA1 survival)", () => {
  const host    = mountFragment(true);
  const row     = host.querySelector("#broadcast-recipients-row") as HTMLElement;
  const commons = host.querySelector("#commons-activity-pane") as HTMLElement;
  // It must NOT be inside the recipients-row — that row is replaceChildren()'d on
  // every recipient refresh, which would wipe a nested commons subtree.
  assert.equal(row.contains(commons), false);
});
