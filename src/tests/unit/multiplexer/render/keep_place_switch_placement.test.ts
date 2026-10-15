// The multiplexer page puts the Keep place switch at the top of the notification history.
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

test("the switch is in the notification history pane, not in the CC session strip", () => {
  const doc    = page();
  const toggle = doc.getElementById("cc-keep-place-toggle");
  assert.ok(toggle !== null, "the switch is on the page");
  assert.equal(toggle!.closest("#cc-session-strip"), null);
  assert.ok(toggle!.closest("#notifications-pane") !== null);
});

test("it is the first thing in the pane, above the broadcast card, and starts off", () => {
  const doc    = page();
  const pane   = doc.getElementById("notifications-pane")!;
  const toggle = doc.getElementById("cc-keep-place-toggle")!;
  const first  = Array.from(pane.children).find(c => c.tagName !== "SCRIPT")!;
  assert.ok(first.contains(toggle), "the first element of the pane holds the switch");
  assert.ok(pane.querySelector("#broadcast-card-mount") !== null);
  assert.equal(toggle.getAttribute("data-keep-place"), "false");
  assert.equal(toggle.getAttribute("role"), "switch");
  assert.equal(toggle.getAttribute("aria-checked"), "false");
});
