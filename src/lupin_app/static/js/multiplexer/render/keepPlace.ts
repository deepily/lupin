/* c8 ignore next */ // tsx phantom-branch artifact on file-header line.

// Keep place: a card arriving at the top must not move what the reader sees.
//
// The preference lives in localStorage under the key the legacy client reads, so one choice holds in both
// clients. Auto-scroll to the top is the default, so it is off unless the stored value is the word "true".

/** The localStorage key shared with the legacy client (notifications.js KEEP_PLACE_KEY). */
export const KEEP_PLACE_KEY = "notifications_keep_place";

/** The part of Storage this module reads. */
export interface KeepPlaceStorage {
  getItem( key: string ): string | null;
}

/**
 * Read the Keep place preference.
 *
 * Requires:
 *   - storage is a Storage-like object, or null when none is available
 *
 * Ensures:
 *   - returns true only for the stored word "true"
 *   - returns false for no value, any other value, a null storage, and a storage that throws
 */
export function readKeepPlace( storage: KeepPlaceStorage | null ): boolean {
  if ( storage === null ) return false;
  try {
    return storage.getItem( KEEP_PLACE_KEY ) === "true";
  } catch {
    return false;
  }
}

/**
 * Whether Keep place is on in this browser, read at the moment of asking.
 *
 * Ensures:
 *   - returns true only for the stored word "true"
 *   - returns false when the storage is unavailable or throws
 */
export function keepPlaceIsOn(): boolean {
  try {
    return readKeepPlace( globalThis.localStorage ?? null );
  } catch {
    return false;
  }
}

/** The strip's height; a card above it is scrolled off and a poor anchor. */
const NAV_OFFSET_PX = 100;

/** How many visible cards are remembered, so one that moves up can be skipped for the next. */
const MAX_CANDIDATES = 4;

/** A visible card, with where it was on screen and in the list. */
export interface PlaceCandidate {
  readonly el    : HTMLElement;
  readonly top   : number;
  readonly index : number;
}

interface ScrollRoot {
  scrollY    : number;
  scrollBy( x: number, y: number ): void;
}

/**
 * Says whether the reading pane is open, so the left column owns the scroll.
 */
function paneIsOpen( doc: Document ): boolean {
  const shell = doc.querySelector(".content-shell");
  return shell !== null && shell.classList.contains("pane-open");
}

/**
 * Remember which cards the reader is looking at, when they have scrolled away from the top.
 *
 * Requires:
 *   - mount is the element whose children are the sender cards
 *   - doc is the page document; win is its window (the scroll container when the reading pane is closed)
 *
 * Ensures:
 *   - returns null when the reader is at the top, so the list behaves as it always did
 *   - otherwise returns up to MAX_CANDIDATES cards whose top is at or below the strip, in list order
 *   - with the reading pane open the left column owns the scroll; otherwise the window does
 */
export function captureKeepPlace( mount: HTMLElement, doc: Document, win: ScrollRoot ): PlaceCandidate[] | null {
  const away = paneIsOpen(doc)
    ? ( doc.querySelector<HTMLElement>(".left-column")?.scrollTop ?? 0 ) > 0
    : win.scrollY > 0;
  if ( !away ) return null;
  const found: PlaceCandidate[] = [];
  const kids = Array.from(mount.children) as HTMLElement[];
  for ( let index = 0; index < kids.length && found.length < MAX_CANDIDATES; index++ ) {
    const top = kids[ index ]!.getBoundingClientRect().top;
    if ( top >= NAV_OFFSET_PX ) found.push({ el: kids[ index ]!, top, index });
  }
  return found;
}

/**
 * Put the reader back where they were after the cards were merged.
 *
 * Requires:
 *   - candidates came from captureKeepPlace on the same mount, before the merge
 *
 * Ensures:
 *   - the anchor is the first remembered card that is still in the list and did not move up it: the
 *     card that moved to the top is never its own anchor
 *   - the scroll container is moved by how far the anchor's top shifted; nothing happens without an anchor
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line.
export function restoreKeepPlace( mount: HTMLElement, candidates: PlaceCandidate[], doc: Document, win: ScrollRoot ): void {
  const kids = Array.from(mount.children);
  for ( const c of candidates ) {
    const now = kids.indexOf(c.el);
    if ( now === -1 || now < c.index ) continue;
    const delta = c.el.getBoundingClientRect().top - c.top;
    if ( delta === 0 ) return;
    if ( paneIsOpen(doc) ) {
      const column = doc.querySelector<HTMLElement>(".left-column");
      if ( column !== null ) column.scrollTop += delta;
    } else {
      win.scrollBy(0, delta);
    }
    return;
  }
}

/** Where each notification-history pane was scrolled, keyed by sender card and day. */
export type HistoryScroll = Map<string, number>;

/** The key one pane is remembered under: its sender card's key, then its day's key. */
function historyKey( cardKey: string, dayKey: string | null ): string {
  return `${cardKey}|${dayKey ?? ""}`;
}

/**
 * Remember how far each card's history is scrolled, before the cards are merged.
 *
 * Requires:
 *   - mount is the element whose children are the sender cards, each carrying data-id-hash
 *
 * Ensures:
 *   - returns an entry for each .date-accordion-messages pane that is scrolled away from its top
 *   - returns an empty map when nothing is scrolled, so there is nothing to restore
 */
export function captureHistoryScroll( mount: HTMLElement ): HistoryScroll {
  const found: HistoryScroll = new Map();
  for ( const card of Array.from(mount.children) as HTMLElement[] ) {
    const cardKey = card.getAttribute("data-id-hash");
    if ( cardKey === null ) continue;
    for ( const pane of Array.from(card.querySelectorAll<HTMLElement>(".date-accordion-messages")) ) {
      if ( pane.scrollTop > 0 ) {
        found.set(historyKey(cardKey, pane.closest(".date-accordion")?.getAttribute("data-date-key") ?? null), pane.scrollTop);
      }
    }
  }
  return found;
}

/**
 * Put each history pane back where it was scrolled to.
 *
 * Moving a card in the DOM, or replacing it with a fresh render, sets every scroller inside it back to the
 * top. So the offsets are written again after the merge, onto whichever pane now stands for that day.
 *
 * Requires:
 *   - remembered came from captureHistoryScroll on the same mount, before the merge
 *
 * Ensures:
 *   - a pane that still exists under the same card and day gets its remembered offset
 *   - a pane that is gone is skipped
 */
/* c8 ignore next */ // tsx phantom-branch artifact on function declaration line; the body below is fully covered.
export function restoreHistoryScroll( mount: HTMLElement, remembered: HistoryScroll ): void {
  if ( remembered.size === 0 ) return;
  for ( const card of Array.from(mount.children) as HTMLElement[] ) {
    const cardKey = card.getAttribute("data-id-hash");
    if ( cardKey === null ) continue;
    for ( const pane of Array.from(card.querySelectorAll<HTMLElement>(".date-accordion-messages")) ) {
      const top = remembered.get(historyKey(cardKey, pane.closest(".date-accordion")?.getAttribute("data-date-key") ?? null));
      if ( top !== undefined && pane.scrollTop !== top ) pane.scrollTop = top;
    }
  }
}
