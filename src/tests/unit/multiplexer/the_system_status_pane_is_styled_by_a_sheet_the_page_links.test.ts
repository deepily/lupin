// 🔴 A CORRECT RENDERER WHOSE STYLESHEET NOTHING LOADS IS A BROKEN PAGE, AND
// EVERY TEST STAYS GREEN — gap G2. B-5 adds a new sheet
// (css/multiplexer/system-status.css) and therefore a new <link> line, which is
// exactly the shape that failed before. Both halves are held here.
//
// 🔴 AND THIS PANE CARRIES A DECLARED EXCEPTION, WHICH IS THE POINT OF THE LIST
// BELOW. Legacy's `updateHealthStatus` (notifications.js:1136) writes
// `status-success` and `status-info` onto the health line, and NO stylesheet the
// legacy page links defines either — checked across all seven of its <link>
// hrefs. So legacy's health line renders unstyled today. The multiplexer emits
// the same two class names for parity of shape, and deliberately ships no rules
// for them: adding rules would make the mux's health line green where legacy's
// is plain, a visible divergence introduced by a stylesheet, which is the
// hardest kind to trace back.
//
// ⚠️ A DECLARED EXCEPTION IS CHECKABLE; AN UNDECLARED ONE IS INVISIBLE. The pair
// is named below with its reason rather than left to redden the sweep, and the
// last test asserts the exception is still EARNED — if legacy ever gains rules
// for them, that test fails and this list should shrink, not grow.
//
// Run: npx tsx --test src/tests/unit/multiplexer/the_system_status_pane_is_styled_by_a_sheet_the_page_links.test.ts

// 🔴 THIS GUARD ONCE COUNTED A CLASS NAMED IN A CSS COMMENT AS STYLED, and it
// carried its own copy of the matcher that did it. Rows 1ce4bf57 (Mr. Radio 🦉)
// and 998ad3b0 (María 🌸) — the same job filed twice. The matcher now comes from
// `testkit/linkedSheets.ts`, which strips comments before matching and ignores
// the inside of attribute selectors, and whose own test file executes the OLD
// behaviour beside the new one so the fix is demonstrated rather than described.
//
// ⚠️ THE SWEEP BELOW STILL ASKS THE BARE-TOKEN QUESTION — "does any selector
// anywhere name this class" — rather than `styledOn`'s "could a selector naming
// this token match THIS element". The stricter question is available in the
// helper and is what the B-6 and B-7 guards use; adopting it here means
// reshaping `paneClasses()` to return per-element class LISTS, and it may
// surface real gaps, as it did on B-7. That is a separate change with its own
// findings, not a silent rider on a matcher swap.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createSystemStatusRenderer } from "../../../lupin_app/static/js/multiplexer/render/SystemStatusRenderer";

import {
  linkedSheets as sharedLinkedSheets,
  linkedCss    as sharedLinkedCss,
  hasRule,
} from "./testkit/linkedSheets";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const HERE        = dirname( fileURLToPath( import.meta.url ) );
const STATIC      = resolve( HERE, "../../../lupin_app/static" );
const MUX_HTML    = join( STATIC, "html/multiplexer.html" );
const LEGACY_HTML = join( STATIC, "html/notifications.html" );
const SHEET       = "/static/css/multiplexer/system-status.css";


// --- the shared matcher (testkit/linkedSheets.ts) --------------------------
const linkedSheets = ( htmlPath: string ): string[] => sharedLinkedSheets( htmlPath );
const linkedCss    = ( htmlPath: string ): string   => sharedLinkedCss( htmlPath, STATIC );

/**
 * Classes the pane emits ON PURPOSE with no rule anywhere — legacy's own defect,
 * inherited rather than fixed. Shrink this list when legacy gains the rules;
 * never grow it to silence a sweep.
 */
const UNSTYLED_BY_LEGACY = [ "status-info", "status-success" ];




/**
 * Mount the pane in EVERY state whose classes differ, and collect them all.
 *
 * 🔴 ONE MOUNT WOULD MISS MOST OF THEM. The status tints are written by the
 * readouts, not by the markup — `status-good` only appears once auth resolves,
 * `status-error` only on a failure, `status-success`/`status-info` only from the
 * health line. A sweep over a single freshly-mounted pane would report a clean
 * bill of health over classes it never saw.
 */
async function paneClasses(): Promise<Set<string>> {
  const found = new Set<string>();
  const intervals: Array<() => void> = [];

  const build = ( tokenOk: boolean, state: "connected" | "failed" ) => {
    const root = document.createElement( "div" );
    const r = createSystemStatusRenderer( {
      eventBus   : createEventBusForTesting(),
      auth       : {
        getToken            : async () => {
          if ( !tokenOk ) throw new Error( "expired" );
          return { accessToken: "t" } as never;
        },
        getCurrentUserEmail : () => "rick@example.com",
        isCurrentUserAdmin  : () => true,
      },
      transports : { queue: { state }, audio: { state } },
      sessionIds : { queue: "wise penguin", audio: "clever dolphin" },
      reinitConfig : async () => ( { status: "success" } ),
      logFn        : () => {},
      nowDateFn    : () => new Date( "2026-09-23T20:30:07Z" ),
      clipboardFn  : async () => {},
      setTimeoutFn : () => 0,
      clearTimeoutFn : () => {},
      setIntervalFn  : ( cb ) => { intervals.push( cb ); return intervals.length; },
      clearIntervalFn: () => {},
    } );
    r.mount( root );
    return { root, r };
  };

  for ( const [ tokenOk, state ] of [ [ true, "connected" ], [ false, "failed" ] ] as const ) {
    const { root, r } = build( tokenOk, state );
    for ( let i = 0; i < 6; i++ ) await Promise.resolve();
    intervals.forEach( ( cb ) => cb() );          // drive the health line to a verdict
    ( root.querySelector( '[data-testid="multiplexer-config-reload-btn"]' ) as HTMLElement ).click();
    for ( let i = 0; i < 6; i++ ) await Promise.resolve();

    for ( const el of [ root, ...Array.from( root.querySelectorAll( "*" ) ) ] ) {
      for ( const cls of Array.from( ( el as HTMLElement ).classList ) ) found.add( cls );
    }
    r.unmount();                                   // also paints HEALTH_STOPPED's class
  }
  return found;
}

test( "the sweeps reach real populations before anything is concluded from them", async () => {
  // 🔴 POSITIVE CONTROLS FIRST. An empty sheet list or an unpainted pane makes
  // every check below pass over nothing, and an absence prints exactly like a
  // clean bill of health.
  const sheets = linkedSheets( MUX_HTML );
  const css    = linkedCss( MUX_HTML );
  const cls    = await paneClasses();

  assert.ok( sheets.length >= 10, `the link sweep found only ${ sheets.length } stylesheets` );
  assert.ok( css.length > 10_000, `the concatenated CSS is only ${ css.length } bytes — a sheet failed to load` );
  assert.ok( cls.size >= 10, `the pane emitted only ${ cls.size } classes — it did not render` );
  for ( const needed of [ "status-good", "status-error", "config-status-ok", "session-entry" ] ) {
    assert.ok( cls.has( needed ),
      `the sweep never saw .${ needed } — a readout did not run, so its class is untested` );
  }
} );

test( "🔴 THE SHEET CARRYING THIS PANE'S RULES IS LINKED BY THE PAGE", () => {
  assert.ok( linkedSheets( MUX_HTML ).includes( SHEET ),
    `multiplexer.html does not link ${ SHEET } — every rule in it is dead, System Status renders ` +
    `unstyled, and no other test is red` );
} );

test( "🔴 EVERY CLASS THE PANE EMITS HAS A RULE IN A LINKED SHEET, except the declared pair", async () => {
  const css     = linkedCss( MUX_HTML );
  const missing = [ ...await paneClasses() ]
    .filter( ( cls ) => !UNSTYLED_BY_LEGACY.includes( cls ) )
    .filter( ( cls ) => !hasRule( css, cls ) )
    .sort();

  assert.deepEqual( missing, [],
    `these classes are emitted by the System Status pane and styled by NO sheet the page links: ` +
    `${ missing.join( ", " ) }. Either add the rule to a LINKED sheet, or add a <link> line — ` +
    `a rule in an unlinked sheet renders a correct renderer as a broken pane while every test stays green` );
} );

test( "🔴 THE DECLARED EXCEPTION IS STILL EARNED — legacy has no rules for these either", () => {
  // The whole justification for shipping two unstyled classes is that legacy
  // ships them unstyled too. If that stops being true, the exception stops being
  // parity and starts being a gap, so the claim is CHECKED rather than asserted
  // once in a comment and left to rot.
  const legacyCss = linkedCss( LEGACY_HTML );
  assert.ok( legacyCss.length > 10_000, "positive control: legacy's own sheets loaded" );
  assert.ok( hasRule( legacyCss, "status-good" ),
    "positive control: the matcher CAN find a rule in legacy's sheets" );

  for ( const cls of UNSTYLED_BY_LEGACY ) {
    assert.equal( hasRule( legacyCss, cls ), false,
      `legacy now defines .${ cls }. The multiplexer should gain the rule too — port it into ` +
      `system-status.css and REMOVE ${ cls } from UNSTYLED_BY_LEGACY. Do not widen the list.` );
  }
} );

test( "the sheet carries the rule families it was ported to carry", () => {
  // ⚠️ NOT A RESTATEMENT OF THE SWEEP. That asks "is every emitted class styled
  // somewhere", which one catch-all rule could satisfy. This asks whether THIS
  // sheet still holds the port.
  const sheet = readFileSync( join( STATIC, SHEET.slice( "/static/".length ) ), "utf8" );
  for ( const selector of [
    ".refresh-link", ".refresh-link:disabled", ".refresh-link.spinning",
    ".status-item", ".session-list", ".session-entry", ".session-entry code", ".copy-btn",
    ".status-good", ".status-error", ".status-warning",
    ".reinit-config-btn", ".config-status", ".config-status-ok", ".config-status-error",
  ] ) {
    assert.ok( sheet.includes( selector ), `system-status.css lost its rule for ${ selector }` );
  }
} );
