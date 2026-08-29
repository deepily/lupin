// Legacy notifications.js — `handleDoneQueueUpdate` payload-reader unit test (2026-08-21).
//
// Row 82fb9fcb. GET /api/get-queue/done returns ONLY `done_jobs_metadata`
// (queues.py:480; the dead and todo/run paths at :538 and :569 are the same
// shape). It has NOT returned a `done_jobs` HTML list for some time.
//
// `handleDoneQueueUpdate` drove its loop off `data.done_jobs`, so with today's
// payload the loop body never ran and `this.doneJobsMetadata` stayed empty.
// That Map is what `replayJobAudio` looks a job up in (notifications.js:10900),
// so Replay on any done job hit "Job metadata not found" and alerted the user.
//
// This test feeds the CURRENT payload shape and asserts the Map is populated.
// It fails against the pre-fix reader (Map size 0) and passes after.
//
// Harness follows session_reaped_handler.test.ts: the file is ~18.5k lines and
// boots a heavy constructor at load, so we slice off the trailing init block,
// load the class in happy-dom, and build an instance via Object.create() to
// bypass the constructor.
//
// Run via:
//   npx tsx --test src/tests/unit/notifications_js/done_queue_metadata_reader.test.ts

import { test, before } from "node:test";
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
  const classOnly  = fullSource.slice( 0, initIdx );
  assert.ok( classOnly.includes( "class NotificationsUI" ), "sliced source must still contain the class" );
  vm.runInThisContext( classOnly + "\n;globalThis.NotificationsUI = NotificationsUI;" );
  assert.equal( typeof ( globalThis as Record<string, unknown> ).NotificationsUI, "function", "NotificationsUI loaded" );
} );

interface DoneUI extends Record<string, unknown> {
  handleDoneQueueUpdate: ( data: unknown ) => Promise<void>;
  doneJobsMetadata: Map<string, Record<string, unknown>>;
  enhancedDoneListHtml: string;
}

// Constructor-bypassed instance carrying only what handleDoneQueueUpdate reads.
function makeUI(): { ui: DoneUI; errors: unknown[] } {
  const Ctor   = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui     = Object.create( Ctor.prototype ) as DoneUI;
  const errors: unknown[] = [];

  ui.debug                 = false;
  ui.log                   = (): void => {};                        // silence Design-by-Contract logging
  ui.error                 = ( ...a: unknown[] ): void => { errors.push( a ); };
  ui.audioCacheInitialized = false;                                 // real checkJobAudioCacheAvailability returns false
  ui.audioCache            = null;

  return { ui, errors };
}

// The exact shape queues.py:480 serves: a list of structured rows, no HTML list.
const DONE_PAYLOAD = {
  done_jobs_metadata: [
    { job_id: "job-alpha", question_text: "What is 2+2?", response_text: "Four.",  timestamp: "2026-08-21T20:00:00" },
    { job_id: "job-beta",  question_text: "What is 3+3?", response_text: "Six.",   timestamp: "2026-08-21T20:01:00" }
  ],
  filtered_by  : "user_abc",
  is_admin_view: false,
  total_jobs   : 2
};

test( "handleDoneQueueUpdate indexes every job from done_jobs_metadata", async () => {
  const { ui, errors } = makeUI();

  await ui.handleDoneQueueUpdate( DONE_PAYLOAD );

  assert.equal( errors.length, 0, "reader must not fall into its error path" );
  assert.equal( ui.doneJobsMetadata.size, 2,
    "both metadata rows must be indexed — replayJobAudio looks jobs up in this Map" );
  assert.ok( ui.doneJobsMetadata.has( "job-alpha" ), "job-alpha must be replayable" );
  assert.ok( ui.doneJobsMetadata.has( "job-beta" ),  "job-beta must be replayable" );
  assert.equal( ui.doneJobsMetadata.get( "job-alpha" )!.response_text, "Four." );
} );

test( "handleDoneQueueUpdate records audio-cache availability per job", async () => {
  const { ui } = makeUI();

  await ui.handleDoneQueueUpdate( DONE_PAYLOAD );

  // audioCache is uninitialized here, so the real check resolves false — the
  // point is that the field is SET, i.e. each row went through the loop body.
  assert.equal( ui.doneJobsMetadata.get( "job-alpha" )!.has_audio_cache, false );
  assert.equal( ui.doneJobsMetadata.get( "job-beta" )!.has_audio_cache,  false );
} );

test( "handleDoneQueueUpdate survives an empty done queue", async () => {
  const { ui, errors } = makeUI();

  await ui.handleDoneQueueUpdate( { done_jobs_metadata: [], filtered_by: "user_abc", is_admin_view: false, total_jobs: 0 } );

  assert.equal( errors.length, 0, "an empty queue is not an error" );
  assert.equal( ui.doneJobsMetadata.size, 0 );
  assert.equal( ui.enhancedDoneListHtml, "" );
} );
