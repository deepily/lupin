// THE JOBS PANE SPEAKS THE LEGACY CLIENT'S WORDS — parity A-2 #10, row 0ef31897.
//
// Build plan src/rnd/v0.2.1/2026.09.15-multiplexer-parity-build-plan.md §1 A-2 row 10;
// the audit is Phase 2 A12 (B9d, B10, Q2, Q5) in
// src/rnd/v0.2.1/2026.09.15-multiplexer-vs-legacy-runtime-disparities.md.
// "Buckets start collapsed" is struck (§3 R2) and is not tested here.
//
// The legacy client is the lead. Each block below cites the legacy code it copies,
// read at 2847ea74:
//
//   Glyphs and labels   notifications.html:1163-1245 in `#queues-section` — the five `.queue-header`s:
//                       🟡 TODO · 🔵 Running · ✅ Done · ❌ Dead · 📋 Job History
//   Empty copy          notifications.js:5735 `updateQueueEmptyMessage` — "No jobs in queue";
//                       notifications.js:6622 `loadJobHistory` — "No job history found"
//   Delete-all confirm  notifications.js:6869 `deleteAllQueueJobs` — the queue by name, the
//                       running-queue interrupt warning, and the history window
//   History dedup       notifications.js:6622 `loadJobHistory` — the ids live in Done and Dead
//                       go to /api/job-history as `exclude_ids`
//
// ⚠️ ONE DELIBERATE DEPARTURE. An admin's delete-all removes EVERY user's jobs whatever the
// Mine switch shows (row 83c3ff74, María's review), and legacy's dialog does not say so.
// The admin wording keeps legacy's shape and adds "for every user"; those cases are pinned in
// the_jobs_pane_follows_the_shared_mine_switch.test.ts. Everything here is a non-admin.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/the_jobs_pane_speaks_the_legacy_words.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";

import { GlobalRegistrator } from "@happy-dom/global-registrator";
import { createEventBusForTesting, type EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createJobStore } from "../../../../lupin_app/static/js/multiplexer/stores/JobStore";
import { createJobsPaneRenderer, type JobsPaneApiClient } from "../../../../lupin_app/static/js/multiplexer/render/JobsPaneRenderer";
import { renderJobBucket } from "../../../../lupin_app/static/js/multiplexer/render/templates/jobBucket";
import type { Job, JobBucket, JobStateTransitionPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

const settle = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 20 ) );

const SERVER_STATE: Record<Job[ "status" ], string> = { todo: "pending", running: "running", done: "completed", dead: "failed" };

/** A job arriving over the WebSocket, the only way a live bucket is ever filled. */
function arrive( bus: EventBus, id: string, status: Job[ "status" ] ): void {
  bus.emit<JobStateTransitionPayload>( {
    type    : "job_state_transition",
    payload : { job_id: id, id_hash: id, from_state: null, to_state: SERVER_STATE[ status ], metadata: { agent_type: "DeepResearchJob" } },
    source  : "test",
    ts      : Date.now(),
  } );
}

interface Pane {
  bus    : EventBus;
  root   : HTMLElement;
  gets   : string[];
  /** Every confirm() the pane raised, in order. Each one answers "cancel". */
  asked  : string[];
  pressDeleteAll : ( bucket: JobBucket ) => string;
  chooseWindow   : ( value: string ) => Promise<void>;
  unmount        : () => void;
}

/** A non-admin's jobs pane over a real JobStore; the history endpoint reports `total`. */
async function mountPane( total = 0 ): Promise<Pane> {
  const bus  = createEventBusForTesting();
  const jobs = createJobStore( { bus } );
  const gets: string[] = [];
  const api: JobsPaneApiClient = {
    get    : async <T>( path: string ): Promise<T> => { gets.push( path ); return { jobs: [], total } as unknown as T; },
    delete : async <T>(): Promise<T> => null as T,
    post   : async <T>(): Promise<T> => null as T,
  };
  const root      = document.createElement( "section" );
  const container = document.createElement( "div" );
  container.id = "jobs-buckets-container";
  root.appendChild( container );
  document.body.appendChild( root );
  const renderer = createJobsPaneRenderer( { eventBus: bus, stores: { jobs }, api } );
  renderer.mount( root );
  await settle();

  const asked: string[] = [];
  return {
    bus, root, gets, asked,
    pressDeleteAll : ( bucket ) => {
      const real = globalThis.confirm;
      globalThis.confirm = ( m?: string ): boolean => { asked.push( String( m ) ); return false; };
      try {
        const btn = root.querySelector( `.queue-delete-all-btn[data-bucket='${ bucket }']` ) as HTMLElement | null;
        assert.notEqual( btn, null, `no delete-all button on the ${ bucket } bucket` );
        btn!.click();
      } finally {
        globalThis.confirm = real;
      }
      assert.ok( asked.length > 0, "the delete-all raised no confirm at all" );
      return asked[ asked.length - 1 ]!;
    },
    chooseWindow : async ( value ) => {
      const select = root.querySelector( ".history-time-select" ) as HTMLSelectElement;
      select.value = value;
      select.dispatchEvent( new Event( "change", { bubbles: true } ) );
      await settle();
    },
    unmount : () => { renderer.unmount(); jobs.disposeForTesting(); root.remove(); },
  };
}

const excludeIdsOf = ( path: string ): string | null => new URL( path, "http://x" ).searchParams.get( "exclude_ids" );

// ---------------------------------------------------------------------------
// Glyphs and labels — notifications.html:1163-1245
// ---------------------------------------------------------------------------

const LEGACY_HEADINGS: ReadonlyArray<[ JobBucket, string, string ]> = [
  [ "todo",    "🟡", "TODO" ],
  [ "running", "🔵", "Running" ],
  [ "done",    "✅", "Done" ],
  [ "dead",    "❌", "Dead" ],
  [ "history", "📋", "Job History" ],
];

for ( const [ bucket, glyph, label ] of LEGACY_HEADINGS ) {
  test( `the ${ bucket } bucket is headed ${ glyph } ${ label }, as legacy heads it`, () => {
    const header = renderJobBucket( bucket, [] ).querySelector( ".jobs-bucket-header" ) as HTMLElement;
    assert.equal( ( header.querySelector( ".jobs-bucket-glyph" )?.textContent ?? "" ).trim(), glyph );
    assert.equal( ( header.querySelector( ".jobs-bucket-label" )?.textContent ?? "" ).trim(), label );
  } );
}

// ---------------------------------------------------------------------------
// Empty copy — notifications.js:5735 updateQueueEmptyMessage, :6622 loadJobHistory
// ---------------------------------------------------------------------------

for ( const bucket of [ "todo", "running", "done", "dead" ] as const ) {
  test( `an empty ${ bucket } bucket says "No jobs in queue"`, () => {
    const empty = renderJobBucket( bucket, [] ).querySelector( ".jobs-bucket-empty" );
    assert.equal( ( empty?.textContent ?? "" ).trim(), "No jobs in queue" );
  } );
}

test( "an empty history bucket says \"No job history found\"", () => {
  const empty = renderJobBucket( "history", [] ).querySelector( ".jobs-bucket-empty" );
  assert.equal( ( empty?.textContent ?? "" ).trim(), "No job history found" );
} );

// ---------------------------------------------------------------------------
// Delete-all confirm — notifications.js:6869 deleteAllQueueJobs
// ---------------------------------------------------------------------------

test( "delete-all on a live queue names the count and the queue, in the plural", async () => {
  const p = await mountPane();
  arrive( p.bus, "t1", "todo" );
  arrive( p.bus, "t2", "todo" );
  assert.equal( p.pressDeleteAll( "todo" ), "Remove all 2 jobs from the todo queue?" );
  p.unmount();
} );

test( "delete-all on a queue holding one job says \"job\", not \"jobs\"", async () => {
  const p = await mountPane();
  arrive( p.bus, "x1", "dead" );
  assert.equal( p.pressDeleteAll( "dead" ), "Remove all 1 job from the dead queue?" );
  p.unmount();
} );

test( "delete-all on the done queue names the done queue", async () => {
  const p = await mountPane();
  assert.equal( p.pressDeleteAll( "done" ), "Remove all 0 jobs from the done queue?" );
  p.unmount();
} );

test( "delete-all on the running queue warns that it cancels and interrupts", async () => {
  const p = await mountPane();
  arrive( p.bus, "r1", "running" );
  assert.equal( p.pressDeleteAll( "running" ), "Cancel and remove all 1 running job? This will interrupt active jobs." );
  arrive( p.bus, "r2", "running" );
  assert.equal( p.pressDeleteAll( "running" ), "Cancel and remove all 2 running jobs? This will interrupt active jobs." );
  p.unmount();
} );

test( "delete-all on history names the server's total and the window it is showing", async () => {
  const p = await mountPane( 7 );
  assert.equal( p.pressDeleteAll( "history" ), "Delete all 7 history entries from last 30 days?" );
  await p.chooseWindow( "1" );
  assert.equal( p.pressDeleteAll( "history" ), "Delete all 7 history entries from last 1 day?" );
  await p.chooseWindow( "all" );
  assert.equal( p.pressDeleteAll( "history" ), "Delete all 7 history entries from all time?" );
  p.unmount();
} );

// ---------------------------------------------------------------------------
// History dedup — notifications.js:6622 loadJobHistory sends `exclude_ids`
// ---------------------------------------------------------------------------

test( "🔴 a history read names the jobs live in Done and Dead, so the server leaves them out", async () => {
  const p = await mountPane();
  assert.equal( excludeIdsOf( p.gets[ 0 ]! ), null, "PRECONDITION: nothing is live at mount, so the first read excludes nothing" );

  arrive( p.bus, "d1", "done" );
  arrive( p.bus, "x1", "dead" );
  arrive( p.bus, "t1", "todo" );        // live, but not Done or Dead: legacy does not exclude it
  arrive( p.bus, "r1", "running" );
  await p.chooseWindow( "7" );

  const last = p.gets[ p.gets.length - 1 ]!;
  assert.match( last, /^\/api\/job-history\?days=7&/, `the window change did not read history: ${ last }` );
  assert.equal( excludeIdsOf( last ), "d1,x1" );
  p.unmount();
} );

test( "a Load More page carries the same exclusions as the page before it", async () => {
  const bus  = createEventBusForTesting();
  const jobs = createJobStore( { bus } );
  const gets: string[] = [];
  const api = {
    get : async <T>( path: string ): Promise<T> =>  {
      gets.push( path );
      return { jobs: [ { id_hash: `h${ gets.length }`, job_type: "X", status: "completed", created_at: 1 } ], total: 5 } as unknown as T;
    },
  };
  arrive( bus, "d1", "done" );
  await jobs.hydrateHistory( api, { days: 30 } );
  await jobs.hydrateHistory( api, { append: true } );
  assert.equal( gets.length, 2 );
  assert.equal( excludeIdsOf( gets[ 1 ]! ), "d1", `the appended page dropped the exclusion: ${ gets[ 1 ] }` );
  assert.match( gets[ 1 ]!, /offset=1/, "the second read is the next page, not the first again" );
  jobs.disposeForTesting();
} );
