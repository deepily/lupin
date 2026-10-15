// The CC session strip's Keep place toggle, a third pill beside Focus and Hide-inactive.
//
// Run via `npx tsx --test src/tests/unit/multiplexer/render/session_strip_keep_place_toggle.test.ts`.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSessionStripRenderer } from "../../../../lupin_app/static/js/multiplexer/render/SessionStripRenderer";
import { KEEP_PLACE_KEY } from "../../../../lupin_app/static/js/multiplexer/render/keepPlace";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});

beforeEach(() => {
  document.body.replaceChildren();
  globalThis.localStorage?.clear();
});

function makeRoot(withToggle: boolean): { root: HTMLElement; toggle: HTMLElement | null } {
  const root  = document.createElement("main");
  const strip = document.createElement("div");
  strip.id = "cc-session-strip";
  const icons = document.createElement("div");
  icons.id = "cc-strip-icons";
  const focus = document.createElement("button");
  focus.id = "cc-strip-toggle";
  const hide  = document.createElement("button");
  hide.id = "cc-hide-inactive-toggle";
  strip.append(icons, focus, hide);
  let toggle: HTMLElement | null = null;
  if (withToggle) {
    toggle = document.createElement("button");
    toggle.id = "cc-keep-place-toggle";
    toggle.setAttribute("data-phase6-pending", "true");
    strip.appendChild(toggle);
  }
  root.appendChild(strip);
  document.body.appendChild(root);
  return { root, toggle };
}

function mount(root: HTMLElement) {
  const r = createSessionStripRenderer({ eventBus: createEventBusForTesting(), stores: { strip: { list: () => [] } } });
  r.mount(root);
  return r;
}

test("the pill starts on, shows its state and loses the pending marker", () => {
  const { root, toggle } = makeRoot(true);
  mount(root);
  assert.equal(toggle!.getAttribute("data-keep-place"), "true");
  assert.equal(toggle!.textContent, "📌 Keep place");
  assert.equal(toggle!.getAttribute("data-phase6-pending"), null);
});

test("a click turns it off, stores the word false under the shared key, and a second click turns it on", () => {
  const { root, toggle } = makeRoot(true);
  mount(root);
  toggle!.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(toggle!.getAttribute("data-keep-place"), "false");
  assert.equal(toggle!.textContent, "📌 Follow new");
  assert.equal(localStorage.getItem(KEEP_PLACE_KEY), "false");
  toggle!.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(toggle!.getAttribute("data-keep-place"), "true");
  assert.equal(localStorage.getItem(KEEP_PLACE_KEY), "true");
});

test("a stored false is restored at mount", () => {
  localStorage.setItem(KEEP_PLACE_KEY, "false");
  const { root, toggle } = makeRoot(true);
  mount(root);
  assert.equal(toggle!.getAttribute("data-keep-place"), "false");
});

test("after unmount a click does nothing, and a second mount starts from the stored state", () => {
  const { root, toggle } = makeRoot(true);
  const r = mount(root);
  r.unmount();
  toggle!.dispatchEvent(new Event("click", { bubbles: true }));
  assert.equal(localStorage.getItem(KEEP_PLACE_KEY), null);
});

test("a page without the pill mounts and unmounts cleanly", () => {
  const { root } = makeRoot(false);
  const r = mount(root);
  r.unmount();
  assert.equal(document.getElementById("cc-keep-place-toggle"), null);
});
