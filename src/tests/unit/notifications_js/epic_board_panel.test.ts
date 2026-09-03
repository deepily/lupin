// Epic Board panel (the MACRO view of the SAME /api/tasks rows) — frontend unit tests.
//
// Plan: src/rnd/v0.2.0/2026.08.24-epic-accordion-mini-plan.md
//
// The Epic Board groups on `correlation_key` ("epic:<slug>") where the Task List
// groups on `owner_persona`. It shares the task list's FETCH — refreshTaskList()
// renders both panes off one composite — so a whole class of test here is about
// what the panel does NOT do: it has no poll, no in-flight guard, and no fetch of
// its own against /api/tasks.
//
// Mirrors the established notifications.js harness (task_list_panel.test.ts):
// load the class via vm.runInThisContext (sliced before the DOM-ready init),
// Object.create the prototype to skip the constructor, hand-set the few fields
// the methods read, then drive the methods directly under happy-dom.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/epic_board_panel.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { TASK_LIST_QUERY } from "../../../lupin_app/static/js/shared/task-list-query.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  window.LUPIN_TASK_LIST_QUERY = TASK_LIST_QUERY;
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type Row = Record<string, unknown>;

type EpicGroupModel = { epicKey: string; tasks: Row[] };
type EpicModel = { totalCount: number; onRick: Row[]; groups: EpicGroupModel[]; drift: Row[] };

type EpicUI = Record<string, unknown> & {
  _epicKeyOf: ( task: unknown ) => string | null;
  _epicTitleLabel: ( key: string ) => string;
  _epicStoryText: ( key: string ) => string;
  _taskWaitsOnRick: ( task: unknown ) => boolean;
  groupTasksByEpic: ( tasks: unknown ) => EpicModel;
  _epicGroupIdSlug: ( key: string ) => string;
  _epicDefaultExpanded: ( key: string ) => boolean;
  loadEpicGroupState: () => Record<string, boolean>;
  saveEpicGroupState: ( state: Record<string, boolean> ) => void;
  _epicGroupIsExpanded: ( key: string, state: unknown ) => boolean;
  toggleEpicCollapsed: ( key: string ) => boolean;
  _renderEpicRow: ( task: Row ) => string;
  renderEpicBoardTable: ( model: EpicModel, state?: unknown ) => string;
  renderEpicBoard: ( composite: unknown, stampUpdated?: boolean ) => void;
  _stampEpicBoardUpdated: () => void;
  _applyEpicGroupCollapseState: ( tbody: HTMLElement, isCollapsed: boolean ) => void;
  _handleEpicAccordionToggle: ( target: unknown ) => void;
  _handleEpicBoardClick: ( target: unknown ) => void;
  _captureOperatorState: ( container: unknown ) => unknown;
  _restoreOperatorState: ( container: unknown, state: unknown ) => void;
  _handleDisclosureToggle: ( button: unknown ) => void;
  loadEpicGroupState: () => Record<string, boolean>;
  _handleRowControlClick: ( target: unknown ) => boolean;
  _disclosureToggle: ( task: Row ) => string;
  _handleDisclosureToggle: ( button: unknown ) => void;
  _handleTaskDropClick: ( button: unknown ) => void;
  _wireEpicBoardAccordion: () => void;
  _epicKeysInDom: () => string[];
  collapseAllEpics: () => void;
  expandAllEpics: () => void;
  fetchEpicStories: () => Promise<Record<string, unknown>>;
  refreshTaskList: () => Promise<void>;
  authedFetch: ( url: string ) => Promise<unknown>;
};

function newUI(): EpicUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as EpicUI;
  ui.debug                       = false;
  ui.log                         = (): void => {};
  ui.error                       = (): void => {};
  ui.EPIC_KEY_PREFIX             = "epic:";
  ui.EPIC_UNASSIGNED_KEY         = "epic:unassigned";
  ui.EPIC_ON_RICK_KEY            = "__on_rick__";
  ui.EPIC_DRIFT_KEY              = "__drift__";
  ui.EPIC_BLOCKER_OF_INTEREST    = "rick";
  ui.EPIC_BOARD_STATE_KEY        = "lupin.epicBoard.groupState";
  ui._epicBoardAccordionWired    = false;
  ui._epicStories                = {};
  ui._epicStoriesFetched         = false;
  ui.TASK_TITLE_TRUNCATE_LEN     = 60;
  // Task-list fields the shared refresh path reads.
  ui._taskListFetchInFlight      = false;
  ui._taskListLastGoodTasks      = null;
  ui.TASK_LIST_COLLAPSED_KEY     = "lupin.taskList.collapsedOwners";
  ui.TASK_LIST_UNASSIGNED_KEY    = "__unassigned__";
  ui._taskListAccordionWired     = false;
  return ui;
}

function buildPanelDOM(): void {
  document.body.replaceChildren();
  const section = document.createElement( "div" );
  section.id = "section-epic-board";
  section.innerHTML = `
    <h3>Epic Board: <span id="epic-board-count">0</span>
        <span id="epic-board-updated"></span></h3>
    <div id="epic-board-container"></div>`;
  document.body.appendChild( section );
}

function fakeResponse( status: number, ok: boolean, jsonBody: unknown ): unknown {
  return { status, ok, json: async () => jsonBody };
}

// ══════════ WIRING THE PANE, BECAUSE `buildPanelDOM` DOES NOT ══════════
//
// 🔴 It paints `#epic-board-container` and stops. So the tests below that called
// `_handleEpicAccordionToggle` or `_handleDisclosureToggle` BY NAME were measuring a
// correct handler against a pane with no listener on it — a control can be dead on
// screen and the test still green.
//
// ⚠️ THIS FILE IS NOT AS BLIND AS `podcast_overlay` WAS. Measured 2026-09-02: delete
// every click listener in notifications.js and it goes 70/0 -> 66 pass / 4 fail,
// because it already carries four real click-path tests. These are gaps in a watched
// file, which wants different framing from a watched denominator of zero.
// ⚠️ IT DOES NOT RESET `_epicBoardAccordionWired`, AND THAT MATTERS. `renderEpicBoard`
// already wires the pane, so forcing a re-wire installs a SECOND listener and one click
// then fires the handler TWICE — which toggles the group open and straight back shut.
// Measured on the way in: three of these tests failed with "expected false, actual true"
// against a perfectly correct page, because the fixture was double-firing. The method's
// own wired-once guard is the thing to lean on, not to defeat.
//
// ⚠️ AND IT DELIBERATELY DIVERGES FROM `task_list_panel.test.ts`, WHICH STILL RESETS.
// Harmonising the two looked obviously right and was tried; measured, it re-introduced
// that file's non-terminating break arm, while the resetting form leaves it readable at
// 162 pass / 13 fail. So the two helpers differ ON PURPOSE — evidence-led, not drift —
// and it is a third fact pointing at the same unexplained interaction over there.
// Noted, not chased: see the open-item note beside that file's accordion tests.
function wirePane( ui: EpicUI ): void {
  ui._wireEpicBoardAccordion();
}

// Dispatch a real bubbling click and assert a handler was REACHED; the caller then goes
// on asserting what the click DID.
//
// 🔴 THE REACHED-CHECK IS WHAT MAKES THE NO-OP CASES MEAN ANYTHING. "Nothing happened"
// is satisfied by a handler that correctly declined AND by no listener existing — two
// sufficient causes for one observation. Proving the handler ran kills the second, and
// the check sits ON THE PATH, so a conversion cannot quietly skip it.
function clickThrough( ui: EpicUI, method: string, el: Element | null, what: string ): void {
  assert.ok( el, `${ what } did not render at all — this test cannot speak to wiring` );

  const target   = ui as unknown as Record<string, ( t: unknown ) => unknown >;
  const original = target[ method ];
  let   reached  = false;
  target[ method ] = ( t: unknown ) => { reached = true; return original.call( ui, t ); };
  el!.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
  target[ method ] = original;

  assert.ok( reached,
    `${ what } reached NO handler — the pane has no click listener for it, so the ` +
    `control is dead on screen however correct the handler is` );
}

// Representative rows. Note R_NO_KEY and R_WRONG_KEY: the no-correlation_key path
// the plan's DoD calls out by name, in BOTH its shapes.
const R_SEAL_A   = { id: "aaaaaaaa1", title: "Block the network", status: "blocked",
                     correlation_key: "epic:seal-the-test-tier", priority: "P1" };
const R_SEAL_B   = { id: "aaaaaaaa2", title: "Widen the coverage frame", status: "queued",
                     correlation_key: "epic:seal-the-test-tier", priority: "P2" };
const R_SEAL_C   = { id: "aaaaaaaa3", title: "Audit the skips", status: "in_progress",
                     correlation_key: "epic:seal-the-test-tier", priority: "P2" };
const R_BOARD    = { id: "bbbbbbbb1", title: "Rick can see his board", status: "in_progress",
                     correlation_key: "epic:board-visibility", priority: "P0" };
const R_UNASSIGN = { id: "cccccccc1", title: "Belongs to no epic on purpose", status: "queued",
                     correlation_key: "epic:unassigned", priority: "P3" };
const R_NO_KEY   = { id: "dddddddd1", title: "Minted without an epic", status: "queued",
                     priority: "P2" };
const R_WRONG_KEY= { id: "eeeeeeee1", title: "Key overwritten by a respawn", status: "queued",
                     correlation_key: "cc-task:respawn-adoption", priority: "P1" };
const R_ON_RICK  = { id: "ffffffff1", title: "Needs a ruling", status: "blocked",
                     correlation_key: "epic:board-visibility", priority: "P0",
                     blocked_by: [ { kind: "user", id: "rick" } ] };

beforeEach( () => { document.body.replaceChildren(); localStorage.clear(); } );

// ───────────────────────────── _epicKeyOf (pure) ──────────────────────────────

test( "_epicKeyOf: an 'epic:' correlation_key is returned verbatim", () => {
  const ui = newUI();
  assert.equal( ui._epicKeyOf( R_SEAL_A ), "epic:seal-the-test-tier" );
  assert.equal( ui._epicKeyOf( R_UNASSIGN ), "epic:unassigned" );
} );

test( "_epicKeyOf: NO correlation_key at all → null (the DoD's no-key path)", () => {
  const ui = newUI();
  assert.equal( ui._epicKeyOf( R_NO_KEY ), null );
  assert.equal( ui._epicKeyOf( {} ), null );
  assert.equal( ui._epicKeyOf( { correlation_key: null } ), null );
  assert.equal( ui._epicKeyOf( { correlation_key: "" } ), null );
} );

test( "_epicKeyOf: a NON-epic correlation_key → null (respawn-adoption overwrite)", () => {
  // The second shape of the same defect: the row HAS a key, it just is not an
  // epic. A plain truthiness check would wrongly file this under its own group.
  const ui = newUI();
  assert.equal( ui._epicKeyOf( R_WRONG_KEY ), null );
  assert.equal( ui._epicKeyOf( { correlation_key: "not-epic:foo" } ), null );
} );

test( "_epicKeyOf: a falsy / undefined task never throws", () => {
  const ui = newUI();
  assert.equal( ui._epicKeyOf( null ), null );
  assert.equal( ui._epicKeyOf( undefined ), null );
} );

// ──────────────────── _epicTitleLabel / _epicStoryText (pure) ─────────────────

test( "_epicTitleLabel: a known epic renders its hand-written title", () => {
  const ui = newUI();
  ui._epicStories = { "epic:seal-the-test-tier": { title: "Seal the test tier", story: "…" } };
  assert.equal( ui._epicTitleLabel( "epic:seal-the-test-tier" ), "Seal the test tier" );
} );

test( "_epicTitleLabel: a MISSING entry de-slugs rather than erroring (DoD)", () => {
  const ui = newUI();
  ui._epicStories = {};
  assert.equal( ui._epicTitleLabel( "epic:seal-the-test-tier" ), "seal the test tier" );
  assert.equal( ui._epicTitleLabel( "epic:board-visibility" ), "board visibility" );
} );

test( "_epicTitleLabel: a story entry with a BLANK title still de-slugs", () => {
  const ui = newUI();
  ui._epicStories = { "epic:board-visibility": { title: "", story: "x" } };
  assert.equal( ui._epicTitleLabel( "epic:board-visibility" ), "board visibility" );
} );

test( "_epicStoryText: present → the text; absent or blank → empty string", () => {
  const ui = newUI();
  ui._epicStories = { "epic:a-b": { title: "A B", story: "The one-liner." },
                      "epic:c-d": { title: "C D" } };
  assert.equal( ui._epicStoryText( "epic:a-b" ), "The one-liner." );
  assert.equal( ui._epicStoryText( "epic:c-d" ), "" );
  assert.equal( ui._epicStoryText( "epic:never-written" ), "" );
} );

// ──────────────────────────── _taskWaitsOnRick (pure) ─────────────────────────

test( "_taskWaitsOnRick: matches kind 'user' AND kind 'persona' — kind is ignored on purpose", () => {
  const ui = newUI();
  assert.equal( ui._taskWaitsOnRick( { blocked_by: [ { kind: "user", id: "rick" } ] } ), true );
  assert.equal( ui._taskWaitsOnRick( { blocked_by: [ { kind: "persona", id: "Rick" } ] } ), true );
  assert.equal( ui._taskWaitsOnRick( { blocked_by: [ { kind: "user", id: "  RICK " } ] } ), true );
} );

test( "_taskWaitsOnRick: an 'item' blocker named rick does NOT count", () => {
  const ui = newUI();
  assert.equal( ui._taskWaitsOnRick( { blocked_by: [ { kind: "item", id: "rick" } ] } ), false );
} );

test( "_taskWaitsOnRick: true when ANY ref names him, among several", () => {
  const ui = newUI();
  const row = { blocked_by: [ { kind: "item", id: "abc" }, { kind: "user", id: "rick" } ] };
  assert.equal( ui._taskWaitsOnRick( row ), true );
} );

test( "_taskWaitsOnRick: absent / non-array / malformed blocked_by → false, never throws", () => {
  const ui = newUI();
  assert.equal( ui._taskWaitsOnRick( {} ), false );
  assert.equal( ui._taskWaitsOnRick( { blocked_by: null } ), false );
  assert.equal( ui._taskWaitsOnRick( { blocked_by: "user:rick" } ), false );
  assert.equal( ui._taskWaitsOnRick( { blocked_by: [ null, "junk", 7 ] } ), false );
  assert.equal( ui._taskWaitsOnRick( null ), false );
} );

// ──────────────────────────── groupTasksByEpic (pure) ─────────────────────────

test( "groupTasksByEpic: groups on correlation_key, biggest bucket first", () => {
  const ui = newUI();
  const m = ui.groupTasksByEpic( [ R_BOARD, R_SEAL_A, R_SEAL_B, R_SEAL_C ] );
  assert.deepEqual( m.groups.map( g => g.epicKey ),
                    [ "epic:seal-the-test-tier", "epic:board-visibility" ] );
  assert.equal( m.groups[ 0 ].tasks.length, 3 );
  assert.equal( m.groups[ 1 ].tasks.length, 1 );
} );

test( "groupTasksByEpic: 'epic:unassigned' sinks LAST even when it is the biggest", () => {
  const ui = newUI();
  const many = [ R_UNASSIGN, { ...R_UNASSIGN, id: "u2" }, { ...R_UNASSIGN, id: "u3" }, R_BOARD ];
  const m = ui.groupTasksByEpic( many );
  assert.equal( m.groups[ m.groups.length - 1 ].epicKey, "epic:unassigned" );
} );

test( "groupTasksByEpic: equal-sized epics order by key, so a re-render never reshuffles", () => {
  const ui = newUI();
  const m1 = ui.groupTasksByEpic( [ R_BOARD, R_SEAL_A ] );
  const m2 = ui.groupTasksByEpic( [ R_SEAL_A, R_BOARD ] );
  assert.deepEqual( m1.groups.map( g => g.epicKey ), m2.groups.map( g => g.epicKey ) );
  assert.deepEqual( m1.groups.map( g => g.epicKey ),
                    [ "epic:board-visibility", "epic:seal-the-test-tier" ] );
} );

test( "groupTasksByEpic: rows with NO epic key land in drift, never silently dropped (DoD)", () => {
  const ui = newUI();
  const m = ui.groupTasksByEpic( [ R_SEAL_A, R_NO_KEY, R_WRONG_KEY ] );
  assert.equal( m.drift.length, 2 );
  assert.deepEqual( m.drift.map( r => r.id ).sort(), [ "dddddddd1", "eeeeeeee1" ] );
  // And they are NOT also in an epic group.
  const grouped = m.groups.flatMap( g => g.tasks.map( t => t.id ) );
  assert.equal( grouped.includes( "dddddddd1" ), false );
  assert.equal( grouped.includes( "eeeeeeee1" ), false );
} );

test( "groupTasksByEpic: every input row lands in exactly one of groups / drift", () => {
  const ui = newUI();
  const rows = [ R_SEAL_A, R_SEAL_B, R_BOARD, R_UNASSIGN, R_NO_KEY, R_WRONG_KEY, R_ON_RICK ];
  const m = ui.groupTasksByEpic( rows );
  const placed = m.groups.flatMap( g => g.tasks ).length + m.drift.length;
  assert.equal( placed, rows.length );
  assert.equal( m.totalCount, rows.length );
} );

test( "groupTasksByEpic: onRick is a HIGHLIGHT — the row ALSO stays under its epic", () => {
  const ui = newUI();
  const m = ui.groupTasksByEpic( [ R_BOARD, R_ON_RICK ] );
  assert.deepEqual( m.onRick.map( r => r.id ), [ "ffffffff1" ] );
  const board = m.groups.find( g => g.epicKey === "epic:board-visibility" )!;
  assert.equal( board.tasks.length, 2, "the on-Rick row is NOT removed from its epic" );
} );

test( "groupTasksByEpic: onRick sorts P0 first, then id — stable across input order", () => {
  const ui = newUI();
  const p2 = { id: "zzz", title: "later", status: "blocked", correlation_key: "epic:a",
               priority: "P2", blocked_by: [ { kind: "user", id: "rick" } ] };
  const m = ui.groupTasksByEpic( [ p2, R_ON_RICK ] );
  assert.deepEqual( m.onRick.map( r => r.priority ), [ "P0", "P2" ] );
} );

test( "groupTasksByEpic: within a group, rows sort blocked-first then priority", () => {
  const ui = newUI();
  const m = ui.groupTasksByEpic( [ R_SEAL_B, R_SEAL_C, R_SEAL_A ] );
  assert.deepEqual( m.groups[ 0 ].tasks.map( r => r.status ),
                    [ "blocked", "in_progress", "queued" ] );
} );

test( "groupTasksByEpic: a non-array / empty input yields an empty model, never throws", () => {
  const ui = newUI();
  for ( const input of [ [], null, undefined, "nope", 7, {} ] ) {
    const m = ui.groupTasksByEpic( input );
    assert.equal( m.totalCount, 0 );
    assert.deepEqual( m.groups, [] );
    assert.deepEqual( m.drift, [] );
    assert.deepEqual( m.onRick, [] );
  }
} );

test( "groupTasksByEpic: falsy rows inside the array collapse to drift, never throw", () => {
  const ui = newUI();
  const m = ui.groupTasksByEpic( [ null, undefined, R_SEAL_A ] );
  assert.equal( m.totalCount, 3 );
  assert.equal( m.drift.length, 2 );
  assert.equal( m.groups.length, 1 );
} );

// ─────────────────────── collapse defaults + persistence ──────────────────────

test( "_epicDefaultExpanded: epics and drift start CLOSED; waiting-on-Rick starts OPEN", () => {
  const ui = newUI();
  assert.equal( ui._epicDefaultExpanded( "epic:anything" ), false );
  assert.equal( ui._epicDefaultExpanded( "__drift__" ), false );
  assert.equal( ui._epicDefaultExpanded( "__on_rick__" ), true );
} );

test( "loadEpicGroupState: absent / garbled / wrong-typed storage → {} (never throws)", () => {
  const ui = newUI();
  assert.deepEqual( ui.loadEpicGroupState(), {} );
  localStorage.setItem( ui.EPIC_BOARD_STATE_KEY as string, "{not json" );
  assert.deepEqual( ui.loadEpicGroupState(), {} );
  localStorage.setItem( ui.EPIC_BOARD_STATE_KEY as string, "[1,2,3]" );
  assert.deepEqual( ui.loadEpicGroupState(), {} );
} );

test( "loadEpicGroupState: non-boolean values are dropped defensively", () => {
  const ui = newUI();
  localStorage.setItem( ui.EPIC_BOARD_STATE_KEY as string,
                        JSON.stringify( { "epic:a": true, "epic:b": "yes", "epic:c": 1 } ) );
  assert.deepEqual( ui.loadEpicGroupState(), { "epic:a": true } );
} );

test( "_epicGroupIsExpanded: a recorded choice WINS over the default, in both directions", () => {
  const ui = newUI();
  // An epic the viewer opened stays open…
  assert.equal( ui._epicGroupIsExpanded( "epic:a", { "epic:a": true } ), true );
  // …and the on-Rick section the viewer closed stays closed.
  assert.equal( ui._epicGroupIsExpanded( "__on_rick__", { "__on_rick__": false } ), false );
  // No record → the default.
  assert.equal( ui._epicGroupIsExpanded( "epic:a", {} ), false );
  assert.equal( ui._epicGroupIsExpanded( "__on_rick__", undefined ), true );
} );

test( "toggleEpicCollapsed: flips, persists, and survives a reload (DoD)", () => {
  const ui = newUI();
  // First toggle on a default-CLOSED epic opens it.
  assert.equal( ui.toggleEpicCollapsed( "epic:a" ), false, "returns the new COLLAPSED boolean" );
  // A fresh instance reading the same storage sees the choice — this is the
  // "collapse state persists across a page reload" requirement.
  const reloaded = newUI();
  assert.equal( reloaded._epicGroupIsExpanded( "epic:a", reloaded.loadEpicGroupState() ), true );
  // Toggling back closes it again.
  assert.equal( ui.toggleEpicCollapsed( "epic:a" ), true );
  assert.equal( newUI()._epicGroupIsExpanded( "epic:a", newUI().loadEpicGroupState() ), false );
} );

test( "a NEWLY-MINTED epic takes the closed default rather than inheriting a stale set", () => {
  // The reason state is stored as CHOICES, not as a collapsed set: an epic the
  // viewer has never seen must not arrive open just because it is absent.
  const ui = newUI();
  ui.saveEpicGroupState( { "epic:old": true } );
  const state = ui.loadEpicGroupState();
  assert.equal( ui._epicGroupIsExpanded( "epic:old", state ), true );
  assert.equal( ui._epicGroupIsExpanded( "epic:brand-new", state ), false );
} );

test( "saveEpicGroupState: a throwing localStorage is swallowed, never breaks rendering", () => {
  const ui = newUI();
  const original = localStorage.setItem;
  ( localStorage as unknown as Record<string, unknown> ).setItem = (): never => {
    throw new Error( "QuotaExceeded" );
  };
  assert.doesNotThrow( () => ui.saveEpicGroupState( { "epic:a": true } ) );
  ( localStorage as unknown as Record<string, unknown> ).setItem = original;
} );

// ───────────────────────────── _epicGroupIdSlug ───────────────────────────────

test( "_epicGroupIdSlug: non-id-safe characters become dashes", () => {
  const ui = newUI();
  assert.equal( ui._epicGroupIdSlug( "epic:seal-the-test-tier" ), "epic-group-epic-seal-the-test-tier" );
  assert.equal( ui._epicGroupIdSlug( "__on_rick__" ), "epic-group-__on_rick__" );
} );

// ──────────────────────────── table rendering (pure) ──────────────────────────

test( "renderEpicBoardTable: FOUR columns — owner is deliberately absent", () => {
  const ui = newUI();
  const html = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ R_SEAL_A ] ), {} );
  assert.ok( html.includes( "epic-col-id" ) );
  assert.ok( html.includes( "epic-col-priority" ) );
  assert.ok( html.includes( "epic-col-status" ) );
  assert.ok( html.includes( "epic-col-title" ) );
  assert.equal( html.includes( "epic-col-owner" ), false );
  assert.equal( html.includes( "task-col-accountable" ), false );
} );

test( "renderEpicBoardTable: waiting-on-Rick leads, drift closes, epics in between", () => {
  const ui = newUI();
  const html = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ R_ON_RICK, R_SEAL_A, R_NO_KEY ] ), {} );
  const onRickAt = html.indexOf( "Waiting on Rick" );
  const epicAt   = html.indexOf( "epic-group-epic-seal-the-test-tier" );
  const driftAt  = html.indexOf( "Drift" );
  assert.ok( onRickAt >= 0 && epicAt >= 0 && driftAt >= 0 );
  assert.ok( onRickAt < epicAt, "the highlight leads" );
  assert.ok( epicAt < driftAt, "drift closes" );
} );

test( "renderEpicBoardTable: an EMPTY drift group still renders, as a green all-clear (DoD)", () => {
  // A section that vanishes when satisfied cannot be told apart from one that
  // failed to render — and zero-drift is exactly what a reader wants confirmed.
  const ui = newUI();
  const html = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ R_SEAL_A ] ), {} );
  assert.ok( html.includes( "epic-group-drift" ), "the drift tbody is present" );
  assert.ok( html.includes( "No drift" ) );
  assert.equal( html.includes( "🔴 Drift" ), false );
} );

test( "renderEpicBoardTable: the waiting-on-Rick group is ABSENT when nothing waits on him", () => {
  const ui = newUI();
  const html = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ R_SEAL_A ] ), {} );
  assert.equal( html.includes( "Waiting on Rick" ), false );
} );

test( "renderEpicBoardTable: collapsed groups get the class, chevron ▸ and aria-expanded=false", () => {
  const ui = newUI();
  const model = ui.groupTasksByEpic( [ R_SEAL_A ] );
  const closed = ui.renderEpicBoardTable( model, {} );
  assert.ok( closed.includes( 'class="epic-group collapsed"' ) );
  assert.ok( closed.includes( 'aria-expanded="false"' ) );
  assert.ok( closed.includes( "▸" ) );
  const open = ui.renderEpicBoardTable( model, { "epic:seal-the-test-tier": true } );
  assert.ok( open.includes( 'aria-expanded="true"' ) );
  assert.ok( open.includes( "▾" ) );
} );

test( "renderEpicBoardTable: an epic with a story renders it; one without renders no story row", () => {
  const ui = newUI();
  ui._epicStories = { "epic:seal-the-test-tier": { title: "Seal the test tier", story: "A green run does not mean what it says." } };
  const html = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ R_SEAL_A, R_BOARD ] ), {} );
  assert.ok( html.includes( "A green run does not mean what it says." ) );
  // board-visibility has no story → exactly two story rows exist (on-Rick has a
  // fixed one only when present; here it is absent), so count them.
  const storyRows = html.split( "epic-story-row" ).length - 1;
  assert.equal( storyRows, 1 );
} );

test( "renderEpicBoardTable: a MISSING story renders the de-slugged name and does not error (DoD)", () => {
  const ui = newUI();
  ui._epicStories = {};
  const html = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ R_SEAL_A ] ), {} );
  assert.ok( html.includes( "seal the test tier" ) );
} );

test( "renderEpicBoardTable: a hostile title/story is escaped, not injected", () => {
  const ui = newUI();
  ui._epicStories = { "epic:x": { title: "<img src=x onerror=alert(1)>", story: "<script>bad()</script>" } };
  const row = { id: "h1", title: "<b>nope</b>", status: "queued", correlation_key: "epic:x", priority: "P1" };
  const html = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ row ] ), { "epic:x": true } );
  assert.equal( html.includes( "<img src=x" ), false );
  assert.equal( html.includes( "<script>bad()" ), false );
  assert.equal( html.includes( "<b>nope</b>" ), false );
  assert.ok( html.includes( "&lt;" ) );
} );

test( "_renderEpicRow: status class + priority heat class + truncated title with full tooltip", () => {
  const ui = newUI();
  const long = "x".repeat( 90 );
  const html = ui._renderEpicRow( { id: "abcdefgh12345", title: long, status: "blocked", priority: "P0" } );
  assert.ok( html.includes( "task-status-blocked" ) );
  assert.ok( html.includes( "task-prio-high" ) );
  assert.ok( html.includes( "abcdefgh" ) && !html.includes( "abcdefgh1<" ) );
  assert.ok( html.includes( "…" ), "title is truncated" );
  assert.ok( html.includes( `title="${long}"` ), "the FULL title rides the tooltip" );
} );

test( "_renderEpicRow: a row missing status/priority still renders, dashed and unknown", () => {
  const ui = newUI();
  const html = ui._renderEpicRow( { id: "z", title: "bare" } );
  assert.ok( html.includes( "task-status-unknown" ) );
  assert.ok( html.includes( "unknown" ) );
  assert.ok( html.includes( "—" ) );
} );

// ───────────────────────────── renderEpicBoard (DOM) ──────────────────────────

test( "renderEpicBoard: happy path fills the container and counts EPICS, not rows", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderEpicBoard( { tasks: [ R_SEAL_A, R_SEAL_B, R_BOARD ], count: 3 } );
  const container = document.getElementById( "epic-board-container" )!;
  assert.equal( container.querySelector( "table.epic-board-table" ) !== null, true );
  // Two epics across three rows — the macro unit is the epic.
  assert.equal( document.getElementById( "epic-board-count" )!.textContent, "2" );
} );

test( "renderEpicBoard: terminal rows are filtered exactly as the task list filters them", () => {
  const ui = newUI();
  buildPanelDOM();
  const done = { id: "d1", title: "Shipped", status: "done", correlation_key: "epic:board-visibility" };
  ui.renderEpicBoard( { tasks: [ R_SEAL_A, done ], count: 2 } );
  // The done row's epic contributes no group.
  assert.equal( document.getElementById( "epic-board-count" )!.textContent, "1" );
} );

test( "renderEpicBoard: auth_required / query_unavailable / unreachable each say their own thing", () => {
  const ui = newUI();
  for ( const [ status, needle ] of [
    [ "auth_required", "Sign-in required" ],
    [ "query_unavailable", "deploy problem" ],
    [ "unreachable", "Store unreachable" ],
  ] as const ) {
    buildPanelDOM();
    ui.renderEpicBoard( { status, tasks: null } );
    assert.ok( document.getElementById( "epic-board-container" )!.innerHTML.includes( needle ),
               `${status} → "${needle}"` );
  }
} );

test( "renderEpicBoard: a missing container is a no-op, not a throw", () => {
  const ui = newUI();
  document.body.replaceChildren();
  assert.doesNotThrow( () => ui.renderEpicBoard( { tasks: [ R_SEAL_A ] } ) );
} );

test( "renderEpicBoard: stamps the updated span, and skips it when told to", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderEpicBoard( { tasks: [ R_SEAL_A ] } );
  assert.ok( document.getElementById( "epic-board-updated" )!.textContent!.startsWith( "updated " ) );
  buildPanelDOM();
  ui.renderEpicBoard( { tasks: [ R_SEAL_A ] }, false );
  assert.equal( document.getElementById( "epic-board-updated" )!.textContent, "" );
} );

// ───────────────────────────── accordion behaviour (DOM) ──────────────────────

function buildAccordionDOM( ui: EpicUI ): void {
  buildPanelDOM();
  ui.renderEpicBoard( { tasks: [ R_ON_RICK, R_SEAL_A, R_SEAL_B, R_NO_KEY ] } );
}

test( "clicking a group header toggles it in place and persists the choice", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const tbody = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"]' ) as HTMLElement;
  assert.ok( tbody.classList.contains( "collapsed" ), "epics start collapsed" );

  const header = tbody.querySelector( ".epic-group-header" ) as HTMLElement;
  wirePane( ui );
  clickThrough( ui, "_handleEpicAccordionToggle", header, "the seal-the-test-tier group header" );
  assert.equal( tbody.classList.contains( "collapsed" ), false );
  assert.equal( header.getAttribute( "aria-expanded" ), "true" );
  assert.equal( tbody.querySelector( ".epic-group-chevron" )!.textContent, "▾" );
  assert.equal( ui.loadEpicGroupState()[ "epic:seal-the-test-tier" ], true );
} );

test( "clicking a descendant of the header (the chevron) still toggles the group", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const tbody   = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"]' ) as HTMLElement;
  const chevron = tbody.querySelector( ".epic-group-chevron" ) as HTMLElement;
  wirePane( ui );
  clickThrough( ui, "_handleEpicAccordionToggle", chevron, "the group chevron" );
  assert.equal( tbody.classList.contains( "collapsed" ), false );
} );

test( "a click outside any header is a no-op", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const before = document.getElementById( "epic-board-container" )!.innerHTML;
  wirePane( ui );
  clickThrough( ui, "_handleEpicAccordionToggle", document.querySelector( ".epic-row" ),
    "an ordinary epic row" );
  // ⚠️ `null` and `{}` STAY BY-NAME. Neither is an element, so there is no click to
  // drive; what they pin is the handler's own tolerance of a junk target, and routing
  // them through a real event would delete the case rather than strengthen it.
  ui._handleEpicAccordionToggle( null );
  ui._handleEpicAccordionToggle( {} );
  assert.equal( document.getElementById( "epic-board-container" )!.innerHTML, before );
} );

test( "the waiting-on-Rick group renders OPEN by default; the drift group renders closed", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const onRick = document.querySelector( 'tbody.epic-group[data-epic="__on_rick__"]' ) as HTMLElement;
  const drift  = document.querySelector( 'tbody.epic-group[data-epic="__drift__"]' ) as HTMLElement;
  assert.equal( onRick.classList.contains( "collapsed" ), false );
  assert.equal( drift.classList.contains( "collapsed" ), true );
} );

test( "_epicKeysInDom: reports every rendered group key", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const keys = ui._epicKeysInDom().sort();
  assert.deepEqual( keys, [ "__drift__", "__on_rick__", "epic:board-visibility", "epic:seal-the-test-tier" ] );
} );

test( "collapseAllEpics / expandAllEpics drive every rendered group and persist", () => {
  const ui = newUI();
  buildAccordionDOM( ui );

  ui.expandAllEpics();
  document.querySelectorAll( "tbody.epic-group" ).forEach( el => {
    assert.equal( el.classList.contains( "collapsed" ), false );
  } );
  const expanded = ui.loadEpicGroupState();
  assert.equal( expanded[ "__drift__" ], true );

  ui.collapseAllEpics();
  document.querySelectorAll( "tbody.epic-group" ).forEach( el => {
    assert.equal( el.classList.contains( "collapsed" ), true );
  } );
  // Collapse-all records an EXPLICIT false even for the default-open group, so
  // the choice survives rather than snapping back open on the next render.
  assert.equal( ui.loadEpicGroupState()[ "__on_rick__" ], false );
} );

test( "the collapse choice survives a re-render — the reload requirement, end to end (DoD)", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const tbody  = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"]' ) as HTMLElement;
  wirePane( ui );
  clickThrough( ui, "_handleEpicAccordionToggle", tbody.querySelector( ".epic-group-header" ),
    "the seal-the-test-tier group header" );

  // A brand-new instance rendering into a brand-new DOM, reading only storage.
  const reborn = newUI();
  buildPanelDOM();
  reborn.renderEpicBoard( { tasks: [ R_ON_RICK, R_SEAL_A, R_SEAL_B, R_NO_KEY ] } );
  const after = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"]' ) as HTMLElement;
  assert.equal( after.classList.contains( "collapsed" ), false, "still open after a reload" );
} );

test( "_wireEpicBoardAccordion: wires at most once, and no-ops without a container", () => {
  const ui = newUI();
  buildPanelDOM();
  ui._wireEpicBoardAccordion();
  assert.equal( ui._epicBoardAccordionWired, true );
  assert.doesNotThrow( () => ui._wireEpicBoardAccordion() );

  const fresh = newUI();
  document.body.replaceChildren();
  fresh._wireEpicBoardAccordion();
  assert.equal( fresh._epicBoardAccordionWired, false, "no container → not wired" );
} );

test( "a real click event on a header toggles through the delegated listener", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const header = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"] .epic-group-header' ) as HTMLElement;
  header.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
  const tbody = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"]' ) as HTMLElement;
  assert.equal( tbody.classList.contains( "collapsed" ), false );
} );

test( "Enter and Space activate a focused header; other keys do not", () => {
  for ( const [ key, expectOpen ] of [ [ "Enter", true ], [ " ", true ], [ "Spacebar", true ], [ "a", false ] ] as const ) {
    const ui = newUI();
    localStorage.clear();
    buildAccordionDOM( ui );
    const header = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"] .epic-group-header' ) as HTMLElement;
    header.dispatchEvent( new window.KeyboardEvent( "keydown", { key, bubbles: true } ) );
    const tbody = document.querySelector( 'tbody.epic-group[data-epic="epic:seal-the-test-tier"]' ) as HTMLElement;
    assert.equal( !tbody.classList.contains( "collapsed" ), expectOpen, `key "${key}"` );
  }
} );

// ───────────────────────────── fetchEpicStories ───────────────────────────────

test( "fetchEpicStories: a 200 caches the stories map", async () => {
  const ui = newUI();
  const body = { stories: { "epic:a": { title: "A", story: "s" } }, count: 1 };
  ui.authedFetch = async () => fakeResponse( 200, true, body ) as never;
  const stories = await ui.fetchEpicStories();
  assert.deepEqual( stories, body.stories );
  assert.equal( ui._epicTitleLabel( "epic:a" ), "A" );
} );

test( "fetchEpicStories: ONE-SHOT — a second call never hits the network again", async () => {
  const ui = newUI();
  let calls = 0;
  ui.authedFetch = async () => { calls++; return fakeResponse( 200, true, { stories: {}, count: 0 } ) as never; };
  await ui.fetchEpicStories();
  await ui.fetchEpicStories();
  await ui.fetchEpicStories();
  assert.equal( calls, 1 );
} );

test( "fetchEpicStories: a FAILURE is memoized too — a down endpoint is not retried each render", async () => {
  const ui = newUI();
  let calls = 0;
  ui.authedFetch = async () => { calls++; throw new Error( "ECONNREFUSED" ); };
  assert.deepEqual( await ui.fetchEpicStories(), {} );
  assert.deepEqual( await ui.fetchEpicStories(), {} );
  assert.equal( calls, 1 );
} );

test( "fetchEpicStories: 401 / 500 / a bad body all degrade to {} rather than throwing", async () => {
  for ( const resp of [
    fakeResponse( 401, false, null ),
    fakeResponse( 500, false, null ),
    fakeResponse( 200, true, { stories: "not an object" } ),
    fakeResponse( 200, true, null ),
  ] ) {
    const ui = newUI();
    ui.authedFetch = async () => resp as never;
    assert.deepEqual( await ui.fetchEpicStories(), {} );
    // …and the board still names its epics, de-slugged.
    assert.equal( ui._epicTitleLabel( "epic:board-visibility" ), "board visibility" );
  }
} );

// ──────────── the DoD's headline claim: NO second poll against /api/tasks ─────

test( "the Epic Board declares NO poll handle and NO interval of its own", () => {
  // Read the source rather than the instance: the claim is about what the file
  // contains, and an instance can be hand-set by this harness.
  const source = readFileSync( NOTIFICATIONS_JS, "utf8" );
  assert.equal( /startEpicBoardPolling/.test( source ), false );
  assert.equal( /epicBoardPollIntervalHandle/.test( source ), false );
  assert.equal( /EPIC_BOARD_POLL_INTERVAL/.test( source ), false );
} );

test( "exactly ONE setInterval in the file targets a task-list refresh", () => {
  const source = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const hits = source.match( /setInterval\(\s*\n?\s*\(\s*\)\s*=>\s*this\.refreshTaskList\(\s*\)/g ) || [];
  assert.equal( hits.length, 1, "a second timer against /api/tasks would give the panes two clocks" );
} );

test( "the Epic Board never fetches /api/tasks itself — it renders off the shared composite", async () => {
  const ui = newUI();
  buildPanelDOM();
  const tl = document.createElement( "div" );
  tl.innerHTML = `<span id="task-list-count">0</span><span id="task-list-updated"></span>
                  <div id="task-list-container"></div>`;
  document.body.appendChild( tl );

  const urls: string[] = [];
  ui.authedFetch = async ( url: string ) => {
    urls.push( url );
    if ( url === "/api/epic-stories" ) return fakeResponse( 200, true, { stories: {}, count: 0 } ) as never;
    if ( url === "/api/tasks/flow-ratio" ) return fakeResponse( 200, true, { created: 1, closed: 2, ratio: 0.5, window_hours: 24 } ) as never;
    return fakeResponse( 200, true, { tasks: [ R_SEAL_A, R_NO_KEY ], count: 2 } ) as never;
  };

  await ui.refreshTaskList();

  // TIGHTENED 2026-09-01. This filtered on the prefix "/api/tasks", which also
  // matches every sibling resource under it — so it could not tell "the rows were
  // polled twice" (the defect it exists to catch) from "a second, different
  // resource was read once" (not a defect). It now names the row list exactly.
  const rowUrls = urls.filter( u => u.startsWith( "/api/tasks?" ) );
  assert.equal( rowUrls.length, 1, "ONE row fetch fed BOTH panes" );
  // The ratio is a SEPARATE resource — counted in SQL, so it cannot be derived
  // from the rows above — but it must still ride this one tick, exactly once.
  assert.equal( urls.filter( u => u === "/api/tasks/flow-ratio" ).length, 1,
                "the ratio rides the shared tick, and is not polled on a timer of its own" );
  // Both panes actually rendered off it.
  assert.equal( document.getElementById( "epic-board-container" )!.querySelector( "table.epic-board-table" ) !== null, true );
  assert.equal( document.getElementById( "task-list-container" )!.querySelector( "table.task-list-table" ) !== null, true );
} );

test( "a second refresh re-renders both panes without re-fetching the stories", async () => {
  const ui = newUI();
  buildPanelDOM();
  const tl = document.createElement( "div" );
  tl.innerHTML = `<span id="task-list-count">0</span><span id="task-list-updated"></span>
                  <div id="task-list-container"></div>`;
  document.body.appendChild( tl );

  const urls: string[] = [];
  ui.authedFetch = async ( url: string ) => {
    urls.push( url );
    if ( url === "/api/epic-stories" ) return fakeResponse( 200, true, { stories: {}, count: 0 } ) as never;
    if ( url === "/api/tasks/flow-ratio" ) return fakeResponse( 200, true, { created: 1, closed: 2, ratio: 0.5, window_hours: 24 } ) as never;
    return fakeResponse( 200, true, { tasks: [ R_SEAL_A ], count: 1 } ) as never;
  };

  await ui.refreshTaskList();
  await ui.refreshTaskList();

  assert.equal( urls.filter( u => u === "/api/epic-stories" ).length, 1 );
  // Row list: once per refresh. The stories are memoized; the rows are not.
  assert.equal( urls.filter( u => u.startsWith( "/api/tasks?" ) ).length, 2 );
  // The ratio is live state, so it re-fetches with the rows — NOT memoized like
  // the stories. Two refreshes, two reads: that is the intended behaviour, and
  // asserting it here is what stops someone "optimising" it into a stale number.
  assert.equal( urls.filter( u => u === "/api/tasks/flow-ratio" ).length, 2 );
} );

// ═════════ progressive disclosure on the EPIC BOARD — the renderer, and the CLICK PATH ═════════
//
// 🔴 THE EPIC BOARD'S ROW CONTROLS WERE DEAD, AND NOTHING SAW IT. `_renderEpicRow`
// emits the ellipsis and the nine controls behind it, but this pane's only click
// listener went straight to `_handleEpicAccordionToggle`, which returns unless the
// click landed in a group header. So on this board the ellipsis opened nothing and
// Drop / Park / Won't-fix / Demote / Approve did nothing — no error, no console line,
// the controls simply were not wired.
//
// ⚠️ THIS IS A MISSING ROUTE, NOT THE `_paneScope` LOOKUP DEFECT OF cd2ea523, and the
// two look identical from the outside. Told apart by measurement: with the handlers
// stubbed and ONE pane in the DOM — no second `data-task-id` for a lookup to pick
// wrongly — the handlers were never invoked at all, while the same probe against the
// task-list pane saw its click arrive. A wrong lookup happens INSIDE a handler that
// runs; nothing ran here.
//
// It stayed invisible because every disclosure test in the tree called the toggle
// method directly. Measured: deleting the disclosure route from the delegation reddened
// 0 of 253 tests. These reach the buttons the way an operator does.

function epicPaneWithRealRows( ui: EpicUI, ...tasks: Row[] ): HTMLElement {
  document.body.replaceChildren();
  const host = document.createElement( "div" );
  host.id = "epic-board-container";
  document.body.appendChild( host );
  ui._epicBoardAccordionWired = false;
  ui._wireEpicBoardAccordion();
  host.innerHTML = `<table id="epic-board-table"><tbody class="epic-group" data-epic="epic:seal">`
                 + tasks.map( t => ui._renderEpicRow( t ) ).join( "" )
                 + `</tbody></table>`;
  return host;
}

function clickIt( el: Element | null ): void {
  assert.ok( el, "the element to click was not rendered" );
  el!.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
}

test( "🔴 _renderEpicRow DECIDES collapsed: its own output carries hidden + aria-expanded=false", () => {
  const ui   = newUI();
  const host = document.createElement( "table" );
  host.innerHTML = `<tbody>${ui._renderEpicRow( R_SEAL_A )}</tbody>`;

  const controls = host.querySelector( ".task-controls-row" ) as HTMLElement;
  const toggle   = host.querySelector( ".task-disclose-button" ) as HTMLElement;
  assert.ok( controls, "no controls row emitted at all" );
  assert.equal( controls.hidden, true,
    "the epic renderer shipped its controls EXPANDED — the layout Rick rejected" );
  assert.ok( toggle, "no ellipsis emitted, so the controls can never be reached" );
  assert.equal( toggle.getAttribute( "aria-expanded" ), "false" );
  assert.equal( toggle.dataset.taskId, controls.dataset.controlsFor,
    "the toggle and its controls row carry different ids — the toggle opens nothing" );
} );

test( "🔴 renderEpicBoardTable: EVERY epic row ships collapsed", () => {
  const ui    = newUI();
  const model = ui.groupTasksByEpic( [ R_SEAL_A, R_SEAL_B, R_SEAL_C ] );
  const host  = document.createElement( "div" );
  host.innerHTML = ui.renderEpicBoardTable( model, {} );

  const controls = Array.from( host.querySelectorAll( ".task-controls-row" ) ) as HTMLElement[];
  assert.ok( controls.length >= 3, "the table emitted fewer controls rows than task rows" );
  assert.ok( controls.every( c => c.hidden ), "at least one epic row shipped expanded" );
} );

test( "🔴 THROUGH THE CLICK PATH: the epic board's ellipsis is WIRED", () => {
  // This is the defect itself. Before the shared dispatch, this click reached nothing.
  const ui   = newUI();
  const host = epicPaneWithRealRows( ui, R_SEAL_A );
  const controls = host.querySelector( ".task-controls-row" ) as HTMLElement;

  assert.equal( controls.hidden, true, "precondition: the row starts collapsed" );
  clickIt( host.querySelector( ".task-disclose-button" ) );
  assert.equal( controls.hidden, false,
    "the epic board's ellipsis is dead — the click reached no handler" );
} );

test( "🔴 THROUGH THE CLICK PATH: the epic board's row ACTION buttons are WIRED", () => {
  // The ellipsis alone is half a fix: disclosing controls that do nothing is worse
  // than not disclosing them, because now the operator watches them fail silently.
  const ui = newUI();
  let dropped = false;
  ui._handleTaskDropClick = (): void => { dropped = true; };
  const host = epicPaneWithRealRows( ui, R_SEAL_A );

  clickIt( host.querySelector( ".task-drop-button" ) );
  assert.equal( dropped, true, "Drop on the epic board reached no handler" );
} );

test( "🔴 a control click on the epic board does NOT also toggle its group", () => {
  const ui = newUI();
  let accordionFired = false;
  ui._handleEpicAccordionToggle = (): void => { accordionFired = true; };
  const host = epicPaneWithRealRows( ui, R_SEAL_A );

  clickIt( host.querySelector( ".task-disclose-button" ) );
  assert.equal( accordionFired, false,
    "one gesture opened the row's controls and collapsed the group they live in" );
} );

test( "the epic group header still toggles — the new route did not swallow it", () => {
  // The positive control for the test above. A dispatch that consumed everything would
  // make that assertion pass while breaking the accordion this pane is built around.
  const ui = newUI();
  let toggledWith: unknown = null;
  ui._handleEpicAccordionToggle = ( t: unknown ): void => { toggledWith = t; };
  const host = epicPaneWithRealRows( ui, R_SEAL_A );
  const header = document.createElement( "tr" );
  header.className = "epic-group-header";
  host.querySelector( "tbody" )!.appendChild( header );

  clickIt( header );
  assert.ok( toggledWith, "a header click no longer reaches the accordion" );
} );

// ═══════ the repaint destroys operator state HERE TOO — the same defect, third pane ═══════
//
// 🔴 All three panes repaint by replacing `container.innerHTML`. The task-list fix closed
// the instance Rick reported; this pane renders the SAME controls off the same shared
// composite and loses the same work. A fix that stops at the reported pane is one somebody
// re-opens the first time an operator types here.

test( "🔴 a repaint of the epic board keeps a typed reason, a shown refusal and a disclosed row", () => {
  const ui = newUI();
  buildPanelDOM();
  const model = ui.groupTasksByEpic( [ R_SEAL_A ] );
  const container = document.getElementById( "epic-board-container" )!;
  ui._epicBoardAccordionWired = false;
  ui._wireEpicBoardAccordion();
  container.innerHTML = ui.renderEpicBoardTable( model, ui.loadEpicGroupState() );

  const box = container.querySelector( ".task-wont-fix-reason" ) as HTMLInputElement;
  assert.ok( box, "no reason box rendered on the epic board — this test cannot speak" );
  box.value = "not doing this";
  clickThrough( ui, "_handleDisclosureToggle", container.querySelector( ".task-disclose-button" ),
    "the epic board's disclosure ellipsis" );
  ui._renderTaskRowError( R_SEAL_A.id as string, "A won't-fix reason is required.", container );
  assert.equal( ( container.querySelector( ".task-controls-row" ) as HTMLElement ).hidden, false );

  ui.renderEpicBoard( { status: "ok", tasks: [ R_SEAL_A ] }, false );      // the poll lands

  assert.equal( ( container.querySelector( ".task-wont-fix-reason" ) as HTMLInputElement ).value,
    "not doing this", "the repaint wiped a reason the operator had typed and not yet sent" );
  assert.equal( ( container.querySelector( ".task-row-error-stripe" ) as HTMLElement ).hidden, false,
    "the repaint wiped the refusal — the control now looks dead" );
  assert.equal( ( container.querySelector( ".task-controls-row" ) as HTMLElement ).hidden, false,
    "the repaint re-collapsed a row the operator had opened" );
} );

// ══════ collapsing an epic group must CLOSE the controls disclosed inside it ══════
//
// 🔴 Rick's own words name this pane: "if you close the epic-group-header it should
// definitely hide the displayed task-actions". Collapse is a CSS class on the tbody and
// the controls row carries its own `hidden`; the two were independent.

test( "🔴 collapsing an epic group closes any controls disclosed inside it", () => {
  const ui = newUI();
  buildPanelDOM();
  const host = document.getElementById( "epic-board-container" )!;
  ui._epicBoardAccordionWired = false;
  ui._wireEpicBoardAccordion();
  host.innerHTML = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ R_SEAL_A ] ), {} );

  // ⚠️ THIS GROUP RENDERS ALREADY COLLAPSED, so the operator's first header click EXPANDS
  // it. Writing the test as disclose-then-click-once measured an expansion and reported the
  // fix as broken — the test was wrong, not the code. Expand first, then follow the real
  // sequence: open a row, then collapse the group around it.
  const header = host.querySelector( ".epic-group-header" ) as HTMLElement;
  assert.ok( ( host.querySelector( "tbody.epic-group" ) as HTMLElement ).classList.contains( "collapsed" ),
    "precondition: this group renders collapsed" );
  header.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
  assert.ok( !( host.querySelector( "tbody.epic-group" ) as HTMLElement ).classList.contains( "collapsed" ),
    "precondition: the first header click expands it" );

  const toggle = host.querySelector( ".task-disclose-button" ) as HTMLElement;
  toggle.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );
  assert.equal( ( host.querySelector( ".task-controls-row" ) as HTMLElement ).hidden, false,
    "precondition: the row is disclosed" );

  header.dispatchEvent( new window.MouseEvent( "click", { bubbles: true } ) );   // collapse

  assert.equal( ( host.querySelector( ".task-controls-row" ) as HTMLElement ).hidden, true,
    "the epic group collapsed with its controls still on screen" );
  assert.equal( toggle.getAttribute( "aria-expanded" ), "false",
    "the ellipsis still claims the row is open inside a collapsed group" );
} );
