// Task-List panel (read-only consumer of GET /api/tasks) — frontend unit tests.
//
// Brief: src/rnd/v0.1.8/2026.06.16-task-list-ui-card-build-brief.md
// Ported from the Cheech-approved TS card (TaskListStore / TaskListRenderer /
// taskListModel / taskListTable) onto the in-service notifications.js card.
//
// Mirrors the established notifications.js harness (fleet_status_panel.test.ts):
// load the class via vm.runInThisContext (sliced before the DOM-ready init),
// Object.create the prototype to skip the constructor, hand-set the few fields
// the methods read, then drive the methods directly under happy-dom.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/task_list_panel.test.ts
// Coverage (c8):
//   npx c8 --include='src/lupin_app/static/js/notifications.js' --reporter=text \
//       npx tsx --test src/tests/unit/notifications_js/task_list_panel.test.ts

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

// The REAL shared constant, not a copy. notifications.js reads the query off
// `window` (it is a classic script and cannot import), so the harness must stand
// in for the <script type="module"> the page loads. Importing the actual module
// rather than pasting the string keeps this test honest: if the constant changes,
// the assertions below travel with it instead of pinning a stale literal.
import { TASK_LIST_QUERY } from "../../../lupin_app/static/js/shared/task-list-query.js";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
  // Stand in for the page's module script. Without this every fetchTaskList call
  // short-circuits to the `query_unavailable` deploy-defect branch — which is
  // correct production behavior and exactly what broke 3 unrelated tests when the
  // global was first introduced without a harness counterpart.
  window.LUPIN_TASK_LIST_QUERY = TASK_LIST_QUERY;
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

type TaskUI = Record<string, unknown> & {
  fetchTaskList: () => Promise<Record<string, unknown>>;
  isTaskOpenStatus: ( status: unknown ) => boolean;
  _taskStatusRank: ( status: unknown ) => number;
  _taskPriorityRank: ( priority: unknown ) => number;
  _taskOwnerLabel: ( task: unknown ) => string;
  _taskTitleLabel: ( task: unknown ) => string;
  _taskCellOrDash: ( value: unknown ) => string;
  _taskStatusClass: ( status: unknown ) => string;
  _taskPriorityClass: ( priority: unknown ) => string;
  _formatTaskChaseTime: ( iso: unknown, ianaZone: unknown ) => string;
  groupTasksByOwner: ( tasks: unknown ) => { totalCount: number; groups: TaskGroupModel[] };
  _renderTaskRow: ( task: Record<string, unknown>, ianaZone?: unknown ) => string;
  renderTaskListTable: ( model: { groups: TaskGroupModel[] }, ianaZone?: unknown, collapsedOwners?: Set<string> ) => string;
  // Row redesign (2026.06.29): id column + title truncation + 📄 body overlay
  _taskIdLabel: ( task: unknown ) => string;
  _truncateTaskTitle: ( label: unknown ) => string;
  _taskBodyIsEmpty: ( task: unknown ) => boolean;
  _handleTaskListClick: ( target: unknown ) => void;
  openTaskBodyOverlay: ( bodyText: string, idLabel: string ) => void;
  _dismissTaskBodyOverlay: () => void;
  TASK_TITLE_TRUNCATE_LEN: number;
  _taskBodyOverlayKeyListener: ( ( e: KeyboardEvent ) => void ) | null;
  // Per-persona accordion (2026-06-17)
  _taskGroupOwnerKey: ( group: TaskGroupModel ) => string | null;
  _taskGroupIdSlug: ( ownerKey: unknown ) => string;
  _escapeTaskAttr: ( value: unknown ) => string;
  loadCollapsedTaskOwners: () => Set<string>;
  saveCollapsedTaskOwners: ( collapsedSet: Iterable<string> ) => void;
  toggleTaskOwnerCollapsed: ( ownerKey: string ) => boolean;
  _applyTaskGroupCollapseState: ( tbody: HTMLElement, isCollapsed: boolean ) => void;
  _handleTaskAccordionToggle: ( target: unknown ) => void;
  _wireTaskListAccordion: () => void;
  _taskListOwnerKeysInDom: () => string[];
  collapseAllTaskOwners: () => void;
  expandAllTaskOwners: () => void;
  error: ( ...args: unknown[] ) => void;
  TASK_LIST_COLLAPSED_KEY: string;
  TASK_LIST_UNASSIGNED_KEY: string;
  _taskListAccordionWired: boolean;
  renderTaskList: ( composite: unknown, stampUpdated?: boolean ) => void;
  // Live/parked header split (2026-08-28)
  _taskIsParked: ( task: unknown, now?: number ) => boolean;
  _formatTaskListCount: ( live: number, parked: number ) => string;
  // Closed-vs-new ratio in the header (2026-09-01)
  _formatFlowRatio: ( payload: unknown ) => string;
  fetchFlowRatio: () => Promise<unknown>;
  _renderFlowRatio: ( payload: unknown ) => void;
  log: ( ...args: unknown[] ) => void;
  _taskListCountText: ( openTasks: unknown, now?: number ) => string;
  _renderTaskListUnreachable: ( container: HTMLElement, countEl: HTMLElement | null ) => void;
  _stampTaskListUpdated: () => void;
  refreshTaskList: () => Promise<void>;
  startTaskListPolling: () => void;
  stopTaskListPolling: () => void;
  authedFetch: ( url: string ) => Promise<unknown>;
  _taskListFetchInFlight: boolean;
  _taskListLastGoodTasks: Record<string, unknown>[] | null;
  taskListPollIntervalHandle: ReturnType<typeof setInterval> | null;
  TASK_LIST_POLL_INTERVAL_MS: number;
};

type TaskGroupModel = {
  ownerPersona: string | null;
  isUnassigned: boolean;
  tasks: Record<string, unknown>[];
};

function newUI(): TaskUI {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui = Object.create( Ctor.prototype ) as TaskUI;
  ui.debug                      = false;
  ui.log                        = (): void => {};
  ui.error                      = (): void => {};
  ui._taskListFetchInFlight     = false;
  ui._taskListLastGoodTasks     = null;
  ui.taskListPollIntervalHandle = null;
  ui.TASK_LIST_POLL_INTERVAL_MS = 60000;
  ui.TASK_LIST_COLLAPSED_KEY    = "lupin.taskList.collapsedOwners";
  ui.TASK_LIST_UNASSIGNED_KEY   = "__unassigned__";
  ui._taskListAccordionWired    = false;
  ui.TASK_TITLE_TRUNCATE_LEN    = 60;
  return ui;
}

function buildPanelDOM(): void {
  document.body.replaceChildren();
  const section = document.createElement( "div" );
  section.id = "section-task-list";
  section.innerHTML = `
    <h3>Task List: <span id="task-list-count">0</span>
        <span id="task-list-updated"></span></h3>
    <div id="task-list-container"></div>`;
  document.body.appendChild( section );
}

function fakeResponse( status: number, ok: boolean, jsonBody: unknown ): unknown {
  return { status, ok, json: async () => jsonBody };
}

// Representative task rows (the /api/tasks _serialize_item shape).
const T_BLOCKED = { id: "t1", item_class: "task", title: "Wire the seam", status: "blocked",
                    blocked_by: "decision:abc", next_chase_ts: "2026-06-17T14:30:00+00:00",
                    owner_persona: "Rio", accountable_manager: "Tiberius", priority: "P1", project: "lupin" };
const T_ACTIVE  = { id: "t2", item_class: "bug", title: "Fix the poke", status: "in_progress",
                    blocked_by: "none", next_chase_ts: null,
                    owner_persona: "Rio", accountable_manager: "Tiberius", priority: "P2", project: "lupin" };
const T_QUEUED  = { id: "t3", item_class: "review_request", title: "Aardvark first", status: "queued",
                    blocked_by: null, next_chase_ts: null,
                    owner_persona: "Krishna", accountable_manager: "Tiberius", priority: "P0", project: "lupin" };
const T_DONE    = { id: "t4", item_class: "task", title: "Shipped", status: "done",
                    owner_persona: "Rio", accountable_manager: "Tiberius", priority: "P3", project: "lupin" };
const T_ORPHAN  = { id: "t5", item_class: "decision", title: "Who owns this?", status: "queued",
                    owner_persona: null, accountable_manager: null, priority: null, project: null };

beforeEach( () => { document.body.replaceChildren(); localStorage.clear(); } );

// A small grouped DOM with three owner tbodies (Krishna · 1, Rio · 2,
// (Unassigned) · 1) for the accordion DOM-manipulation tests.
function buildAccordionDOM( ui: TaskUI ): void {
  buildPanelDOM();
  const model = ui.groupTasksByOwner( [ T_BLOCKED, T_ACTIVE, T_QUEUED, T_ORPHAN ] );
  document.getElementById( "task-list-container" )!.innerHTML =
    ui.renderTaskListTable( model, undefined, ui.loadCollapsedTaskOwners() );
}

// ─────────────────────────── isTaskOpenStatus (pure) ───────────────────────────

test( "isTaskOpenStatus: terminal done/dropped/wont_fix → false; everything else (incl. missing) → true", () => {
  const ui = newUI();
  assert.equal( ui.isTaskOpenStatus( "done" ), false );
  assert.equal( ui.isTaskOpenStatus( "dropped" ), false );
  // wont_fix joined TERMINAL_STATUSES 2026-09-02. Before that this function knew
  // only the first two, so every won't-fixed row counted as work still owed.
  assert.equal( ui.isTaskOpenStatus( "wont_fix" ), false );
  // not_approved is deliberately NOT terminal — a held row is waiting, not finished.
  // It is hidden from the board by a server-side denylist, not by this predicate.
  assert.equal( ui.isTaskOpenStatus( "not_approved" ), true );
  assert.equal( ui.isTaskOpenStatus( "blocked" ), true );
  assert.equal( ui.isTaskOpenStatus( "queued" ), true );
  assert.equal( ui.isTaskOpenStatus( null ), true );
  assert.equal( ui.isTaskOpenStatus( undefined ), true );
  assert.equal( ui.isTaskOpenStatus( "" ), true );
} );

// ─────────────────────────── _taskStatusRank / _taskPriorityRank (pure) ───────────────────────────

// Renumbered in TENS 2026-09-02 to make room for `parked` and `not_approved`, which
// belong between `queued` and the unknown slot and had nowhere to go on the old
// 0..7 scale. THE ORDER IS THE CONTRACT; the absolute values are arbitrary, so this
// asserts the ORDERING rather than re-pinning a fresh set of magic numbers — a test
// that pins literals has to be rewritten by whoever adds the next status, and that
// edit is indistinguishable from breaking it.
test( "_taskStatusRank: orders most-urgent first, unknown between open and terminal", () => {
  const ui = newUI();
  const order = [ "blocked", "in_progress", "claimed", "review", "queued",
                  "parked", "not_approved", "bananas", "done", "dropped", "wont_fix" ];
  const ranks = order.map( s => ui._taskStatusRank( s ) );

  for ( let i = 1; i < ranks.length; i++ ) {
    assert.ok( ranks[ i - 1 ] < ranks[ i ],
      `${order[ i - 1 ]} (${ranks[ i - 1 ]}) must sort before ${order[ i ]} (${ranks[ i ]})` );
  }
  // A missing status sorts exactly where an unrecognized one does.
  assert.equal( ui._taskStatusRank( null ), ui._taskStatusRank( "bananas" ) );
  // ...and that slot sits below every open status and above every terminal one,
  // which is the property the "unknown" rank exists for.
  assert.ok( ui._taskStatusRank( "bananas" ) > ui._taskStatusRank( "not_approved" ) );
  assert.ok( ui._taskStatusRank( "bananas" ) < ui._taskStatusRank( "done" ) );
} );

test( "_taskPriorityRank: P<n> → n, missing/non-match → 99", () => {
  const ui = newUI();
  assert.equal( ui._taskPriorityRank( "P0" ), 0 );
  assert.equal( ui._taskPriorityRank( "P3" ), 3 );
  assert.equal( ui._taskPriorityRank( null ), 99 );
  assert.equal( ui._taskPriorityRank( "urgent" ), 99 );
} );

// ─────────────────────────── label / cell formatters (pure) ───────────────────────────

test( "_taskOwnerLabel: owner_persona preferred, else Unassigned", () => {
  const ui = newUI();
  assert.equal( ui._taskOwnerLabel( { owner_persona: "Rio" } ), "Rio" );
  assert.equal( ui._taskOwnerLabel( { owner_persona: null } ), "Unassigned" );
  assert.equal( ui._taskOwnerLabel( {} ), "Unassigned" );
  assert.equal( ui._taskOwnerLabel( null ), "Unassigned" );
} );

test( "_taskTitleLabel: title preferred, else (untitled)", () => {
  const ui = newUI();
  assert.equal( ui._taskTitleLabel( { title: "Do X" } ), "Do X" );
  assert.equal( ui._taskTitleLabel( { title: "" } ), "(untitled)" );
  assert.equal( ui._taskTitleLabel( {} ), "(untitled)" );
  assert.equal( ui._taskTitleLabel( null ), "(untitled)" );
} );

test( "_taskCellOrDash: falsy/'none' → em-dash, else value", () => {
  const ui = newUI();
  assert.equal( ui._taskCellOrDash( "decision:abc" ), "decision:abc" );
  assert.equal( ui._taskCellOrDash( "none" ), "—" );
  assert.equal( ui._taskCellOrDash( null ), "—" );
  assert.equal( ui._taskCellOrDash( "" ), "—" );
} );

test( "_taskStatusClass: each band, non-string and unrecognized → unknown", () => {
  const ui = newUI();
  assert.equal( ui._taskStatusClass( "blocked" ),     "task-status-blocked" );
  assert.equal( ui._taskStatusClass( "in_progress" ), "task-status-active" );
  assert.equal( ui._taskStatusClass( "claimed" ),     "task-status-active" );
  assert.equal( ui._taskStatusClass( "review" ),      "task-status-review" );
  assert.equal( ui._taskStatusClass( "queued" ),      "task-status-queued" );
  assert.equal( ui._taskStatusClass( "done" ),        "task-status-done" );
  assert.equal( ui._taskStatusClass( "dropped" ),     "task-status-dropped" );
  assert.equal( ui._taskStatusClass( "  BLOCKED " ),  "task-status-blocked" );   // trim + lowercase
  assert.equal( ui._taskStatusClass( "bananas" ),     "task-status-unknown" );
  assert.equal( ui._taskStatusClass( null ),          "task-status-unknown" );   // non-string
  assert.equal( ui._taskStatusClass( 42 as unknown ), "task-status-unknown" );
} );

test( "_taskPriorityClass: high/mid/low bands; non-string and non-`P<n>` → ''", () => {
  const ui = newUI();
  assert.equal( ui._taskPriorityClass( "P0" ), "task-prio-high" );
  assert.equal( ui._taskPriorityClass( "P1" ), "task-prio-high" );
  assert.equal( ui._taskPriorityClass( "P2" ), "task-prio-mid" );
  assert.equal( ui._taskPriorityClass( "P3" ), "task-prio-low" );
  assert.equal( ui._taskPriorityClass( "P9" ), "task-prio-low" );
  assert.equal( ui._taskPriorityClass( " P0 " ), "task-prio-high" );   // trimmed
  assert.equal( ui._taskPriorityClass( "urgent" ), "" );
  assert.equal( ui._taskPriorityClass( null ), "" );                   // non-string
} );

// ─────────────────────────── _formatTaskChaseTime (Cheech tz nit) ───────────────────────────

test( "_formatTaskChaseTime: null/absent → em-dash", () => {
  const ui = newUI();
  assert.equal( ui._formatTaskChaseTime( null, "America/New_York" ), "—" );
  assert.equal( ui._formatTaskChaseTime( undefined, null ), "—" );
} );

test( "_formatTaskChaseTime: offset-bearing ISO formats in the given IANA zone (MM-DD HH:MM)", () => {
  const ui = newUI();
  // 14:30Z → 10:30 EDT (UTC-4 in June)
  const out = ui._formatTaskChaseTime( "2026-06-17T14:30:00+00:00", "America/New_York" );
  assert.match( out, /06\D17/ );   // month/day, separator is locale-dependent
  assert.match( out, /10:30/ );
} );

test( "_formatTaskChaseTime: NAIVE (tz-less) ISO is interpreted as UTC, not browser-local", () => {
  const ui = newUI();
  // No Z, no offset → guard appends 'Z' → 14:30 UTC → 10:30 EDT
  const naive = ui._formatTaskChaseTime( "2026-06-17T14:30:00", "America/New_York" );
  const zulu  = ui._formatTaskChaseTime( "2026-06-17T14:30:00Z", "America/New_York" );
  assert.equal( naive, zulu, "naive string treated identically to an explicit Z" );
  assert.match( naive, /10:30/ );
} );

test( "_formatTaskChaseTime: a +HHMM (no colon) offset is recognized as tz-qualified (not re-stamped)", () => {
  const ui = newUI();
  const out = ui._formatTaskChaseTime( "2026-06-17T14:30:00+0000", "America/New_York" );
  assert.match( out, /10:30/ );
} );

test( "_formatTaskChaseTime: unparseable string → em-dash", () => {
  const ui = newUI();
  assert.equal( ui._formatTaskChaseTime( "not-a-date", "America/New_York" ), "—" );
} );

test( "_formatTaskChaseTime: invalid IANA zone degrades to browser-local (no throw)", () => {
  const ui = newUI();
  const out = ui._formatTaskChaseTime( "2026-06-17T14:30:00Z", "Not/AZone" );
  assert.match( out, /\d{2}\D\d{2}/ );   // month/day present
  assert.match( out, /\d{2}:\d{2}/ );
} );

test( "_formatTaskChaseTime: absent zone uses browser-local", () => {
  const ui = newUI();
  const out = ui._formatTaskChaseTime( "2026-06-17T14:30:00Z", null );
  assert.match( out, /\d{2}:\d{2}/ );
} );

// ─────────────────────────── groupTasksByOwner (pure) ───────────────────────────

test( "groupTasksByOwner: owner groups persona-sorted, Unassigned bucket LAST", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_ACTIVE, T_QUEUED, T_ORPHAN ] );  // Rio, Krishna, (none)
  assert.equal( model.totalCount, 3 );
  assert.deepEqual( model.groups.map( g => g.ownerPersona ), [ "Krishna", "Rio", null ] );
  const last = model.groups[ model.groups.length - 1 ];
  assert.equal( last.isUnassigned, true );
  assert.equal( last.tasks.length, 1 );
} );

test( "groupTasksByOwner: within a group, sorts blocked-first, then priority, then title", () => {
  const ui = newUI();
  // Same owner Rio: blocked(P1) vs in_progress(P2) → blocked first by status rank
  const model = ui.groupTasksByOwner( [ T_ACTIVE, T_BLOCKED ] );
  const rio = model.groups.find( g => g.ownerPersona === "Rio" )!;
  assert.deepEqual( rio.tasks.map( t => t.status ), [ "blocked", "in_progress" ] );
} );

test( "groupTasksByOwner: priority then title break a status tie", () => {
  const ui = newUI();
  const a = { owner_persona: "Rio", status: "queued", priority: "P2", title: "Zebra" };
  const b = { owner_persona: "Rio", status: "queued", priority: "P0", title: "Yak" };
  const c = { owner_persona: "Rio", status: "queued", priority: "P2", title: "Apple" };
  const model = ui.groupTasksByOwner( [ a, b, c ] );
  const rio = model.groups[ 0 ];
  // P0 first; then the two P2s alpha by title (Apple < Zebra)
  assert.deepEqual( rio.tasks.map( t => t.title ), [ "Yak", "Apple", "Zebra" ] );
} );

test( "groupTasksByOwner: existing-bucket push (two tasks, same owner) → one group", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED, T_ACTIVE ] );   // both Rio
  assert.equal( model.groups.length, 1 );
  assert.equal( model.groups[ 0 ].tasks.length, 2 );
} );

test( "groupTasksByOwner: non-array input → empty; falsy rows collapse to {} (Unassigned, no throw)", () => {
  const ui = newUI();
  assert.deepEqual( ui.groupTasksByOwner( null ), { totalCount: 0, groups: [] } );
  const model = ui.groupTasksByOwner( [ null, undefined ] );
  assert.equal( model.totalCount, 2 );
  assert.equal( model.groups.length, 1 );
  assert.equal( model.groups[ 0 ].isUnassigned, true );
} );

test( "groupTasksByOwner: all-owned input → no Unassigned bucket", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED, T_QUEUED ] );   // Rio, Krishna
  assert.ok( !model.groups.some( g => g.isUnassigned ), "no Unassigned bucket when every row is owned" );
} );

// ─────────────────────────── _renderTaskRow / renderTaskListTable (pure) ───────────────────────────

test( "_renderTaskRow: status class on <tr>, status dot, all ten cells, blocked_by shown", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( T_BLOCKED, "America/New_York" );
  assert.match( html, /<tr class="task-row task-status-blocked">/ );
  assert.match( html, /<td class="task-col-id">t1<\/td>/ );    // NEW leftmost ID col (first 8 of id)
  assert.match( html, /<td class="task-col-status"><span class="task-status-dot"><\/span>blocked<\/td>/ );
  assert.match( html, /Wire the seam/ );
  assert.match( html, /decision:abc/ );                 // blocked_by rendered
  assert.match( html, /10:30/ );                        // next_chase in EDT
  assert.match( html, /task-col-priority task-prio-high/ );   // P1 → high tint
  assert.match( html, />lupin</ );                      // project
  assert.match( html, /task-class-badge task-class-task/ );
  assert.match( html, /<td class="task-col-detail">/ );       // NEW rightmost Detail col
} );

test( "_renderTaskRow: 'none' blocked_by → em-dash; null next_chase → em-dash; no prio tint for missing", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( T_ORPHAN, undefined );
  assert.match( html, /<td class="task-col-blocked">—<\/td>/ );
  assert.match( html, /<td class="task-col-chase">—<\/td>/ );
  assert.match( html, /<td class="task-col-priority">—<\/td>/ );   // null priority → no tint class
  assert.match( html, /task-status-queued/ );
} );

test( "_renderTaskRow: defensively fills a bare row (no status/title/class)", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( { id: "x" }, undefined );
  assert.match( html, /task-status-unknown/ );
  assert.match( html, />unknown</ );                    // status word default
  assert.match( html, /\(untitled\)/ );
  assert.match( html, /task-class-task/ );              // item_class default
} );

test( "_renderTaskRow: escapeHtml neutralizes a malicious title (XSS-safe)", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( { title: "<img src=x onerror=alert(1)>", status: "queued" }, undefined );
  assert.ok( !html.includes( "<img src=x" ), "raw markup must not survive" );
  assert.match( html, /&lt;img/ );
} );

test( "_renderTaskRow: item_class is slug-sanitized in the class attr (no attribute injection)", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( { title: "t", status: "queued", item_class: 'task" onmouseover="x' }, undefined );
  assert.ok( !html.includes( 'onmouseover="x' ), "injected attribute must not survive the class slug" );
  assert.match( html, /task-class-taskonmouseoverx/ );   // stripped to alnum/_/-
} );

test( "renderTaskListTable: owner group header (owner · count) + Unassigned label, eleven columns, colspan 11", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED, T_QUEUED, T_ORPHAN ] );
  const html = ui.renderTaskListTable( model, undefined );
  assert.match( html, /<table class="task-list-table">/ );
  assert.match( html, /Rio · 1/ );
  assert.match( html, /Krishna · 1/ );
  assert.match( html, /\(Unassigned\)/ );
  assert.match( html, /task-group-unassigned/ );
  for ( const col of [ "ID", "Title", "Class", "Status", "Blocked by", "Next chase", "Accountable", "Filed by", "Priority", "Project", "Detail" ] ) {
    assert.ok( html.includes( col ), `header "${col}" present` );
  }
  // The group-header bar must span EVERY column. A stale colspan does not throw
  // and does not look broken in a screenshot — the bar simply stops short of the
  // last column, which is why this is asserted rather than eyeballed.
  assert.match( html, /colspan="11"/ );                 // 8 → 10 (row redesign) → 11 (Filed by)
  assert.ok( !/colspan="10"/.test( html ), "a stale colspan leaves the group bar short of the last column" );
  assert.ok( html.indexOf( "Krishna" ) < html.indexOf( "(Unassigned)" ), "Unassigned renders last" );
} );

// ─────────────── Row redesign 2026.06.29: id col + title truncation + 📄 body overlay ───────────────

test( "_taskIdLabel: first 8 chars of id; long UUID truncated; absent/null → em-dash", () => {
  const ui = newUI();
  assert.equal( ui._taskIdLabel( { id: "3b85863e-ccb9-4948-948c-627e3922850e" } ), "3b85863e" );
  assert.equal( ui._taskIdLabel( { id: "abc" } ), "abc" );      // shorter than 8 → verbatim
  assert.equal( ui._taskIdLabel( { id: "" } ), "—" );
  assert.equal( ui._taskIdLabel( { } ), "—" );                  // id absent
  assert.equal( ui._taskIdLabel( { id: null } ), "—" );
  assert.equal( ui._taskIdLabel( null ), "—" );                 // no task object
} );

test( "_truncateTaskTitle: under/at cap verbatim; over cap → slice(60)+ellipsis", () => {
  const ui = newUI();
  assert.equal( ui._truncateTaskTitle( "short title" ), "short title" );
  const at = "x".repeat( 60 );
  assert.equal( ui._truncateTaskTitle( at ), at );              // exactly at cap → no ellipsis
  const over = "y".repeat( 90 );
  assert.equal( ui._truncateTaskTitle( over ), "y".repeat( 60 ) + "…" );
} );

test( "_taskBodyIsEmpty: null/undefined/blank → true; non-blank → false", () => {
  const ui = newUI();
  assert.equal( ui._taskBodyIsEmpty( { body: null } ), true );
  assert.equal( ui._taskBodyIsEmpty( { } ), true );             // body absent
  assert.equal( ui._taskBodyIsEmpty( { body: "" } ), true );
  assert.equal( ui._taskBodyIsEmpty( { body: "   \n\t " } ), true );
  assert.equal( ui._taskBodyIsEmpty( null ), true );            // no task object
  assert.equal( ui._taskBodyIsEmpty( { body: "detail here" } ), false );
} );

test( "_renderTaskRow: long title truncated in cell, FULL title in title= tooltip", () => {
  const ui = newUI();
  const longTitle = "Z".repeat( 90 );
  const html = ui._renderTaskRow( { id: "abcdef12", title: longTitle, status: "queued" }, undefined );
  assert.match( html, /<td class="task-col-id">abcdef12<\/td>/ );
  assert.ok( html.includes( "Z".repeat( 60 ) + "…" ), "cell text truncated + ellipsis" );
  assert.ok( html.includes( `title="${longTitle}"` ), "full title rides the tooltip attr" );
} );

test( "_renderTaskRow: body present → live clickable 📄 carrying data-task-body/-id", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( { id: "feedface", title: "t", status: "queued", body: "the detail" }, undefined );
  assert.match( html, /class="task-detail-emoji" role="button" tabindex="0"/ );
  assert.match( html, /data-task-id="feedface"/ );
  assert.match( html, /data-task-body="the detail"/ );
  assert.ok( !html.includes( "task-detail-empty" ), "a live emoji is not dimmed" );
} );

test( "_renderTaskRow: empty body → DIMMED 📄 in place (disabled, no data-body)", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( { id: "x", title: "t", status: "queued", body: "" }, undefined );
  assert.match( html, /class="task-detail-emoji task-detail-empty" aria-disabled="true"/ );
  assert.ok( !html.includes( "data-task-body=" ), "dimmed emoji carries no body payload" );
} );

test( "_renderTaskRow: a body containing quotes/markup is attribute-escaped (no injection)", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( { id: "x", title: "t", status: "queued", body: '"><img onerror=alert(1)>' }, undefined );
  assert.ok( !html.includes( '"><img' ), "raw quote+markup must not break out of the attribute" );
  assert.match( html, /&quot;&gt;&lt;img/ );
} );

test( "_renderTaskRow: array blocked_by — typed ref, kind-less ref, and raw entry all rendered", () => {
  const ui = newUI();
  const html = ui._renderTaskRow(
    { id: "x", title: "t", status: "blocked",
      blocked_by: [ { kind: "persona", id: "rio" }, { id: "bare" }, "raw-str" ] }, undefined );
  assert.match( html, /persona:rio/ );      // typed ref → kind:id
  assert.match( html, /bare/ );             // object w/o kind → id only
  assert.match( html, /raw-str/ );          // non-object entry → String(b)
} );

test( "_handleTaskListClick: a target lacking .closest is safely ignored (defensive guard)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui._handleTaskListClick( {} );            // no .closest → emoji null → accordion toggle no-ops
  assert.ok( document.getElementById( "task-body-overlay" ) === null );
} );

test( "_handleTaskListClick: a LIVE 📄 with NO dataset opens overlay with empty body/id (|| '' fallback)", () => {
  const ui = newUI();
  buildPanelDOM();
  const emoji = document.createElement( "span" );
  emoji.className = "task-detail-emoji";    // live (not dimmed) but carries no data-task-* attrs
  document.getElementById( "task-list-container" )!.appendChild( emoji );
  ui._handleTaskListClick( emoji );
  const overlay = document.getElementById( "task-body-overlay" )!;
  assert.ok( overlay, "overlay opened even with no dataset" );
  assert.equal( overlay.querySelector( ".task-body-overlay-body" )!.textContent, "" );
  assert.match( overlay.querySelector( ".task-body-overlay-header" )!.textContent!, /Task detail/ );
  ui._dismissTaskBodyOverlay();
} );

test( "_handleTaskListClick: clicking a LIVE 📄 opens the body overlay", () => {
  const ui = newUI();
  buildPanelDOM();
  const container = document.getElementById( "task-list-container" )!;
  container.innerHTML = ui._renderTaskRow( { id: "abcd1234", title: "t", status: "queued", body: "overlay body text" }, undefined );
  const emoji = container.querySelector( ".task-detail-emoji" )!;
  ui._handleTaskListClick( emoji );
  const overlay = document.getElementById( "task-body-overlay" );
  assert.ok( overlay, "overlay opened" );
  assert.match( overlay!.querySelector( ".task-body-overlay-body" )!.textContent!, /overlay body text/ );
  assert.match( overlay!.querySelector( ".task-body-overlay-header" )!.textContent!, /abcd1234/ );
  ui._dismissTaskBodyOverlay();
} );

test( "_handleTaskListClick: a DIMMED 📄 is inert — no overlay, no accordion toggle", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const container = document.getElementById( "task-list-container" )!;
  // Inject a dimmed emoji and click it: must neither open an overlay nor toggle a group.
  const dimmed = document.createElement( "span" );
  dimmed.className = "task-detail-emoji task-detail-empty";
  container.appendChild( dimmed );
  const before = container.innerHTML;
  ui._handleTaskListClick( dimmed );
  assert.ok( document.getElementById( "task-body-overlay" ) === null, "no overlay for dimmed emoji" );
  assert.equal( container.innerHTML, before, "no accordion toggle for dimmed emoji" );
} );

test( "_handleTaskListClick: a non-emoji target delegates to the accordion toggle", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const header = document.querySelector( ".task-group-header" ) as HTMLElement;
  const tbody  = header.closest( "tbody.task-group" ) as HTMLElement;
  assert.ok( !tbody.classList.contains( "collapsed" ) );
  ui._handleTaskListClick( header );
  assert.ok( tbody.classList.contains( "collapsed" ), "non-emoji click toggled the group (delegation intact)" );
} );

test( "openTaskBodyOverlay: backdrop click dismisses; inner panel click does NOT", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.openTaskBodyOverlay( "body", "id8" );
  const overlay = document.getElementById( "task-body-overlay" )!;
  const panel   = overlay.querySelector( ".task-body-overlay-content" ) as HTMLElement;
  panel.dispatchEvent( new Event( "click", { bubbles: true } ) );   // inner click bubbles to overlay but is stopped
  assert.ok( document.getElementById( "task-body-overlay" ), "inner-panel click keeps overlay open" );
  overlay.dispatchEvent( new Event( "click", { bubbles: true } ) ); // backdrop click
  assert.ok( document.getElementById( "task-body-overlay" ) === null, "backdrop click dismissed" );
} );

test( "openTaskBodyOverlay: Escape dismisses + detaches its keydown listener", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.openTaskBodyOverlay( "body", "id8" );
  assert.ok( ui._taskBodyOverlayKeyListener, "Esc listener stored while open" );
  document.dispatchEvent( new KeyboardEvent( "keydown", { key: "Escape" } ) );
  assert.ok( document.getElementById( "task-body-overlay" ) === null, "Esc dismissed" );
  assert.equal( ui._taskBodyOverlayKeyListener, null, "Esc listener detached on dismiss" );
} );

test( "openTaskBodyOverlay: a non-Escape key does NOT dismiss", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.openTaskBodyOverlay( "body", "id8" );
  document.dispatchEvent( new KeyboardEvent( "keydown", { key: "a" } ) );
  assert.ok( document.getElementById( "task-body-overlay" ), "non-Esc key keeps overlay open" );
  ui._dismissTaskBodyOverlay();
} );

test( "openTaskBodyOverlay: opening twice replaces the prior overlay (single instance)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.openTaskBodyOverlay( "first", "id1" );
  ui.openTaskBodyOverlay( "second", "id2" );
  assert.equal( document.querySelectorAll( "#task-body-overlay" ).length, 1, "only one overlay at a time" );
  assert.match( document.querySelector( ".task-body-overlay-body" )!.textContent!, /second/ );
  ui._dismissTaskBodyOverlay();
} );

test( "openTaskBodyOverlay: empty idLabel → generic 'Task detail' header", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.openTaskBodyOverlay( "body", "" );
  assert.match( document.querySelector( ".task-body-overlay-header" )!.textContent!, /Task detail/ );
  ui._dismissTaskBodyOverlay();
} );

test( "openTaskBodyOverlay: no document.body → no-op (degrade-safe, no throw)", () => {
  const ui = newUI();
  buildPanelDOM();
  const body = document.body;
  body.remove();                                        // document.body becomes null
  assert.ok( document.body === null );
  ui.openTaskBodyOverlay( "body", "id" );               // must not throw, must not create
  document.documentElement.appendChild( body );         // restore for subsequent tests
  assert.ok( document.getElementById( "task-body-overlay" ) === null );
} );

test( "_dismissTaskBodyOverlay: idempotent when no overlay is open (no throw)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui._dismissTaskBodyOverlay();                         // nothing open
  assert.ok( document.getElementById( "task-body-overlay" ) === null );
} );

test( "_wireTaskListAccordion: a delegated 📄 click through the wired listener opens the overlay", () => {
  const ui = newUI();
  buildPanelDOM();
  const container = document.getElementById( "task-list-container" )!;
  container.innerHTML = ui._renderTaskRow( { id: "wired123", title: "t", status: "queued", body: "delegated body" }, undefined );
  ui._wireTaskListAccordion();
  const emoji = container.querySelector( ".task-detail-emoji" ) as HTMLElement;
  emoji.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.ok( document.getElementById( "task-body-overlay" ), "wired delegation opened the overlay" );
  ui._dismissTaskBodyOverlay();
} );

test( "_wireTaskListAccordion: Enter on a focused 📄 opens the overlay (keyboard a11y)", () => {
  const ui = newUI();
  buildPanelDOM();
  const container = document.getElementById( "task-list-container" )!;
  container.innerHTML = ui._renderTaskRow( { id: "kbd12345", title: "t", status: "queued", body: "kbd body" }, undefined );
  ui._wireTaskListAccordion();
  const emoji = container.querySelector( ".task-detail-emoji" ) as HTMLElement;
  emoji.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true } ) );
  assert.ok( document.getElementById( "task-body-overlay" ), "Enter on emoji opened the overlay" );
  ui._dismissTaskBodyOverlay();
} );

test( "_wireTaskListAccordion: a keydown that is neither emoji nor header is ignored", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  ui._wireTaskListAccordion();
  const container = document.getElementById( "task-list-container" )!;
  // Enter on the container itself (not on an emoji or header) → early return, no overlay/toggle.
  container.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true } ) );
  assert.ok( document.getElementById( "task-body-overlay" ) === null );
} );

// ─────────────────────────── renderTaskList (DOM dispatch) ───────────────────────────

test( "renderTaskList: auth_required → sign-in message, count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { status: "auth_required" } );
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /Sign-in required/ );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 0" );
} );

test( "renderTaskList: unreachable with NO prior good fetch → indicator + 'No tasks loaded yet', count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { status: "unreachable", tasks: null } );
  const html = document.getElementById( "task-list-container" )!.innerHTML;
  assert.match( html, /Store unreachable/ );
  assert.match( html, /No tasks loaded yet/ );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 0" );
} );

test( "renderTaskList: unreachable AFTER a good fetch → indicator + LAST-KNOWN rows (never blank)", () => {
  const ui = newUI();
  buildPanelDOM();
  // First a good fetch populates last-known.
  ui.renderTaskList( { tasks: [ T_BLOCKED, T_QUEUED ] } );
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /task-list-table/ );
  // Then an outage — rows must replay under the indicator.
  ui.renderTaskList( { status: "unreachable", tasks: null } );
  const html = document.getElementById( "task-list-container" )!.innerHTML;
  assert.match( html, /Store unreachable/ );
  assert.match( html, /Wire the seam/ );                // last-known row replayed
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 2" );
} );

test( "renderTaskList: non-array tasks (defensive) → unreachable branch", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: "oops" } );
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /Store unreachable/ );
} );

test( "renderTaskList: null composite → unreachable branch (no throw)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( null );
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /Store unreachable/ );
} );

test( "renderTaskList: all-terminal rows → 'No open tasks', count 0 (terminal filtered out)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_DONE ] } );
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /No open tasks/ );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 0" );
} );

test( "renderTaskList: empty tasks array → 'No open tasks', count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [], count: 0 } );
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /No open tasks/ );
} );

test( "renderTaskList: populated → grouped table, count = OPEN rows only, stamped", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_BLOCKED, T_ACTIVE, T_QUEUED, T_DONE ] } );   // 3 open, 1 done
  const container = document.getElementById( "task-list-container" )!;
  assert.match( container.innerHTML, /task-list-table/ );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 3" );
  assert.match( document.getElementById( "task-list-updated" )!.textContent, /updated \d{2}:\d{2}:\d{2}/ );
} );

test( "renderTaskList: falsy row inside tasks is filtered defensively (isTaskOpenStatus on {})", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_BLOCKED, null ] } );   // null row must not throw
  // null → {} → open → counted; table renders
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 2" );
} );

test( "renderTaskList: stampUpdated=false skips re-stamping", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_BLOCKED ] }, false );
  assert.equal( document.getElementById( "task-list-updated" )!.textContent, "" );
} );

test( "renderTaskList: no container in DOM → no-op (no throw)", () => {
  const ui = newUI();
  document.body.replaceChildren();
  ui.renderTaskList( { tasks: [] } );   // must not throw
} );

test( "renderTaskList: container present but NO count element → no throw (auth + table + empty paths)", () => {
  const ui = newUI();
  document.body.replaceChildren();
  const c = document.createElement( "div" );
  c.id = "task-list-container";
  document.body.appendChild( c );
  ui.renderTaskList( { status: "auth_required" } );        // count-null guard (auth)
  assert.match( c.innerHTML, /Sign-in required/ );
  ui.renderTaskList( { tasks: [ T_BLOCKED ] } );           // count-null guard (table)
  assert.match( c.innerHTML, /task-list-table/ );
  ui.renderTaskList( { tasks: [] } );                      // count-null guard (empty)
  assert.match( c.innerHTML, /No open tasks/ );
} );

test( "_renderTaskListUnreachable: countEl null with last-known rows → no throw", () => {
  const ui = newUI();
  const c = document.createElement( "div" );
  ui._taskListLastGoodTasks = [ T_BLOCKED ];
  ui._renderTaskListUnreachable( c, null );   // countEl null branch WITH rows
  assert.match( c.innerHTML, /Wire the seam/ );
} );

test( "_renderTaskListUnreachable: countEl null with NO last-known rows → 'No tasks loaded yet', no throw", () => {
  const ui = newUI();
  const c = document.createElement( "div" );
  ui._taskListLastGoodTasks = null;
  ui._renderTaskListUnreachable( c, null );   // countEl null branch WITHOUT rows
  assert.match( c.innerHTML, /No tasks loaded yet/ );
} );

// ─────────────────────────── _stampTaskListUpdated ───────────────────────────

test( "_stampTaskListUpdated: stamps the span when present", () => {
  const ui = newUI();
  buildPanelDOM();
  ui._stampTaskListUpdated();
  assert.match( document.getElementById( "task-list-updated" )!.textContent, /updated \d{2}:\d{2}:\d{2}/ );
} );

test( "_stampTaskListUpdated: no span → no-op (no throw)", () => {
  const ui = newUI();
  document.body.replaceChildren();
  ui._stampTaskListUpdated();   // must not throw
} );

// ─────────────────────────── fetchTaskList (auth + degradation) ───────────────────────────

test( "fetchTaskList: 200 ok → parsed { tasks, count }", async () => {
  const ui = newUI();
  const body = { tasks: [ T_BLOCKED ], count: 1 };
  ui.authedFetch = async () => fakeResponse( 200, true, body );
  assert.deepEqual( await ui.fetchTaskList(), body );
} );

test( "fetchTaskList: fetches the shared query — guard escapes in, terminal rows OUT", async () => {
  // RE-CUT 2026-07-22. The old version of this test asserted
  // `include_terminal=true` and its comment claimed that kept "the human's
  // all-status view from ever being truncated". Measurement disproved both
  // halves: include_terminal dragged done/dropped history in, inflating the
  // result to 1,171 rows against a server `limit` hard-capped at 500, so 671
  // rows were dropped with no indicator — and since ordering is newest-first,
  // the evicted rows were the OPEN ones this panel exists to show. The comment
  // promised an invariant the parameter was actively breaking.
  const ui = newUI();
  let seen = "";
  ui.authedFetch = async ( url: string ) => { seen = url; return fakeResponse( 200, true, { tasks: [], count: 0 } ); };
  await ui.fetchTaskList();
  assert.ok( seen.includes( "/api/tasks?" ), "hits the tasks endpoint" );
  assert.ok( seen.includes( "unscoped_audit=true" ), "passes unscoped_audit=true" );
  assert.ok( seen.includes( "limit=500" ), "still caps at 500" );
  assert.ok( seen.includes( "char_budget=0" ), "opts out of the response byte budget" );
  assert.ok( seen.includes( "hide_parked=false" ), "asks for parked rows the server hides by default" );
  assert.ok( !seen.includes( "include_terminal" ), "must NOT request terminal rows — that was the truncation bug" );
} );

test( "fetchTaskList: uses the SHARED constant, not a private literal", async () => {
  // The whole point of the shared module: one string, two consumers. If this
  // panel ever grows its own copy again, the two will drift exactly as they did
  // before (char_budget=0 in one, absent in the other) and a fix applied to one
  // will leave the bug live in the other.
  const ui = newUI();
  let seen = "";
  ui.authedFetch = async ( url: string ) => { seen = url; return fakeResponse( 200, true, { tasks: [], count: 0 } ); };
  await ui.fetchTaskList();
  assert.equal( seen, TASK_LIST_QUERY, "fetches exactly the shared constant" );
} );

test( "fetchTaskList: missing query module → query_unavailable, NOT unreachable", async () => {
  // A 404 on the static module is a DEPLOY defect. It must not borrow the
  // store's transport-error state: same blank board, different remedy, and the
  // poll repeats every 60s, so collapsing them has an operator triaging a
  // missing asset as an outage indefinitely.
  const ui = newUI();
  let fetched = false;
  ui.authedFetch = async () => { fetched = true; return fakeResponse( 200, true, { tasks: [], count: 0 } ); };
  const saved = window.LUPIN_TASK_LIST_QUERY;
  delete window.LUPIN_TASK_LIST_QUERY;
  try {
    assert.deepEqual( await ui.fetchTaskList(), { status: "query_unavailable", tasks: null } );
    assert.equal( fetched, false, "never hits the network without a query" );
  } finally {
    window.LUPIN_TASK_LIST_QUERY = saved;
  }
} );

test( "fetchTaskList: 401 → auth_required", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 401, false, null );
  assert.deepEqual( await ui.fetchTaskList(), { status: "auth_required" } );
} );

test( "fetchTaskList: non-ok (500) → unreachable", async () => {
  const ui = newUI();
  ui.authedFetch = async () => fakeResponse( 500, false, null );
  assert.deepEqual( await ui.fetchTaskList(), { status: "unreachable", tasks: null } );
} );

test( "fetchTaskList: network throw → unreachable (never throws)", async () => {
  const ui = newUI();
  ui.authedFetch = async () => { throw new Error( "ECONNREFUSED" ); };
  assert.deepEqual( await ui.fetchTaskList(), { status: "unreachable", tasks: null } );
} );

// ─────────────────────────── refreshTaskList (debounce) ───────────────────────────

test( "refreshTaskList: fetches and renders; guard reset in finally", async () => {
  const ui = newUI();
  buildPanelDOM();
  ui.authedFetch = async () => fakeResponse( 200, true, { tasks: [], count: 0 } );
  await ui.refreshTaskList();
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /No open tasks/ );
  assert.equal( ui._taskListFetchInFlight, false, "guard reset in finally" );
} );

test( "refreshTaskList: in-flight guard short-circuits a concurrent call", async () => {
  const ui = newUI();
  buildPanelDOM();
  let calls = 0;
  ui.authedFetch = async () => { calls++; return fakeResponse( 200, true, { tasks: [] } ); };
  ui._taskListFetchInFlight = true;
  await ui.refreshTaskList();
  assert.equal( calls, 0, "no fetch fired while one is in flight" );
} );

// ─────────────────────────── start/stop polling ───────────────────────────

test( "startTaskListPolling sets a handle + immediate refresh; stop clears it", async () => {
  const ui = newUI();
  buildPanelDOM();
  ui.authedFetch = async () => fakeResponse( 200, true, { tasks: [] } );
  ui.startTaskListPolling();
  assert.ok( ui.taskListPollIntervalHandle, "interval handle set" );
  ui.stopTaskListPolling();
  assert.equal( ui.taskListPollIntervalHandle, null, "handle cleared" );
} );

test( "stopTaskListPolling is a no-op when not polling", () => {
  const ui = newUI();
  ui.taskListPollIntervalHandle = null;
  ui.stopTaskListPolling();   // must not throw
  assert.equal( ui.taskListPollIntervalHandle, null );
} );

test( "startTaskListPolling is idempotent (clears a prior interval first)", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.authedFetch = async () => fakeResponse( 200, true, { tasks: [] } );
  ui.startTaskListPolling();
  const first = ui.taskListPollIntervalHandle;
  ui.startTaskListPolling();
  const second = ui.taskListPollIntervalHandle;
  assert.notEqual( first, second, "a fresh interval replaced the old one" );
  ui.stopTaskListPolling();
} );

// ═══════════════════════════ PER-PERSONA ACCORDION ═══════════════════════════
// Plan: src/rnd/v0.1.8/2026.06.17-task-list-accordion/01-design-and-build-plan.md

// ─────────────── pure key / slug / attr helpers ───────────────

test( "_taskGroupOwnerKey: owned group → persona; Unassigned group → sentinel", () => {
  const ui = newUI();
  assert.equal( ui._taskGroupOwnerKey( { ownerPersona: "Rio", isUnassigned: false, tasks: [] } ), "Rio" );
  assert.equal( ui._taskGroupOwnerKey( { ownerPersona: null, isUnassigned: true, tasks: [] } ), "__unassigned__" );
} );

test( "_taskGroupIdSlug: prefixes + sanitizes non [A-Za-z0-9_-] to '-'; underscores survive", () => {
  const ui = newUI();
  assert.equal( ui._taskGroupIdSlug( "Rio" ), "task-group-Rio" );
  assert.equal( ui._taskGroupIdSlug( "__unassigned__" ), "task-group-__unassigned__" );
  assert.equal( ui._taskGroupIdSlug( "a b/c" ), "task-group-a-b-c" );
  assert.equal( ui._taskGroupIdSlug( 42 as unknown as string ), "task-group-42" );   // String() coercion
} );

test( "_escapeTaskAttr: entity-encodes & \" < > ; coerces non-strings", () => {
  const ui = newUI();
  assert.equal( ui._escapeTaskAttr( 'a&b"c<d>e' ), "a&amp;b&quot;c&lt;d&gt;e" );
  assert.equal( ui._escapeTaskAttr( "plain" ), "plain" );
  assert.equal( ui._escapeTaskAttr( 7 as unknown as string ), "7" );
} );

// ─────────────── renderTaskListTable accordion markup (pure) ───────────────

test( "renderTaskListTable: each owner is its own <tbody.task-group> with data-owner + id slug", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED, T_QUEUED, T_ORPHAN ] );   // Rio, Krishna, (none)
  const html  = ui.renderTaskListTable( model, undefined, new Set() );
  assert.match( html, /<tbody class="task-group" id="task-group-Rio" data-owner="Rio">/ );
  assert.match( html, /<tbody class="task-group" id="task-group-Krishna" data-owner="Krishna">/ );
  assert.match( html, /<tbody class="task-group" id="task-group-__unassigned__" data-owner="__unassigned__">/ );
  // table no longer wraps groups in one shared tbody
  assert.ok( !/<tbody>\s*<tr class="task-group-header/.test( html ), "no bare shared tbody wrapper" );
} );

test( "renderTaskListTable: expanded group → ▾ + aria-expanded=true + no collapsed class", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED ] );          // Rio
  const html  = ui.renderTaskListTable( model, undefined, new Set() );
  assert.match( html, /<tbody class="task-group" id="task-group-Rio"/ );   // NOT "task-group collapsed"
  assert.match( html, /aria-expanded="true"/ );
  assert.match( html, /<span class="task-group-chevron" aria-hidden="true">▾<\/span>/ );
} );

test( "renderTaskListTable: collapsed owner → collapsed class + ▸ + aria-expanded=false", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED, T_QUEUED ] );           // Rio, Krishna
  const html  = ui.renderTaskListTable( model, undefined, new Set( [ "Rio" ] ) );
  assert.match( html, /<tbody class="task-group collapsed" id="task-group-Rio" data-owner="Rio">/ );
  assert.match( html, /aria-expanded="false"[^>]*>\s*<td colspan="11"><span class="task-group-chevron" aria-hidden="true">▸/ );
  // Krishna (not in the set) stays expanded
  assert.match( html, /<tbody class="task-group" id="task-group-Krishna"/ );
} );

test( "renderTaskListTable: Unassigned collapses via the sentinel key", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_ORPHAN ] );           // (Unassigned)
  const html  = ui.renderTaskListTable( model, undefined, new Set( [ "__unassigned__" ] ) );
  assert.match( html, /<tbody class="task-group collapsed" id="task-group-__unassigned__" data-owner="__unassigned__">/ );
} );

test( "renderTaskListTable: missing collapsedOwners arg defaults to all-expanded (first-load default)", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED ] );
  const html  = ui.renderTaskListTable( model, undefined );    // no 3rd arg → new Set()
  assert.ok( !html.includes( "collapsed" ), "no group collapsed by default" );
  assert.match( html, /aria-expanded="true"/ );
} );

// ─────────────── persistence (localStorage) ───────────────

test( "loadCollapsedTaskOwners: absent key → empty set", () => {
  const ui = newUI();
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

test( "loadCollapsedTaskOwners: valid JSON array → Set; non-string members filtered", () => {
  const ui = newUI();
  localStorage.setItem( ui.TASK_LIST_COLLAPSED_KEY, JSON.stringify( [ "Rio", "__unassigned__", 5, null ] ) );
  const set = ui.loadCollapsedTaskOwners();
  assert.deepEqual( Array.from( set ).sort(), [ "Rio", "__unassigned__" ].sort() );
} );

test( "loadCollapsedTaskOwners: non-array JSON → empty set", () => {
  const ui = newUI();
  localStorage.setItem( ui.TASK_LIST_COLLAPSED_KEY, JSON.stringify( { not: "an array" } ) );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

test( "loadCollapsedTaskOwners: empty-string value → empty set (falsy raw)", () => {
  const ui = newUI();
  localStorage.setItem( ui.TASK_LIST_COLLAPSED_KEY, "" );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

test( "loadCollapsedTaskOwners: malformed JSON → empty set (catch), error logged", () => {
  const ui = newUI();
  let logged = 0;
  ui.error = (): void => { logged++; };
  localStorage.setItem( ui.TASK_LIST_COLLAPSED_KEY, "{not json" );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
  assert.equal( logged, 1, "error path exercised" );
} );

test( "saveCollapsedTaskOwners: writes the set as a JSON array", () => {
  const ui = newUI();
  ui.saveCollapsedTaskOwners( new Set( [ "Rio", "Krishna" ] ) );
  assert.deepEqual( JSON.parse( localStorage.getItem( ui.TASK_LIST_COLLAPSED_KEY )! ).sort(), [ "Krishna", "Rio" ] );
} );

test( "saveCollapsedTaskOwners: a throw inside the write is swallowed (error logged, no throw)", () => {
  const ui = newUI();
  let logged = 0;
  ui.error = (): void => { logged++; };
  // Array.from(null) throws "not iterable" INSIDE the try → exercises the catch
  // without depending on a (non-reassignable, in happy-dom) localStorage.setItem.
  ui.saveCollapsedTaskOwners( null as unknown as Iterable<string> );   // must not throw
  assert.equal( logged, 1, "save error path exercised" );
} );

test( "toggleTaskOwnerCollapsed: absent → adds (returns true) + persists; present → removes (false)", () => {
  const ui = newUI();
  assert.equal( ui.toggleTaskOwnerCollapsed( "Rio" ), true );
  assert.deepEqual( Array.from( ui.loadCollapsedTaskOwners() ), [ "Rio" ] );
  assert.equal( ui.toggleTaskOwnerCollapsed( "Rio" ), false );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

// ─────────────── DOM state application ───────────────

test( "_applyTaskGroupCollapseState: collapse=true sets class + aria=false + ▸; false reverses", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const tbody = document.querySelector( 'tbody.task-group[data-owner="Rio"]' ) as HTMLElement;
  assert.ok( tbody, "Rio tbody present" );

  ui._applyTaskGroupCollapseState( tbody, true );
  assert.ok( tbody.classList.contains( "collapsed" ) );
  const header = tbody.querySelector( ".task-group-header" )!;
  assert.equal( header.getAttribute( "aria-expanded" ), "false" );
  assert.equal( header.querySelector( ".task-group-chevron" )!.textContent, "▸" );

  ui._applyTaskGroupCollapseState( tbody, false );
  assert.ok( !tbody.classList.contains( "collapsed" ) );
  assert.equal( header.getAttribute( "aria-expanded" ), "true" );
  assert.equal( header.querySelector( ".task-group-chevron" )!.textContent, "▾" );
} );

test( "_applyTaskGroupCollapseState: tbody with no header → no throw (guard)", () => {
  const ui = newUI();
  const tbody = document.createElement( "tbody" );   // no header inside
  ui._applyTaskGroupCollapseState( tbody, true );     // must not throw
  assert.ok( tbody.classList.contains( "collapsed" ) );
} );

test( "_applyTaskGroupCollapseState: header without a chevron span → no throw (guard)", () => {
  const ui = newUI();
  const tbody = document.createElement( "tbody" );
  const tr    = document.createElement( "tr" );
  tr.className = "task-group-header";                  // header but NO chevron child
  tbody.appendChild( tr );
  ui._applyTaskGroupCollapseState( tbody, true );      // must not throw
  assert.equal( tr.getAttribute( "aria-expanded" ), "false" );
} );

// ─────────────── toggle handler ───────────────

test( "_handleTaskAccordionToggle: target lacking .closest → no-op (defensive)", () => {
  const ui = newUI();
  ui._handleTaskAccordionToggle( {} );                 // {}.closest is undefined → return, no throw
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

test( "_handleTaskAccordionToggle: target with no header ancestor → no-op", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const container = document.getElementById( "task-list-container" )!;   // not inside a header
  ui._handleTaskAccordionToggle( container );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

test( "_handleTaskAccordionToggle: header detached from any tbody.task-group → no-op", () => {
  const ui = newUI();
  const tr = document.createElement( "tr" );
  tr.className = "task-group-header";                   // a header with no tbody.task-group ancestor
  document.body.appendChild( tr );
  ui._handleTaskAccordionToggle( tr );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

test( "_handleTaskAccordionToggle: header inside a group → toggles class + persists", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  const header = document.querySelector( 'tbody.task-group[data-owner="Rio"] .task-group-header' ) as HTMLElement;
  ui._handleTaskAccordionToggle( header );
  assert.deepEqual( Array.from( ui.loadCollapsedTaskOwners() ), [ "Rio" ] );
  assert.ok( document.querySelector( 'tbody.task-group[data-owner="Rio"]' )!.classList.contains( "collapsed" ) );
  // toggling again expands + clears
  ui._handleTaskAccordionToggle( header );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
} );

// ─────────────── delegation wiring ───────────────

test( "_wireTaskListAccordion: no container → no-op, stays unwired", () => {
  const ui = newUI();
  document.body.replaceChildren();
  ui._wireTaskListAccordion();
  assert.equal( ui._taskListAccordionWired, false );
} );

test( "_wireTaskListAccordion: wires once; second call is a guarded no-op", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  ui._wireTaskListAccordion();
  assert.equal( ui._taskListAccordionWired, true );
  ui._wireTaskListAccordion();   // guard: early return, no throw
  assert.equal( ui._taskListAccordionWired, true );
} );

test( "delegation: a real click on a header toggles its group", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  ui._wireTaskListAccordion();
  const header = document.querySelector( 'tbody.task-group[data-owner="Krishna"] .task-group-header' ) as HTMLElement;
  header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.ok( document.querySelector( 'tbody.task-group[data-owner="Krishna"]' )!.classList.contains( "collapsed" ) );
} );

test( "delegation: Enter on a header toggles; Space toggles; other keys ignored; non-header ignored", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  ui._wireTaskListAccordion();
  const container = document.getElementById( "task-list-container" )!;
  const header    = document.querySelector( 'tbody.task-group[data-owner="Rio"] .task-group-header' ) as HTMLElement;

  // a non-toggle key on a header → ignored
  header.dispatchEvent( new KeyboardEvent( "keydown", { key: "a", bubbles: true } ) );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0, "non-toggle key ignored" );

  // Enter on a header → toggles (collapse)
  header.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true } ) );
  assert.deepEqual( Array.from( ui.loadCollapsedTaskOwners() ), [ "Rio" ] );

  // Space on a header → toggles (expand)
  header.dispatchEvent( new KeyboardEvent( "keydown", { key: " ", bubbles: true } ) );
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );

  // legacy "Spacebar" key → toggles (collapse again)
  header.dispatchEvent( new KeyboardEvent( "keydown", { key: "Spacebar", bubbles: true } ) );
  assert.deepEqual( Array.from( ui.loadCollapsedTaskOwners() ), [ "Rio" ] );

  // a toggle key NOT on a header (target = container) → ignored (no further change)
  container.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true } ) );
  assert.deepEqual( Array.from( ui.loadCollapsedTaskOwners() ), [ "Rio" ], "non-header keydown ignored" );
} );

// ─────────────── collapse-all / expand-all ───────────────

test( "_taskListOwnerKeysInDom: returns rendered owner keys; empty when no table", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  assert.deepEqual( ui._taskListOwnerKeysInDom().sort(), [ "Krishna", "Rio", "__unassigned__" ] );
  document.body.replaceChildren();
  assert.deepEqual( ui._taskListOwnerKeysInDom(), [] );
} );

test( "collapseAllTaskOwners: persists every rendered owner + collapses each group DOM", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  ui.collapseAllTaskOwners();
  assert.deepEqual( Array.from( ui.loadCollapsedTaskOwners() ).sort(), [ "Krishna", "Rio", "__unassigned__" ] );
  const collapsed = Array.from( document.querySelectorAll( "tbody.task-group" ) )
    .every( el => el.classList.contains( "collapsed" ) );
  assert.ok( collapsed, "every group collapsed in DOM" );
} );

test( "expandAllTaskOwners: clears the persisted set + expands each group DOM", () => {
  const ui = newUI();
  buildAccordionDOM( ui );
  ui.collapseAllTaskOwners();         // start collapsed
  ui.expandAllTaskOwners();
  assert.equal( ui.loadCollapsedTaskOwners().size, 0 );
  const anyCollapsed = Array.from( document.querySelectorAll( "tbody.task-group" ) )
    .some( el => el.classList.contains( "collapsed" ) );
  assert.ok( !anyCollapsed, "no group collapsed in DOM" );
} );

// ─────────────── renderTaskList wires delegation + honors persisted collapse ───────────────

test( "renderTaskList: wires accordion delegation + renders persisted-collapsed group", () => {
  const ui = newUI();
  buildPanelDOM();
  localStorage.setItem( ui.TASK_LIST_COLLAPSED_KEY, JSON.stringify( [ "Rio" ] ) );
  ui.renderTaskList( { tasks: [ T_BLOCKED, T_QUEUED ] } );   // Rio (collapsed), Krishna (open)
  assert.equal( ui._taskListAccordionWired, true, "delegation wired during render" );
  const rio = document.querySelector( 'tbody.task-group[data-owner="Rio"]' )!;
  assert.ok( rio.classList.contains( "collapsed" ), "persisted collapse honored on render" );
  const krishna = document.querySelector( 'tbody.task-group[data-owner="Krishna"]' )!;
  assert.ok( !krishna.classList.contains( "collapsed" ) );
} );

// ═══════════════════════════════════════════════════════════════════════════
// PARK-ACTIVE predicate — the browser twin of park_is_active()
// (cosa/rest/task_store_owed.py). That module exists because divergence across
// its readers "has bitten this fleet repeatedly", and this panel is now a
// FOURTH reader. Every case below is lifted from the Python twin's own
// contract so a drift on either side shows up here.
// ═══════════════════════════════════════════════════════════════════════════

// FIXTURE MARGINS ARE DELIBERATE (audit rule, María 2026-07-22): a fixture's
// distance from the boundary must be SMALLER than the largest quantity that
// could mask the bug, or the assertion cannot fail. The first draft of this
// block used ±6h and a mutation deleting the timezone normalization outright
// SURVIVED it — a 4h local offset cannot flip a 6h margin.
//
// These two are ZONED (explicit Z), so no offset applies and the masking
// quantity is any accidental skew — ms/seconds confusion, a hardcoded fudge.
// Five minutes is tighter than any such slip, so anything of the kind flips
// them. The zone-less pair below is sized differently and for a different
// reason; see that test.
const NOW_MS   = Date.parse( "2026-07-22T12:00:00Z" );
const FUTURE   = "2026-07-22T12:05:00Z";
const PAST     = "2026-07-22T11:55:00Z";
const PARKED   = ( over: Record<string, unknown> = {} ) =>
  ( { id: "p1", item_class: "task", title: "Deferred", status: "parked",
      owner_persona: "Rio", park_reason: "waiting on Rick", next_chase_ts: FUTURE, ...over } );

// The RENDER path calls _taskIsParked( task ) with no `now`, so it reads the
// wall clock. Freeze it, or these tests quietly depend on the hour they run in.
//
// This helper exists because tightening the fixtures above EXPOSED that
// dependence: with FUTURE at +6h the render tests passed only because 18:00Z was
// still ahead of real time when they were written — a time bomb that would have
// gone red on its own that evening and looked like a regression in the code.
// The clock is now an input, not an ambient condition.
function withFrozenNow<T>( atMs: number, fn: () => T ): T {
  const realNow = Date.now;
  Date.now = () => atMs;
  try { return fn(); } finally { Date.now = realNow; }
}

test( "_taskIsParked: parked + FUTURE chase → park-active", () => {
  assert.equal( newUI()._taskIsParked( PARKED(), NOW_MS ), true );
} );

test( "_taskIsParked: parked + PAST chase → NOT parked (expired, rejoined owed)", () => {
  // Self-expiry is computed at read time and never written back. A row whose
  // chase has passed is workable again and must render normally — dimming it
  // forever is the failure mode the whole read-time rule exists to avoid.
  assert.equal( newUI()._taskIsParked( PARKED( { next_chase_ts: PAST } ), NOW_MS ), false );
} );

test( "_taskIsParked: parked + chase EXACTLY now → NOT parked (the boundary)", () => {
  // The Python twin pins `chase == now -> False` explicitly: the chase has COME
  // DUE. Pinned here because an off-by-one to >= is invisible in every other case.
  assert.equal( newUI()._taskIsParked( PARKED( { next_chase_ts: "2026-07-22T12:00:00Z" } ), NOW_MS ), false );
} );

test( "_taskIsParked: parked + NULL chase → NOT parked (fail-loud-toward-owed)", () => {
  // ⚠️ THE COUNTER-INTUITIVE ONE, and the reason the first draft of this
  // predicate was overruled. A malformed park is VISIBLE work: the store's
  // is_owed( "parked", None, now ) is True. Dimming it would have the dashboard
  // whisper "deferred, ignore me" over a row the store is actively counting as
  // owed — the same masquerade the marking exists to prevent, pointed backwards.
  assert.equal( newUI()._taskIsParked( PARKED( { next_chase_ts: null } ), NOW_MS ), false );
} );

test( "_taskIsParked: parked + unparseable chase → NOT parked", () => {
  assert.equal( newUI()._taskIsParked( PARKED( { next_chase_ts: "not-a-date" } ), NOW_MS ), false );
} );

test( "_taskIsParked: keyed on STATUS, not on park_reason", () => {
  // park_reason is not the marker — `parked` is a real status. A queued row that
  // merely carries a reason is not parked, and a parked row is parked whether or
  // not the reason survived.
  assert.equal( newUI()._taskIsParked( PARKED( { status: "queued" } ), NOW_MS ), false );
  assert.equal( newUI()._taskIsParked( PARKED( { park_reason: null } ), NOW_MS ), true );
} );

test( "_taskIsParked: a ZONE-LESS chase is read as UTC, matching the Python twin", () => {
  // Cross-language trap: Python does chase.replace( tzinfo=utc ) for a naive
  // value, while Date.parse( "…T14:00:00" ) resolves as LOCAL time. Untreated,
  // the twins disagree by the operator's UTC offset — silently, and only for
  // zone-less rows.
  //
  // ⚠️ THE TIMES ARE CHOSEN, NOT ARBITRARY — this test's FIRST draft used ±6h
  // from `now` and a mutation that deleted the normalization entirely SURVIVED
  // it: a 4-hour local offset cannot flip a 6-hour margin, so both assertions
  // passed either way and the test proved nothing. Both instants below sit
  // INSIDE one UTC offset of `now` (12:00Z), and they straddle it in opposite
  // directions so the pair is sensitive to offsets of either sign:
  //
  //   09:00 naive → as UTC 09:00Z (before now → false)
  //                 read LOCAL at a NEGATIVE offset it lands after now → flips
  //   13:00 naive → as UTC 13:00Z (after now  → true)
  //                 read LOCAL at a POSITIVE offset it lands before now → flips
  //
  // Any non-zero offset flips at least one. Only a UTC±0 machine passes both
  // under the mutation — and there the two readings are genuinely identical.
  const ui = newUI();
  assert.equal( ui._taskIsParked( PARKED( { next_chase_ts: "2026-07-22T09:00:00" } ), NOW_MS ), false,
    "09:00 zone-less is 09:00Z — BEFORE now, so not parked" );
  assert.equal( ui._taskIsParked( PARKED( { next_chase_ts: "2026-07-22T13:00:00" } ), NOW_MS ), true,
    "13:00 zone-less is 13:00Z — AFTER now, so still parked" );
} );

test( "_taskIsParked: junk input never throws", () => {
  const ui = newUI();
  for ( const junk of [ null, undefined, {}, { status: "parked" }, { status: "parked", next_chase_ts: 42 } ] ) {
    assert.equal( ui._taskIsParked( junk, NOW_MS ), false );
  }
} );

test( "_renderTaskRow: park-active row is dimmed + badged; expired park is NOT", () => {
  const ui = newUI();
  withFrozenNow( NOW_MS, () => {
    const active = ui._renderTaskRow( PARKED() );
    assert.ok( active.includes( "task-row-parked" ), "park-active row carries the dim class" );
    assert.ok( active.includes( "task-parked-badge" ), "and the badge" );
    assert.ok( active.includes( "waiting on Rick" ), "badge tooltip carries the operator's own reason" );

    const expired = ui._renderTaskRow( PARKED( { next_chase_ts: PAST } ) );
    assert.ok( !expired.includes( "task-row-parked" ), "expired park renders as ordinary workable row" );
  } );
} );

test( "parked rows are NON-terminal and survive the open-status filter", () => {
  // The path that can actually regress. With include_terminal gone the renderer
  // never receives done/dropped at all, so terminal-parked is moot by
  // construction — but a parked row MUST reach the table, or asking the server
  // for it with hide_parked=false accomplishes nothing.
  const ui = newUI();
  assert.equal( ui.isTaskOpenStatus( "parked" ), true, "parked is non-terminal" );
  buildPanelDOM();
  withFrozenNow( NOW_MS, () => {
    ui.renderTaskList( { tasks: [ PARKED() ], count: 1, total: 1, has_more: false } );
  } );
  // ⚠️ THIS ASSERTION CHANGED MEANING ON 2026-08-28, deliberately. It used to
  // read "1" — one open row, parked or not. The header now DISCLOSES the split,
  // so a board of one park-active row reads as zero live work with one deferred
  // row behind it. The edit is the visible record that the number's meaning moved.
  assert.equal( document.getElementById( "task-list-count" )!.textContent,
    "Live: 0 · Parked: 1 · Total: 1", "parked row is counted on the PARKED side" );
  assert.ok( document.querySelector( "tr.task-row-parked" ), "parked row is rendered, dimmed" );
} );

// ═══════════════════════════════════════════════════════════════════════════
// HEADER COUNT — LIVE vs PARKED. The old header printed one number over a board
// that was 5/8 deliberately-deferred, so every "drive the board to zero" talk
// started from a figure that was mostly rows nobody intended to touch.
// ═══════════════════════════════════════════════════════════════════════════

test( "_formatTaskListCount: parked present → the three-part disclosure", () => {
  assert.equal( newUI()._formatTaskListCount( 3, 5 ), "Live: 3 · Parked: 5 · Total: 8" );
} );

test( "_formatTaskListCount: zero parked → labelled, but no parked split", () => {
  // CHANGED 2026-09-01. This used to assert the BARE number "3". The header now
  // carries a SECOND number beside it — the closed-vs-new ratio — and a bare
  // integer next to a bare decimal is two unlabelled quantities the reader has to
  // tell apart by shape. The parked split stays conditional; only the label went
  // unconditional.
  assert.equal( newUI()._formatTaskListCount( 3, 0 ), "Live: 3" );
  assert.equal( newUI()._formatTaskListCount( 0, 0 ), "Live: 0" );
} );

test( "_formatTaskListCount: all-parked board still shows the live zero", () => {
  assert.equal( newUI()._formatTaskListCount( 0, 5 ), "Live: 0 · Parked: 5 · Total: 5" );
} );

test( "_formatTaskListCount: non-numeric counts degrade to 0, never NaN", () => {
  const ui = newUI();
  assert.equal( ui._formatTaskListCount( undefined as unknown as number, 2 ), "Live: 0 · Parked: 2 · Total: 2" );
  assert.equal( ui._formatTaskListCount( 2, undefined as unknown as number ), "Live: 2" );
} );

// ═══════════════════════════════════════════════════════════════════════════
// CLOSED-vs-NEW RATIO IN THE HEADER (2026-09-01). The number is counted in SQL by
// GET /api/tasks/flow-ratio; the header is a thin consumer of it. Two things the
// endpoint's own docstring insists on and these tests pin: the WINDOW travels with
// the number, and ratio:null renders as an em dash rather than 0.00.
// ═══════════════════════════════════════════════════════════════════════════

test( "_formatFlowRatio: prints the ratio as a PERCENT, short enough for the bar", () => {
  assert.equal(
    newUI()._formatFlowRatio( { created: 10, closed: 13, ratio: 0.77, window_hours: 24 } ),
    "10 created / 13 closed  over 1d = 77%"
  );
} );

test( "_formatFlowRatio: the WINDOW is not cosmetic — same board, different window", () => {
  // The measured pair from the endpoint's docstring. The verdict FLIPS on the
  // window alone, so a header that showed 0.77 and 1.10 without saying which
  // window produced each would be showing two numbers that look like a
  // contradiction and are not. A fixture that hard-coded 24 could not see this.
  const ui = newUI();
  assert.equal( ui._formatFlowRatio( { ratio: 0.77, window_hours: 24 } ),
                "1d = 77%" );
  assert.equal( ui._formatFlowRatio( { ratio: 1.10, window_hours: 168 } ),
                "7d = 110%" );
} );

test( "_formatFlowRatio: nothing closed is INFINITY, never a number", () => {
  // closed === 0 with rows created means nothing was finished in the window, which
  // is the WORST case and a DENY. Rendering it as 0% would read as the best, and a
  // big number like 999% would be a lie carrying a number's authority.
  const text = newUI()._formatFlowRatio( { created: 4, closed: 0, ratio: null, window_hours: 24 } );
  assert.equal( text, "4 created / 0 closed  over 1d = \u221e" );
  // ⚠️ NARROWED, NOT WEAKENED. This read `!/[0-9]/` — no digit anywhere — which was a
  // correct proxy while the clause was only "Gate: <ratio>". The clause now also carries
  // the window and the counts, so digits are expected and that form would fail on text
  // that is entirely right. The INTENT was always that the unmeasurable RATIO must not
  // acquire a number, so the assertion now says exactly that.
  assert.ok( !/[0-9]+%/.test( text ),
             "an unmeasurable ratio must not render as a percentage" );
  assert.match( text, /\u221e/, "it renders as infinity instead" );
} );

test( "_formatFlowRatio: an IDLE window is an em dash, not infinity", () => {
  // Nothing created and nothing closed is not a failing window — it is an empty one,
  // and the gate allows. Distinct from the deny case above, which it would otherwise
  // render identically to.
  assert.equal( newUI()._formatFlowRatio( { created: 0, closed: 0, ratio: null, window_hours: 24 } ),
                "0 created / 0 closed  over 1d = \u2014" );
} );

test( "_formatFlowRatio: percents are whole numbers, and above 100% is legal", () => {
  assert.equal( newUI()._formatFlowRatio( { ratio: 1.1, window_hours: 24 } ),
                "1d = 110%" );
  assert.equal( newUI()._formatFlowRatio( { ratio: 2, window_hours: 24 } ),
                "1d = 200%" );
} );

test( "_formatFlowRatio: unusable payloads yield an EMPTY clause, not a zero", () => {
  const ui = newUI();
  for ( const junk of [ null, undefined, "nope", 42, [], {}, { ratio: 0.5 } ] ) {
    assert.equal( ui._formatFlowRatio( junk ), "",
                  `expected an omitted clause for ${JSON.stringify( junk )}` );
  }
} );

test( "_renderFlowRatio: writes the clause with its leading separator", () => {
  document.body.innerHTML = `<span id="task-list-flow-ratio"></span>`;
  newUI()._renderFlowRatio( { ratio: 0.77, window_hours: 24 } );
  assert.equal( document.getElementById( "task-list-flow-ratio" )!.textContent,
                " \u00b7 1d = 77%" );
} );

test( "_renderFlowRatio: an unreachable endpoint CLEARS the clause, leaving no stale number", () => {
  document.body.innerHTML = `<span id="task-list-flow-ratio"> \u00b7 1d = 77%</span>`;
  newUI()._renderFlowRatio( null );
  assert.equal( document.getElementById( "task-list-flow-ratio" )!.textContent, "" );
} );

test( "_renderFlowRatio: absent span is a no-op, not a throw", () => {
  document.body.innerHTML = ``;
  assert.doesNotThrow( () => newUI()._renderFlowRatio( { ratio: 0.5, window_hours: 24 } ) );
} );

test( "fetchFlowRatio: returns the payload on a 2xx", async () => {
  const ui = newUI();
  const seen: string[] = [];
  ui.authedFetch = async ( url: string ) => {
    seen.push( url );
    return { ok: true, status: 200, json: async () => ( { ratio: 0.77, window_hours: 24 } ) };
  };
  assert.deepEqual( await ui.fetchFlowRatio(), { ratio: 0.77, window_hours: 24 } );
  assert.deepEqual( seen, [ "/api/tasks/flow-ratio" ] );
} );

test( "fetchFlowRatio: every failure shape returns null, and none of them throw", async () => {
  const ui = newUI();
  ui.log = () => {};

  ui.authedFetch = async () => ( { ok: false, status: 401, json: async () => ( {} ) } );
  assert.equal( await ui.fetchFlowRatio(), null, "401" );

  ui.authedFetch = async () => ( { ok: false, status: 500, json: async () => ( {} ) } );
  assert.equal( await ui.fetchFlowRatio(), null, "500" );

  ui.authedFetch = async () => { throw new Error( "network down" ); };
  assert.equal( await ui.fetchFlowRatio(), null, "network throw" );

  ui.authedFetch = async () => ( { ok: true, status: 200, json: async () => { throw new Error( "bad json" ); } } );
  assert.equal( await ui.fetchFlowRatio(), null, "unparseable body" );

  ui.authedFetch = async () => ( { ok: true, status: 200, json: async () => "not an object" } );
  assert.equal( await ui.fetchFlowRatio(), null, "wrong shape" );
} );

test( "_taskListCountText: splits a mixed board on the park-ACTIVE predicate", () => {
  const ui   = newUI();
  const rows = [ T_BLOCKED, T_ACTIVE, PARKED(), PARKED( { id: "p2" } ) ];
  assert.equal( ui._taskListCountText( rows, NOW_MS ), "Live: 2 · Parked: 2 · Total: 4" );
} );

test( "🔴 _taskListCountText: an EXPIRED park counts LIVE, not parked", () => {
  // THE FALSIFYING CASE, and the one the whole feature turns on. Parked is a
  // status PLUS a live clock: once next_chase_ts passes, the store counts the row
  // as owed again with nothing sweeping it. A header that kept calling it parked
  // would under-report live work — the same fiction this change removes, pointed
  // the other way.
  //
  // Chosen so the two rows differ ONLY in their chase time: any implementation
  // that keys on `status` or on `park_reason` instead of the clock reports
  // "Live: 0 · Parked: 2" here and goes red.
  const ui   = newUI();
  const rows = [ PARKED(), PARKED( { id: "p2", next_chase_ts: PAST } ) ];
  assert.equal( ui._taskListCountText( rows, NOW_MS ), "Live: 1 · Parked: 1 · Total: 2" );
} );

test( "_taskListCountText: a null chase counts LIVE (fail-loud-toward-owed)", () => {
  // A malformed park is visible work — is_owed( "parked", None, now ) is True.
  const ui = newUI();
  assert.equal( ui._taskListCountText( [ PARKED( { next_chase_ts: null } ) ], NOW_MS ), "Live: 1" );
} );

test( "_taskListCountText: junk argument counts 0 rather than throwing", () => {
  const ui = newUI();
  for ( const junk of [ null, undefined, {}, "nope" ] ) {
    assert.equal( ui._taskListCountText( junk, NOW_MS ), "Live: 0" );
  }
} );

test( "renderTaskList: header shows the split on a mixed board", () => {
  const ui = newUI();
  buildPanelDOM();
  withFrozenNow( NOW_MS, () => {
    ui.renderTaskList( { tasks: [ T_BLOCKED, T_ACTIVE, PARKED() ], count: 3, total: 3, has_more: false } );
  } );
  assert.equal( document.getElementById( "task-list-count" )!.textContent,
    "Live: 2 · Parked: 1 · Total: 3" );
} );

test( "renderTaskList: an unparked board keeps the plain single number", () => {
  const ui = newUI();
  buildPanelDOM();
  withFrozenNow( NOW_MS, () => {
    ui.renderTaskList( { tasks: [ T_BLOCKED, T_ACTIVE ], count: 2, total: 2, has_more: false } );
  } );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 2" );
} );

test( "the outage replay uses the SAME split, so the two states can't disagree", () => {
  // Last-known rows survive a store outage. If that branch kept printing a raw
  // length, the header would silently change MEANING the moment the store blinked.
  const ui = newUI();
  buildPanelDOM();
  withFrozenNow( NOW_MS, () => {
    ui.renderTaskList( { tasks: [ T_ACTIVE, PARKED() ], count: 2, total: 2, has_more: false } );
    assert.equal( document.getElementById( "task-list-count" )!.textContent,
      "Live: 1 · Parked: 1 · Total: 2", "fresh fetch" );

    ui.renderTaskList( { status: "unreachable" } );
    assert.equal( document.getElementById( "task-list-count" )!.textContent,
      "Live: 1 · Parked: 1 · Total: 2", "outage replay of the same rows reads identically" );
  } );
} );

// ═══════════════════════════════════════════════════════════════════════════
// TRUNCATION BANNER — the LOUD half. The defect was the silence, not the number.
// ═══════════════════════════════════════════════════════════════════════════

test( "truncation banner: absent when the server reports a complete board", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 1, total: 1, has_more: false } );
  assert.ok( !document.querySelector( ".task-list-truncated" ), "no banner on a complete board" );
} );

test( "truncation banner: fires on has_more, naming shown / total / remainder", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 500, total: 1171, has_more: true } );
  const banner = document.querySelector( ".task-list-truncated" );
  assert.ok( banner, "banner present" );
  const text = banner!.textContent ?? "";
  assert.match( text, /500/, "names how many are shown" );
  assert.match( text, /1171/, "names how many exist" );
  assert.match( text, /671/, "names the remainder — the number nobody could see before" );
} );

test( "truncation banner: count < total fires it even when has_more is absent", () => {
  // Two independent ways to notice, so one missing field cannot restore silence.
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 500, total: 1171 } );
  assert.ok( document.querySelector( ".task-list-truncated" ), "cross-check fires without has_more" );
} );

test( "truncation banner: rows that DID arrive are still rendered beneath it", () => {
  // The banner supplements the board; it never replaces it. A truncated board is
  // still worth reading.
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_BLOCKED, T_QUEUED ], count: 500, total: 1171, has_more: true } );
  assert.ok( document.querySelector( ".task-list-truncated" ), "banner present" );
  assert.ok( document.querySelectorAll( "tr.task-row" ).length >= 2, "table still rendered" );
} );

test( "truncation banner: fires on an EMPTY page that the server says is partial", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [], count: 0, total: 40, has_more: true } );
  assert.ok( document.querySelector( ".task-list-truncated" ), "banner survives the empty branch" );
  assert.ok( document.querySelector( ".task-list-empty" ), "empty message still shown" );
} );

test( "truncation banner: garbage / missing totals are treated as no claim", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 1 } );
  assert.ok( !document.querySelector( ".task-list-truncated" ), "absent total makes no claim" );
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 1, total: "lots", has_more: "yes" } );
  assert.ok( !document.querySelector( ".task-list-truncated" ), "non-numeric total makes no claim" );
} );

// ── Trigger 3: the one that survives `total` going missing ────────────────────
// has_more and count<total BOTH key on `total`. One shared dependency, and its
// absence restores the exact silence this banner removes. This trigger needs
// neither field.

test( "truncation banner: a FULL page with no total says UNKNOWN, not nothing", () => {
  const ui = newUI();
  buildPanelDOM();
  // 500 rows === the limit in the shared query, and no `total` to check it
  // against. Legitimately-exactly-500 is possible, which is why the wording is
  // UNKNOWN rather than a truncation claim — unknown-and-loud beats
  // assumed-complete-and-quiet.
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 500 } );
  const banner = document.querySelector( ".task-list-truncated" );
  assert.ok( banner, "full page + no total still raises a banner" );
  assert.match( banner!.textContent ?? "", /UNKNOWN/, "says completeness is unknown" );
} );

test( "truncation banner: a full page WITH a matching total is silent", () => {
  // The discriminator. Same 500 rows; the server accounted for them, so there is
  // nothing to warn about. Without this the trigger would fire on every full
  // healthy page and train the operator to ignore the banner.
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 500, total: 500, has_more: false } );
  assert.ok( !document.querySelector( ".task-list-truncated" ), "accounted-for full page is silent" );
} );

test( "truncation banner: a SHORT page with no total is silent", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 499 } );
  assert.ok( !document.querySelector( ".task-list-truncated" ), "a page under the limit implies the end of the board" );
} );

test( "_taskListQueryLimit: read from the shared query, not hardcoded", () => {
  // A hardcoded 500 would stop matching the day the query is edited, and the
  // full-page trigger would quietly never fire again — a guard that cannot fire.
  const ui = newUI();
  assert.equal( ui._taskListQueryLimit(), 500, "parses the live constant" );
  const saved = window.LUPIN_TASK_LIST_QUERY;
  try {
    window.LUPIN_TASK_LIST_QUERY = "/api/tasks?limit=750&unscoped_audit=true";
    assert.equal( ui._taskListQueryLimit(), 750, "tracks an edited limit" );
    buildPanelDOM();
    ui.renderTaskList( { tasks: [ T_QUEUED ], count: 750 } );
    assert.ok( document.querySelector( ".task-list-truncated" ), "full-page trigger follows the new limit" );
    window.LUPIN_TASK_LIST_QUERY = "/api/tasks?unscoped_audit=true";
    assert.ok( Number.isNaN( ui._taskListQueryLimit() ), "absent limit → NaN, trigger simply does not fire" );
  } finally {
    window.LUPIN_TASK_LIST_QUERY = saved;
  }
} );

// ── Server warnings[] — verbatim, own line, never in the arithmetic ───────────

test( "server warnings render VERBATIM on their own line", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 1, total: 1, has_more: false,
                       warnings: [ "non-terse pull returned 900 full rows" ] } );
  const bar = document.querySelector( ".task-list-truncated" );
  assert.ok( bar, "a warning alone raises the bar even on a complete board" );
  assert.match( bar!.textContent ?? "", /non-terse pull returned 900 full rows/, "server text unedited" );
} );

test( "server warnings do NOT feed the shown/total arithmetic", () => {
  // An unrecognized warning has no numbers. Inventing them would be worse than
  // silence, so the count sentence and the warning line stay separate elements.
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_QUEUED ], count: 500, total: 1171, has_more: true,
                       warnings: [ "something new the client has never seen" ] } );
  const bars = document.querySelectorAll( ".task-list-truncated" );
  assert.equal( bars.length, 2, "two separate lines: the count claim and the server's own words" );
  assert.match( bars[ 0 ]!.textContent ?? "", /671 not displayed/, "arithmetic line unchanged by the warning" );
  assert.match( bars[ 1 ]!.textContent ?? "", /something new the client has never seen/ );
} );

test( "server warnings: empty / non-array is silent", () => {
  const ui = newUI();
  for ( const w of [ [], undefined, null, "a string", 42 ] ) {
    buildPanelDOM();
    ui.renderTaskList( { tasks: [ T_QUEUED ], count: 1, total: 1, has_more: false, warnings: w } );
    assert.ok( !document.querySelector( ".task-list-truncated" ), `no bar for ${JSON.stringify( w )}` );
  }
} );

// ═══════════════════════════════════════════════════════════════════════════
// query_unavailable render branch — a deploy defect wearing its own face
// ═══════════════════════════════════════════════════════════════════════════

test( "renderTaskList: query_unavailable names the missing FILE and is not an outage", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { status: "query_unavailable", tasks: null } );
  const el = document.querySelector( ".task-list-query-unavailable" );
  assert.ok( el, "renders its own distinct state" );
  assert.match( el!.textContent ?? "", /task-list-query\.js/, "names the file an operator must go look for" );
  assert.ok( !document.querySelector( ".task-list-unreachable" ), "does NOT masquerade as a store outage" );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "Live: 0" );
} );

test( "renderTaskList: query_unavailable does NOT replay last-known rows", () => {
  // Deliberate contrast with the unreachable branch, which replays. A stale
  // board under a deploy error invites the operator to believe the panel is
  // working; the unreachable branch replays because the data was once real and
  // the outage is expected to end.
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_BLOCKED, T_QUEUED ], count: 2, total: 2 } );
  assert.ok( document.querySelectorAll( "tr.task-row" ).length >= 2, "good board first" );
  ui.renderTaskList( { status: "query_unavailable", tasks: null } );
  assert.equal( document.querySelectorAll( "tr.task-row" ).length, 0, "no stale rows under a deploy error" );
} );

if ( typeof process !== "undefined" && process.argv.includes( "--run" ) ) { /* node --test entry */ }

// ═══════════════════════════════════════════════════════════════════════════
// FILED-BY COLUMN (2026-09-02). Rick asked by voice for the filer's name on every
// board row — specifically the ones he was blocking — so a row he wants chased
// names a person rather than only an id. `created_by` was already populated on
// every live row; it was invisible only because it was absent from the terse
// projection the board reads.
// ═══════════════════════════════════════════════════════════════════════════

test( "_taskFilerLabel: a TWO-WORD persona survives — the split()[0] trap", () => {
  // 🔴 THE DEFECT THIS EXISTS TO PREVENT. `created_by.split( " " )[ 0 ]` returns
  // "mr" for "mr radio 0e61abe3". María measured it wrong on 6 of 13 live rows,
  // and those six are exactly the rows Rick asked about — the naive form fails
  // hardest precisely where the feature is for.
  const ui = newUI();
  assert.equal( ui._taskFilerLabel( { created_by: "mr radio 0e61abe3" } ), "Mr Radio" );
  assert.equal( ui._taskFilerLabel( { created_by: "Krishna 420f5ec9" } ),  "Krishna" );
  assert.equal( ui._taskFilerLabel( { created_by: "rio b45d54db" } ),      "Rio" );
} );

test( "_taskFilerLabel: an unrecognised shape renders WHOLE, never sliced", () => {
  // A truncated name is a WRONG name wearing a right one's clothes; a full odd
  // string is visibly odd and sends the reader to the row. So the fall-through
  // must not guess where the name stops.
  const ui = newUI();
  assert.equal( ui._taskFilerLabel( { created_by: "some automated importer" } ),
                "Some Automated Importer" );
  assert.equal( ui._taskFilerLabel( { created_by: "mr radio zzzzzzzz" } ),
                "Mr Radio Zzzzzzzz",
                "zzzzzzzz is 8 chars but not hex — it is part of the name, not a session id" );
} );

test( "_taskFilerLabel: absent, blank and whitespace-only all give an em dash", () => {
  const ui = newUI();
  for ( const row of [ {}, { created_by: "" }, { created_by: "   " }, { created_by: null } ] ) {
    assert.equal( ui._taskFilerLabel( row ), "—", `${JSON.stringify( row )} → em dash` );
  }
  assert.equal( ui._taskFilerLabel( undefined ), "—" );
} );

test( "the Filed-by column renders the filer, and it is NOT the owner column", () => {
  // Filer and owner differ on 3 of 13 live rows, so merging them into one "who"
  // column misreports the person on roughly a quarter of the board. This asserts
  // they are carried separately by giving one row a filer the owner is not.
  const ui = newUI();
  const html = ui._renderTaskRow( {
    id: "abcdef12-0000-0000-0000-000000000000",
    title: "a row filed by someone other than its owner",
    status: "queued",
    owner_persona: "maria",
    accountable_manager: "maria",
    created_by: "mr radio 0e61abe3",
    priority: "P2",
    project: "lupin"
  }, undefined );

  assert.match( html, /<td class="task-col-filer">Mr Radio<\/td>/ );
  assert.match( html, /<td class="task-col-accountable">maria<\/td>/,
    "the accountable column must still carry the manager, not the filer" );
} );

test( "the Filed-by cell is escaped like every other store-sourced value", () => {
  // The card writes via innerHTML, so an unescaped cell is an injection point.
  const ui = newUI();
  const html = ui._renderTaskRow(
    { id: "x", title: "t", status: "queued", created_by: '<img src=x onerror=alert(1)> aaaaaaaa' },
    undefined
  );
  assert.ok( !html.includes( "<img src=x" ), "the filer cell rendered raw HTML" );
  // Case-INSENSITIVE deliberately: display-casing runs after escaping, so the
  // shipped output is "&lt;Img". A case-sensitive /&lt;img/ fails here on code
  // that is escaping correctly — which is what it did on first run.
  assert.match( html, /&lt;img/i );
  assert.ok( !html.includes( "onerror=alert(1)>" ), "the raw handler survived unescaped" );
} );
