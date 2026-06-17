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

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

before( () => {
  if ( typeof globalThis.document === "undefined" ) {
    GlobalRegistrator.register();
  }
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
  renderTaskListTable: ( model: { groups: TaskGroupModel[] }, ianaZone?: unknown ) => string;
  renderTaskList: ( composite: unknown, stampUpdated?: boolean ) => void;
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
  ui._taskListFetchInFlight     = false;
  ui._taskListLastGoodTasks     = null;
  ui.taskListPollIntervalHandle = null;
  ui.TASK_LIST_POLL_INTERVAL_MS = 60000;
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

beforeEach( () => { document.body.replaceChildren(); } );

// ─────────────────────────── isTaskOpenStatus (pure) ───────────────────────────

test( "isTaskOpenStatus: terminal done/dropped → false; everything else (incl. missing) → true", () => {
  const ui = newUI();
  assert.equal( ui.isTaskOpenStatus( "done" ), false );
  assert.equal( ui.isTaskOpenStatus( "dropped" ), false );
  assert.equal( ui.isTaskOpenStatus( "blocked" ), true );
  assert.equal( ui.isTaskOpenStatus( "queued" ), true );
  assert.equal( ui.isTaskOpenStatus( null ), true );
  assert.equal( ui.isTaskOpenStatus( undefined ), true );
  assert.equal( ui.isTaskOpenStatus( "" ), true );
} );

// ─────────────────────────── _taskStatusRank / _taskPriorityRank (pure) ───────────────────────────

test( "_taskStatusRank: known ranks, missing → 5, unknown → 5", () => {
  const ui = newUI();
  assert.equal( ui._taskStatusRank( "blocked" ), 0 );
  assert.equal( ui._taskStatusRank( "in_progress" ), 1 );
  assert.equal( ui._taskStatusRank( "claimed" ), 2 );
  assert.equal( ui._taskStatusRank( "review" ), 3 );
  assert.equal( ui._taskStatusRank( "queued" ), 4 );
  assert.equal( ui._taskStatusRank( "done" ), 6 );
  assert.equal( ui._taskStatusRank( "dropped" ), 7 );
  assert.equal( ui._taskStatusRank( null ), 5 );        // missing
  assert.equal( ui._taskStatusRank( "bananas" ), 5 );   // unknown
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

test( "_renderTaskRow: status class on <tr>, status dot, all eight cells, blocked_by shown", () => {
  const ui = newUI();
  const html = ui._renderTaskRow( T_BLOCKED, "America/New_York" );
  assert.match( html, /<tr class="task-row task-status-blocked">/ );
  assert.match( html, /<td class="task-col-status"><span class="task-status-dot"><\/span>blocked<\/td>/ );
  assert.match( html, /Wire the seam/ );
  assert.match( html, /decision:abc/ );                 // blocked_by rendered
  assert.match( html, /10:30/ );                        // next_chase in EDT
  assert.match( html, /task-col-priority task-prio-high/ );   // P1 → high tint
  assert.match( html, />lupin</ );                      // project
  assert.match( html, /task-class-badge task-class-task/ );
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

test( "renderTaskListTable: owner group header (owner · count) + Unassigned label, eight columns, colspan 8", () => {
  const ui = newUI();
  const model = ui.groupTasksByOwner( [ T_BLOCKED, T_QUEUED, T_ORPHAN ] );
  const html = ui.renderTaskListTable( model, undefined );
  assert.match( html, /<table class="task-list-table">/ );
  assert.match( html, /Rio · 1/ );
  assert.match( html, /Krishna · 1/ );
  assert.match( html, /\(Unassigned\)/ );
  assert.match( html, /task-group-unassigned/ );
  for ( const col of [ "Title", "Class", "Status", "Blocked by", "Next chase", "Accountable", "Priority", "Project" ] ) {
    assert.ok( html.includes( col ), `header "${col}" present` );
  }
  assert.match( html, /colspan="8"/ );
  assert.ok( html.indexOf( "Krishna" ) < html.indexOf( "(Unassigned)" ), "Unassigned renders last" );
} );

// ─────────────────────────── renderTaskList (DOM dispatch) ───────────────────────────

test( "renderTaskList: auth_required → sign-in message, count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { status: "auth_required" } );
  assert.match( document.getElementById( "task-list-container" )!.innerHTML, /Sign-in required/ );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "0" );
} );

test( "renderTaskList: unreachable with NO prior good fetch → indicator + 'No tasks loaded yet', count 0", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { status: "unreachable", tasks: null } );
  const html = document.getElementById( "task-list-container" )!.innerHTML;
  assert.match( html, /Store unreachable/ );
  assert.match( html, /No tasks loaded yet/ );
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "0" );
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
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "2" );
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
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "0" );
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
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "3" );
  assert.match( document.getElementById( "task-list-updated" )!.textContent, /updated \d{2}:\d{2}:\d{2}/ );
} );

test( "renderTaskList: falsy row inside tasks is filtered defensively (isTaskOpenStatus on {})", () => {
  const ui = newUI();
  buildPanelDOM();
  ui.renderTaskList( { tasks: [ T_BLOCKED, null ] } );   // null row must not throw
  // null → {} → open → counted; table renders
  assert.equal( document.getElementById( "task-list-count" )!.textContent, "2" );
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

if ( typeof process !== "undefined" && process.argv.includes( "--run" ) ) { /* node --test entry */ }
