// The multiplexer page puts the Keep place switch on the strip's toggles row.
//
// Run via `npx tsx --test src/tests/unit/multiplexer/render/keep_place_switch_placement.test.ts`.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

function page(): Document {
  const html = readFileSync(resolve(process.cwd(), "src/lupin_app/static/html/multiplexer.html"), "utf8");
  const doc  = document.implementation.createHTMLDocument("m");
  doc.documentElement.innerHTML = html.slice(html.indexOf("<body"));
  return doc;
}

test("the switch is on the strip's toggles row, in the notification history pane", () => {
  const doc    = page();
  const toggle = doc.getElementById("cc-keep-place-toggle");
  assert.ok(toggle !== null, "the switch is on the page");
  assert.equal(toggle!.parentElement!.id, "cc-strip-toggles");
  assert.ok(toggle!.closest("#cc-session-strip") !== null);
  assert.ok(toggle!.closest("#notifications-pane") !== null);
});

test("the toggles row follows the persona badges and holds Focus, All and Keep place in that order", () => {
  const doc  = page();
  const row  = doc.getElementById("cc-strip-toggles")!;
  const icons = doc.getElementById("cc-strip-icons")!;
  assert.ok( icons.nextElementSibling === row, "the row sits directly under the badges" );
  assert.ok( icons.querySelector(".cc-strip-toggle") === null, "the badge row holds no toggle" );
  assert.deepEqual(Array.from(row.children).map(c => c.id), [ "cc-strip-toggle", "cc-hide-inactive-toggle", "cc-keep-place-toggle" ]);
  assert.ok( doc.getElementById("sender-cards-container")!.previousElementSibling === doc.getElementById("cc-session-strip"), "the cards container sits directly under the session strip" );
});

test("the switch starts off", () => {
  const toggle = page().getElementById("cc-keep-place-toggle")!;
  assert.equal(toggle.getAttribute("data-keep-place"), "false");
  assert.equal(toggle.getAttribute("role"), "switch");
  assert.equal(toggle.getAttribute("aria-checked"), "false");
});
