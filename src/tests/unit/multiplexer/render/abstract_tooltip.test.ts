// Row fff605be — the multiplexer's 📋 indicator did nothing in VERTICAL layout.
// Run via `npx tsx --test src/tests/unit/multiplexer/render/abstract_tooltip.test.ts`.
//
// Target: 100% lines / branches / functions on render/abstractTooltip.ts.

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import {
  createAbstractTooltip,
  computeTooltipPosition,
  ABSTRACT_TOOLTIP_ID,
} from "../../../../lupin_app/static/js/multiplexer/render/abstractTooltip";
import type { AbstractTooltip } from "../../../../lupin_app/static/js/multiplexer/render/abstractTooltip";
import type { LayoutMode } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before(() => {
  if (typeof globalThis.document === "undefined") GlobalRegistrator.register();
  const w = globalThis as unknown as {
    marked    : { parse(s: string): string };
    DOMPurify : { sanitize(s: string): string };
  };
  w.marked    = { parse: ( s: string ): string => `<p>${s.replace( /\*\*(.+?)\*\*/g, "<strong>$1</strong>" )}</p>` };
  w.DOMPurify = { sanitize: ( s: string ): string => s };
});

let tooltip : AbstractTooltip | null = null;
let layout  : LayoutMode = "vertical";

/** Runs the deferred measurement immediately, so placement is observable synchronously. */
const syncSchedule = ( fn: () => void ): void => fn();

function mountTooltip( schedule: ( ( fn: () => void ) => void ) | undefined = syncSchedule ): AbstractTooltip {
  tooltip = createAbstractTooltip( { getLayoutMode: () => layout, schedule } );
  tooltip.mount();
  return tooltip;
}

function addIndicator( abstract: string ): HTMLElement {
  const card = document.createElement( "div" );
  card.className = "notification-message";
  card.innerHTML = `<span class="message-text">hello <span class="abstract-indicator" role="button">📋</span></span>`;
  const indicator = card.querySelector( ".abstract-indicator" ) as HTMLElement;
  indicator.setAttribute( "data-abstract", abstract );   // RAW, as the mux writer stores it
  document.body.appendChild( card );
  return indicator;
}

function tip(): HTMLElement {
  return document.getElementById( ABSTRACT_TOOLTIP_ID ) as HTMLElement;
}

beforeEach(() => {
  document.body.replaceChildren();
  layout = "vertical";
});

afterEach(() => {
  if ( tooltip !== null ) { tooltip.unmount(); tooltip = null; }
});

// ---------------------------------------------------------------- the defect itself

test( "vertical layout: clicking 📋 shows the abstract, markdown-rendered", () => {
  mountTooltip();
  const indicator = addIndicator( "see **the list** at 100% done" );
  indicator.click();

  assert.ok( tip().classList.contains( "visible" ), "the tooltip must open on a vertical-layout click" );
  const content = tip().querySelector( ".abstract-tooltip-content" ) as HTMLElement;
  assert.equal( content.querySelector( "strong" )?.textContent, "the list" );
  assert.match( content.textContent ?? "", /100% done/, "a bare % must survive — the abstract is read raw" );
  assert.equal( tip().style.visibility, "visible" );
});

test( "horizontal layout: the tooltip stands aside for the Reading Pane", () => {
  layout = "horizontal";
  mountTooltip();
  addIndicator( "pane content" ).click();
  assert.equal( tip().classList.contains( "visible" ), false );
});

test( "a doc link in the abstract reaches the DOM as a real anchor", () => {
  mountTooltip();
  addIndicator( "<a href=\"/app/docs?path=lupin/README.md\">Open</a>" ).click();
  const anchor = tip().querySelector( ".abstract-tooltip-content a" ) as HTMLAnchorElement;
  assert.ok( anchor !== null, "the link Rick could not reach must be in the tooltip" );
  assert.equal( anchor.getAttribute( "href" ), "/app/docs?path=lupin/README.md" );
});

test( "an indicator with no data-abstract opens an empty tooltip rather than throwing", () => {
  mountTooltip();
  const indicator = addIndicator( "x" );
  indicator.removeAttribute( "data-abstract" );
  indicator.click();
  assert.ok( tip().classList.contains( "visible" ) );
});

// ---------------------------------------------------------------- closing

test( "the × button closes it", () => {
  mountTooltip();
  addIndicator( "a" ).click();
  ( tip().querySelector( ".abstract-tooltip-close" ) as HTMLElement ).click();
  assert.equal( tip().classList.contains( "visible" ), false );
});

test( "a click outside closes it; a click inside does not", () => {
  mountTooltip();
  addIndicator( "a" ).click();

  ( tip().querySelector( ".abstract-tooltip-content" ) as HTMLElement ).click();
  assert.ok( tip().classList.contains( "visible" ), "clicking inside must keep it open" );

  document.body.click();
  assert.equal( tip().classList.contains( "visible" ), false, "clicking outside must close it" );
});

test( "Escape closes it; other keys do not", () => {
  mountTooltip();
  addIndicator( "a" ).click();
  document.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter" } ) );
  assert.ok( tip().classList.contains( "visible" ) );
  document.dispatchEvent( new KeyboardEvent( "keydown", { key: "Escape" } ) );
  assert.equal( tip().classList.contains( "visible" ), false );
});

// ---------------------------------------------------------------- lifecycle

test( "mount is idempotent and unmount removes the container and its listeners", () => {
  const t = mountTooltip();
  t.mount();
  assert.equal( document.querySelectorAll( `#${ABSTRACT_TOOLTIP_ID}` ).length, 1 );

  t.unmount();
  assert.equal( document.getElementById( ABSTRACT_TOOLTIP_ID ), null );
  t.unmount();                        // second unmount is a no-op
  addIndicator( "after unmount" ).click();
  assert.equal( document.getElementById( ABSTRACT_TOOLTIP_ID ), null, "no listener may survive unmount" );
  tooltip = null;
});

test( "the default scheduler defers placement to the next animation frame", async () => {
  tooltip = createAbstractTooltip( { getLayoutMode: () => layout } );   // no schedule → requestAnimationFrame
  tooltip.mount();
  addIndicator( "a" ).click();
  assert.equal( tip().style.visibility, "hidden", "placement must wait for the frame" );
  await new Promise<void>( ( resolve ) => requestAnimationFrame( () => resolve() ) );
  await new Promise<void>( ( resolve ) => setTimeout( resolve, 0 ) );
  assert.equal( tip().style.visibility, "visible" );
});

// ---------------------------------------------------------------- placement arithmetic

test( "placement: below the indicator, centred, when it fits", () => {
  const pos = computeTooltipPosition(
    { top: 100, bottom: 120, left: 400, width: 20 },
    { width: 200, height: 100 },
    { width: 1000, height: 800 },
  );
  assert.deepEqual( pos, { top: 128, left: 310 } );
});

test( "placement: flips above when below would clip the viewport bottom", () => {
  const pos = computeTooltipPosition(
    { top: 700, bottom: 720, left: 400, width: 20 },
    { width: 200, height: 100 },
    { width: 1000, height: 800 },
  );
  assert.equal( pos.top, 592 );
});

test( "placement: never above the top margin, and clamped inside both side edges", () => {
  const high = computeTooltipPosition(
    { top: 50, bottom: 70, left: 5, width: 10 },
    { width: 300, height: 790 },
    { width: 1000, height: 800 },
  );
  assert.equal( high.top, 10 );
  assert.equal( high.left, 10 );

  const right = computeTooltipPosition(
    { top: 100, bottom: 120, left: 990, width: 10 },
    { width: 300, height: 100 },
    { width: 1000, height: 800 },
  );
  assert.equal( right.left, 690 );
});
