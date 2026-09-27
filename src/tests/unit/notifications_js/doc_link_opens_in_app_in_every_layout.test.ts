// Row 47759aa3 — THE LEGACY CLIENT'S HALF: a history doc link opens in-app, in every
// layout, and opens no tab.
//
// Rick's ruling 2026-09-26, verbatim on the tab: "links currently displayed within the
// notification history open a new tab wherein they shouldn't". They render in the
// content pane wherever the layout puts it.
//
// 🔴 VERTICAL WAS THE BROKEN MODE AND IT IS THE DEFAULT. Chloé measured both clients on
// :7999 (2026-09-26) with the real `#layout-mode-toggle`: horizontal claimed the click
// and filled the pane, vertical returned on `this._layoutMode !== "horizontal"` — the
// listener's FIRST line — and the anchor's baked-in `target="_blank"` opened a tab.
// `window.open` was called ZERO times, so the tab came from the ATTRIBUTE, not a call.
//
// ⚠️ THAT IS WHY "no new tab" IS NOT ASSERTED ON window.open ALONE. A window.open watch
// would have been green through the whole regression. Each case below reads the claim
// (preventDefault), the absence of a window.open, and — for the emitter — the absence of
// the attribute that was the real mechanism.
//
// ⚠️ THE TWO EXCEPTION SURFACES MUST KEEP THEIR TAB, and they are the reason a test
// phrased as "a doc link opens no new tab" passes or fails on WHERE it clicks. The pane
// is shared with the live action-required response buttons and `_renderContentPaneEntry`
// clears it, which would destroy buttons mid-press. Legacy paid twice: 11c01fbc for the
// card, 17ce50a5 for the tooltip — fixed-position and appended to <body>, so an ancestry
// test against the card alone misses it. María ratified the carve-out. Chloé measured 0
// of 5 live anchors inside one, so these cases PLANT their anchors: a loop over nothing
// passes every assertion in it.
//
// ENTERED THROUGH `_initMasterDetailLayout`, the real registration site, rather than by
// calling the handler directly — the defect was a guard on the listener's first line, and
// a test that invokes the inner logic itself never sees the line that returned.
//
// Run: npx tsx --test src/tests/unit/notifications_js/doc_link_opens_in_app_in_every_layout.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE             = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const DOC_HREF = "/app/docs?path=lupin/src/rnd/a-real-doc.md";


/** One recorded in-app pane open. */
interface PaneOpen { kind: string; payload: string; title: string }
/** One recorded new-tab request. */
interface TabOpen { url?: string; target?: string; features?: string }

let paneOpens: PaneOpen[] = [];
let tabOpens : TabOpen[]  = [];
let ui       : Record<string, unknown>;

beforeEach( () => {
  paneOpens = [];
  tabOpens  = [];
  buildDOM();
} );

/** Put the single mounted instance into a layout mode, the way the toggle would. */
function setMode( mode: Mode ): void {
  ui._layoutMode = mode;
  assert.equal( ui._layoutMode, mode, "the fixture must actually be in the mode it claims" );
}

/**
 * The shell the listener runs against.
 *
 * `#action-required-content` sits inside the notifications column exactly as the page
 * ships it, and the history container is a sibling — so a "history" anchor and an
 * "exception" anchor differ ONLY in which element they are planted in, which is the
 * distinction under test.
 */
function buildDOM(): void {
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  host.innerHTML = `
    <div class="content-shell">
      <div class="left-column">
        <button id="layout-mode-toggle" type="button">⇆</button>
        <button class="toolbar-btn" id="doc-roots-toggle" type="button">📂</button>
        <div id="action-required-content"><button class="ar-respond">Respond</button></div>
        <div id="notification-list"><div class="notification-message">a history entry</div></div>
      </div>
      <div id="content-pane-splitter" role="separator"></div>
      <aside class="content-pane" id="content-pane" hidden>
        <div id="content-pane-body"></div>
      </aside>
    </div>`;
  document.body.appendChild( host );
}

type Mode = "vertical" | "horizontal";

/**
 * A bare instance with the doc-link listener REALLY registered.
 *
 * `_openContentPane` and `window.open` are the two outcomes this row distinguishes, so
 * they are recorded rather than performed. Everything else `_initMasterDetailLayout`
 * touches is stubbed: those surfaces have their own guards and none of them decides
 * where a doc link goes.
 */
function mountListenerOnce(): void {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  ui = Object.create( Ctor.prototype ) as Record<string, unknown>;
  ui.debug = false;
  ui.log   = (): void => {};
  ui.error = (): void => {};
  ui._openContentPane = ( kind: string, payload: string, title: string ): void => {
    paneOpens.push( { kind, payload, title } );
  };
  // Siblings of the doc-link listener, each with its own guards and its own tests.
  ui._initPaneSplitter               = (): void => {};
  ui._updateLayoutModeButtonTooltip  = (): void => {};
  ui._handleEmbeddedAudioClick       = (): void => {};
  ui._handleIoFileDownloadClick      = (): void => {};
  ui._toggleLayoutMode               = (): void => {};

  ( globalThis as unknown as { open: unknown } ).open =
    ( url?: string, target?: string, features?: string ): null => {
      tabOpens.push( { url, target, features } );
      return null;
    };

  ( ui as unknown as { _initMasterDetailLayout(): void } )._initMasterDetailLayout();
}

/** Plant a doc anchor in `host`, click it, return whether the app claimed the click. */
function clickDocAnchorIn( host: Element, href: string = DOC_HREF ): boolean {
  const a = document.createElement( "a" );
  a.setAttribute( "href", href );
  a.textContent = "A real doc";
  host.appendChild( a );
  const ev = new MouseEvent( "click", { bubbles: true, cancelable: true } );
  a.dispatchEvent( ev );
  return ev.defaultPrevented;
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
  buildDOM();
  mountListenerOnce();
} );

// ===========================================================================
// 1 — The history link, in BOTH layouts.
// ===========================================================================

for ( const mode of [ "vertical", "horizontal" ] as Mode[] ) {
  test( `${mode}: a history doc link opens the content pane and opens no tab`, () => {
    setMode( mode );
    {
      const claimed = clickDocAnchorIn( document.getElementById( "notification-list" ) as Element );

      assert.equal( claimed, true,
        `the app did not claim the click in ${mode} layout. Unclaimed is precisely how the ` +
        "regression presented: the listener returned on its first line and the anchor's " +
        "target=_blank did the rest" );
      assert.deepEqual( tabOpens, [],
        "no new tab for a history link. This prong is WEAK on its own — window.open was " +
        "measured at zero calls throughout the regression — which is why `claimed` is read too" );
      assert.equal( paneOpens.length, 1, `exactly one in-app open in ${mode} layout` );
      assert.deepEqual( paneOpens[ 0 ], { kind: "doc", payload: DOC_HREF, title: "A real doc" } );
    }
  } );
}

test( "vertical: the absolute-loopback form of the same href is claimed and normalized", () => {
  setMode( "vertical" );
  {
    const claimed = clickDocAnchorIn( document.getElementById( "notification-list" ) as Element,
                                      `http://localhost:7999${DOC_HREF}` );
    assert.equal( claimed, true, "senders emit both forms; a raw-href prefix test misses the absolute one" );
    assert.equal( paneOpens[ 0 ]?.payload, DOC_HREF );
  }
} );

test( "vertical: an external link is left alone — the fix has a ceiling", () => {
  setMode( "vertical" );
  {
    const claimed = clickDocAnchorIn( document.getElementById( "notification-list" ) as Element,
                                      "https://example.com/an-external-page" );
    assert.equal( claimed, false, "dropping the mode guard must not make the app intercept every link" );
    assert.deepEqual( paneOpens, [] );
    assert.deepEqual( tabOpens, [], "and the browser, not the app, is what opens it" );
  }
} );

// ===========================================================================
// 2 — The ratified exceptions. PLANTED anchors, one case each.
// ===========================================================================

const EXCEPTION_SURFACES: ReadonlyArray<{ name: string; plant: () => Element; why: string }> = [
  {
    name  : "#action-required-content",
    plant : () => document.getElementById( "action-required-content" ) as Element,
    why   : "bug 11c01fbc — the live response buttons live here, and _renderContentPaneEntry clears the pane",
  },
  {
    name  : ".abstract-tooltip appended to <body>",
    plant : () => {
      // 🔴 PLANTED ON <body>, NOT INSIDE THE CARD. The tooltip is fixed-position and
      // body-appended (bug 17ce50a5); planting it inside #action-required-content
      // would pass on the CARD's exemption and say nothing about the tooltip's.
      const tip = document.createElement( "div" );
      tip.className = "abstract-tooltip";
      document.body.appendChild( tip );
      return tip;
    },
    why   : "bug 17ce50a5 — fixed-position and body-appended, so an ancestry test against the card misses it",
  },
];

for ( const surface of EXCEPTION_SURFACES ) {
  test( `exception: a doc link planted in ${surface.name} opens a NEW TAB, explicitly`, () => {
    setMode( "vertical" );
    {
      const host = surface.plant();
      assert.ok( host !== null,
        `the fixture failed to provide ${surface.name} — every assertion below would be vacuous` );

      const claimed = clickDocAnchorIn( host );

      assert.equal( claimed, true,
        "claimed, but NOT to open the pane. preventDefault is required here too now that the " +
        "markdown post-process no longer stamps target=_blank: a bare return would navigate the " +
        "CURRENT tab and destroy the pane this exception exists to protect. " +
        `Reason it is exempt: ${surface.why}` );
      assert.equal( tabOpens.length, 1, `${surface.name} must open exactly one new tab` );
      assert.deepEqual( tabOpens[ 0 ], { url: DOC_HREF, target: "_blank", features: "noopener,noreferrer" } );
      assert.deepEqual( paneOpens, [],
        "and the pane must stay shut — opening it is the harm, not the goal" );
    }
  } );
}

// ===========================================================================
// 3 — The global entry point (row 47759aa3, the part Rick actually asked for).
// ===========================================================================

for ( const mode of [ "vertical", "horizontal" ] as Mode[] ) {
  test( `${mode}: the toolbar folder button opens the roots landing in the content pane`, () => {
    setMode( mode );
    const btn = document.getElementById( "doc-roots-toggle" );
    assert.ok( btn !== null,
      "the fixture must carry #doc-roots-toggle BEFORE _initMasterDetailLayout runs — the " +
      "legacy wiring is guarded by `if ( rootsBtn )`, so a shell without it skips the " +
      "binding silently and this case would pass over nothing" );

    btn.dispatchEvent( new MouseEvent( "click", { bubbles: true, cancelable: true } ) );

    assert.equal( paneOpens.length, 1, `exactly one in-app open in ${mode} layout` );
    assert.deepEqual( paneOpens[ 0 ], { kind: "doc", payload: "/app/docs", title: "Files" },
      "it must open /app/docs with NO ?path= — the bare form is what makes the viewer render " +
      "the roots landing rather than its old 'No document path specified' error" );
    assert.deepEqual( tabOpens, [],
      "and IN-APP, never a new tab — the same ruling the doc links got" );
  } );
}

test( "the folder button is NOT a section toggle", () => {
  // Every other .toolbar-btn carries data-section and the delegated handler flips that
  // section's visibility. This one opens a pane instead, so carrying data-section would
  // make one click do two unrelated things — and the bug would present as a section
  // vanishing when the user asked to browse files.
  const btn = document.getElementById( "doc-roots-toggle" );
  assert.equal( btn?.hasAttribute( "data-section" ), false,
    "#doc-roots-toggle must not carry data-section; the layout-mode button sets the same " +
    "precedent for a non-section button living in that bar" );
} );

// ===========================================================================
// 4 — The emitter, and the guard that is now absent by design.
// ===========================================================================

const SOURCE = readFileSync( NOTIFICATIONS_JS, "utf8" );

// Comments stripped for the guard below. The removed line is QUOTED in the comment that
// explains its removal, so a raw search finds the very text whose absence it is checking
// — a guard that reddens on its own documentation. This is the trap the sibling
// boot_wires_* guards strip comments for, and it caught this file on the first run.
const SOURCE_CODE_ONLY = SOURCE
  .split( "\n" )
  .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
  .join( "\n" );

test( "the markdown post-process skips target=_blank for a doc link, at every site", () => {
  // Both post-process sites were stamping every anchor; a fix applied to one of them
  // would leave the other emitting the fallback, and only one of the two renders
  // abstracts. Counting is how a half-applied fix is caught.
  const skips = SOURCE.split( "_isDocLinkHref" ).length - 1;
  assert.ok( skips >= 3,
    `expected the shared predicate at 3+ sites (its definition plus both markdown ` +
    `post-processes plus the listener), found ${skips} — a site left un-converted still ` +
    "stamps the attribute that was the regression's mechanism" );
} );

test( "the doc-link listener carries no layout-mode guard", () => {
  // Anchored on the CODE that registers the listener, not on a comment: a comment is the
  // first thing a refactor rewrites, and this guard must not go quietly vacuous when it does.
  const start = SOURCE_CODE_ONLY.indexOf( 'const anchor = ev.target.closest( "a[href]" );' );
  assert.notEqual( start, -1,
    "cannot locate the doc-link listener's body — this guard would otherwise pass over the " +
    "wrong region, or over nothing at all" );
  const region = SOURCE_CODE_ONLY.slice( Math.max( 0, start - 400 ), start + 1800 );
  assert.doesNotMatch( region, /_layoutMode !== "horizontal"/,
    "this is the exact line Chloé measured returning in vertical layout. It must not come back: " +
    "with target=_blank now gone from doc links, a re-added guard means the click falls through " +
    "to a CURRENT-tab navigation that wipes the pane — worse than the bug it used to cause" );
} );
