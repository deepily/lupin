// Multiplexer Phase 5 — render/dom.ts unit tests.
// AC5 floor: ≥3 tests. Uses happy-dom global registrator for document API.

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  replaceChildren,
  keyedListMerge,
  type KeyedEntry,
} from "../../../../lupin_app/static/js/multiplexer/render/dom";

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
  assert.ok( parent.children[0] === refC );
  assert.ok( parent.children[1] === refA );
  assert.ok( parent.children[2] === refB );
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

// ---------------------------------------------------------------------------
// P0 8cb5c22e — keyedListMerge moves ONLY out-of-position children. Re-appending
// a child already in place detaches and re-inserts it, which in a browser drops
// its scroll position and restarts its animations (the focus-mode flicker).
// ---------------------------------------------------------------------------

function ids(parent: Element): string[] {
  return Array.from(parent.children).map(c => c.getAttribute("data-id-hash") ?? "");
}

async function childListMoves(parent: Element, run: () => void): Promise<string[]> {
  const moved: string[] = [];
  const observer = new MutationObserver((records) => {
    for (const r of records) {
      for (const n of Array.from(r.removedNodes)) moved.push(`-${(n as Element).getAttribute("data-id-hash")}`);
    }
  });
  observer.observe(parent, { childList: true });
  run();
  await new Promise<void>(resolve => setTimeout(resolve, 0));
  observer.disconnect();
  return moved;
}

test("keyedListMerge: children already in target order are never detached", async () => {
  const parent = document.createElement("ul");
  const entries: Item[] = [ { idHash: "a", text: "1" }, { idHash: "b", text: "2" }, { idHash: "c", text: "3" } ];
  keyedListMerge({ parent, entries, create: makeEl });

  const moved = await childListMoves(parent, () => keyedListMerge({ parent, entries, create: makeEl }));

  assert.deepEqual(moved, []);
  assert.deepEqual(ids(parent), [ "a", "b", "c" ]);
});

test("keyedListMerge: raising one child to the top moves only that child", async () => {
  const parent = document.createElement("ul");
  keyedListMerge({ parent, entries: [ { idHash: "a", text: "" }, { idHash: "b", text: "" }, { idHash: "c", text: "" } ], create: makeEl });

  const moved = await childListMoves(parent, () => keyedListMerge({
    parent,
    entries: [ { idHash: "c", text: "" }, { idHash: "a", text: "" }, { idHash: "b", text: "" } ],
    create : makeEl,
  }));

  assert.deepEqual(moved, [ "-c" ]);
  assert.deepEqual(ids(parent), [ "c", "a", "b" ]);
});

test("keyedListMerge: a full reversal plus a new child and an orphan still lands in target order", () => {
  const parent = document.createElement("ul");
  keyedListMerge({ parent, entries: [ { idHash: "a", text: "" }, { idHash: "b", text: "" }, { idHash: "c", text: "" }, { idHash: "x", text: "" } ], create: makeEl });

  keyedListMerge({
    parent,
    entries: [ { idHash: "c", text: "" }, { idHash: "n", text: "" }, { idHash: "b", text: "" }, { idHash: "a", text: "" } ],
    create : makeEl,
  });

  assert.deepEqual(ids(parent), [ "c", "n", "b", "a" ]);
});

// ---------------------------------------------------------------------------
// Row 11793820 — the merge finds existing children by an index, not a scan
// ---------------------------------------------------------------------------
//
// Each entry used to be located with `parent.querySelector(":scope > …")`, twice
// when an update ran: every child visited for every entry, O(S²) — about ten
// million visits at the 3,233 sender cards Rick's window returned. Counting the
// calls is the test, because a quadratic lookup is still CORRECT and every
// order/identity test above would stay green with it put back.

function countQuerySelector(parent: Element): { calls: number } {
  const counter  = { calls: 0 };
  const original = parent.querySelector.bind(parent);
  parent.querySelector = ((selector: string) => {
    counter.calls += 1;
    return original(selector);
  }) as typeof parent.querySelector;
  return counter;
}

test("keyedListMerge: 1,000 kept children are found with no per-entry querySelector", () => {
  const parent  = document.createElement("ul");
  const entries = Array.from({ length: 1000 }, (_, i) => ({ idHash: `k${i}`, text: `t${i}` }));
  keyedListMerge({ parent, entries, create: makeEl });
  const before  = Array.from(parent.children);

  const counter = countQuerySelector(parent);
  keyedListMerge({ parent, entries, create: makeEl, update: () => { /* keep the node */ } });

  assert.equal(counter.calls, 0, `the merge called parent.querySelector ${counter.calls} times`);
  assert.deepEqual(Array.from(parent.children), before, "a kept child lost its node identity");
});

test("keyedListMerge: an update that replaces its node is sequenced by the replacement, still with no scan", () => {
  const parent  = document.createElement("ul");
  const entries = Array.from({ length: 1000 }, (_, i) => ({ idHash: `k${i}`, text: `t${i}` }));
  keyedListMerge({ parent, entries, create: makeEl });

  // Reverse the order AND replace every other node — the replacement has to be
  // found where the old node stood and then moved, or the order comes out wrong.
  const reversed = [ ...entries ].reverse();
  const fresh    = new Map<string, Element>();
  const counter  = countQuerySelector(parent);
  keyedListMerge({
    parent,
    entries: reversed,
    create : makeEl,
    update : (el, entry) => {
      if (Number(entry.idHash.slice(1)) % 2 !== 0) return;
      const replacement = makeEl({ idHash: entry.idHash, text: `fresh ${entry.text}` });
      fresh.set(entry.idHash, replacement);
      el.replaceWith(replacement);
    },
  });

  assert.equal(counter.calls, 0, `the merge called parent.querySelector ${counter.calls} times`);
  assert.deepEqual(ids(parent), reversed.map(e => e.idHash));
  for (const [ key, el ] of fresh) {
    assert.equal(parent.querySelector(`:scope > [data-id-hash="${key}"]`), el, `${key}: the replacement is not the live child`);
  }
  assert.equal(parent.children.length, 1000);
});
