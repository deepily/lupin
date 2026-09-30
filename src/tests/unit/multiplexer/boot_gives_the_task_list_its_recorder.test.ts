// Row ab1f06e7 — boot hands the task list the recorder, so the New Ticket card gets its mics.
//
// 🔴 WHY THE ROW MIC WAS NO WITNESS. TaskRowController falls back to the `recordingManager`
// singleton when no recorder is given, so the task list's row mics worked with boot passing
// none. The New Ticket card is the opposite: it offers Title and Details mics only when a
// recorder IS given. So the multiplexer's card rendered with no mics, with every row mic
// working beside it and every renderer test green, because those tests inject a fake.
//
// A source-level check, the established guard for boot wiring (see
// boot_wires_requests_into_both_boards.test.ts for why no test boots `bootMultiplexer`).
// The browser half, the booted page's card measured in Chromium, is
// src/tests/smoke/test_the_new_ticket_mics_butt_against_their_fields.py.
//
// Run: npx tsx --test src/tests/unit/multiplexer/boot_gives_the_task_list_its_recorder.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

// Resolved from THIS file, never from LUPIN_ROOT, so a worktree reads its own boot.ts.
const BOOT_CODE = readFileSync(
  resolve( dirname( fileURLToPath( import.meta.url ) ), "../../../lupin_app/static/js/multiplexer/boot.ts" ), "utf8",
).split( "\n" ).filter( ( line ) => !line.trimStart().startsWith( "//" ) ).join( "\n" );

/** The text of `createTaskListRenderer({ … })`, found exactly once. */
function taskListBlock(): string {
  const starts = [ ...BOOT_CODE.matchAll( /createTaskListRenderer\(\{/g ) ];
  assert.equal( starts.length, 1, `expected exactly one createTaskListRenderer({ in boot.ts, found ${ starts.length }` );
  const start = starts[ 0 ]!.index!;
  const end   = BOOT_CODE.indexOf( "});", start );
  assert.ok( end > start, "the createTaskListRenderer block has no end" );
  return BOOT_CODE.slice( start, end );
}

const WIRED = /\brecorder\s*:\s*recordingManager\s*,/;

test( "positive control: the block is the task list's, and the pattern can fail", () => {
  assert.ok( taskListBlock().includes( "lookupFetch" ), "the block found is not the task list's" );
  assert.equal( WIRED.test( "recorder : undefined," ), false, "the pattern matches a missing recorder" );
} );

test( "the task list is built WITH the recorder, so the New Ticket card has its mics", () => {
  assert.match( taskListBlock(), WIRED,
    "boot.ts must pass `recorder : recordingManager` to createTaskListRenderer" );
} );

test( "the recorder boot passes is the singleton itself, imported from the recording manager", () => {
  assert.match( BOOT_CODE, /import \{ recordingManager \} from "\.\/audio\/recordingManager";/,
    "boot.ts must import the one recordingManager — a second recorder would fight the first for the mic" );
} );
