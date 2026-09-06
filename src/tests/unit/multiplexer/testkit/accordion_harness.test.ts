// Inner-accordion component-isolation harness entry tests (happy-dom).
//
// Drives accordionHarness.ts to c8 100%: importing the module wires the window
// test surface; __accordionMount mounts the three panes that HAVE an inner
// accordion, from the real canonical fixture.
//
// ⚠️ happy-dom has NO LAYOUT ENGINE. Every assertion here is a DOM claim —
// which nodes exist, with which classes and attributes. It says nothing about
// whether the accordions LOOK right; that is a browser tier's job.
//
// ⚠️ BOTH `??` ARMS ARE EXERCISED ON PURPOSE. The zone and stories defaults are
// branches, and a suite that only ever mounts a fully-populated scenario covers
// the line while never being able to notice the fallback running wrong.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

interface AccordionHarnessWindow {
  __accordionHarnessReady?: boolean;
  __accordionMount?: ( s: unknown ) => number;
}

const ENTRY = "../../../../lupin_app/static/js/multiplexer/testkit/accordionHarness";

interface Scenario {
  app_timezone? : string | null;
  task_list     : { tasks: unknown[] };
  holding_area  : { tasks: unknown[] };
  epic_stories? : unknown;
}

let scenario: Scenario;

before( async () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  scenario = JSON.parse(
    readFileSync(
      new URL( "../../../e2e_ui/fixtures/accordion-parity-scenario.json", import.meta.url ),
      "utf-8",
    ),
  ) as Scenario;
} );

beforeEach( () => {
  document.body.innerHTML = '<main class="container"><div id="accordion-panes-container"></div></main>';
} );

test( "accordionHarness: import wires the window test surface", async () => {
  await import( ENTRY );
  const w = window as unknown as AccordionHarnessWindow;
  assert.equal( w.__accordionHarnessReady, true );
  assert.equal( typeof w.__accordionMount, "function" );
} );

test( "accordionHarness: __accordionMount renders the three panes that have an inner accordion", async () => {
  await import( ENTRY );
  const w = window as unknown as AccordionHarnessWindow;

  // THREE, not four: fleet status renders a flat table with no inner grouping
  // in either client, so it has no inner accordion to contract.
  assert.equal( w.__accordionMount!( scenario ), 3 );

  const ids = [ ...document.querySelectorAll( "#accordion-panes-container > .accordion-pane" ) ]
    .map( ( p ) => p.id );
  assert.deepEqual( ids, [ "pane-task-list", "pane-holding-area", "pane-epic-board" ] );

  // One group per bucket, from the fixture's deliberately distinct group sizes.
  assert.equal( document.querySelectorAll( "tbody.task-group" ).length, 3 );
  assert.equal( document.querySelectorAll( "div.holding-area-group" ).length, 3 );
  // three fixture epics + the drift section, which renders ALWAYS
  assert.equal( document.querySelectorAll( "tbody.epic-group" ).length, 4 );

  // The two collapse referees are DIFFERENT NODES on purpose, and a walker that
  // flattened them would report one pane's groups as broken.
  const task = document.querySelector( "tbody.task-group" )!;
  const epic = document.querySelector( 'tbody.epic-group[data-epic="epic:alpha"]' )!;
  assert.equal( task.classList.contains( "collapsed" ), false, "task groups default EXPANDED" );
  assert.equal( epic.classList.contains( "collapsed" ), true,  "epic groups default COLLAPSED" );
} );

test( "accordionHarness: __accordionMount is idempotent — a re-mount replaces, never appends", async () => {
  await import( ENTRY );
  const w = window as unknown as AccordionHarnessWindow;

  w.__accordionMount!( scenario );
  w.__accordionMount!( scenario );

  assert.equal( document.querySelectorAll( "#accordion-panes-container > .accordion-pane" ).length, 3 );
  assert.equal( document.querySelectorAll( "tbody.task-group" ).length, 3 );
} );

test( "accordionHarness: an absent zone and an absent stories map take their defaults", async () => {
  await import( ENTRY );
  const w = window as unknown as AccordionHarnessWindow;

  // The `?? null` / `?? {}` arms: a scenario carrying neither key still mounts,
  // and the storied epic then renders NO story row — the map is what supplies it.
  const bare = { task_list: scenario.task_list, holding_area: scenario.holding_area };
  assert.equal( w.__accordionMount!( bare ), 3 );

  const alpha = document.querySelector( 'tbody.epic-group[data-epic="epic:alpha"]' )!;
  assert.equal( alpha.querySelectorAll( "tr.epic-story-row" ).length, 0 );
} );

test( "accordionHarness: the stories map supplies the story row", async () => {
  await import( ENTRY );
  const w = window as unknown as AccordionHarnessWindow;

  w.__accordionMount!( scenario );
  const alpha = document.querySelector( 'tbody.epic-group[data-epic="epic:alpha"]' )!;
  assert.equal( alpha.querySelectorAll( "tr.epic-story-row" ).length, 1,
    "the storied epic renders its story row INSIDE the group" );
} );
