// Parity B-4 — the Time Saved dashboard.
//
// LEGACY BEING MIRRORED, cited by symbol so the coordinate survives an edit
// above it (manifest standing rule 1):
//   - `refreshTimeSavedStats`  notifications.js:8608   both reads, both fallbacks
//   - `renderTopSolutions`     notifications.js:8663   rank · question · stats, server order
//   - the markup                notifications.html:1276 four tiles + the leaderboard
//
// 🔴 THE THREE FAILURE RULES ARE WHAT THIS FILE MOSTLY TESTS, because they are
// the ones a green suite hides. A dashboard that blanks on a failed read still
// looks like a dashboard: "--" does not read as "the fetch failed", it reads as
// "you have saved no time" — a claim about the operator's work rather than
// about the network. So: a non-2xx leaves the previous values (T2), a throw only
// logs (T5), and the two endpoints are independent of each other.
//
// ⚠️ ONE DELIBERATE DIVERGENCE, AND THE BUILD PLAN NAMES IT (T6): legacy calls a
// bare `fetch` with a hand-attached Bearer header, so neither call refreshes an
// expired token. This builds on `ApiClient`. The tests below drive an `ApiClient`
// fake and therefore CANNOT observe that difference — it is asserted by the call
// going through the injected client at all, and stated here so the gap is named
// rather than implied.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/time_saved_renderer_parity.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  createTimeSavedRenderer,
  TIME_SAVED_ENDPOINT,
  TIME_SAVED_GLOBAL_ENDPOINT,
  TIME_SAVED_PLACEHOLDER,
  TOP_SOLUTIONS_LOADING,
  TOP_SOLUTIONS_EMPTY,
} from "../../../../lupin_app/static/js/multiplexer/render/TimeSavedRenderer";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

/**
 * An api fake that HOLDS per-endpoint answers and RECORDS every path asked for.
 *
 * 🔴 PER-ENDPOINT, NOT ONE ANSWER FOR BOTH. The independence rule below — the
 * second call failing must not undo the first's repaint — is unobservable
 * against a fake that answers the same thing whatever it is asked.
 */
function fakeApi( init: { stats?: unknown; global?: unknown; failStats?: boolean; failGlobal?: boolean } = {} ) {
  const state = {
    stats      : init.stats  ?? {},
    global     : init.global ?? {},
    failStats  : init.failStats  === true,
    failGlobal : init.failGlobal === true,
    paths      : [] as string[],
  };
  const api = {
    get: async <T>( path: string ): Promise<T> => {
      state.paths.push( path );
      if ( path === TIME_SAVED_ENDPOINT ) {
        if ( state.failStats ) throw new Error( "500 time-saved" );
        return state.stats as T;
      }
      if ( state.failGlobal ) throw new Error( "500 global" );
      return state.global as T;
    },
  };
  return { api, state };
}

/**
 * Mount and let the init fetch pair settle.
 *
 * ⚠️ IT DRAINS THE MICROTASK QUEUE; IT DOES NOT CALL `refreshForTesting()`.
 * Mount already fires one refresh, so awaiting a SECOND one would double every
 * count this file asserts — and it did, which is how the log-count assertions
 * below caught the helper rather than the code.
 */
async function settle(): Promise<void> {
  for ( let i = 0; i < 6; i++ ) await Promise.resolve();
}

async function mountPane( init: Parameters<typeof fakeApi>[ 0 ] = {} ) {
  const { api, state } = fakeApi( init );
  const logs: string[] = [];
  const root = document.createElement( "div" );
  const r = createTimeSavedRenderer( { api, logFn: ( m ) => logs.push( m ) } );
  r.mount( root );
  await settle();
  const tile = ( testid: string ): string =>
    root.querySelector( `[data-testid="${ testid }"]` )?.textContent ?? "";
  const solutionRows = (): HTMLElement[] =>
    Array.from( root.querySelectorAll<HTMLElement>( ".top-solution-item" ) );
  return { root, renderer: r, state, logs, tile, solutionRows };
}

const SOLID_STATS = {
  total_time_saved_formatted      : "3h 12m",
  time_saved_for_others_formatted : "48m",
  solutions_created               : 17,
  total_replays_benefited         : 42,
};

// ---------------------------------------------------------------------------
// Chrome + the pre-fetch state (B10)
// ---------------------------------------------------------------------------

test( "the pane builds its own chrome: header, 🔄, four tiles, the leaderboard", async () => {
  const { root } = await mountPane();
  const h3 = root.querySelector( ".section-header h3" ) as HTMLElement;
  assert.ok( h3.textContent?.includes( "⏱️ Time Saved Dashboard" ), "legacy's glyph and title" );
  assert.notEqual( root.querySelector( '[data-testid="multiplexer-time-saved-refresh"]' ), null );
  assert.equal( root.querySelectorAll( ".stat-item" ).length, 4, "four tiles, as legacy's markup" );
  assert.notEqual( root.querySelector( '[data-testid="multiplexer-top-solutions"]' ), null );
} );

test( "B7: the header is STATIC — no count chip text", async () => {
  const { root } = await mountPane( { stats: SOLID_STATS } );
  assert.equal(
    root.querySelector( ".section-header-count" )?.textContent, "",
    "there is no ONE number this pane counts; a chip showing one of four would be picking a favourite",
  );
} );

test( "B10: before any fetch resolves the tiles read '--' and the leaderboard reads 'Loading...'", () => {
  // Deliberately NOT awaited — this is the paint between mount and the first
  // resolution, which is the only place these two strings are ever on screen.
  const { api } = fakeApi();
  const root = document.createElement( "div" );
  createTimeSavedRenderer( { api, logFn: () => {} } ).mount( root );

  for ( const id of [ "multiplexer-time-total", "multiplexer-time-others",
                      "multiplexer-solutions-created", "multiplexer-replays-benefited" ] ) {
    assert.equal( root.querySelector( `[data-testid="${ id }"]` )?.textContent, TIME_SAVED_PLACEHOLDER, id );
  }
  assert.equal(
    root.querySelector( '[data-testid="multiplexer-top-solutions"]' )?.textContent, TOP_SOLUTIONS_LOADING,
    "the leaderboard says it is loading, which is a different claim from 'there is nothing'",
  );
} );

// ---------------------------------------------------------------------------
// T1 — fetched once at init, never on a timer
// ---------------------------------------------------------------------------

test( "T1: mounting fires BOTH reads exactly once, and nothing schedules another", async () => {
  const { api, state } = fakeApi();
  const root = document.createElement( "div" );
  const r = createTimeSavedRenderer( { api, logFn: () => {} } );
  r.mount( root );
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  assert.deepEqual( state.paths, [ TIME_SAVED_ENDPOINT, TIME_SAVED_GLOBAL_ENDPOINT ],
    "both endpoints, in legacy's order, once each" );

  // A timer would show up as more paths after the microtask queue drains. This
  // pane has none on purpose: the numbers are cumulative and move hourly.
  await new Promise( ( res ) => setTimeout( res, 5 ) );
  assert.equal( state.paths.length, 2, "no poll — a third read means a timer was added" );
  r.unmount();
} );

// ---------------------------------------------------------------------------
// T2 — the tiles, and the two different fallbacks
// ---------------------------------------------------------------------------

test( "T2: a good read paints all four tiles from the server's own fields", async () => {
  const { tile } = await mountPane( { stats: SOLID_STATS } );
  assert.equal( tile( "multiplexer-time-total" ),        "3h 12m" );
  assert.equal( tile( "multiplexer-time-others" ),       "48m" );
  assert.equal( tile( "multiplexer-solutions-created" ), "17" );
  assert.equal( tile( "multiplexer-replays-benefited" ), "42" );
} );

test( "🔴 the two FALLBACKS differ, and that asymmetry is legacy's, copied on purpose", async () => {
  // `stats.total_time_saved_formatted || '--'` for the durations;
  // `stats.solutions_created || 0` for the counts. So a server that omits a
  // duration says "unmeasured" and one that omits a count says "none". It is an
  // inconsistency — but a LIVE one, and a pane that quietly harmonised it would
  // disagree with the other client about what the same payload means.
  const { tile } = await mountPane( { stats: {} } );
  assert.equal( tile( "multiplexer-time-total" ),        TIME_SAVED_PLACEHOLDER, "a missing duration is unmeasured" );
  assert.equal( tile( "multiplexer-time-others" ),       TIME_SAVED_PLACEHOLDER );
  assert.equal( tile( "multiplexer-solutions-created" ), "0", "a missing count is none" );
  assert.equal( tile( "multiplexer-replays-benefited" ), "0" );
} );

test( "an empty-string duration and a zero count take the same fallbacks", async () => {
  const { tile } = await mountPane( {
    stats: { total_time_saved_formatted: "", solutions_created: 0, total_replays_benefited: 0 },
  } );
  assert.equal( tile( "multiplexer-time-total" ),        TIME_SAVED_PLACEHOLDER );
  assert.equal( tile( "multiplexer-solutions-created" ), "0" );
  assert.equal( tile( "multiplexer-replays-benefited" ), "0" );
} );

// ---------------------------------------------------------------------------
// T3 / T4 — the leaderboard
// ---------------------------------------------------------------------------

test( "T4: one row per solution — rank, question and 'N replays · X saved', in SERVER order", async () => {
  const { solutionRows } = await mountPane( {
    global: { top_solutions: [
      { question: "beta",  replays: 9, time_saved_formatted: "1h" },
      { question: "alpha", replays: 2, time_saved_formatted: "4m" },
    ] },
  } );
  const rows = solutionRows();
  assert.equal( rows.length, 2 );

  // 🔴 SERVER ORDER, NOT SORTED HERE. "beta" is first with MORE replays and
  // "alpha" second — alphabetically backwards on purpose, so a client-side sort
  // by either field would reorder them and redden this.
  assert.equal( rows[ 0 ]!.querySelector( ".rank" )?.textContent,     "#1" );
  assert.equal( rows[ 0 ]!.querySelector( ".question" )?.textContent, "beta" );
  assert.equal( rows[ 0 ]!.querySelector( ".stats" )?.textContent,    "9 replays · 1h saved" );
  assert.equal( rows[ 1 ]!.querySelector( ".rank" )?.textContent,     "#2" );
  assert.equal( rows[ 1 ]!.querySelector( ".question" )?.textContent, "alpha" );
} );

test( "🔴 a question containing markup is TEXT, never parsed", async () => {
  const nasty = '<img src=x onerror="alert(1)">';
  const { root, solutionRows } = await mountPane( {
    global: { top_solutions: [ { question: nasty, replays: 1, time_saved_formatted: "1m" } ] },
  } );
  assert.equal( solutionRows()[ 0 ]!.querySelector( ".question" )?.textContent, nasty,
    "the characters survive verbatim" );
  assert.equal( root.querySelector( "img" ), null,
    "and NO element was created from them — legacy escapes by hand, this goes through textContent" );
} );

test( "an empty leaderboard reads as a MEASURED zero, not as still-loading", async () => {
  const { root } = await mountPane( { global: { top_solutions: [] } } );
  assert.equal( root.querySelector( ".no-data" )?.textContent, TOP_SOLUTIONS_EMPTY );
} );

test( "a payload with no top_solutions field at all takes the same empty message", async () => {
  const { root } = await mountPane( { global: {} } );
  assert.equal( root.querySelector( ".no-data" )?.textContent, TOP_SOLUTIONS_EMPTY );
} );

test( "a solution missing its fields still renders a row, with each field's own fallback", async () => {
  const { solutionRows } = await mountPane( { global: { top_solutions: [ {} ] } } );
  const row = solutionRows()[ 0 ]!;
  assert.equal( row.querySelector( ".question" )?.textContent, "" );
  assert.equal( row.querySelector( ".stats" )?.textContent, `0 replays · ${ TIME_SAVED_PLACEHOLDER } saved` );
} );

// ---------------------------------------------------------------------------
// T2 / T5 — 🔴 a failed read must not erase what is on screen
// ---------------------------------------------------------------------------

test( "🔴 T2+T5: a failing stats read LEAVES THE PREVIOUS VALUES and only logs", async () => {
  const { api, state } = fakeApi( { stats: SOLID_STATS, global: { top_solutions: [] } } );
  const logs: string[] = [];
  const root = document.createElement( "div" );
  const r = createTimeSavedRenderer( { api, logFn: ( m ) => logs.push( m ) } );
  r.mount( root );
  await r.refreshForTesting();

  const before = root.querySelector( '[data-testid="multiplexer-time-total"]' )?.textContent;
  assert.equal( before, "3h 12m", "positive control: there are values to preserve" );

  state.failStats = true;
  await r.refreshForTesting();

  assert.equal( root.querySelector( '[data-testid="multiplexer-time-total"]' )?.textContent, "3h 12m",
    "a failed read must not blank a tile — '--' here reads as 'you saved no time', not 'the fetch failed'" );
  assert.equal( root.querySelector( ".time-saved-error" ), null, "and no error is painted into the pane" );
  assert.equal( logs.length, 1, "it is logged exactly once" );
  assert.match( logs[ 0 ]!, /leaving prior values/ );
} );

test( "🔴 the two endpoints are INDEPENDENT — a failing global read does not undo the tiles", async () => {
  const { tile, root, logs } = await mountPane( {
    stats: SOLID_STATS, global: { top_solutions: [] }, failGlobal: true,
  } );
  assert.equal( tile( "multiplexer-time-total" ), "3h 12m",
    "one try/catch around both awaits would let the second endpoint's health decide whether the first's numbers appear" );
  assert.equal( root.querySelector( '[data-testid="multiplexer-top-solutions"]' )?.textContent,
    TOP_SOLUTIONS_LOADING, "and the leaderboard is left exactly as it was" );
  assert.equal( logs.length, 1 );
  assert.match( logs[ 0 ]!, /leaving prior leaderboard/ );
} );

test( "both failing logs twice and rejects nothing", async () => {
  const { logs, tile } = await mountPane( { failStats: true, failGlobal: true } );
  assert.equal( logs.length, 2 );
  assert.equal( tile( "multiplexer-time-total" ), TIME_SAVED_PLACEHOLDER, "nothing was ever painted to lose" );
} );

// ---------------------------------------------------------------------------
// B2 / B3 / B8 — the header controls
// ---------------------------------------------------------------------------

test( "B8: 🔄 refetches BOTH endpoints and repaints, with no debounce guard", async () => {
  const { root, state } = await mountPane( { stats: SOLID_STATS, global: { top_solutions: [] } } );
  const before = state.paths.length;

  const btn = root.querySelector( '[data-testid="multiplexer-time-saved-refresh"]' ) as HTMLElement;
  state.stats = { ...SOLID_STATS, total_time_saved_formatted: "9h 00m" };
  btn.click();
  btn.click();   // twice, immediately — legacy has no guard and neither does this
  await new Promise( ( res ) => setTimeout( res, 0 ) );

  assert.equal( state.paths.length, before + 4, "two presses, two endpoints each — nothing was swallowed" );
  assert.equal( root.querySelector( '[data-testid="multiplexer-time-total"]' )?.textContent, "9h 00m",
    "and the pane repainted from the new answer" );
} );

test( "B2: pressing 🔄 does NOT collapse the section", async () => {
  const { root } = await mountPane();
  ( root.querySelector( '[data-testid="multiplexer-time-saved-refresh"]' ) as HTMLElement )
    .dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.notEqual( root.getAttribute( "data-collapsed" ), "true",
    "the 🔄 is a <button>, so the shared header guard refuses it — the structural form of legacy's stopPropagation" );
} );

test( "B3: collapse works and is NOT persisted", async () => {
  const { root } = await mountPane();
  ( root.querySelector( ".section-header h3" ) as HTMLElement )
    .dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( root.getAttribute( "data-collapsed" ), "true", "it collapses" );

  // Since A-2 #6 persistence is available, so its ABSENCE is now a decision.
  // A second pane is built from scratch and must come back open.
  const second = await mountPane();
  assert.notEqual( second.root.getAttribute( "data-collapsed" ), "true",
    "this pane is session-only; a persisted collapse here would be a divergence, not a bonus" );
} );

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test( "mounting twice throws, and unmount empties the root", async () => {
  const { root, renderer } = await mountPane();
  assert.throws( () => renderer.mount( document.createElement( "div" ) ), /already mounted/ );
  renderer.unmount();
  assert.equal( root.children.length, 0 );
} );

test( "a header click after unmount is inert", async () => {
  const { root, renderer } = await mountPane();
  const header = root.querySelector( ".section-header" ) as HTMLElement;
  renderer.unmount();
  header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.notEqual( root.getAttribute( "data-collapsed" ), "true", "the collapse listener was removed" );
} );
