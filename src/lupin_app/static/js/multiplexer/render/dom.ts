/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.
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
  //    The survivors are indexed by key in the SAME pass (row 11793820): step 2
  //    used to find each entry with `parent.querySelector(":scope > …")`, twice
  //    per entry — a scan of every child for every entry, O(S²), ~10M child
  //    visits at 3,233 sender cards. First match wins, as querySelector did.
  const byKey = new Map<string, Element>();
  for (const child of Array.from(parent.children)) {
    const key = child.getAttribute("data-id-hash");
    if (key === null || !wantedKeys.has(key)) {
      child.remove();
    } else if (!byKey.has(key)) {
      byKey.set(key, child);
    }
  }

  // 2. Collect the target sequence in entry order. For each entry: create-or-
  //    discover-and-update. `update()` callbacks may call
  //    `existing.replaceWith(fresh)` — the replacement is then found where the
  //    old node stood, so the sequencing step in (3) sees the live element, not
  //    a detached stale ref.
  const targetEls: Element[] = [];
  for (const entry of entries) {
    let el: Element | undefined = byKey.get(entry.idHash);
    if (el === undefined) {
      el = create(entry);
      /* c8 ignore next 3 */ // defensive belt: contract says create() returns elements with data-id-hash already set; this branch is a safety net for callers that forget — never hit in tests because all test fixtures comply.
      if (el.getAttribute("data-id-hash") !== entry.idHash) {
        el.setAttribute("data-id-hash", entry.idHash);
      }
    } else if (update !== undefined) {
      el = updateAndLocate(parent, el, entry, update);
    }
    targetEls.push(el);
  }

  // 3. Place in target order, moving ONLY what is out of position. P0 8cb5c22e
  //    (2026-09-10): this used to re-append every element, which detaches and
  //    re-inserts even a child already in place — a browser drops its scroll
  //    position and restarts its animations, so an unchanged card flickered on
  //    every render. Invariant: the element children before `cursor` are exactly
  //    targetEls[0..i-1], in order. A target equal to `cursor` is already in
  //    place; any other target sits after `cursor` and is moved in front of it
  //    (`insertBefore(el, null)` appends a fresh element at the end).
  let cursor: Element | null = parent.firstElementChild;
  for (const el of targetEls) {
    if (el === cursor) {
      cursor = cursor.nextElementSibling;
    } else {
      placeBefore(parent, el, cursor);
    }
  }
}

// `Element.moveBefore` (Chrome 133+) is not in this TypeScript DOM lib yet.
type MovableParent = Element & { moveBefore?: (node: Node, child: Node | null) => void };

// Put `el` in front of `cursor`. Row 11793820: `insertBefore` detaches a child
// before re-inserting it, so a card that moves to the top loses the scroll
// position inside it (Chrome, bundle 3d959d529554: 100 → 0). `moveBefore` moves
// an element that is ALREADY a child without detaching it, keeping scroll, focus
// and running animations. It throws where such a move is not allowed (for
// example a parent not in the document), and the plain insert still places the
// element. A new element was never attached, so it is simply inserted.
function placeBefore(parent: MovableParent, el: Element, cursor: Element | null): void {
  if (el.parentNode === parent && typeof parent.moveBefore === "function") {
    try {
      parent.moveBefore(el, cursor);
      return;
    } catch {
      // fall through to insertBefore
    }
  }
  parent.insertBefore(el, cursor);
}

// Run `update(el)` and return the element that now holds `el`'s place under
// `parent`. An update that keeps its node returns `el`. An update that called
// `el.replaceWith(fresh)` leaves `fresh` exactly where `el` stood, so it is read
// off the neighbour captured beforehand — O(1). Anything else an update might do
// (remove the node, insert elsewhere) falls back to the old keyed scan.
function updateAndLocate<T extends KeyedEntry>(
  parent : Element,
  el     : Element,
  entry  : T,
  update : (el: Element, entry: T) => void,
): Element {
  const before = el.previousElementSibling;
  update(el, entry);
  if (el.parentElement === parent) return el;
  const inPlace = before === null ? parent.firstElementChild : before.nextElementSibling;
  if (inPlace !== null && inPlace.getAttribute("data-id-hash") === entry.idHash) return inPlace;
  /* c8 ignore next 2 */ // defensive: no caller removes or relocates the node inside update(); kept so a future one degrades to the pre-11793820 lookup instead of sequencing a detached element.
  const found = parent.querySelector(`:scope > [data-id-hash="${cssEscape(entry.idHash)}"]`);
  return found ?? el;
}

// CSS.escape polyfill — same as NotificationsListRenderer's cssEscape.
/* c8 ignore start */ // CSS.escape polyfill: production browsers always provide CSS.escape (Baseline 2020); the fallback regex path exists only for non-DOM Node contexts where keyedListMerge is never actually called (this module is consumed exclusively by browser-side renderer code).
function cssEscape(value: string): string {
  if (typeof globalThis !== "undefined" && typeof (globalThis as { CSS?: { escape?: (s: string) => string } }).CSS?.escape === "function") {
    return (globalThis as { CSS: { escape: (s: string) => string } }).CSS.escape(value);
  }
  return value.replace(/[^a-zA-Z0-9_-]/g, (m) => "\\" + m);
}
/* c8 ignore stop */
