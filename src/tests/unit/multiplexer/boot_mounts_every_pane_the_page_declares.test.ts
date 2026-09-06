// Row 87812328 — the guard for IMPLEMENTED-BUT-NOT-INSTALLED.
//
// 🔴 A COMPONENT CAN BE COMPLETE, CORRECT, FULLY COVERED AND ENTIRELY ABSENT
// FROM THE RUNNING PAGE, and every test that builds the component itself stays
// green. The holding area and the epic board each sat at 100% coverage for an
// hour while no page carried a mount id and boot.ts wired neither — the suites
// were reporting on two components, and said nothing about the product.
//
// ⇒ So this file asks a different question from every other test on this
// surface: not "does the renderer work" but "does the APP reach it". Its two
// halves are deliberately different in kind:
//
//   1. TWO source-level sweeps, in OPPOSITE directions, because one direction
//      catches only one kind of defect:
//        a. every id boot.ts looks up must EXIST in the page — catches a mount
//           whose id DRIFTS or is misspelled.
//        b. every <section> and every *-mount the page declares must be MOUNTED
//           by boot — catches a mount that is DELETED.
//
//      🔴 (b) WAS MISSING UNTIL 2026-09-05 AND THIS HEADER CLAIMED OTHERWISE.
//      It read "it fails on a mount that is deleted as loudly as on one that is
//      misspelled", which is FALSE of (a) and was false when written: deleting a
//      mount makes boot's id list SHORTER, and a shorter list has nothing missing
//      from the page, so (a) passes. Raised by Tiberius 👑 in adversarial review;
//      MEASURED before it was accepted — four arms, one variable each, on 34f89644:
//
//        delete the holding-area mount  → RED (test 3 names that pane)
//        delete the task-list mount     → RED — BY ACCIDENT. Test 1's positive
//                                         control happens to use it as its canary;
//                                         that control exists to prove the SWEEP
//                                         reaches something, not to guard a mount.
//        delete the fleet-status mount  → 🔴 GREEN, 8/8. Invisible.
//        delete the notifications mount → 🔴 GREEN, 8/8. The oldest pane on the
//                                         page, silently gone from the product.
//
//      ⇒ A hand-named list of two panes was standing in for the population —
//      the enumeration defect this file's own comments warn about one paragraph
//      down, committed by this file.
//
//      🔴 AND A PREDICATE THAT RESTS ON A NAMING PREMISE IS AN ENUMERATION IN
//      HIDING — Tiberius 👑's second finding, and the sharper half of the two.
//      `<section>` and `-mount` are CONVENTIONS, not laws. boot.ts resolves 15
//      ids; the two predicates derive 13 (7 panes + 6 mount points). The other
//      two — `action-required-section` and `sender-cards-container` — follow
//      neither convention, so the premise is ALREADY FALSE TODAY, and a
//      sixteenth non-conforming id would land silently outside the frame.
//
//      ⇒ So the premise is PINNED rather than the regexes widened: the test
//      below asserts the uncovered set equals exactly those two KNOWN names.
//      The exceptions become declared instead of invisible, and a seventeenth id
//      reddens on the day it lands. Widening the regexes would have fixed today
//      and been wrong again on the next non-conforming name — which is the same
//      enumeration defect wearing a regex.
//   2. A BEHAVIOURAL check — the real renderers mounted into the REAL section
//      elements parsed out of multiplexer.html. A renderer that mounts fine
//      into a hand-built <div> and not into the page's own markup would pass
//      every other test in the tier.
//
// ⚠️ THE TWO SIDES COME FROM DIFFERENT FILES ON PURPOSE. Asserting boot.ts's
// ids against a list retyped here would share a provenance with nothing and
// prove only that I can copy. boot.ts is the actual consumer; the HTML is the
// actual supplier; the comparison can fail.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createHoldingAreaRenderer } from "../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { createEpicBoardRenderer } from "../../../lupin_app/static/js/multiplexer/render/EpicBoardRenderer";
import type { TaskListComposite } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

const HERE = dirname( fileURLToPath( import.meta.url ) );
const BOOT_PATH = resolve( HERE, "../../../lupin_app/static/js/multiplexer/boot.ts" );
const HTML_PATH = resolve( HERE, "../../../lupin_app/static/html/multiplexer.html" );

const bootSource = (): string => readFileSync( BOOT_PATH, "utf8" );
const htmlSource = (): string => readFileSync( HTML_PATH, "utf8" );

/**
 * Every id boot.ts resolves with getElementById, in source order.
 *
 * 🔴 COMMENT LINES ARE DROPPED, AND THAT IS NOT TIDYING. boot.ts carries an
 * 8-line copy-verbatim handshake in a comment block whose placeholder reads
 * `getElementById("<#mount-id>")`. The first cut of this sweep matched it and
 * reported a mount the page does not declare — a real-looking finding about a
 * line that never executes. § A HIT IS NOT A USE: the grep found the NAME, and
 * the question was about the USE.
 *
 * ⚠️ Line-level, not block-level: `/* … *\/` comments would slip past this. It
 * is enough for boot.ts, which uses `//` throughout, and the placeholder test
 * below is what would catch it if that ever stops being true.
 */
function bootMountIds(): string[] {
  return bootSource()
    .split( "\n" )
    .filter( ( line ) => !line.trimStart().startsWith( "//" ) )
    .flatMap( ( line ) => ( line.match( /getElementById\(\s*"([^"]+)"\s*\)/g ) ?? [] ) )
    .map( ( m ) => /"([^"]+)"/.exec( m )![ 1 ] );
}

/** Every id the page declares. */
function pageIds(): Set<string> {
  return new Set( ( htmlSource().match( /\bid="([^"]+)"/g ) ?? [] )
    .map( ( m ) => /"([^"]+)"/.exec( m )![ 1 ] ) );
}

test( "the two sweeps reach real populations before anything is concluded from them", () => {
  // 🔴 POSITIVE CONTROLS FIRST. An extraction that matched nothing would make
  // the sweep below pass over an empty set — a loop over nothing is green, and
  // that is how an absence and a clean bill of health print the same page.
  const ids   = bootMountIds();
  const page  = pageIds();

  assert.ok( ids.length >= 8, `boot.ts sweep found only ${ ids.length } getElementById calls — the regex is not reaching the mounts` );
  assert.ok( page.size >= 8,  `the page sweep found only ${ page.size } ids — the regex is not reaching the markup` );

  // And a known member of each, so a sweep that returns the wrong KIND of thing
  // in the right QUANTITY cannot pass either.
  assert.ok( ids.includes( "task-list-pane" ), "boot.ts no longer mounts the task list — or the sweep is reading the wrong file" );
  assert.ok( page.has( "task-list-pane" ),     "the page no longer declares the task-list pane" );

  // 🔴 AND THE FILTER IS PROVEN, not assumed: boot.ts's copy-verbatim comment
  // block contains a literal `getElementById("<#mount-id>")` placeholder. It
  // must be IN the file (or this control is vacuous) and OUT of the sweep.
  assert.ok( bootSource().includes( 'getElementById("<#mount-id>")' ),
    "the placeholder is gone from boot.ts — this control no longer proves the comment filter does anything" );
  assert.ok( !ids.includes( "<#mount-id>" ),
    "the sweep is reading commented-out code as a live mount" );
} );

test( "EVERY id boot.ts mounts into is declared by the page", () => {
  // ⚠️ THE DENOMINATOR RUNS THE RIGHT WAY ROUND. This asks whether anything
  // boot REACHES FOR is missing, rather than whether a list I wrote is present
  // — a list satisfies itself by being short, and would not have caught a pane
  // I forgot to add.
  const page    = pageIds();
  const missing = bootMountIds().filter( ( id ) => !page.has( id ) );

  assert.deepEqual( missing, [],
    `boot.ts mounts into ids the page does not declare: ${ JSON.stringify( missing ) } — each of these throws at boot` );
} );

test( "the page declares the holding-area and epic-board panes, and boot mounts BOTH", () => {
  // 🔴 THE MUTATION THIS FILE EXISTS FOR. Delete either mount block from
  // boot.ts and the renderer's own 17 or 32 tests stay green, its coverage
  // stays at 100%, and the pane is simply gone from the product.
  const ids  = bootMountIds();
  const page = pageIds();

  for ( const id of [ "holding-area-pane", "epic-board-pane" ] ) {
    assert.ok( page.has( id ), `the page does not declare #${ id }` );
    assert.ok( ids.includes( id ), `boot.ts never mounts #${ id } — the pane is implemented and not installed` );
  }
} );

/**
 * Every mount point the page declares, as PREDICATES over the markup rather than
 * a list typed here.
 *
 * 🔴 A `<section>` WITH AN id IS WHAT A PANE IS ON THIS PAGE. The obvious
 * predicate — an id ending in `-pane` — over-reports: `content-pane` is an
 * `<aside>` layout column nothing mounts into. And a naive `grep 'id="'`
 * over-reports worse still, because `data-testid="` ENDS IN `id="` — that
 * population defect fired on the first probe written for this very fix and
 * returned seven ids that do not exist.
 *
 * ⚠️ A LIST WOULD RE-CREATE THE DEFECT THIS TEST EXISTS TO CLOSE. The guard was
 * blind precisely because two pane names were hand-written into it; replacing
 * them with thirteen hand-written names fixes today and is wrong again the day a
 * fourteenth mount lands. A predicate cannot go stale that way.
 */
function pageMountIds(): string[] {
  const html = htmlSource();
  const sections = ( html.match( /<section[^>]*\sid="([^"]+)"/g ) ?? [] )
    .map( ( m ) => /id="([^"]+)"/.exec( m )![ 1 ] as string );
  const mountPoints = ( html.match( /\sid="([^"]*-mount)"/g ) ?? [] )
    .map( ( m ) => /id="([^"]+)"/.exec( m )![ 1 ] as string );
  return Array.from( new Set( [ ...sections, ...mountPoints ] ) ).sort();
}

test( "EVERY pane and mount point the page declares is MOUNTED by boot — the DELETION direction", () => {
  // 🔴 THE DENOMINATOR THE OTHER WAY ROUND FROM THE TEST ABOVE, and both are
  // needed: that one asks whether anything boot REACHES FOR is missing from the
  // page (drift); this asks whether anything the page DECLARES is missing from
  // boot (deletion). Neither direction can see the other's defect.
  const declared = pageMountIds();
  const mounted  = new Set( bootMountIds() );

  // Positive controls FIRST — a predicate that matched nothing would make the
  // sweep below pass over an empty set, and a loop over nothing is green.
  assert.ok( declared.length >= 13,
    `the sweep found only ${ declared.length } mount points — the predicates are not reaching the markup` );
  assert.ok( declared.includes( "notifications-pane" ),
    "the sweep is not finding the oldest pane on the page — it is reading the wrong thing" );
  assert.ok( declared.includes( "section-toolbar-mount" ),
    "the *-mount predicate found no mount points — only the <section> half is working" );
  // And that it does NOT over-report, which is what makes a failure believable.
  assert.ok( !declared.includes( "content-pane" ),
    "the sweep picked up the layout column — a false finding here trains the next reader to ignore it" );

  const unmounted = declared.filter( ( id ) => !mounted.has( id ) );
  assert.deepEqual( unmounted, [],
    `the page declares mount points boot never resolves: ${ JSON.stringify( unmounted ) } — each is implemented and not installed` );
} );

test( "the two predicates COVER boot, and the exceptions are DECLARED rather than invisible", () => {
  // 🔴 THE PREMISE THE SWEEP ABOVE RESTS ON, PINNED. `<section>` and `-mount`
  // are conventions, not laws, and two live mounts already follow neither — so
  // the premise is false TODAY, not hypothetically. Without this assertion a
  // sixteenth non-conforming id lands silently OUTSIDE the frame, and the
  // deletion-blindness just closed re-opens for it with nothing to say so.
  //
  // ⚠️ PINNED TO THE KNOWN TWO, NOT TO EMPTY. Pinning to [] would demand the
  // exceptions be eliminated, which is a different (and unratified) decision;
  // pinning to the names makes them a declared frontier that a new one breaks.
  // Same move as KNOWN_UNSEEABLE in the coverage gate. Tiberius 👑's form,
  // adopted verbatim — widening the regexes instead would have fixed today and
  // been wrong on the next non-conforming name, which is this file's own
  // enumeration defect wearing a regex.
  // 🔴 WHAT THIS GUARD DISCRIMINATES ON — SAY IT, BECAUSE THE OBVIOUS READING IS
  // WRONG AND IT IS THE FLATTERING ONE. It fires on a NON-CONFORMING ID, never
  // on "a new mount appeared". A new pane called `whatever-pane` inside a
  // `<section>`, or a new `whatever-mount`, is absorbed by the predicates and
  // reddens NOTHING — correctly, because the predicates already cover it. Only a
  // name outside BOTH conventions reaches this assertion.
  //
  // ⚠️ AND THE EVIDENCE FOR THAT IS AN ARM, NOT AN EVENT. Measured 2026-09-05: a
  // fabricated `getElementById("some-new-widget-host")` was INJECTED into
  // boot.ts, this test was observed to go red, and the injection was reverted —
  // restore sha-verified. No sixteenth mount has ever appeared in this repo and
  // nothing was detected in the wild. The claim is a property of the TEST;
  // recording it as a field detection would put a fact in the record that never
  // happened, and that is the version which sounds stronger.
  //
  // ⚠️ WHEN IT DOES FIRE, ADD THE NAME HERE — DO NOT WIDEN A PREDICATE TO SWALLOW
  // IT. Widening turns a declared exception back into an invisible one, which is
  // the enumeration defect this whole file is a correction for. María's ruling,
  // and the same reason the list is pinned to the known two rather than to empty.
  const declared  = new Set( pageMountIds() );
  const uncovered = bootMountIds().filter( ( id ) => !declared.has( id ) );

  assert.deepEqual( Array.from( new Set( uncovered ) ).sort(),
    [ "action-required-section", "sender-cards-container" ],
    "a boot mount falls outside BOTH predicates — widen one, or add it here deliberately" );
} );

test( "the epic board takes NO poll of its own, and the holding area DOES", () => {
  // ⚠️ NOT STYLE. The epic board reads the task list's composite so the two
  // panes cannot show different clocks; a startPolling() on it would reintroduce
  // exactly the drift the shared composite prevents. The holding area's query
  // is a SECOND one — not_approved rows are invisible to the task list's — so
  // it must have its own.
  const src = bootSource();
  assert.ok( src.includes( "stores.holdingArea.startPolling()" ),
    "the holding area does not poll — its pane would never populate" );
  assert.ok( !/stores\.epicBoard/.test( src ),
    "the epic board grew a store of its own — it must read the task list's composite" );
  assert.ok( !/epicBoardRenderer[\s\S]{0,400}?startPolling/.test( src ),
    "the epic board grew a timer of its own — two clocks read as a bug the first time they disagree" );
} );

test( "boot loads the epic stories ONCE and hands them to the board", () => {
  // ⚠️ WITHOUT THE HAND-OFF THE STORE IS LOADED AND UNREAD. That is the
  // implemented-but-not-installed shape one level down: a store at 100%
  // coverage, fetched at boot, and wired to nothing — the board would render
  // de-slugged forever and every one of its own tests would stay green.
  const src = bootSource();
  assert.ok( src.includes( "stores.epicStories.load()" ),
    "boot never loads the epic stories — the board renders de-slugged forever" );
  assert.ok( /storiesFn\s*:\s*\(\)\s*=>\s*stores\.epicStories\.stories\(\)/.test( src ),
    "the stories store is loaded but never handed to the board" );

  // 🔴 AND IT MUST NOT BECOME A POLL. The endpoint serves a hand-edited file;
  // a timer would ask the same question of the same static answer forever.
  assert.ok( !/stores\.epicStories\.startPolling/.test( src ),
    "the epic stories grew a timer — the file is hand-edited, not live state" );
} );

// ---------------------------------------------------------------------------
// The behavioural half — the real renderers into the REAL page markup
// ---------------------------------------------------------------------------

function sectionFromPage( id: string ): HTMLElement {
  const host = document.createElement( "div" );
  host.innerHTML = htmlSource();
  const el = host.querySelector( `#${ id }` );
  assert.ok( el, `#${ id } is not in multiplexer.html` );
  return el as HTMLElement;
}

function stubStore( composite: TaskListComposite | null ) {
  return { composite: () => composite, async refresh() { /* no-op */ } };
}

test( "the holding-area renderer mounts into the PAGE'S OWN section element", () => {
  const section = sectionFromPage( "holding-area-pane" );
  assert.equal( section.childNodes.length, 0, "the page's section is not empty — this test would not prove the mount filled it" );

  createHoldingAreaRenderer( {
    eventBus  : createEventBusForTesting(),
    store     : stubStore( { tasks: [] } ),
    nowDateFn : () => new Date( "2026-09-05T21:00:00Z" ),
  } ).mount( section );

  assert.ok( section.querySelector( ".holding-area-container" ), "the pane painted no container into the page's section" );
} );

test( "the epic-board renderer mounts into the PAGE'S OWN section element", () => {
  const section = sectionFromPage( "epic-board-pane" );
  assert.equal( section.childNodes.length, 0 );

  createEpicBoardRenderer( {
    eventBus  : createEventBusForTesting(),
    store     : stubStore( { tasks: [] } ),
    storiesFn : () => ( {} ),
    nowDateFn : () => new Date( "2026-09-05T21:00:00Z" ),
  } ).mount( section );

  assert.ok( section.querySelector( ".epic-board-container" ), "the pane painted no container into the page's section" );
} );

test( "the page keeps the legacy pane ORDER — task list, then holding area, then epic board", () => {
  // Carbon copy of notifications.html, where the three sit in that order. A
  // reader moving between the two clients should not have to re-find them.
  const html = htmlSource();
  const at = ( id: string ): number => {
    const i = html.indexOf( `id="${ id }"` );
    assert.ok( i !== -1, `#${ id } is not in the page` );
    return i;
  };
  assert.ok( at( "task-list-pane" ) < at( "holding-area-pane" ), "the holding area sits above the task list" );
  assert.ok( at( "holding-area-pane" ) < at( "epic-board-pane" ), "the epic board sits above the holding area" );
} );
