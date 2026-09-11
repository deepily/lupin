// 360de81b — the minimized row a queued Action Required card shows while another card holds the slot.
// Expected values are typed from legacy notifications.js renderMinimizedNotificationDOM (:21498) and
// formatTimeoutDisplay (:21546), never read off the template, so the two cannot agree by construction.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderActionRequiredQueueRow,
  formatQueueTimeout,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/actionRequiredQueueRow";
import type { ActionRequiredItem } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeItem(over: Partial<ActionRequiredItem> = {}): ActionRequiredItem {
  return {
    id_hash         : "ar2",
    prompt          : "Proceed?",
    response_type   : "yes_no",
    questions       : [],
    expires_at      : null,
    timeout_seconds : 30,
    state           : "pending",
    ...over,
  };
}

function part(el: HTMLElement, name: string): string {
  return el.querySelector(`.action-required-minimized-${name}`)!.textContent ?? "";
}

test("a queued row carries its id, a #N position, the prompt, the timeout and legacy's no-jumping tooltip", () => {
  const el = renderActionRequiredQueueRow(makeItem(), 3);
  assert.ok(el.classList.contains("action-required-minimized"));
  assert.equal(el.getAttribute("data-id-hash"), "ar2");
  assert.equal(el.getAttribute("data-testid"), "multiplexer-action-required-queued");
  assert.equal(part(el, "position"), "#3");
  assert.equal(part(el, "message"), "Proceed?");
  assert.equal(part(el, "timeout"), "30s");
  assert.equal(el.getAttribute("title"), "Please respond to the current notification first");
  assert.equal(el.querySelectorAll("button, input").length, 0, "nothing to answer out of turn");
});

test("the type icon is legacy's: ❓ yes_no, 💬 open_ended, 📋 multiple_choice, 📢 anything else (so batch gets 📢)", () => {
  const icons = (["yes_no", "open_ended", "multiple_choice", "open_ended_batch"] as const)
    .map(rt => part(renderActionRequiredQueueRow(makeItem({ response_type: rt }), 1), "icon"));
  assert.deepEqual(icons, ["❓", "💬", "📋", "📢"]);
});

test("a prompt over 60 characters is cut to 57 plus '...'; exactly 60 is left whole", () => {
  const sixty     = "x".repeat(60);
  const sixtyOne  = "y".repeat(61);
  assert.equal(part(renderActionRequiredQueueRow(makeItem({ prompt: sixty }), 1), "message"), sixty);
  assert.equal(part(renderActionRequiredQueueRow(makeItem({ prompt: sixtyOne }), 1), "message"), "y".repeat(57) + "...");
});

test("formatQueueTimeout: whole minutes at 60 s and above, seconds below", () => {
  assert.deepEqual([formatQueueTimeout(45), formatQueueTimeout(59), formatQueueTimeout(60), formatQueueTimeout(150)], ["45s", "59s", "1m", "2m"]);
});

test("a prompt carrying markup renders as text, never as elements", () => {
  const el = renderActionRequiredQueueRow(makeItem({ prompt: "<img src=x onerror=alert(1)>" }), 1);
  assert.equal(el.querySelector("img"), null);
  assert.equal(part(el, "message"), "<img src=x onerror=alert(1)>");
});

test("AC2e: source file contains zero .innerHTML= / rawHTML( / .outerHTML= sinks", () => {
  const src = readFileSync(
    "src/lupin_app/static/js/multiplexer/render/templates/actionRequiredQueueRow.ts",
    "utf8",
  );
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  for (const re of [/\.innerHTML\s*=/, /\brawHTML\s*\(/, /\.outerHTML\s*=/]) {
    assert.equal(re.test(stripped), false, `AC2e violation: pattern ${re} found in actionRequiredQueueRow.ts`);
  }
});
