// Multiplexer Phase 5 — tiny DOM diff utilities.
//
// `keyedListMerge` matches existing children to incoming items by `data-id-hash`
// (per F12 — every element participating in keyed merge MUST carry the
// attribute). Re-orders + appends new + removes orphans. Native DOM ops only;
// no virtual DOM, no framework.
//
// `replaceChildren` is a thin wrapper over the native `Element.replaceChildren()`
// (Baseline 2020); kept for grep-able intent ("renderer is doing a wholesale
// replacement here") and a single seam for future instrumentation.
//
// Q-B render strategy uses these primitives — hydrate=full (replaceChildren),
// added/updated/expired=keyed (keyedListMerge), tick=text-node only (NEITHER —
// renderer pokes a single .textContent directly).

/**
 * Replace `parent`'s children with the contents of `incoming`.
 *
 * Thin wrapper over `Element.replaceChildren()`. Prefer this over manual
 * `innerHTML = ""` + appending — avoids the TT sink + flushes layout once.
 *
 * Requires:
 *   - `parent` is an Element or DocumentFragment
 *   - `incoming` is a Node or DocumentFragment
 *
 * Ensures:
 *   - parent's previous children are detached
 *   - incoming.firstChild..lastChild become parent's children
 */
export function replaceChildren(parent: Element | DocumentFragment, incoming: Node): void {
  parent.replaceChildren(incoming);
}

/**
 * Keyed list merge — reconcile `parent`'s child elements against `entries`
 * keyed by `data-id-hash`.
 *
 * Algorithm:
 *   1. Build a map of existing children by `data-id-hash` value
 *   2. Walk `entries` in target order; for each:
 *      a. If existing child has matching id_hash, move into position +
 *         optionally re-render its body via `update()`
 *      b. Otherwise, render via `create()` and insert at the position
 *   3. Remove any existing children whose id_hash isn't in the new set
 *
 * Per F12 invariant: every renderable element MUST carry `data-id-hash`. The
 * `data-id-hash` value is the canonical key; legacy `id="..."` attribute is
 * NOT consulted (keyed-merge correctness depends on a single key surface).
 *
 * Requires:
 *   - `parent` is the element holding the keyed list
 *   - `entries` is the target ordering, each entry having a unique `idHash`
 *   - `create(entry)` returns a new element with `data-id-hash="${entry.idHash}"`
 *     already set
 *   - `update(el, entry)` mutates `el` in place; OPTIONAL — when omitted,
 *     existing elements are left untouched on match
 *
 * Ensures:
 *   - parent's children after the call exactly match `entries` order
 *   - elements whose id_hash appears in both old + new are reused (DOM
 *     identity preserved; no flicker; child state like focus survives)
 */
export interface KeyedEntry {
  readonly idHash : string;
}

export interface KeyedMergeOptions<T extends KeyedEntry> {
  parent : Element;
  entries: ReadonlyArray<T>;
  create : (entry: T) => Element;
  update?: (el: Element, entry: T) => void;
}

export function keyedListMerge<T extends KeyedEntry>(opts: KeyedMergeOptions<T>): void {
  const { parent, entries, create, update } = opts;

  const wantedKeys = new Set<string>();
  for (const entry of entries) wantedKeys.add(entry.idHash);

  // 1. Remove orphans first — children whose id_hash isn't in the new set, OR
  //    children with no data-id-hash at all (e.g. stale empty-state elements).
  for (const child of Array.from(parent.children)) {
    const key = child.getAttribute("data-id-hash");
    if (key === null || !wantedKeys.has(key)) {
      child.remove();
    }
  }

  // 2. Collect the target sequence in entry order. For each entry: create-or-
  //    discover-and-update. `update()` callbacks may call
  //    `existing.replaceWith(fresh)` — we re-discover via querySelector so the
  //    sequencing step in (3) sees the live element, not a detached stale ref.
  const targetEls: Element[] = [];
  for (const entry of entries) {
    const selector = `:scope > [data-id-hash="${cssEscape(entry.idHash)}"]`;
    let el: Element | null = parent.querySelector(selector);
    if (el === null) {
      el = create(entry);
      if (el.getAttribute("data-id-hash") !== entry.idHash) {
        el.setAttribute("data-id-hash", entry.idHash);
      }
    } else if (update !== undefined) {
      update(el, entry);
      const fresh = parent.querySelector(selector);
      if (fresh !== null) el = fresh;
    }
    targetEls.push(el);
  }

  // 3. Re-attach in target order. `appendChild` on an existing child MOVES
  //    it (DOM identity preserved); on a fresh element, inserts. Successive
  //    appends in entry order produce the desired sequence.
  for (const el of targetEls) {
    parent.appendChild(el);
  }
}

// CSS.escape polyfill — same as NotificationsListRenderer's cssEscape.
function cssEscape(value: string): string {
  if (typeof globalThis !== "undefined" && typeof (globalThis as { CSS?: { escape?: (s: string) => string } }).CSS?.escape === "function") {
    return (globalThis as { CSS: { escape: (s: string) => string } }).CSS.escape(value);
  }
  return value.replace(/[^a-zA-Z0-9_-]/g, (m) => "\\" + m);
}
