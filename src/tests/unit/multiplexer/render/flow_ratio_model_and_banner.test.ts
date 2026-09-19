// Parity A-2 #8 (row c1bb2be7) — the pure halves: the flow-ratio text and colour
// (render/flowRatioModel.ts) and the truncation banner (templates/truncationBanner.ts).
// The readout is legacy's #task-list-flow-ratio, notifications.html:968-970; the
// banner leads #holding-area-container inside #holding-area-section, notifications.html:1083.
// Every expected string is legacy's, character for character, from these methods
// (unnamed in io/phase2/A9.md): _formatFlowRatio · _flowRatioRoomText ·
// _flowRatioPercentText · _flowRatioWindowDays · _flowRatioLongForm · _flowRatioIsOpen ·
// _renderTaskListTruncationBanner · _holdingAreaWarningCount · _taskListQueryLimit.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  flowRatioIsOpen,
  flowRatioLongForm,
  flowRatioPercentText,
  flowRatioReadoutText,
  flowRatioRoomText,
  flowRatioSettingsUsable,
  flowRatioSourceLine,
  flowRatioThreshold,
  flowRatioWindowDays,
  formatFlowRatio,
} from "../../../../lupin_app/static/js/multiplexer/render/flowRatioModel";
import {
  heldWarningCount,
  queryLimit,
  renderTruncationBanner,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/truncationBanner";
import type { TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const RATIO = { created: 12, closed: 10, ratio: 1.2, close_needed: 2, room_for: 0, window_hours: 24, allow_below: 1.0 };

// ---------------------------------------------------------------------------
// The readout text
// ---------------------------------------------------------------------------

test( "the window is whole days, never below 1; an unusable window is null", () => {
  assert.equal( flowRatioWindowDays( 24 ), 1 );
  assert.equal( flowRatioWindowDays( 6 ), 1, "a sub-day window still reads 1d" );
  assert.equal( flowRatioWindowDays( 84 ), 4, "rounded: 3.5 days → 4" );
  assert.equal( flowRatioWindowDays( 0 ), null );
  assert.equal( flowRatioWindowDays( -24 ), null );
  assert.equal( flowRatioWindowDays( "24" ), null );
} );

test( "the percent is rounded; no ratio reads ∞ when something was created, — when nothing was", () => {
  assert.equal( flowRatioPercentText( { ratio: 1.234 } ), "123%" );
  assert.equal( flowRatioPercentText( { ratio: null, created: 3 } ), "∞" );
  assert.equal( flowRatioPercentText( { ratio: null, created: 0 } ), "—" );
  assert.equal( flowRatioPercentText( {} ), "—" );
} );

test( "the room clause reads CLOSE first, then Room for, then FULL, else nothing", () => {
  assert.equal( flowRatioRoomText( { close_needed: 2, room_for: 5 } ), "  · CLOSE 2" );
  assert.equal( flowRatioRoomText( { close_needed: 0, room_for: 3 } ), "  · Room for 3 more" );
  assert.equal( flowRatioRoomText( { room_for: 0 } ), "  · FULL" );
  assert.equal( flowRatioRoomText( { room_for: -1 } ), "" );
  assert.equal( flowRatioRoomText( {} ), "" );
} );

test( "the clause: counts, window, percent and room; counts omitted when either is missing", () => {
  assert.equal( formatFlowRatio( RATIO ), "12 created / 10 closed  over 1d = 120%  · CLOSE 2" );
  assert.equal( formatFlowRatio( { ratio: 0.5, window_hours: 48 } ), "2d = 50%" );
  assert.equal( formatFlowRatio( null ), "" );
  assert.equal( formatFlowRatio( { ratio: 0.5 } ), "", "no window, no clause" );
} );

test( "mid-drag the clause withholds the counts and says it is recounting", () => {
  assert.equal( formatFlowRatio( RATIO, 7 ), "recounting…  over 7d" );
  assert.equal( formatFlowRatio( null, 7 ), "", "nothing to recount without a payload" );
} );

test( "the readout prefixes ' · Gate: ' or is empty; the hover carries the scope caveat", () => {
  assert.equal( flowRatioReadoutText( RATIO ), " · Gate: 12 created / 10 closed  over 1d = 120%  · CLOSE 2" );
  assert.equal( flowRatioReadoutText( null ), "" );
  assert.equal( flowRatioLongForm( RATIO ),
    "Closed vs New Ratio — 12 created / 10 closed  over 1d = 120%  · CLOSE 2\n"
    + "Counts creation across EVERY project and priority, not only this pane." );
  assert.equal( flowRatioLongForm( null ), "" );
  assert.equal( flowRatioLongForm( { ratio: 1 } ), "", "no window, no hover" );
  assert.equal( flowRatioLongForm( { window_hours: -5 } ), "", "a window that yields no clause yields no hover" );
} );

// ---------------------------------------------------------------------------
// The colour
// ---------------------------------------------------------------------------

test( "open is strictly below the threshold; no threshold reads open", () => {
  assert.equal( flowRatioIsOpen( { ratio: 0.9 }, 1.0 ), true );
  assert.equal( flowRatioIsOpen( { ratio: 1.0 }, 1.0 ), false, "exactly at the threshold is CLOSED" );
  assert.equal( flowRatioIsOpen( { ratio: 1.5 }, Number.NaN ), true );
  assert.equal( flowRatioIsOpen( { ratio: null, created: 4 }, 1.0 ), false, "created but nothing closed: closed" );
  assert.equal( flowRatioIsOpen( { ratio: null, created: 0 }, 1.0 ), true );
  assert.equal( flowRatioIsOpen( null, 1.0 ), true );
} );

test( "defect 5 fixed: the threshold falls back to the ratio payload's own allow_below", () => {
  const settings = { allow_below: 0.8, window_hours: 24 };
  assert.equal( flowRatioThreshold( settings, { allow_below: 1.5 } ), 0.8, "settings win when usable" );
  assert.equal( flowRatioThreshold( null, { allow_below: 1.5 } ), 1.5, "legacy read undefined here, i.e. OPEN" );
  assert.ok( Number.isNaN( flowRatioThreshold( null, null ) ) );
  assert.ok( Number.isNaN( flowRatioThreshold( { allow_below: 1 }, {} ) ), "unusable settings, no payload threshold" );
} );

test( "settings are usable only with both numbers; the source line names an override", () => {
  assert.equal( flowRatioSettingsUsable( { allow_below: 1, window_hours: 24 } ), true );
  assert.equal( flowRatioSettingsUsable( { allow_below: 1 } ), false );
  assert.equal( flowRatioSettingsUsable( null ), false );
  assert.equal( flowRatioSourceLine( { window_source: "override" } ), "saved override" );
  assert.equal( flowRatioSourceLine( { threshold_source: "override" } ), "saved override" );
  assert.equal( flowRatioSourceLine( { window_source: "config", threshold_source: "config" } ), "from config" );
} );

// ---------------------------------------------------------------------------
// The truncation banner
// ---------------------------------------------------------------------------

const Q = "/api/tasks?limit=500&unscoped_audit=true&status=not_approved&char_budget=0";
const texts = ( c: TaskListComposite | null, count: number | null = null ): string[] =>
  renderTruncationBanner( c, Q, count ).map( ( p ) => `${p.className}|${p.textContent}` );

test( "the query's own limit is read; no limit is NaN", () => {
  assert.equal( queryLimit( Q ), 500 );
  assert.ok( Number.isNaN( queryLimit( "/api/tasks?status=x" ) ) );
} );

test( "a complete page says nothing", () => {
  assert.deepEqual( texts( null ), [] );
  assert.deepEqual( texts( { tasks: [], count: 3, total: 3 } ), [] );
} );

test( "total above shown says how many are missing", () => {
  assert.deepEqual( texts( { count: 500, total: 1912, tasks: [] } ),
    [ "task-list-message task-list-truncated|✂️ Board truncated: showing 500 of 1912 — 1412 not displayed." ] );
} );

test( "a page exactly `limit` long with no total is completeness UNKNOWN; shown falls back to tasks.length", () => {
  const tasks = Array.from( { length: 500 }, ( _, i ) => ( { id: String( i ) } ) ) as TaskListComposite["tasks"];
  assert.deepEqual( texts( { tasks } ),
    [ "task-list-message task-list-truncated|✂️ Board truncated: the page came back exactly full (500) and the server reported no total — completeness UNKNOWN." ] );
} );

test( "has_more alone says the server held rows back", () => {
  assert.deepEqual( texts( { has_more: true, tasks: [] } ),
    [ "task-list-message task-list-truncated|✂️ Board truncated: the server held rows back — some work is not displayed." ] );
  assert.deepEqual( texts( { has_more: true, total: 9, count: Number.NaN } ).length, 1, "no finite count, no tasks array" );
} );

test( "server warnings follow verbatim, joined by ' · ', after the ✂️ line (legacy defect 7, left)", () => {
  assert.deepEqual( texts( { count: 500, total: 600, warnings: [ "row-cap truncation — 100 rows held", 7 ] } ), [
    "task-list-message task-list-truncated|✂️ Board truncated: showing 500 of 600 — 100 not displayed.",
    "task-list-message task-list-truncated|⚠️ Server: row-cap truncation — 100 rows held · 7",
  ] );
  assert.deepEqual( texts( { count: 2, total: 2, warnings: [ "just a note" ] } ),
    [ "task-list-message task-list-truncated|⚠️ Server: just a note" ], "a warning shows without a trigger too" );
} );

test( "the holding-area note becomes 'N waiting for your approval', dropped when it repeats the header count", () => {
  const note = "⚠️ 16 row(s) matching your filters are in the HOLDING AREA ('not_approved') and were WITHHELD";
  assert.equal( heldWarningCount( note ), 16 );
  assert.equal( heldWarningCount( "matching your filters are in the HOLDING AREA but no count" ), null );
  assert.equal( heldWarningCount( 16 ), null );
  assert.deepEqual( texts( { count: 1, total: 1, warnings: [ note ] }, 3 ),
    [ "task-list-message task-list-truncated task-list-holding-note|16 waiting for your approval" ] );
  assert.deepEqual( texts( { count: 1, total: 1, warnings: [ note ] }, 16 ), [], "already on the header" );
} );
