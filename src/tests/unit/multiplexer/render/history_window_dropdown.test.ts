// P0 5ebd2aff (2026-09-10) — Rick's ruling 1: the legacy history-window picker.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/history_window_dropdown.test.ts`.
//
// These pin the picker to legacy's markup (ids, classes, option order), the
// open / pick / close behaviour, and that no click inside it collapses the
// section header it sits in.

import { test, before, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createHistoryWindowDropdown } from "../../../../lupin_app/static/js/multiplexer/render/historyWindowDropdown";
import type { HistoryWindow } from "../../../../lupin_app/static/js/multiplexer/stores/historyWindow";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
});
afterEach(() => {
  if (globalThis.document !== undefined) document.body.replaceChildren();
});

function fakeStore(initial: HistoryWindow = 48) {
  let current = initial;
  const calls: HistoryWindow[] = [];
  return {
    calls,
    set(w: HistoryWindow) { current = w; },
    store: {
      historyWindow    : () => current,
      setHistoryWindow : (w: HistoryWindow) => { calls.push(w); current = w; },
    },
  };
}

function mount(initial: HistoryWindow = 48) {
  const f      = fakeStore(initial);
  const parent = document.createElement("div");
  document.body.appendChild(parent);
  const handle = createHistoryWindowDropdown(f.store, document);
  parent.appendChild(handle.element);
  const menu    = handle.element.querySelector("#history-dropdown-menu") as HTMLElement;
  const display = handle.element.querySelector("button.dropdown-display") as HTMLButtonElement;
  const items   = Array.from(menu.querySelectorAll(".dropdown-item")) as HTMLElement[];
  return { ...f, parent, handle, menu, display, items };
}

const click = (el: Element) => el.dispatchEvent(new Event("click", { bubbles: true }));

test("markup matches legacy: ids, classes, six options in order, the current one selected", () => {
  const { handle, menu, display, items } = mount(48);
  assert.equal(handle.element.id, "history-window-dropdown");
  assert.ok(handle.element.classList.contains("history-window-dropdown"));
  assert.ok(menu.classList.contains("dropdown-menu"));
  assert.deepEqual(items.map(i => i.textContent), ["Today", "Last 24 hours", "Last 2 days", "Last week", "Last month", "All time"]);
  assert.equal(display.querySelector(".dropdown-display-label")!.textContent, "Last 2 days");
  assert.equal(display.querySelector(".dropdown-arrow")!.textContent, "▼");
  assert.deepEqual(items.map(i => i.classList.contains("selected")), [false, false, true, false, false, false]);
  assert.ok(!menu.classList.contains("show"), "the menu starts closed");
  handle.dispose();
});

test("clicking the display opens the menu, and clicking it again closes it", () => {
  const { handle, menu, display } = mount();
  click(display);
  assert.ok(menu.classList.contains("show"));
  click(display);
  assert.ok(!menu.classList.contains("show"));
  handle.dispose();
});

test("picking All time closes the menu, sets null on the store, and repaints", () => {
  const { handle, menu, display, items, calls } = mount(48);
  click(display);
  click(items[5]!);
  assert.deepEqual(calls, [null]);
  assert.ok(!menu.classList.contains("show"));
  assert.equal(display.querySelector(".dropdown-display-label")!.textContent, "All time");
  assert.equal(display.querySelector(".dropdown-arrow")!.textContent, "▼", "the arrow survives a change");
  assert.deepEqual(items.map(i => i.classList.contains("selected")), [false, false, false, false, false, true]);
  handle.dispose();
});

test("a click outside the dropdown closes an open menu", () => {
  const { handle, menu, display } = mount();
  click(display);
  const elsewhere = document.createElement("p");
  document.body.appendChild(elsewhere);
  click(elsewhere);
  assert.ok(!menu.classList.contains("show"));
  handle.dispose();
});

test("no click inside the dropdown reaches an ancestor — the header never collapses from it", () => {
  const { handle, parent, display, items } = mount();
  let heard = 0;
  parent.addEventListener("click", () => { heard++; });
  click(display);
  click(items[0]!);
  assert.equal(heard, 0);
  handle.dispose();
});

test("sync repaints after the store changes elsewhere", () => {
  const { handle, display, items, set } = mount(48);
  set("today");
  handle.sync();
  assert.equal(display.querySelector(".dropdown-display-label")!.textContent, "Today");
  assert.ok(items[0]!.classList.contains("selected"));
  handle.dispose();
});

test("dispose detaches the outside-click listener", () => {
  const { handle, menu, display } = mount();
  handle.dispose();
  click(display);
  click(document.body);
  assert.ok(menu.classList.contains("show"), "after dispose an outside click no longer closes it");
});
