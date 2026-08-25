// Multiplexer Phase 6c Node A — personaModal template tests.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/templates_persona_modal.test.ts`.
//
// AC-A3 target: ≥10 cases (incl #11 null-persona-omission edge tested via
// renderer suite since template assumes non-null input by contract).

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  renderPersonaPopover,
  type PersonaPopoverInput,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/personaModal";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

function makeInput( over: Partial<PersonaPopoverInput> = {} ): PersonaPopoverInput {
  return {
    sender_id : "sess_42",
    name      : "Tiberius",
    voice_id  : "vid_42",
    icon      : "🌑",
    color     : "#3F51B5",
    borrowed  : false,
    ...over,
  };
}

// AC-A3 #1
test("popover root carries id derived from slugified sender_id, popover='auto', class='persona-popover'", () => {
  const root = renderPersonaPopover(makeInput({ sender_id: "claude.code@lupin.deepily.ai#c7333045" }));
  assert.equal(root.id, "persona-popover-claude-code-lupin-deepily-ai-c7333045");
  assert.equal(root.getAttribute("popover"), "auto");
  assert.ok(root.classList.contains("persona-popover"));
});

// AC-A3 #2
test("accent strip carries the inline persona color (NOT --persona-color CSS var)", () => {
  const root = renderPersonaPopover(makeInput({ color: "#ab1234" }));
  const accent = root.querySelector<HTMLElement>(".persona-popover-accent")!;
  // happy-dom preserves the literal value set via .style.backgroundColor;
  // real browsers normalize hex → rgb(). Both are valid inline assignments.
  assert.equal(accent.style.backgroundColor, "#ab1234");
});

// AC-A3 #3
test("name row renders '{icon} {name}' with inline persona color", () => {
  const root = renderPersonaPopover(makeInput({ icon: "🌑", name: "Tiberius", color: "#3F51B5" }));
  const nameEl = root.querySelector<HTMLElement>(".persona-popover-name")!;
  assert.equal(nameEl.textContent, "🌑 Tiberius");
  // happy-dom preserves the literal hex; real browsers normalize to rgb().
  assert.equal(nameEl.style.color, "#3F51B5");
});

// AC-A3 #4
test("voice_id row always renders with 'Voice:' prefix", () => {
  const root = renderPersonaPopover(makeInput({ voice_id: "abcd1234" }));
  const voiceEl = root.querySelector<HTMLElement>(".persona-popover-voice-id")!;
  assert.equal(voiceEl.textContent, "Voice: abcd1234");
});

// AC-A3 #5
test("display_name row OMITTED when display_name absent", () => {
  const root = renderPersonaPopover(makeInput());
  assert.ok( root.querySelector(".persona-popover-display-name") === null );
});

// AC-A3 #6
test("display_name row OMITTED when display_name === name (avoid redundant rendering)", () => {
  const root = renderPersonaPopover(makeInput({ name: "Tiberius", display_name: "Tiberius" }));
  assert.ok( root.querySelector(".persona-popover-display-name") === null );
});

// AC-A3 #7
test("display_name row RENDERED when it differs from name", () => {
  const root = renderPersonaPopover(makeInput({ name: "tiberius", display_name: "Tiberius (Lupin session)" }));
  const displayEl = root.querySelector<HTMLElement>(".persona-popover-display-name");
  assert.notEqual(displayEl, null);
  assert.equal(displayEl!.textContent, "Tiberius (Lupin session)");
});

// AC-A3 #8
test("borrowed=false renders the borrowed div with `hidden` attribute set", () => {
  const root = renderPersonaPopover(makeInput({ borrowed: false }));
  const borrowedEl = root.querySelector<HTMLElement>(".persona-popover-borrowed")!;
  assert.ok(borrowedEl.hasAttribute("hidden"));
});

// AC-A3 #9
test("borrowed=true renders the borrowed div WITHOUT `hidden` attribute (visible)", () => {
  const root = renderPersonaPopover(makeInput({ borrowed: true }));
  const borrowedEl = root.querySelector<HTMLElement>(".persona-popover-borrowed")!;
  assert.equal(borrowedEl.hasAttribute("hidden"), false);
});

// AC-A3 #10
test("close button uses declarative popovertargetaction='hide' with matching popovertarget id", () => {
  const root = renderPersonaPopover(makeInput({ sender_id: "alice@x" }));
  const closeBtn = root.querySelector<HTMLButtonElement>(".persona-popover-close")!;
  assert.equal(closeBtn.getAttribute("popovertargetaction"), "hide");
  assert.equal(closeBtn.getAttribute("popovertarget"), root.id);
  assert.equal(closeBtn.type, "button", "type='button' guards against implicit form submission");
});

// AC-A3 #11 — empty-icon path (name renders WITHOUT a leading space)
test("empty-string icon: name row renders just the name (no leading space)", () => {
  const root = renderPersonaPopover(makeInput({ icon: "", name: "Tiberius" }));
  const nameEl = root.querySelector<HTMLElement>(".persona-popover-name")!;
  assert.equal(nameEl.textContent, "Tiberius");
});

// AC-A3 #12 — display_name empty string is treated as absent
test("display_name === '' (empty string) does NOT render the display-name row", () => {
  const root = renderPersonaPopover(makeInput({ name: "Tiberius", display_name: "" }));
  assert.ok( root.querySelector(".persona-popover-display-name") === null );
});
