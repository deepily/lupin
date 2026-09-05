// The disclosed task row — taskRowDisclosed unit tests.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// THIS FILE'S CENTRAL ASSERTION IS TRAP 2: the three row panes must be
// CELL-FOR-CELL IDENTICAL. Rick asked for that personally — "moving between
// the epic board and the task list meant re-parsing the layout" — so a pane
// that quietly grows or drops a cell is a behavioural regression. The
// cross-pane test is the only thing standing between this port and three
// panes that drift apart one commit at a time.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const M = () => import( "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed" );
const S = () => import( "../../../../lupin_app/static/js/multiplexer/render/rowSchema" );

const TASK = {
  id                  : "0123456789abcdef",
  title               : "a task",
  item_class          : "bug",
  status              : "blocked",
  priority            : "P1",
  blocked_by          : [ { kind: "user", id: "rick" } ],
  next_chase_ts       : "2026-09-08T18:00:00+00:00",
  accountable_manager : "maria",
  created_by          : "mr radio 0e61abe3",
  project             : "lupin",
  body                : "some body",
};

const PANES = [ "task-list", "holding-area", "epic-board" ] as const;

test( "🔴 TRAP 2: all three panes emit the SAME cells in the SAME order", async () => {
  const { renderDisclosedRow } = await M();
  const shapes = PANES.map( ( pane ) => {
    const tr = renderDisclosedRow( TASK, pane, "UTC" ).querySelector( "tr" )!;
    return Array.from( tr.children ).map( ( c ) => ( c as HTMLElement ).className.split( " " )[ 0 ] );
  } );
  assert.ok( shapes[ 0 ].length >= 6, "positive control: the row rendered cells at all" );
  assert.deepEqual( shapes[ 1 ], shapes[ 0 ], "holding area diverged from the task list" );
  assert.deepEqual( shapes[ 2 ], shapes[ 0 ], "epic board diverged from the task list" );
} );

test( "🔴 the visible cell COUNT equals rowWidth() in every pane", async () => {
  const { renderDisclosedRow } = await M();
  const { rowWidth } = await S();
  for ( const pane of PANES ) {
    const tr = renderDisclosedRow( TASK, pane, "UTC" ).querySelector( "tr" )!;
    assert.equal( tr.children.length, rowWidth(), `${ pane } row is not rowWidth() wide` );
  }
} );

test( "the visible cells are ROW_SCHEMA.line1 IN ORDER, then the disclose cell", async () => {
  const { renderDisclosedRow } = await M();
  const { ROW_SCHEMA } = await S();
  const tr  = renderDisclosedRow( TASK, "task-list", "UTC" ).querySelector( "tr" )!;
  const got = Array.from( tr.children ).map( ( c ) => ( c as HTMLElement ).className.split( " " )[ 0 ] );
  assert.deepEqual( got, [ ...ROW_SCHEMA.line1.map( ( f ) => `task-col-${ f }` ), "task-col-disclose" ] );
} );

test( "only the epic board carries the epic-row class", async () => {
  const { renderDisclosedRow } = await M();
  const cls = ( p: typeof PANES[ number ] ) =>
    renderDisclosedRow( TASK, p, "UTC" ).querySelector( "tr" )!.className;
  assert.ok(  cls( "epic-board" ).includes( "epic-row" ) );
  assert.ok( !cls( "task-list" ).includes( "epic-row" ) );
  assert.ok( !cls( "holding-area" ).includes( "epic-row" ) );
} );

test( "one task emits THREE rows: visible, controls, error stripe", async () => {
  const { renderDisclosedRow } = await M();
  const rows = Array.from( renderDisclosedRow( TASK, "task-list", "UTC" ).children );
  assert.equal( rows.length, 3 );
  assert.ok( ( rows[ 0 ] as HTMLElement ).className.includes( "task-row" ) );
  assert.ok( ( rows[ 1 ] as HTMLElement ).className.includes( "task-controls-row" ) );
  assert.ok( ( rows[ 2 ] as HTMLElement ).className.includes( "task-row-error-stripe" ) );
} );

test( "the two extra rows are HIDDEN and keyed to the task", async () => {
  const { renderDisclosedRow } = await M();
  const rows = Array.from( renderDisclosedRow( TASK, "task-list", "UTC" ).children ) as HTMLElement[];
  assert.equal( rows[ 1 ].hidden, true );
  assert.equal( rows[ 2 ].hidden, true );
  assert.equal( rows[ 1 ].getAttribute( "data-controls-for" ), TASK.id );
  assert.equal( rows[ 2 ].getAttribute( "data-error-for" ),    TASK.id );
} );

test( "the visible row carries data-task-id, and an absent id becomes ''", async () => {
  const { renderDisclosedRow } = await M();
  const tr = renderDisclosedRow( {}, "task-list", "UTC" ).querySelector( "tr" )!;
  assert.equal( tr.getAttribute( "data-task-id" ), "" );
} );

test( "the title cell truncates but keeps the FULL title in the title attribute", async () => {
  const { renderDisclosedRow } = await M();
  const long = "x".repeat( 120 );
  const cell = renderDisclosedRow( { title: long }, "task-list", "UTC" ).querySelector( ".task-col-title" )!;
  assert.ok( cell.textContent!.length < long.length );
  assert.equal( cell.getAttribute( "title" ), long );
} );

test( "the status cell carries the dot span AND the status word", async () => {
  const { renderDisclosedRow } = await M();
  const cell = renderDisclosedRow( TASK, "task-list", "UTC" ).querySelector( ".task-col-status" )!;
  assert.ok( cell.querySelector( ".task-status-dot" ) );
  assert.ok( cell.textContent!.includes( "blocked" ) );
} );

test( "a missing status renders 'unknown', never blank", async () => {
  const { renderDisclosedRow } = await M();
  const cell = renderDisclosedRow( {}, "task-list", "UTC" ).querySelector( ".task-col-status" )!;
  assert.ok( cell.textContent!.includes( "unknown" ) );
} );

test( "the class cell badges item_class, defaulting to 'task'", async () => {
  const { renderDisclosedRow } = await M();
  const badge = renderDisclosedRow( {}, "task-list", "UTC" ).querySelector( ".task-col-class .task-class-badge" )!;
  assert.equal( badge.textContent, "task" );
  assert.ok( badge.className.includes( "task-class-task" ) );
} );

test( "the priority cell carries its value and an em-dash when absent", async () => {
  const { renderDisclosedRow } = await M();
  assert.equal( renderDisclosedRow( TASK, "task-list", "UTC" ).querySelector( ".task-col-priority" )!.textContent, "P1" );
  assert.equal( renderDisclosedRow( {},   "task-list", "UTC" ).querySelector( ".task-col-priority" )!.textContent, "—" );
} );

test( "the id cell renders the short id label", async () => {
  const { renderDisclosedRow } = await M();
  const cell = renderDisclosedRow( TASK, "task-list", "UTC" ).querySelector( ".task-col-id" )!;
  assert.ok( TASK.id.startsWith( cell.textContent! ) );
} );

test( "the FILER is disclosed and uses the trailing-session-id rule", async () => {
  const { renderDisclosedRow } = await M();
  const v = renderDisclosedRow( TASK, "task-list", "UTC" ).querySelector( ".task-col-filer .task-disclosed-value" )!;
  assert.equal( v.textContent, "Mr Radio" );
} );

test( "disclosedValues supplies every disclosed field, none undefined", async () => {
  const { disclosedValues } = await M();
  const { ROW_SCHEMA } = await S();
  const vals = disclosedValues( TASK, "UTC" );
  const all  = [ ...ROW_SCHEMA.line2, ...ROW_SCHEMA.line3 ];
  assert.equal( all.length, 7 );          // positive control on the corpus
  for ( const f of all ) assert.ok( vals[ f ] != null, `no value for ${ f }` );
} );

// 🔴 LINE 2 IS TEXT AND LINE 3 IS CONTROLS — the split is the whole point, and a
// test asserting "everything is a string" is what let line 3 render an em-dash
// where the JS card renders nine controls.
test( "line2 is formatted TEXT and line3 is live CONTROLS — not both strings", async () => {
  const { disclosedValues } = await M();
  const { ROW_SCHEMA } = await S();
  const vals = disclosedValues( TASK, "UTC", [ "maria" ] );
  for ( const f of ROW_SCHEMA.line2 ) {
    assert.equal( typeof vals[ f ], "string", `${ f } should be text` );
  }
  for ( const f of ROW_SCHEMA.line3 ) {
    assert.notEqual( typeof vals[ f ], "string", `${ f } should be a live node` );
    assert.ok( ( vals[ f ] as Node ).nodeType, `${ f } should be a Node` );
  }
} );

test( "detail is the INTERACTIVE affordance, not a dead glyph", async () => {
  const { disclosedValues } = await M();
  const withBody = disclosedValues( TASK, "UTC" ).detail as HTMLElement;
  assert.equal( withBody.textContent, "📄" );
  assert.equal( withBody.getAttribute( "role" ), "button" );
  assert.equal( withBody.getAttribute( "tabindex" ), "0" );

  const noBody = disclosedValues( {}, "UTC" ).detail as HTMLElement;
  assert.equal( noBody.textContent, "📄" );
  assert.equal( noBody.getAttribute( "role" ), null );   // nothing to open
  assert.equal( noBody.getAttribute( "aria-disabled" ), "true" );
} );

// 🔴 THE REGRESSION THIS FILE EXISTS TO STOP: a disclosed row that carries the
// row's shape and none of its verbs. Nine controls, named individually, because
// a count alone goes green on nine copies of the wrong one.
test( "the actions field carries the REAL control group, not an em-dash", async () => {
  const { disclosedValues } = await M();
  const actions = disclosedValues( TASK, "UTC", [ "maria", "john" ] ).actions as DocumentFragment;
  const host = document.createElement( "div" );
  host.appendChild( actions );
  for ( const sel of [ ".task-priority-select", ".task-owner-select",
                       ".task-verb-select", ".task-reason-input", ".task-submit-button" ] ) {
    assert.ok( host.querySelector( sel ), `missing ${ sel }` );
  }
  assert.ok( host.querySelectorAll( ".task-verb-select option" ).length >= 6,
             "placeholder + five verbs" );
} );

test( "⚠️ a NULL zone still formats — the epic board passes null deliberately", async () => {
  const { disclosedValues } = await M();
  assert.equal( typeof disclosedValues( TASK, null ).chase, "string" );
} );

test( "an empty task yields em-dashes, never 'undefined' or 'null'", async () => {
  const { disclosedValues } = await M();
  for ( const [ field, v ] of Object.entries( disclosedValues( {}, "UTC" ) ) ) {
    assert.ok( !String( v ).includes( "undefined" ), `${ field } leaked undefined` );
    assert.ok( !String( v ).includes( "null" ),      `${ field } leaked null` );
  }
} );

// 🔴 THIS TEST ENTERS AT THE LAYER THE DEFECT ENTERS AT, AND THE ONES ABOVE DO NOT.
// Every assertion above reads the VALUES MAP. A mutation that made
// renderDisclosedField write every value with textContent — which silently
// stringifies a DocumentFragment to nothing — left all of them GREEN while the
// rendered row carried an empty actions field. The map being right says nothing
// about the controls reaching the DOM; only rendering the row does.
test( "the RENDERED controls row carries the live controls, not stringified nodes", async () => {
  const { renderDisclosedRow } = await M();
  const host = document.createElement( "table" );
  host.appendChild( renderDisclosedRow( TASK, "task-list", "UTC", [ "maria", "john" ] ) );

  const controls = host.querySelector( ".task-controls-row" );
  assert.ok( controls, "no controls row rendered" );

  // Named individually: a count goes green on nine copies of the wrong control.
  for ( const sel of [ ".task-priority-select", ".task-owner-select",
                       ".task-verb-select", ".task-reason-input", ".task-submit-button" ] ) {
    assert.ok( controls!.querySelector( sel ), `controls row is missing ${ sel }` );
  }

  // The detail affordance must be interactive INSIDE the rendered row too.
  const detail = controls!.querySelector( ".task-detail-emoji" );
  assert.ok( detail, "no detail affordance in the rendered row" );
  assert.equal( detail!.getAttribute( "role" ), "button" );

  // POSITIVE CONTROL — a text field still renders as text, so this test is not
  // simply asserting "everything is an element".
  const filer = controls!.querySelector( ".task-col-filer .task-disclosed-value" );
  assert.ok( filer, "no filer field" );
  assert.equal( filer!.children.length, 0, "a text field must not become markup" );
  assert.ok( ( filer!.textContent || "" ).length > 0, "filer rendered empty" );
} );
