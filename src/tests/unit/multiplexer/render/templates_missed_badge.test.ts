// Multiplexer Lane E WP15 — missedBadge template tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderMissedBadge,
  type MissedBadgeHandlers,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/missedBadge";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeHandlers(): { handlers: MissedBadgeHandlers; calls: { resets: number } } {
  const calls = { resets: 0 };
  const handlers: MissedBadgeHandlers = { onReset(): void { calls.resets += 1; } };
  return { handlers, calls };
}

test("renders .missed-badge.missed-visible root with data-testid", () => {
  const { handlers } = makeHandlers();
  const el = renderMissedBadge({ count: 3 }, handlers);
  assert.ok(el.classList.contains("missed-badge"));
  assert.ok(el.classList.contains("missed-visible"));
  assert.equal(el.getAttribute("data-testid"), "multiplexer-missed-badge");
});

test("status text reads '<count> missed while away'", () => {
  const { handlers } = makeHandlers();
  const el = renderMissedBadge({ count: 7 }, handlers);
  const status = el.querySelector(".missed-status");
  assert.ok(status);
  assert.equal(status.textContent, "7 missed while away");
});

test("renders a Reset button", () => {
  const { handlers } = makeHandlers();
  const el = renderMissedBadge({ count: 1 }, handlers);
  const btn = el.querySelector<HTMLButtonElement>(".missed-reset-button");
  assert.ok(btn);
  assert.equal(btn.textContent, "Reset");
  assert.equal(btn.getAttribute("type"), "button");
});

test("Reset button click fires onReset", () => {
  const { handlers, calls } = makeHandlers();
  const el = renderMissedBadge({ count: 2 }, handlers);
  const btn = el.querySelector<HTMLButtonElement>(".missed-reset-button");
  assert.ok(btn);
  btn.click();
  btn.click();
  assert.equal(calls.resets, 2);
});

test("source file contains zero .innerHTML= / rawHTML( / .outerHTML= sinks", () => {
  const src = readFileSync(
    "src/lupin_app/static/js/multiplexer/render/templates/missedBadge.ts",
    "utf8",
  );
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const banned = [/\.innerHTML\s*=/, /\brawHTML\s*\(/, /\.outerHTML\s*=/];
  for (const re of banned) {
    assert.equal(re.test(stripped), false, `safe-write violation: ${re} in missedBadge.ts`);
  }
});
