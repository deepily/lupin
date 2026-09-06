// Epic-board card — epicBoardTable template unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 THE FIVE HEADER AND STORY STRINGS ARE COMPARED AGAINST notifications.js,
// NOT AGAINST LITERALS TYPED HERE — the rule this branch already applies to the
// holding area's tooltips, for the same reason: a literal retyped in this file
// shares its provenance with the one in the template, so the two move together
// on any copy-paste error and the comparison can never fail.
//
// ⚠️ THE EXTRACTION CARRIES A COUNT CONTROL. A regex slice that matches nothing
// yields "", and two empty strings compare equal. Non-empty is not enough
// either: it still passes on a slice that found the RIGHT string for the WRONG
// section. So the count of extracted strings is asserted before any comparison.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  renderEpicBoardTable,
  epicBoardSections,
  EPIC_ON_RICK_LABEL,
  EPIC_ON_RICK_STORY,
  EPIC_DRIFT_LABEL,
  EPIC_NO_DRIFT_LABEL,
  EPIC_DRIFT_STORY,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/epicBoardTable";
import {
  groupTasksByEpic,
  epicTitleLabel,
  epicStoryText,
} from "../../../../lupin_app/static/js/multiplexer/render/epicBoardModel";
import {
  EPIC_ON_RICK_KEY,
  EPIC_DRIFT_KEY,
  epicGroupIdSlug,
} from "../../../../lupin_app/static/js/multiplexer/render/epicBoardCollapse";
import { rowWidth } from "../../../../lupin_app/static/js/multiplexer/render/rowSchema";
import type { TaskItem } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before(() => {
  if (typeof globalThis.document === "undefined") {
    GlobalRegistrator.register();
  }
});

beforeEach(() => { localStorage.clear(); });

// ---------------------------------------------------------------------------
// The legacy side
// ---------------------------------------------------------------------------

const HERE = dirname( fileURLToPath( import.meta.url ) );
const LEGACY_PATH = resolve( HERE, "../../../../lupin_app/static/js/notifications.js" );

/** The body of `renderEpicBoardTable`, sliced out of the legacy client. */
function legacyBoardSource(): string {
  const src   = readFileSync( LEGACY_PATH, "utf8" );
  const start = src.indexOf( "renderEpicBoardTable( model, state ) {" );
  assert.ok( start !== -1, "legacy renderEpicBoardTable not found — the extraction is pointing at nothing" );
  const end   = src.indexOf( "renderEpicBoard( composite, stampUpdated = true ) {", start );
  assert.ok( end > start, "legacy renderEpicBoard not found after the table builder" );
  return src.slice( start, end );
}

/**
 * Every double-quoted string literal the legacy board builder passes as text.
 *
 * 🔴 THE `\n` IN THE CHARACTER CLASS IS LOAD-BEARING AND WAS ADDED AFTER THIS
 * EXTRACTION SHIPPED GARBAGE. Without it the regex pairs the CLOSING quote of
 * one literal with the OPENING quote of the next, and returns slabs of source
 * code as "strings" — ten of them, none a section label.
 *
 * ⚠️ AND BOTH OF THE OBVIOUS CONTROLS PASSED ON THAT GARBAGE. The COUNT asked
 * for at least five and got ten; DISTINCTNESS held, because ten slabs of source
 * are all different. A count catches a population whose SIZE is wrong and is
 * blind to a population of the right size made of the wrong things — so it is
 * necessary and NOT sufficient, and the SHAPE control below is the one that
 * covers what it cannot.
 */
function legacyStrings(): string[] {
  return ( legacyBoardSource().match( /"[^"\n]{10,}"/g ) ?? [] ).map( ( s ) => s.slice( 1, -1 ) );
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function task( id: string, epic: string | null, blockedOnRick = false ): TaskItem {
  return {
    id,
    title           : `row ${ id }`,
    status          : "todo",
    priority        : "P2",
    correlation_key : epic ?? undefined,
    blocked_by      : blockedOnRick ? [ { kind: "user", id: "rick" } ] : [],
  } as unknown as TaskItem;
}

// ---------------------------------------------------------------------------
// The extraction's positive control
// ---------------------------------------------------------------------------

test( "the legacy extraction reaches the board builder's own strings", () => {
  const found = legacyStrings();

  // 🔴 EXACTLY EIGHT, DERIVED INDEPENDENTLY RATHER THAN READ OFF THIS
  // EXTRACTOR. A floor ("at least five") is satisfied by garbage — it was, once:
  // the unanchored regex returned TEN and passed. The 8 comes from a different
  // instrument entirely, `awk` over the function's line range piped to
  // `grep -o`, which agrees literal-for-literal with the list below. A control
  // that takes its expected value from the thing it is checking is a tautology.
  //
  //   ⏳ Waiting on Rick · epic-group-on-rick · the highlight story ·
  //   🔴 Drift — rows carrying no epic · ✅ No drift · epic-group-drift ·
  //   the drift story · epic-board-table
  assert.equal( found.length, 8,
    `expected exactly eight quoted literals in the legacy board builder, found ${ found.length } — either the slice boundaries moved or the builder gained a string: ${ JSON.stringify( found.map( ( f ) => f.slice( 0, 40 ) ) ) }` );
  assert.equal( new Set( found ).size, found.length,
    "the extraction returned duplicates — the slice is picking up one section twice" );

  // 🔴 THE SHAPE CONTROL — the one that would have caught the garbage the count
  // and the distinctness both waved through. A section label is a single line;
  // anything carrying a newline or a brace is source code the regex swallowed by
  // pairing quotes across two different literals.
  for ( const found_str of found ) {
    assert.ok( !found_str.includes( "\n" ),
      `an extracted string spans lines — the regex is pairing quotes across two literals: ${ JSON.stringify( found_str.slice( 0, 60 ) ) }` );
    assert.ok( !/[{};]/.test( found_str ),
      `an extracted string carries source punctuation — it is code, not a label: ${ JSON.stringify( found_str.slice( 0, 60 ) ) }` );
  }
} );

test( "the five section strings are byte-identical to the legacy client's", () => {
  const found = new Set( legacyStrings() );
  for ( const [ name, value ] of Object.entries( {
    EPIC_ON_RICK_LABEL, EPIC_ON_RICK_STORY, EPIC_DRIFT_LABEL, EPIC_NO_DRIFT_LABEL, EPIC_DRIFT_STORY,
  } ) ) {
    assert.ok( found.has( value ),
      `${ name } is not present verbatim in the legacy board builder: ${ JSON.stringify( value ) }` );
  }
} );

// ---------------------------------------------------------------------------
// Section order and membership
// ---------------------------------------------------------------------------

test( "the sections run Waiting-on-Rick, then the epics, then Drift LAST", () => {
  const model = groupTasksByEpic( [
    task( "t1", "epic:alpha", true ),
    task( "t2", "epic:alpha" ),
    task( "t3", "epic:beta" ),
    task( "t4", null ),
  ] );
  const keys = epicBoardSections( model ).map( ( s ) => s.epicKey );

  assert.equal( keys[ 0 ], EPIC_ON_RICK_KEY );
  assert.equal( keys[ keys.length - 1 ], EPIC_DRIFT_KEY );
  assert.deepEqual( keys.slice( 1, -1 ), model.groups.map( ( g ) => g.epicKey ) );
} );

test( "Waiting-on-Rick is a HIGHLIGHT — its rows also stay under their own epic", () => {
  const model = groupTasksByEpic( [ task( "t1", "epic:alpha", true ) ] );
  const sections = epicBoardSections( model );

  const onRick = sections.find( ( s ) => s.epicKey === EPIC_ON_RICK_KEY )!;
  const alpha  = sections.find( ( s ) => s.epicKey === "epic:alpha" )!;

  // 🔴 THE SAME ROW IN BOTH. A port that MOVED it would empty an epic that is
  // not empty, and the board would read as though alpha had no work.
  assert.deepEqual( onRick.tasks.map( ( t ) => t.id ), [ "t1" ] );
  assert.deepEqual( alpha.tasks.map( ( t ) => t.id ),  [ "t1" ] );
  assert.equal( onRick.story, EPIC_ON_RICK_STORY,
    "the highlight lost its story line — nothing else tells the reader the rows are duplicated" );
} );

test( "an EMPTY Waiting-on-Rick section is omitted; an empty Drift section is NOT", () => {
  const model = groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] );
  const keys  = epicBoardSections( model ).map( ( s ) => s.epicKey );

  assert.ok( !keys.includes( EPIC_ON_RICK_KEY ), "an empty highlight section rendered — that is noise" );

  // 🔴 THE ASYMMETRY IS THE FINDING, NOT AN INCONSISTENCY. A drift section that
  // vanishes when satisfied is indistinguishable from one that failed to render,
  // and zero drift is exactly what a reader comes here to confirm.
  assert.ok( keys.includes( EPIC_DRIFT_KEY ), "the drift section vanished at zero — its absence is unreadable" );
} );

test( "the drift section swaps BOTH its label and its story between the two states", () => {
  const withDrift = epicBoardSections( groupTasksByEpic( [ task( "t1", null ) ] ) )
    .find( ( s ) => s.epicKey === EPIC_DRIFT_KEY )!;
  const clean = epicBoardSections( groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] ) )
    .find( ( s ) => s.epicKey === EPIC_DRIFT_KEY )!;

  assert.equal( withDrift.label, EPIC_DRIFT_LABEL );
  assert.equal( withDrift.story, EPIC_DRIFT_STORY );

  assert.equal( clean.label, EPIC_NO_DRIFT_LABEL );
  // The all-clear carries NO story — "stamp one" is an instruction for rows that
  // exist, and printing it under a green section is an instruction to do nothing.
  assert.equal( clean.story, "" );
} );

test( "an epic with no story entry still gets a readable de-slugged name", () => {
  const model = groupTasksByEpic( [ task( "t1", "epic:board-visibility" ) ] );
  const section = epicBoardSections( model ).find( ( s ) => s.epicKey === "epic:board-visibility" )!;
  assert.equal( section.label, "board visibility" );
  assert.equal( section.story, "" );
} );

test( "a hand-written story supplies both the title and the one-line story", () => {
  const model = groupTasksByEpic( [ task( "t1", "epic:board-visibility" ) ] );
  const stories = { "epic:board-visibility": { title: "Board Visibility", story: "Make the board legible." } };
  const section = epicBoardSections( model, stories ).find( ( s ) => s.epicKey === "epic:board-visibility" )!;
  assert.equal( section.label, "Board Visibility" );
  assert.equal( section.story, "Make the board legible." );
} );

test( "a story entry with blank fields falls back rather than rendering blank", () => {
  // ⚠️ A PRESENT-BUT-EMPTY ENTRY IS THE CASE A `stories[key] &&` GUARD ALONE
  // GETS WRONG: the object exists, so a truthiness check on the ENTRY passes and
  // the label renders as "".
  const model = groupTasksByEpic( [ task( "t1", "epic:board-visibility" ) ] );
  const section = epicBoardSections( model, { "epic:board-visibility": { title: "", story: "" } } )
    .find( ( s ) => s.epicKey === "epic:board-visibility" )!;
  assert.equal( section.label, "board visibility" );
  assert.equal( section.story, "" );
} );

// ---------------------------------------------------------------------------
// The rendered table
// ---------------------------------------------------------------------------

test( "the table uses the SHARED row head, so its width cannot drift from the rows'", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] ), undefined );
  assert.ok( table.classList.contains( "epic-board-table" ) );
  assert.equal( table.querySelectorAll( "thead th" ).length, rowWidth() );
} );

test( "each section is its own tbody, carrying data-epic and the id its header points at", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] ), undefined );
  const bodies = Array.from( table.querySelectorAll( "tbody.epic-group" ) );
  assert.equal( bodies.length, 2, "expected the alpha epic and the always-present drift section" );

  for ( const tbody of bodies ) {
    const epicKey = tbody.getAttribute( "data-epic" );
    assert.ok( epicKey, "a section tbody carries no data-epic — the accordion cannot key on it" );
    assert.equal( tbody.id, epicGroupIdSlug( epicKey! ) );

    // 🔴 aria-controls MUST NAME THE TBODY'S OWN ID. A header pointing at
    // something else announces the wrong region to a screen reader while looking
    // perfectly correct on screen.
    const header = tbody.querySelector( "tr.epic-group-header" )!;
    assert.equal( header.getAttribute( "aria-controls" ), tbody.id );
  }
} );

test( "every section header is keyboard-operable, not just clickable", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [ task( "t1", "epic:alpha", true ) ] ), undefined );
  const headers = Array.from( table.querySelectorAll( "tr.epic-group-header" ) );
  assert.ok( headers.length >= 3, `expected highlight + alpha + drift, found ${ headers.length }` );
  for ( const h of headers ) {
    assert.equal( h.getAttribute( "role" ), "button" );
    assert.equal( h.getAttribute( "tabindex" ), "0" );
  }
} );

test( "a collapsed section carries the class, the ▸ chevron and aria-expanded=false", () => {
  const model = groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] );
  const table = renderEpicBoardTable( model, { "epic:alpha": false } );

  const tbody = table.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  assert.ok( tbody.classList.contains( "collapsed" ) );

  const header = tbody.querySelector( "tr.epic-group-header" )!;
  assert.equal( header.getAttribute( "aria-expanded" ), "false" );
  assert.equal( tbody.querySelector( ".epic-group-chevron" )!.textContent, "▸" );

  // 🔴 THE ROWS STAY IN THE DOM — collapse is a CSS class flip, not a removal.
  // Asserting their absence would pin a mechanism this pane does not use.
  assert.equal( tbody.querySelectorAll( "tr.task-row" ).length, 1 );
} );

test( "an expanded section carries the ▾ chevron and aria-expanded=true", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] ), { "epic:alpha": true } );
  const tbody = table.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;

  assert.ok( !tbody.classList.contains( "collapsed" ) );
  assert.equal( tbody.querySelector( "tr.epic-group-header" )!.getAttribute( "aria-expanded" ), "true" );
  assert.equal( tbody.querySelector( ".epic-group-chevron" )!.textContent, "▾" );
} );

test( "the header shows THIS section's row count", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [
    task( "t1", "epic:alpha" ), task( "t2", "epic:alpha" ), task( "t3", null ),
  ] ), undefined );

  const alpha = table.querySelector( 'tbody[data-epic="epic:alpha"]' )!;
  const drift = table.querySelector( `tbody[data-epic="${ EPIC_DRIFT_KEY }"]` )!;
  assert.equal( alpha.querySelector( ".epic-group-count" )!.textContent, "2" );
  assert.equal( drift.querySelector( ".epic-group-count" )!.textContent, "1" );
} );

test( "the story row rides INSIDE the group, spanning the full row width", () => {
  const model = groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] );
  const table = renderEpicBoardTable( model, undefined, { "epic:alpha": { story: "Make the board legible." } } );

  const tbody = table.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  const story = tbody.querySelector( "tr.epic-story-row" ) as HTMLElement;
  assert.ok( story, "the story row is not inside the group — opening the epic would not answer 'what is this?'" );
  assert.equal( story.textContent, "Make the board legible." );
  assert.equal( ( story.querySelector( "td" ) as HTMLTableCellElement ).colSpan, rowWidth() );
} );

test( "a section with no story emits NO story row at all", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] ), undefined );
  const tbody = table.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  assert.equal( tbody.querySelectorAll( "tr.epic-story-row" ).length, 0,
    "an empty story row rendered — a blank stripe reads as a story that says nothing" );
} );

test( "the highlight and drift sections carry their accent classes on BOTH tbody and header", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [ task( "t1", null, true ) ] ), undefined );

  const onRick = table.querySelector( `tbody[data-epic="${ EPIC_ON_RICK_KEY }"]` ) as HTMLElement;
  const drift  = table.querySelector( `tbody[data-epic="${ EPIC_DRIFT_KEY }"]` ) as HTMLElement;

  assert.ok( onRick.classList.contains( "epic-group-on-rick" ) );
  assert.ok( onRick.querySelector( "tr.epic-group-header" )!.classList.contains( "epic-group-on-rick-header" ) );
  assert.ok( drift.classList.contains( "epic-group-drift" ) );
  assert.ok( drift.querySelector( "tr.epic-group-header" )!.classList.contains( "epic-group-drift-header" ) );

  // A plain epic gets neither accent — otherwise the accents mean nothing.
  const table2 = renderEpicBoardTable( groupTasksByEpic( [ task( "t2", "epic:alpha" ) ] ), undefined );
  const alpha  = table2.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;
  assert.ok( !alpha.classList.contains( "epic-group-on-rick" ) );
  assert.ok( !alpha.classList.contains( "epic-group-drift" ) );
} );

test( "rows are the SHARED disclosed row, tagged epic-board", () => {
  const table = renderEpicBoardTable( groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] ), undefined );
  const tbody = table.querySelector( 'tbody[data-epic="epic:alpha"]' ) as HTMLElement;

  const row = tbody.querySelector( "tr.task-row" ) as HTMLElement;
  assert.ok( row.classList.contains( "epic-row" ), "the epic board's rows lost their epic-row class" );
  assert.equal( row.getAttribute( "data-task-id" ), "t1" );

  // Three <tr> per task — visible line, hidden controls row, hidden error stripe
  // — plus the section header, and no story row for an epic without one.
  assert.equal( tbody.querySelectorAll( "tr" ).length, 4 );
} );

test( "reassignTargets reach the row's owner select through this pane too", () => {
  const table = renderEpicBoardTable(
    groupTasksByEpic( [ task( "t1", "epic:alpha" ) ] ), undefined, {}, null, [ "rachel", "sam" ] );
  const options = Array.from( table.querySelectorAll( "select option" ) ).map( ( o ) => o.textContent );
  assert.ok( options.some( ( o ) => o === "rachel" ), `owner select never received the roster: ${ JSON.stringify( options ) }` );
} );
