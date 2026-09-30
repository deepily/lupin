// The three items ported from row 4a06ded1 onto the landed pane (162be6c2).
//
// 🔴 WHY A SEPARATE FILE RATHER THAN MORE ASSERTIONS IN THEIRS. Two of these three
// gaps survived a careful, well-tested port precisely BECAUSE the landed tests
// asserted the pre-ruling behaviour — `[ "When", "What", "Who", "Why" ]` did not
// merely miss the rename, it PINNED the superseded word in place. A guard whose whole
// subject is "did this ruling land" is easier to read, and harder to quietly relax,
// than three more lines inside a test named for something else.
//
// The rulings, both Rick's, 2026-09-07 ~20:10 by voice, row 86a5c818:
//   · "the WHAT column should actually read TITLE"
//   · "I want an icon for type — done, dropped or won't fix — on a per-row basis"
// The third item is a defect, not a ruling: two-word personas were truncated.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { renderFinishedTasksTable } from "../../../../lupin_app/static/js/multiplexer/render/templates/finishedTasksTable";
import { actorPersona, type FinishedTaskEvent } from "../../../../lupin_app/static/js/multiplexer/render/finishedTasksModel";

before( () => { if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register(); } );

const NOW = Date.parse( "2026-09-07T20:00:00Z" );
const ago = ( m: number ): string => new Date( NOW - m * 60000 ).toISOString();

const ev = ( over: Partial<FinishedTaskEvent> = {} ): FinishedTaskEvent => ( {
  id: 1, item_id: "x", ts: ago( 10 ), actor: "rio c079db30",
  transition: "in_progress->done", reason: "r", title: "a row", ...over
} as FinishedTaskEvent );

function render( rows: FinishedTaskEvent[] ): HTMLElement {
  const host = document.createElement( "div" );
  host.appendChild( renderFinishedTasksTable( rows, NOW ) );
  return host;
}

// ═══════════════ ITEM 1 — Rick's header rename ═══════════════

test( "the header reads TITLE and no longer reads WHAT", () => {
  const host = render( [ ev() ] );
  const heads = [ ...host.querySelectorAll( "thead th" ) ].map( th => th.textContent );
  assert.deepEqual( heads, [ "When", "Title", "Who", "Why" ] );
  assert.ok( !heads.includes( "What" ), "the header still carries the superseded word" );
} );

// ═══════════════ ITEM 2 — Rick's per-row status glyph ═══════════════

test( "every row carries a status glyph, and it is a PREFIX inside WHEN — not a fifth column", () => {
  // Design §6.4, and it is load-bearing: a grid that changes shape when you click a
  // filter makes the reader re-find every column. Four cells across all seven filter
  // combinations is the property; the glyph costs no horizontal space.
  const host = render( [ ev() ] );
  const row  = host.querySelector( "tbody tr" )!;

  assert.equal( row.querySelectorAll( "td" ).length, 4,
    "the row is no longer four cells — a fifth column reshuffles the grid, which §6.4 rejects" );
  const when = row.querySelector( "td.finished-when" )!;
  assert.ok( when.querySelector( ".finished-status-glyph" ), "the glyph is not inside the WHEN cell" );
  // ...and it did not REPLACE the age. Asserting the glyph alone would pass on a cell
  // that had lost its relative time entirely.
  assert.match( when.textContent ?? "", /10m/ );
} );

test( "three different statuses render three DIFFERENT glyphs", () => {
  const host = render( [
    ev( { id: 1, transition: "->done" } ),
    ev( { id: 2, transition: "->dropped" } ),
    ev( { id: 3, transition: "->wont_fix" } ),
  ] );
  const glyphs = [ ...host.querySelectorAll( ".finished-status-glyph" ) ].map( g => g.textContent );
  // POSITIVE CONTROL: without this, an empty result would satisfy the set assertion
  // below on a page that rendered no glyphs at all.
  assert.equal( glyphs.length, 3, "expected one glyph per row" );
  assert.equal( new Set( glyphs ).size, 3, `two statuses share a glyph: ${ JSON.stringify( glyphs ) }` );
} );

test( "the glyph is aria-hidden — it repeats what the row already says in words", () => {
  // data-status carries the same fact machine-readably, so announcing an emoji as well
  // is noise rather than access.
  const host  = render( [ ev() ] );
  const glyph = host.querySelector( ".finished-status-glyph" )!;
  assert.equal( glyph.getAttribute( "aria-hidden" ), "true" );
  assert.equal( host.querySelector( "tbody tr" )!.getAttribute( "data-status" ), "done" );
} );

test( "an unrecognised status renders a NEUTRAL glyph, never a borrowed one", () => {
  // `PILL_FACES[ status ] ?? …` would walk the prototype chain and hand back a truthy
  // FUNCTION for "toString". This goes through ownLookup, so an unknown key falls back.
  const host  = render( [ ev( { transition: "->toString" } ) ] );
  const glyph = host.querySelector( ".finished-status-glyph" )!;
  assert.equal( glyph.textContent, "•", "an inherited value reached the glyph" );
} );

// ═══════════════ ITEM 3 — the persona truncation ═══════════════

test( "a TWO-WORD persona survives the WHO column; only the session id is stripped", () => {
  // The naive `actor.split( /\s+/ )[ 0 ]` renders "mr radio" as "mr". Measured by María
  // 2026-09-02 on the sibling field: wrong on 6 of 13 live rows, and those six are
  // exactly the ones Rick asked about.
  assert.equal( actorPersona( "mr radio 8353ea70" ), "mr radio" );
  assert.equal( actorPersona( "rio c079db30" ), "rio" );

  // And it reaches the rendered column — the unit above passing while the cell shows
  // "mr" is exactly the gap this ports.
  const host = render( [ ev( { actor: "mr radio 8353ea70" } ) ] );
  assert.equal( host.querySelector( "td.finished-who" )!.textContent, "mr radio" );
} );

test( "an actor with no session id is shown WHOLE rather than guessed at", () => {
  // A truncated name is a WRONG name wearing a right one's clothes; an unexpected
  // format shown in full is visibly odd and sends the reader to the row.
  assert.equal( actorPersona( "no session id here" ), "no session id here" );
  assert.equal( actorPersona( "mr" ), "mr" );
} );
