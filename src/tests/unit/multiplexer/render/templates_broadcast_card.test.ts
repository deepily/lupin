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
  assert.notEqual(host.querySelector("#broadcast-submit-card"), null);
  assert.notEqual(host.querySelector("#broadcast-submit-header"), null);
  assert.notEqual(host.querySelector("#broadcast-submit-toggle"), null);
  assert.notEqual(host.querySelector("#broadcast-submit-section"), null);
  assert.notEqual(host.querySelector("#broadcast-recipients-row"), null);
  assert.notEqual(host.querySelector("#broadcast-recipients-label"), null);
  assert.notEqual(host.querySelector("#broadcast-recipients-refresh"), null);
  assert.notEqual(host.querySelector("#broadcast-stt-button"), null);
  assert.notEqual(host.querySelector("#broadcast-textarea"), null);
  assert.notEqual(host.querySelector("#broadcast-send-button"), null);
  assert.notEqual(host.querySelector("#broadcast-submit-status"), null);
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
