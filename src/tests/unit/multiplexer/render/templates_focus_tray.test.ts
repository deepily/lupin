// Multiplexer Phase 6c Node B — focusTray template tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/templates_focus_tray.test.ts`.
//
// AC-B3 target: ≥7 cases (Round-2 bumped from ≥6 per cascade ratification).

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { renderFocusTray } from "../../../../fastapi_app/static/js/multiplexer/render/templates/focusTray";
import type { SenderRecord, VoicePersona } from "../../../../fastapi_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makePersona( over: Partial<VoicePersona> = {} ): VoicePersona {
  return {
    name     : "Tiberius",
    voice_id : "vid_42",
    icon     : "🌑",
    color    : "#3F51B5",
    borrowed : false,
    ...over,
  };
}

function makeSender( over: Partial<SenderRecord> = {} ): SenderRecord {
  return {
    sender_id                : "alice@x",
    display_name             : "Alice",
    last_active_ts           : 1_000_000,
    unread_count             : 0,
    conversation_mode_active : false,
    ...over,
  };
}

// AC-B3 #1
test("empty senders list renders the focus-tray-empty placeholder", () => {
  const root = renderFocusTray([]);
  assert.equal(root.className, "focus-tray-list");
  const empty = root.querySelector(".focus-tray-empty");
  assert.ok(empty, "expected .focus-tray-empty div for an empty list");
  assert.match(empty!.textContent ?? "", /No senders hidden/);
});

// AC-B3 #2
test("single sender renders a single .focus-tray-row button with the display_name", () => {
  const root = renderFocusTray([ makeSender({ sender_id: "a", display_name: "Alice" }) ]);
  const rows = root.querySelectorAll<HTMLButtonElement>(".focus-tray-row");
  assert.equal(rows.length, 1);
  assert.match(rows[0]!.textContent ?? "", /Alice/);
});

// AC-B3 #3
test("sender with voice_persona sets --persona-color on the button via style.setProperty", () => {
  const root = renderFocusTray([
    makeSender({ sender_id: "a", display_name: "Alice", voice_persona: makePersona({ color: "#ab1234" }) }),
  ]);
  const button = root.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  // style.getPropertyValue returns the custom-property value set via setProperty.
  assert.equal(button.style.getPropertyValue("--persona-color"), "#ab1234");
});

// AC-B3 #4 — F-Arnold-B-Stage2-2 currentColor fallback
test("sender WITHOUT persona leaves --persona-color unset so the currentColor fallback kicks in", () => {
  const root = renderFocusTray([ makeSender({ sender_id: "a", display_name: "Alice" }) ]);
  const button = root.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  assert.equal(button.style.getPropertyValue("--persona-color"), "",
    "--persona-color must NOT be set when persona is absent (CSS falls through to currentColor)");
  // The inline style attribute itself still carries the `color: var(...)` declaration.
  assert.match(button.getAttribute("style") ?? "", /color:\s*var\(--persona-color, currentColor\)/);
});

// AC-B3 #5
test("persona icon is prepended to the label with a separator space", () => {
  const root = renderFocusTray([
    makeSender({ sender_id: "a", display_name: "Alice", voice_persona: makePersona({ icon: "🌑" }) }),
  ]);
  const button = root.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  assert.match(button.textContent ?? "", /🌑 Alice/);
});

// AC-B3 #6
test("persona with empty-string icon renders label WITHOUT a leading space", () => {
  const root = renderFocusTray([
    makeSender({ sender_id: "a", display_name: "Alice", voice_persona: makePersona({ icon: "" }) }),
  ]);
  const button = root.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  // No leading whitespace.
  assert.equal((button.textContent ?? "").trim(), "Alice");
  assert.doesNotMatch(button.textContent ?? "", /^\s+Alice/);
});

// AC-B3 #7
test("each row carries the data-sender-id attribute for click-delegation routing", () => {
  const root = renderFocusTray([
    makeSender({ sender_id: "alice@x" }),
    makeSender({ sender_id: "bob@x", display_name: "Bob" }),
  ]);
  const rows = root.querySelectorAll<HTMLButtonElement>(".focus-tray-row");
  assert.equal(rows.length, 2);
  assert.equal(rows[0]!.getAttribute("data-sender-id"), "alice@x");
  assert.equal(rows[1]!.getAttribute("data-sender-id"), "bob@x");
});

// AC-B3 #8 — falls through to sender_id when display_name absent
test("sender with empty display_name falls back to sender_id as label", () => {
  const root = renderFocusTray([ makeSender({ sender_id: "fallback@x", display_name: "" }) ]);
  const button = root.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  assert.match(button.textContent ?? "", /fallback@x/);
});

// AC-B3 #9 — type="button" guards against implicit form submit
test("each row sets type='button' (prevents implicit form-submit semantics)", () => {
  const root = renderFocusTray([ makeSender() ]);
  const button = root.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  assert.equal(button.getAttribute("type"), "button");
});

// AC-B3 #10 — persona color empty-string is treated as no persona color
test("persona.color === '' (empty string) does NOT set the --persona-color custom property", () => {
  const root = renderFocusTray([
    makeSender({ sender_id: "a", display_name: "Alice", voice_persona: makePersona({ color: "" }) }),
  ]);
  const button = root.querySelector<HTMLButtonElement>(".focus-tray-row")!;
  assert.equal(button.style.getPropertyValue("--persona-color"), "");
});
