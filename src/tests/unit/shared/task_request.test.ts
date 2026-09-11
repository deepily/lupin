// The promote/demote request chip and verdict body both clients share — row c9fafb9d.
//
// ⚠️ LIKE ITS SIBLINGS, `shared/*.js` IS NOT IN THE c8 DENOMINATOR (run-typescript-tests.sh
// covers multiplexer/**, nav/** and diagnostic/**). These assertions run and fail loudly;
// they emit no coverage number, so read this file, not the gate, for this module.
//
// 🔴 THE FIRST TEST PINS THE CLIENT'S WORDS TO THE SERVER'S. The move and state strings
// here are a mirror of `task_approval_settings.MOVE_*` and `task_request_lifecycle`; a
// client that spelled one differently would render no chip for a real pending request and
// every other assertion in this file would stay green.
//
// Run: npx tsx --test src/tests/unit/shared/task_request.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  REQUEST_PENDING, MOVE_ADMIT, MOVE_DEMOTE, VERDICT_APPROVED, VERDICT_DENIED,
  BADGE_HOLDING_AREA, BADGE_TASK_AREA, REQUEST_BADGES_PATH, DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE,
  requestVerdictPath, requestAge, pendingRequestChip, requestVerdictBody, requestBadgeText,
  REQUEST_FILED_TRANSITION, REQUEST_REASON_SEPARATOR, requestEventsPath, requestFiledDetail,
} from "../../../lupin_app/static/js/shared/task-request.js";
import { TRIAGE_DATE_LABEL } from "../../../lupin_app/static/js/shared/task-request.js";
import { TASK_VERB_SPECS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE      = path.dirname( fileURLToPath( import.meta.url ) );
const REPO_ROOT = path.resolve( HERE, "../../../.." );
const read      = ( rel: string ) => readFileSync( path.join( REPO_ROOT, rel ), "utf8" );

const NOW = Date.parse( "2026-09-10T12:00:00Z" );

test( "the client's move, state, verdict and badge words are the server's words", () => {
  const settings  = read( "src/cosa/rest/task_approval_settings.py" );
  const lifecycle = read( "src/cosa/rest/task_request_lifecycle.py" );
  const router    = read( "src/cosa/rest/routers/tasks.py" );

  assert.match( settings,  new RegExp( `MOVE_ADMIT\\s+=\\s+"${MOVE_ADMIT}"` ) );
  assert.match( settings,  new RegExp( `MOVE_DEMOTE\\s+=\\s+"${MOVE_DEMOTE}"` ) );
  assert.match( lifecycle, new RegExp( `REQUEST_PENDING\\s+=\\s+"${REQUEST_PENDING}"` ) );
  assert.match( lifecycle, new RegExp( `REQUEST_APPROVED\\s+=\\s+"${VERDICT_APPROVED}"` ) );
  assert.match( lifecycle, new RegExp( `REQUEST_DENIED\\s+=\\s+"${VERDICT_DENIED}"` ) );
  assert.match( lifecycle, new RegExp( `BADGE_HOLDING_AREA\\s+=\\s+"${BADGE_HOLDING_AREA}"` ) );
  assert.match( lifecycle, new RegExp( `BADGE_TASK_AREA\\s+=\\s+"${BADGE_TASK_AREA}"` ) );
  assert.ok( router.includes( `"${REQUEST_BADGES_PATH.replace( "/api", "" )}"` ), "the badge route moved" );
  assert.ok( router.includes( '"/tasks/{task_id}/request-verdict"' ), "the verdict route moved" );
} );

test( "a pending admit renders a promote chip with its age", () => {
  const chip = pendingRequestChip(
    { request_state: "pending", request_move: "admit", request_ts: "2026-09-10T09:00:00Z" }, NOW );
  assert.deepEqual( chip, { move: "admit", text: "Promote requested", age: "3h", needsTriageDate: false } );
} );

test( "a pending demote renders a demote chip that needs a triage date", () => {
  const chip = pendingRequestChip(
    { request_state: "pending", request_move: "demote", request_ts: "2026-09-08T11:00:00Z" }, NOW );
  assert.deepEqual( chip, { move: "demote", text: "Demote requested", age: "2d", needsTriageDate: true } );
} );

test( "an answered, absent or malformed request renders NO chip", () => {
  for ( const row of [
    { request_state: "approved", request_move: "admit",  request_ts: "2026-09-10T09:00:00Z" },
    { request_state: "denied",   request_move: "demote", request_ts: "2026-09-10T09:00:00Z" },
    { request_state: null,       request_move: null,     request_ts: null },
    { request_state: "pending",  request_move: "wont_fix" },
    {},
  ] ) {
    assert.equal( pendingRequestChip( row, NOW ), null, JSON.stringify( row ) );
  }
  assert.equal( pendingRequestChip( null as never, NOW ), null );
} );

test( "request age reads just now, minutes, hours and days, and nothing for no time", () => {
  assert.equal( requestAge( "2026-09-10T11:59:30Z", NOW ), "just now" );
  assert.equal( requestAge( "2026-09-10T11:48:00Z", NOW ), "12m" );
  assert.equal( requestAge( "2026-09-10T11:00:00Z", NOW ), "1h" );
  assert.equal( requestAge( "2026-09-07T12:00:00Z", NOW ), "3d" );
  assert.equal( requestAge( "2026-09-10T13:00:00Z", NOW ), "just now", "a clock skewed ahead reads as just now, never negative" );
  assert.equal( requestAge( null, NOW ), "" );
  assert.equal( requestAge( "", NOW ), "" );
  assert.equal( requestAge( "not a date", NOW ), "" );
} );

test( "approving a DEMOTE without a triage date is refused client-side, with its reason", () => {
  assert.deepEqual( requestVerdictBody( VERDICT_APPROVED, MOVE_DEMOTE ),
                    { ok: false, message: DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE } );
  assert.deepEqual( requestVerdictBody( VERDICT_APPROVED, MOVE_DEMOTE, { triageByIso: "" } ),
                    { ok: false, message: DEMOTE_NEEDS_TRIAGE_DATE_MESSAGE } );
} );

test( "approving a demote with a date sends next_chase_ts; an admit and a denial never do", () => {
  assert.deepEqual(
    requestVerdictBody( VERDICT_APPROVED, MOVE_DEMOTE, { triageByIso: "2026-09-17T13:00:00.000Z", reason: "  not now  " } ),
    { ok: true, body: { verdict: "approved", next_chase_ts: "2026-09-17T13:00:00.000Z", reason: "not now" } } );
  assert.deepEqual( requestVerdictBody( VERDICT_APPROVED, MOVE_ADMIT, { triageByIso: "2026-09-17T13:00:00.000Z" } ),
                    { ok: true, body: { verdict: "approved" } } );
  assert.deepEqual( requestVerdictBody( VERDICT_DENIED, MOVE_DEMOTE, { reason: "   " } ),
                    { ok: true, body: { verdict: "denied" } } );
} );

test( "the verdict path encodes its id", () => {
  assert.equal( requestVerdictPath( "abc-123" ), "/api/tasks/abc-123/request-verdict" );
  assert.equal( requestVerdictPath( "a/b" ),     "/api/tasks/a%2Fb/request-verdict" );
} );

test( "a badge shows its own count, nothing at zero, and never reads the other badge", () => {
  const counts = { holding_area: 2, task_area: 1 };
  assert.equal( requestBadgeText( counts, BADGE_HOLDING_AREA ), "2 requests" );
  assert.equal( requestBadgeText( counts, BADGE_TASK_AREA ),    "1 request" );
  assert.equal( requestBadgeText( { holding_area: 0, task_area: 5 }, BADGE_HOLDING_AREA ), "" );
  assert.equal( requestBadgeText( null, BADGE_TASK_AREA ), "" );
  assert.equal( requestBadgeText( { task_area: "3" }, BADGE_TASK_AREA ), "", "a non-number is not a count" );
} );

test( "the filing event's transition and reason separator are the repository's own", () => {
  // `apply_request_filing` writes the preamble and the manager's words in ONE f-string.
  // A reworded preamble would leave the chip showing "move: 'admit' (prior …" as the reason.
  const repo = read( "src/cosa/rest/db/repositories/task_repository.py" );
  assert.ok( repo.includes( `"${REQUEST_FILED_TRANSITION}"` ), "the filing transition was renamed" );
  assert.ok( repo.includes( `(prior request: {before!r})${REQUEST_REASON_SEPARATOR}{reason}"` ),
             "the filing event's reason format moved" );
} );

test( "the filer and reason come from the LAST request_filed event, in the repository's format", () => {
  const body = { events: [
    { transition: "created",       actor: "mr radio 52f3fe21", reason: null },
    { transition: "request_filed", actor: "mr radio 52f3fe21", reason: "move: 'admit' (prior request: None) | reason: first ask" },
    { transition: "request_denied", actor: "rick", reason: null },
    { transition: "request_filed", actor: "cheech 1a2b3c4d",   reason: "move: 'admit' (prior request: 'denied') | reason: ready now | truly" },
  ] };
  assert.deepEqual( requestFiledDetail( body ), { filer: "cheech 1a2b3c4d", reason: "ready now | truly" } );
} );

test( "a filing with no separator shows its whole reason; odd events and bodies read as nothing", () => {
  assert.deepEqual( requestFiledDetail( { events: [ { transition: "request_filed", actor: 7, reason: "just words" } ] } ),
                    { filer: "", reason: "just words" } );
  assert.deepEqual( requestFiledDetail( { events: [ { transition: "request_filed" } ] } ), { filer: "", reason: "" } );
  assert.equal( requestFiledDetail( { events: [ null, { transition: "created" } ] } ), null );
  assert.equal( requestFiledDetail( { events: "nope" } ), null );
  assert.equal( requestFiledDetail( null ), null );
} );

test( "the events path encodes its id", () => {
  assert.equal( requestEventsPath( "a/b" ), "/api/tasks/a%2Fb/events" );
} );

test( "the chip's triage label IS the demote verb's own date label (Tiffany F4)", () => {
  // Two copies of one string drift; this is the tie. Approving a demote asks for the same date
  // Rick's own Demote asks for, so a renamed label must rename both or redden here.
  assert.equal( TRIAGE_DATE_LABEL, ( TASK_VERB_SPECS as Record<string, { dateLabel: string }> ).demote!.dateLabel );
} );
