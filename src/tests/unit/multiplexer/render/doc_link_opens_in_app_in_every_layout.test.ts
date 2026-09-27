// Row 47759aa3 — A HISTORY DOC LINK OPENS IN-APP, IN EVERY LAYOUT, AND OPENS NO TAB.
//
// Rick's ruling 2026-09-26: a doc link in the notification history renders in the
// content area wherever the user's layout puts it — on top of the vertical accordion
// stack, or in the right-hand pane. Verbatim on the tab: "links currently displayed
// within the notification history open a new tab wherein they shouldn't".
//
// 🔴 THE DEFECT WAS DETERMINISTIC ON LAYOUT MODE, AND VERTICAL IS THE DEFAULT.
// Chloé measured it on :7999 (2026-09-26, both clients, real `#layout-mode-toggle`):
// horizontal intercepted the click and filled the pane; vertical bailed on
// `getLayoutMode() !== "horizontal"` and the anchor's baked-in `target="_blank"`
// opened a tab. `window.open` was called ZERO times in that measurement — the tab
// came from the ATTRIBUTE. Every existing case in reading_pane_renderer.test.ts seeds
// HORIZONTAL, which is exactly why none of them saw it.
//
// ⚠️ SO "NO NEW TAB" IS ASSERTED ON THREE PRONGS, not one. A test that only watched
// `window.open` would have passed throughout the entire regression. The prongs are:
// the click is preventDefault'd, `window.open` is untouched, and the rendered anchor
// carries no `target="_blank"` for the emitter to fall back to.
//
// ⚠️ AND "NO NEW TAB, EVER" WOULD BREAK SOMETHING PAID FOR TWICE. The pane is SHARED
// with the live action-required response buttons, and opening a doc calls
// replaceChildren — which deletes the buttons the user is mid-press on. Legacy earned
// that carve-out through bugs 11c01fbc (the card) and 17ce50a5 (the tooltip, which is
// fixed-position and appended to <body>, so an ancestry test against the card alone
// misses it). María ratified it 2026-09-26. Those anchors KEEP opening a tab, and each
// surface gets its own case with a PLANTED anchor — Chloé measured 0 of 5 live anchors
// sitting in one, and a loop over nothing passes every assertion in it.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/doc_link_opens_in_app_in_every_layout.test.ts

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createStorageServiceForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import type { StorageService } from "../../../../lupin_app/static/js/multiplexer/shared/StorageService";
import { createReadingPaneStore } from "../../../../lupin_app/static/js/multiplexer/stores/ReadingPaneStore";
import { createReadingPaneRenderer } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import type { ReadingPaneRenderer, WindowLike, WindowDocLike } from "../../../../lupin_app/static/js/multiplexer/render/ReadingPaneRenderer";
import { renderMarkdown } from "../../../../lupin_app/static/js/multiplexer/render/markdown";
import { PANE_RESIDENT_SELECTOR } from "../../../../lupin_app/static/js/multiplexer/render/docLink";

const DOC_HREF = "/app/docs?path=lupin/src/rnd/a-real-doc.md";

/** renderMarkdown returns a RawValue `{__raw}`, never a bare string (html.ts:22). */
function htmlOf( rawValue: unknown ): string {
  return ( rawValue as { __raw: string } ).__raw;
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const w = globalThis as unknown as {
    marked    : { parse( s: string ): string };
    DOMPurify : { sanitize( s: string ): string };
    scrollBy  : ( x: number, y: number ) => void;
  };
  // renderMarkdown reuses the page's marked + DOMPurify. The pass-through keeps the
  // anchor attributes intact, which is the whole point of the emitter cases below.
  w.marked    = { parse: ( s: string ): string => s };
  w.DOMPurify = { sanitize: ( s: string ): string => s };
  w.scrollBy  = (): void => {};
} );

let activeRenderer: ReadingPaneRenderer | null = null;

beforeEach( () => {
  document.body.replaceChildren();
  document.body.removeAttribute( "data-layout-mode" );
} );

afterEach( () => {
  // The renderer binds a DOCUMENT-level click listener; leaking one across tests
  // would let a previous renderer claim this test's click.
  if ( activeRenderer !== null ) { activeRenderer.unmount(); activeRenderer = null; }
} );

/** Records window.open instead of performing it — the second prong. */
function makeWindowStub(): { win: WindowLike; opens: Array<{ url?: string; target?: string; features?: string }> } {
  const opens: Array<{ url?: string; target?: string; features?: string }> = [];
  const win: WindowLike = {
    open( url?: string, target?: string, features?: string ): WindowDocLike | null {
      opens.push( { url, target, features } );
      return { document: { open() {}, write() {}, close() {} } };
    },
  };
  return { win, opens };
}

// The master-detail shell, matching multiplexer.html. `#action-required-section`
// and `#action-required-content` are both here because both are pane-resident
// surfaces, and the tooltip is planted on <body> per case.
function buildShell(): HTMLElement {
  const shell = document.createElement( "div" );
  shell.className = "content-shell";
  shell.innerHTML = `
    <div class="left-column">
      <button id="layout-mode-toggle" type="button">⇆</button>
      <main class="container">
        <section id="notifications-pane">
          <div id="action-required-section">
            <div id="action-required-content"><button class="ar-respond">Respond</button></div>
          </div>
          <div id="sender-cards-container">
            <div class="sender-card" data-sender-id="alice">
              <span class="message-text">A history entry that carries a doc link</span>
            </div>
          </div>
        </section>
      </main>
    </div>
    <div id="content-pane-splitter" role="separator"></div>
    <aside class="content-pane" id="content-pane" hidden>
      <div class="content-pane-header">
        <button id="content-pane-back" type="button" disabled>←</button>
        <span id="content-pane-title"></span>
        <button id="content-pane-bustout" type="button">⤢</button>
        <button id="content-pane-close" type="button">×</button>
      </div>
      <div id="content-pane-body"></div>
    </aside>`;
  document.body.appendChild( shell );
  return shell;
}

type Mode = "vertical" | "horizontal";

function setup( mode: Mode ) {
  const bus     = createEventBusForTesting();
  const storage = createStorageServiceForTesting( bus );
  // Seeded through the store's own persistence key, the way a returning user
  // arrives. "vertical" is the store's DEFAULT (ReadingPaneStore.ts:108) — the mode
  // the regression lived in, and the mode no pre-existing case covered.
  storage.setJSON( "reading_pane_layout_mode", { mode }, 1 );
  const store    = createReadingPaneStore( { bus, storage } );
  const win      = makeWindowStub();
  const shell    = buildShell();
  const renderer = createReadingPaneRenderer( {
    eventBus  : bus,
    stores    : { readingPane: store, actionRequired: { list: () => [] } },
    windowRef : win.win,
  } );
  renderer.mount( shell );
  activeRenderer = renderer;
  assert.equal( store.getLayoutMode(), mode, "the fixture must actually be in the mode it claims" );
  return { store, win, shell };
}

/** Plant a doc anchor somewhere and click it; returns whether the click was claimed. */
function clickDocAnchorIn( host: Element, href: string = DOC_HREF ): boolean {
  const a = document.createElement( "a" );
  a.setAttribute( "href", href );
  a.textContent = "A real doc";
  host.appendChild( a );
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  a.dispatchEvent( ev );
  return ev.defaultPrevented;
}

// ===========================================================================
// 1 — The history link, in BOTH layouts. Vertical is the regression.
// ===========================================================================

for ( const mode of [ "vertical", "horizontal" ] as Mode[] ) {
  test( `${mode}: a history doc link renders in the content pane and opens no tab`, () => {
    const { store, win, shell } = setup( mode );
    const history = shell.querySelector( "#sender-cards-container" ) as Element;

    const claimed = clickDocAnchorIn( history );

    // PRONG 1 — the click was claimed. This is the mechanism that stops a tab now
    // that the attribute is gone, and it is what read FALSE in vertical before the fix.
    assert.equal( claimed, true,
      `the app did not claim the click in ${mode} layout — unclaimed is exactly how the ` +
      "regression presented, and the user gets whatever the anchor says instead" );
    // PRONG 2 — no tab was asked for.
    assert.deepEqual( win.opens, [],
      "a history doc link must not call window.open. NOTE this prong alone proves little: " +
      "Chloé measured window.open at ZERO calls THROUGHOUT the regression, so it passed then too" );
    // The positive half of the ruling: it rendered where the user is looking.
    assert.equal( store.isPaneOpen(), true, `the pane must open in ${mode} layout` );
    assert.equal( store.currentEntry()?.type, "doc" );
    assert.equal( store.currentEntry()?.payload, DOC_HREF );
    assert.equal( store.currentEntry()?.title, "A real doc" );
  } );
}

test( "vertical: the absolute-loopback form of the same href is also claimed", () => {
  const { store } = setup( "vertical" );
  const history = document.querySelector( "#sender-cards-container" ) as Element;
  const claimed = clickDocAnchorIn( history, `http://localhost:7999${DOC_HREF}` );
  assert.equal( claimed, true,
    "senders emit both the bare and the absolute-loopback form; a prefix test that runs " +
    "on the raw href silently misses the absolute one" );
  assert.equal( store.currentEntry()?.payload, DOC_HREF, "and it is normalized before the pane sees it" );
} );

test( "vertical: a genuinely external link is left alone", () => {
  const { store, win } = setup( "vertical" );
  const history = document.querySelector( "#sender-cards-container" ) as Element;
  const claimed = clickDocAnchorIn( history, "https://example.com/an-external-page" );
  assert.equal( claimed, false,
    "dropping the mode guard must not turn the app into an interceptor of every link — " +
    "this is the ceiling on the fix" );
  assert.equal( store.isPaneOpen(), false );
  assert.deepEqual( win.opens, [] );
} );

// ===========================================================================
// 2 — The ratified exceptions. PLANTED anchors, one case each.
// ===========================================================================

// Each entry is a surface the pane is shared with, and the reason it is exempt.
const EXCEPTION_SURFACES: ReadonlyArray<{ name: string; plant: ( shell: Element ) => Element; why: string }> = [
  {
    name  : "#action-required-content",
    plant : ( shell ) => shell.querySelector( "#action-required-content" ) as Element,
    why   : "bug 11c01fbc — the live response buttons live here and replaceChildren would delete them",
  },
  {
    name  : "#action-required-section",
    plant : ( shell ) => shell.querySelector( "#action-required-section" ) as Element,
    why   : "Chloé's defensive widening (2026-09-26) — the multiplexer wipes its pane the same way; " +
            "flagged on the row as a JUDGEMENT, not a measurement, so this case pins the behaviour as shipped",
  },
  {
    name  : ".abstract-tooltip appended to <body>",
    plant : () => {
      // 🔴 DELIBERATELY NOT INSIDE THE SHELL. The tooltip is fixed-position and
      // appended to <body> (bug 17ce50a5), so a test that plants it inside the
      // action-required card would pass on the CARD's exemption and prove nothing
      // about the tooltip's.
      const tip = document.createElement( "div" );
      tip.className = "abstract-tooltip";
      document.body.appendChild( tip );
      return tip;
    },
    why   : "bug 17ce50a5 — fixed-position, body-appended, so ancestry against the card misses it",
  },
];

for ( const surface of EXCEPTION_SURFACES ) {
  test( `exception: a doc link planted in ${surface.name} opens a NEW TAB, explicitly`, () => {
    const { store, win, shell } = setup( "vertical" );
    const host = surface.plant( shell );
    assert.ok( host !== null, `the fixture failed to provide ${surface.name} — every assertion below would be vacuous` );
    assert.ok( host.matches( PANE_RESIDENT_SELECTOR ) || host.closest( PANE_RESIDENT_SELECTOR ) !== null,
      `${surface.name} must actually satisfy the shipped selector, or this case is testing my fixture ` +
      `rather than the code. Reason it is exempt: ${surface.why}` );

    const claimed = clickDocAnchorIn( host );

    assert.equal( claimed, true,
      "claimed, but NOT to open the pane — preventDefault is required here too, because the " +
      "emitter no longer stamps target=_blank, so a bare return would navigate the CURRENT tab " +
      "and destroy the very pane this exception exists to protect" );
    assert.equal( win.opens.length, 1, `${surface.name} must open exactly one new tab` );
    assert.deepEqual( win.opens[ 0 ], { url: DOC_HREF, target: "_blank", features: "noopener,noreferrer" } );
    assert.equal( store.isPaneOpen(), false,
      "and the pane must stay shut — opening it is the harm, not the goal" );
  } );
}

// ===========================================================================
// 3 — The emitter. No attribute means no silent fallback.
// ===========================================================================

test( "markdown: an in-app doc link is emitted with NO target, so there is nothing to fall back to", () => {
  const html = htmlOf( renderMarkdown( `<a href="${DOC_HREF}">a doc</a>` ) );
  assert.match( html, /href="\/app\/docs\?path=/, "the fixture's anchor must survive the render at all" );
  assert.doesNotMatch( html, /target="_blank"/,
    "this attribute IS the regression's mechanism: while interception holds it sits harmless, " +
    "and the moment anything fails to intercept it opens a tab with no error anywhere" );
} );

test( "markdown: a genuinely external link still gets target=_blank", () => {
  const html = htmlOf( renderMarkdown( '<a href="https://example.com/x">out</a>' ) );
  assert.match( html, /target="_blank"/,
    "leaving the site is what a new tab is FOR — this is the ceiling, and it is what makes the " +
    "case above a statement about DOC links rather than about all links" );
  assert.match( html, /rel="noopener noreferrer"/ );
} );

test( "markdown: a SINGLE-quoted doc href is recognised too", () => {
  // The href-extracting regex has a double-quoted arm and a single-quoted one, and only
  // the first was exercised. A quoting style is exactly the sort of thing that differs
  // between the two markdown renderers and the hand-written abstracts senders emit, and
  // the un-exercised arm would have stamped _blank back onto a doc link.
  const html = htmlOf( renderMarkdown( `<a href='${DOC_HREF}'>a doc</a>` ) );
  assert.doesNotMatch( html, /target="_blank"/,
    "a doc link in single quotes is the same doc link; the quoting style must not decide " +
    "whether it opens in-app" );
} );

test( "markdown: an anchor with no href at all is stamped, not crashed on", () => {
  // `<a name="x">` is legal markup and the regex finds no href in it, so the extractor
  // returns null. That arm was unexercised; a null reaching isDocLinkHref must simply
  // mean "not a doc link" rather than throwing inside a render.
  const html = htmlOf( renderMarkdown( '<a name="anchor-only">no href here</a>' ) );
  assert.match( html, /target="_blank"/,
    "with no href to judge, the anchor takes the ordinary external treatment — the safe " +
    "direction, and the same one it got before this row" );
} );

test( "markdown: the absolute-loopback doc form is also left bare", () => {
  const html = htmlOf( renderMarkdown( `<a href="http://localhost:7999${DOC_HREF}">a doc</a>` ) );
  assert.doesNotMatch( html, /target="_blank"/,
    "the emitter and the interceptor consult the SAME predicate; if one normalized and the other " +
    "did not, this form would be stamped and then intercepted, which is the old bug wearing new clothes" );
} );
