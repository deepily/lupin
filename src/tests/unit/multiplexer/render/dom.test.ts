// Multiplexer Phase 5 — render/dom.ts unit tests.
// AC5 floor: ≥3 tests. Uses happy-dom global registrator for document API.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  replaceChildren,
  keyedListMerge,
  type KeyedEntry,
} from "../../../../fastapi_app/static/js/multiplexer/render/dom";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

interface Item extends KeyedEntry {
  readonly idHash : string;
  readonly text   : string;
}

function makeEl(entry: Item): HTMLElement {
  const el = document.createElement("div");
  el.setAttribute("data-id-hash", entry.idHash);
  el.textContent = entry.text;
  return el;
}

// ---------------------------------------------------------------------------
// replaceChildren
// ---------------------------------------------------------------------------

test("replaceChildren swaps in a single Node", () => {
  const parent = document.createElement("section");
  parent.appendChild(document.createElement("p"));
  parent.appendChild(document.createElement("p"));
  const incoming = document.createElement("h1");
  replaceChildren(parent, incoming);
  assert.equal(parent.children.length, 1);
  assert.equal(parent.firstElementChild!.tagName, "H1");
});

// ---------------------------------------------------------------------------
// keyedListMerge — F12 invariant: every element carries data-id-hash
// ---------------------------------------------------------------------------

test("keyedListMerge: empty parent + entries produces ordered children with data-id-hash", () => {
  const parent = document.createElement("ul");
  const entries: Item[] = [
    { idHash: "a", text: "alpha" },
    { idHash: "b", text: "beta"  },
    { idHash: "c", text: "gamma" },
  ];
  keyedListMerge({ parent, entries, create: makeEl });
  assert.equal(parent.children.length, 3);
  assert.equal(parent.children[0]!.getAttribute("data-id-hash"), "a");
  assert.equal(parent.children[1]!.getAttribute("data-id-hash"), "b");
  assert.equal(parent.children[2]!.getAttribute("data-id-hash"), "c");
});

test("keyedListMerge: re-order existing children preserves DOM identity (no flicker)", () => {
  const parent = document.createElement("ul");
  // Initial state.
  keyedListMerge({
    parent,
    entries: [{ idHash: "a", text: "alpha" }, { idHash: "b", text: "beta" }, { idHash: "c", text: "gamma" }],
    create : makeEl,
  });
  const refA = parent.querySelector('[data-id-hash="a"]')!;
  const refB = parent.querySelector('[data-id-hash="b"]')!;
  const refC = parent.querySelector('[data-id-hash="c"]')!;

  // Re-order: c, a, b
  keyedListMerge({
    parent,
    entries: [{ idHash: "c", text: "gamma" }, { idHash: "a", text: "alpha" }, { idHash: "b", text: "beta" }],
    create : makeEl,
  });

  // Same DOM nodes preserved (identity check).
  assert.strictEqual(parent.children[0], refC);
  assert.strictEqual(parent.children[1], refA);
  assert.strictEqual(parent.children[2], refB);
});

test("keyedListMerge: removes orphans (entries not in new set)", () => {
  const parent = document.createElement("ul");
  keyedListMerge({
    parent,
    entries: [{ idHash: "a", text: "alpha" }, { idHash: "b", text: "beta" }, { idHash: "c", text: "gamma" }],
    create : makeEl,
  });
  // Drop "b".
  keyedListMerge({
    parent,
    entries: [{ idHash: "a", text: "alpha" }, { idHash: "c", text: "gamma" }],
    create : makeEl,
  });
  assert.equal(parent.children.length, 2);
  assert.equal(parent.children[0]!.getAttribute("data-id-hash"), "a");
  assert.equal(parent.children[1]!.getAttribute("data-id-hash"), "c");
});

test("keyedListMerge: update() callback fires on matching keys; create() fires on new", () => {
  const parent = document.createElement("ul");
  const created : string[] = [];
  const updated : string[] = [];
  const create = (e: Item): HTMLElement => {
    created.push(e.idHash);
    return makeEl(e);
  };
  const update = (el: Element, e: Item): void => {
    updated.push(e.idHash);
    el.textContent = e.text;
  };

  keyedListMerge({ parent, entries: [{ idHash: "a", text: "1" }], create });
  assert.deepEqual(created, [ "a" ]);
  assert.deepEqual(updated, [           ]);

  keyedListMerge({
    parent,
    entries: [{ idHash: "a", text: "2" }, { idHash: "b", text: "1" }],
    create,
    update,
  });
  // "a" already present → update fires; "b" is new → create fires.
  assert.deepEqual(created, [ "a", "b" ]);
  assert.deepEqual(updated, [ "a"      ]);
  assert.equal(parent.children[0]!.textContent, "2");
});
