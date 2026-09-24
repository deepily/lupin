// Parity B-2 — SubmitJobsStore unit tests.
//
// LEGACY UNDER TEST, by symbol:
//   notifications.js  submitClaudeCodeToQueue    — the CC door, refreshAllQueues after it
//   notifications.js  submitResearchJob          — command-by-checkbox, topic cleared
//   notifications.js  submitTestSuiteJob         — validation, combined args, the position
//   notifications.js  submitTFEResume            — ambiguous vs resumed
//   notifications.js  _getSchedulingParams       — scheduled_at + monopolize, top-level
//   notifications.js  FILE_DRIVEN_TEST_TYPES     — the two path-requiring types
//
// 🔴 THE FOUR CARDS ARE NOT FOUR COPIES OF ONE SHAPE, and most of this file exists to
// pin the places they differ — the differences are the parity, and a test suite that
// asserted one shape four times would pass while the cards drifted into each other.
//
// Run: npx tsx --test src/tests/unit/multiplexer/submit_jobs_store.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createSubmitJobsStore,
  FILE_DRIVEN_TEST_TYPES,
  type SubmitJobsStore,
  type SchedulingInput,
} from "../../../lupin_app/static/js/multiplexer/stores/SubmitJobsStore";

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

interface Post {
  path    : string;
  body    : Record<string, unknown>;
  headers : Readonly<Record<string, string>> | undefined;
}

interface Harness {
  store    : SubmitJobsStore;
  posts    : Post[];
  ccRefresh: () => number;
  /** What the next post resolves to, or throws. */
  reply    : ( value: unknown ) => void;
  fail     : ( err: unknown ) => void;
  last     : () => Post;
}

function setup(): Harness {
  const bus   = createEventBusForTesting();
  const posts : Post[] = [];
  let   next  : unknown = { job_id: "job-1", queue_position: 3 };
  let   thrown: unknown = null;
  let   refreshes = 0;

  const store = createSubmitJobsStore( {
    bus,
    api : {
      post: async <T>( path: string, body: unknown, opts?: { headers?: Readonly<Record<string, string>> } ): Promise<T> => {
        posts.push( { path, body: body as Record<string, unknown>, headers: opts?.headers } );
        if ( thrown !== null ) throw thrown;
        return next as T;
      },
    },
    sessionId     : () => "wise penguin",
    onCcSubmitted : () => { refreshes += 1; },
    nowFn         : () => 1_000,
  } );

  return {
    store, posts,
    ccRefresh : () => refreshes,
    reply     : ( v ) => { next = v; thrown = null; },
    fail      : ( e ) => { thrown = e; },
    last      : () => {
      const p = posts[ posts.length - 1 ];
      assert.notEqual( p, undefined, "no request was made" );
      return p as Post;
    },
  };
}

const NO_SCHEDULE: SchedulingInput = { scheduled: false, time: "", monopolize: false };

const CC = {
  prompt: "do the thing", project: "lupin", taskType: "BOUNDED",
  dryRun: true, scheduling: NO_SCHEDULE,
};
const RESEARCH = {
  topic: "what is a lupin", budget: "3.00", withPodcast: false,
  withPresentation: false, dryRun: true, scheduling: NO_SCHEDULE,
};
const SUITE = {
  testTypes: "integration,e2e", filePath: "", failFast: false,
  pytestArgs: "", dryRun: true, autoFix: false, scheduling: NO_SCHEDULE,
};

// ---------------------------------------------------------------------------
// Initial state — B10
// ---------------------------------------------------------------------------

test( "every card's status starts EMPTY (B10), and none is in flight", () => {
  const h = setup();
  for ( const card of [ "cc", "research", "testSuite", "tfe" ] as const ) {
    assert.equal( h.store.status( card ).text, "" );
    assert.equal( h.store.busy( card ), false );
  }
  assert.deepEqual( h.store.tfeCandidates(), [] );
} );

// ---------------------------------------------------------------------------
// The session header — J14
// ---------------------------------------------------------------------------

test( "every door carries X-Session-ID alongside the auth header", async () => {
  const h = setup();
  await h.store.submitCc( CC );
  await h.store.submitResearch( RESEARCH );
  await h.store.submitTestSuite( SUITE );
  h.reply( { status: "resumed", resumed_job_id: "tfe-1", source_type: "job_id", phase_name: "p" } );
  await h.store.submitTfeResume( "tfe-1" );

  assert.equal( h.posts.length, 4 );
  for ( const p of h.posts ) {
    assert.deepEqual( p.headers, { "X-Session-ID": "wise penguin" }, `missing on ${p.path}` );
  }
} );

// ---------------------------------------------------------------------------
// Card 1 — Claude Code
// ---------------------------------------------------------------------------

test( "CC posts the v2 door with its args inside `args` and its directives top-level", async () => {
  const h = setup();
  await h.store.submitCc( CC );

  const p = h.last();
  assert.equal( p.path, "/api/v2/submit" );
  assert.equal( p.body.command, "agent router go to claude code" );
  assert.deepEqual( p.body.args, {
    prompt: "do the thing", project: "lupin", task_type: "BOUNDED",
    max_turns: 50, dry_run: true,
  } );
  // 🔴 websocket_id is the QUEUE session id. Legacy's CC card sends `this.sessionId`,
  // a field never assigned, so the key drops out of the JSON entirely and the server
  // falls back to api-<uid>. §6a ruling 13 (Rick, 2026-09-19): a defect in the lead,
  // NOT back-ported.
  assert.equal( p.body.websocket_id, "wise penguin" );
  assert.equal( p.body.question, "do the thing" );
} );

test( "CC sends max_turns 200 for INTERACTIVE and 50 otherwise", async () => {
  const h = setup();
  await h.store.submitCc( { ...CC, taskType: "INTERACTIVE" } );
  assert.equal( ( h.last().body.args as Record<string, unknown> ).max_turns, 200 );

  await h.store.submitCc( { ...CC, taskType: "BOUNDED" } );
  assert.equal( ( h.last().body.args as Record<string, unknown> ).max_turns, 50 );
} );

test( "an empty CC prompt is refused in red with NO request", async () => {
  const h = setup();
  assert.equal( await h.store.submitCc( { ...CC, prompt: "   " } ), false );
  assert.deepEqual( h.posts, [] );
  assert.deepEqual( h.store.status( "cc" ), {
    text: "⚠️ Please enter a task prompt.", color: "#dc3545",
  } );
} );

test( "CC's success line names the job id and NO queue position (deliberate)", async () => {
  // The v2 response carries no queue_position and is not being widened for one: a
  // place in the queue is stale the moment it is printed. The test-suite card, on a
  // different door, DOES print one — see below.
  const h = setup();
  h.reply( { job_id: "cc-42", queue_position: 7 } );
  await h.store.submitCc( CC );

  assert.equal( h.store.status( "cc" ).text, "✓ Claude Code job submitted! Job ID: cc-42" );
  assert.equal( h.store.status( "cc" ).color, "#28a745" );
  assert.doesNotMatch( h.store.status( "cc" ).text, /Position/ );
} );

test( "🔴 ONLY the CC card refreshes the queues on success (B8)", async () => {
  const h = setup();
  await h.store.submitCc( CC );
  assert.equal( h.ccRefresh(), 1 );

  await h.store.submitResearch( RESEARCH );
  await h.store.submitTestSuite( SUITE );
  h.reply( { status: "resumed", resumed_job_id: "t", source_type: "s", phase_name: "p" } );
  await h.store.submitTfeResume( "t" );
  assert.equal( h.ccRefresh(), 1, "no sibling card may refresh the queues" );
} );

test( "a FAILED CC submit does not refresh the queues", async () => {
  const h = setup();
  h.fail( new Error( "HTTP 500" ) );
  assert.equal( await h.store.submitCc( CC ), false );
  assert.equal( h.ccRefresh(), 0 );
  assert.equal( h.store.status( "cc" ).text, "✗ Error: HTTP 500" );
} );

// ---------------------------------------------------------------------------
// Card 2 — Research
// ---------------------------------------------------------------------------

test( "research with neither box posts the plain command and no extra arg", async () => {
  const h = setup();
  await h.store.submitResearch( RESEARCH );

  const p = h.last();
  assert.equal( p.path, "/api/v2/submit" );
  assert.equal( p.body.command, "agent router go to deep research" );
  assert.deepEqual( p.body.args, { query: "what is a lupin", budget: 3, dry_run: true } );
} );

test( "the podcast box picks the podcast COMMAND and adds the languages arg", async () => {
  const h = setup();
  await h.store.submitResearch( { ...RESEARCH, withPodcast: true } );

  const p = h.last();
  assert.equal( p.body.command, "agent router go to research to podcast" );
  assert.deepEqual( ( p.body.args as Record<string, unknown> ).target_languages, [ "en", "es-MX" ] );
  assert.equal( h.store.status( "research" ).text, "✓ Research→Podcast job submitted! Job ID: job-1" );
} );

test( "the presentation box picks its command and adds the duration arg", async () => {
  const h = setup();
  await h.store.submitResearch( { ...RESEARCH, withPresentation: true } );

  const p = h.last();
  assert.equal( p.body.command, "agent router go to research to presentation" );
  assert.equal( ( p.body.args as Record<string, unknown> ).target_duration_minutes, 15 );
  assert.equal( h.store.status( "research" ).text, "✓ Research→Presentation job submitted! Job ID: job-1" );
} );

test( "with BOTH boxes set, the command and the arg agree with each other", async () => {
  // ⚠️ LEGACY DOES NOT. Its command chain tests presentation first while its args
  // chain tests podcast first, so both-ticked sends the PRESENTATION command carrying
  // the PODCAST's languages argument. Not reproduced: the renderer makes the boxes
  // mutually exclusive (J11), so both-ticked is unreachable for an operator and
  // copying the mismatch would be importing a bug, not parity.
  const h = setup();
  await h.store.submitResearch( { ...RESEARCH, withPodcast: true, withPresentation: true } );

  const p = h.last();
  assert.equal( p.body.command, "agent router go to research to presentation" );
  const args = p.body.args as Record<string, unknown>;
  assert.equal( args.target_duration_minutes, 15 );
  assert.equal( "target_languages" in args, false );
} );

test( "the budget parses, and falls back to 3.00 on anything unparseable", async () => {
  const h = setup();
  for ( const [ raw, expected ] of [
    [ "7.50", 7.5 ], [ "0.50", 0.5 ], [ "", 3 ], [ "abc", 3 ], [ "0", 3 ],
  ] as ReadonlyArray<readonly [ string, number ]> ) {
    await h.store.submitResearch( { ...RESEARCH, budget: raw } );
    assert.equal(
      ( h.last().body.args as Record<string, unknown> ).budget, expected,
      `budget ${JSON.stringify( raw )}`,
    );
  }
} );

test( "an empty research topic is refused in red with no request", async () => {
  const h = setup();
  assert.equal( await h.store.submitResearch( { ...RESEARCH, topic: "  " } ), false );
  assert.deepEqual( h.posts, [] );
  assert.equal( h.store.status( "research" ).text, "⚠️ Please enter a research topic." );
} );

test( "research reports TRUE on success — the caller clears the topic, which CC does not", async () => {
  const h = setup();
  assert.equal( await h.store.submitResearch( RESEARCH ), true );
} );

// ---------------------------------------------------------------------------
// Card 3 — Test Suite
// ---------------------------------------------------------------------------

test( "the test-suite card posts its OWN door, not the v2 one", async () => {
  const h = setup();
  await h.store.submitTestSuite( SUITE );
  assert.equal( h.last().path, "/api/test-suite/submit" );
} );

test( "🔴 and its success line DOES print the queue position", async () => {
  const h = setup();
  h.reply( { job_id: "ts-9", queue_position: 4 } );
  await h.store.submitTestSuite( SUITE );
  assert.equal(
    h.store.status( "testSuite" ).text,
    "✓ Test suite job submitted! Job ID: ts-9, Position: 4",
  );
} );

test( "a file-driven type with no path is refused with legacy's exact sentence", async () => {
  const h = setup();
  for ( const t of FILE_DRIVEN_TEST_TYPES ) {
    assert.equal( await h.store.submitTestSuite( { ...SUITE, testTypes: t } ), false );
    assert.equal( h.store.status( "testSuite" ).text, `✗ Error: ${t} requires a test file path` );
  }
  assert.deepEqual( h.posts, [], "the refusal must happen before any request" );
} );

test( "a NON-file-driven type needs no path", async () => {
  // The positive control for the refusal above: without it, a validator that refused
  // everything would pass that test.
  const h = setup();
  assert.equal( await h.store.submitTestSuite( { ...SUITE, testTypes: "unit" } ), true );
  assert.equal( h.posts.length, 1 );
} );

test( "the file path is PREPENDED and --fail-fast APPENDED, in that order", async () => {
  const h = setup();
  await h.store.submitTestSuite( {
    ...SUITE, testTypes: "pytest_direct", filePath: "src/tests/x.py", pytestArgs: "-v -k auth",
  } );
  assert.equal( h.last().body.pytest_args, "src/tests/x.py -v -k auth" );

  await h.store.submitTestSuite( { ...SUITE, testTypes: "all", failFast: true, pytestArgs: "-v" } );
  assert.equal( h.last().body.pytest_args, "-v --fail-fast" );
} );

test( "a file-driven type with no other args sends just the path", async () => {
  const h = setup();
  await h.store.submitTestSuite( { ...SUITE, testTypes: "smoke_direct", filePath: "src/tests/y.py" } );
  assert.equal( h.last().body.pytest_args, "src/tests/y.py" );
} );

test( "'all' with fail-fast and no other args sends just the flag", async () => {
  const h = setup();
  await h.store.submitTestSuite( { ...SUITE, testTypes: "all", failFast: true } );
  assert.equal( h.last().body.pytest_args, "--fail-fast" );
} );

test( "--fail-fast rides ONLY when the type is exactly 'all'", async () => {
  const h = setup();
  await h.store.submitTestSuite( { ...SUITE, testTypes: "unit", failFast: true, pytestArgs: "-v" } );
  assert.equal( h.last().body.pytest_args, "-v" );
} );

test( "empty pytest args are OMITTED from the body rather than sent empty", async () => {
  const h = setup();
  await h.store.submitTestSuite( SUITE );
  assert.equal( "pytest_args" in h.last().body, false );
} );

test( "the auto-fix override always rides, in both positions", async () => {
  const h = setup();
  await h.store.submitTestSuite( { ...SUITE, autoFix: true } );
  assert.equal( h.last().body.auto_fix_on_failure, true );
  await h.store.submitTestSuite( { ...SUITE, autoFix: false } );
  assert.equal( h.last().body.auto_fix_on_failure, false );
} );

test( "the test-suite body never carries monopolize — it is always-on server-side", async () => {
  const h = setup();
  await h.store.submitTestSuite( {
    ...SUITE, scheduling: { scheduled: true, time: "2026-10-01T11:00", monopolize: true },
  } );
  assert.equal( "monopolize" in h.last().body, false );
  assert.equal( typeof h.last().body.scheduled_at, "string" );
} );

// ---------------------------------------------------------------------------
// Card 4 — TFE resume
// ---------------------------------------------------------------------------

test( "TFE posts the expediter door with the raw text", async () => {
  const h = setup();
  h.reply( { status: "resumed", resumed_job_id: "tfe-7", source_type: "job_id", phase_name: "phase two" } );
  assert.equal( await h.store.submitTfeResume( "  tfe-7  " ), true );

  const p = h.last();
  assert.equal( p.path, "/api/test-fix-expediter/resume-from" );
  assert.deepEqual( p.body, { resume_from: "tfe-7" } );
  assert.equal( h.store.status( "tfe" ).text, "✓ Resumed via job_id: tfe-7 from phase two" );
} );

test( "a resumed response with no phase NAME falls back to the phase number", async () => {
  const h = setup();
  h.reply( { status: "resumed", resumed_job_id: "tfe-8", source_type: "plan", resume_from_phase: 3 } );
  await h.store.submitTfeResume( "x" );
  assert.equal( h.store.status( "tfe" ).text, "✓ Resumed via plan: tfe-8 from phase 3" );
} );

test( "a resumed response with no source type reads 'unknown'", async () => {
  const h = setup();
  h.reply( { status: "resumed", resumed_job_id: "tfe-9", phase_name: "p" } );
  await h.store.submitTfeResume( "x" );
  assert.equal( h.store.status( "tfe" ).text, "✓ Resumed via unknown: tfe-9 from p" );
} );

test( "🔴 'ambiguous' publishes the candidates and is NOT a success", async () => {
  // The input must survive it — the operator has to pick one or retype.
  const h = setup();
  h.reply( { status: "ambiguous", candidates: [
    { job_id: "a", confidence: 0.9 }, { job_id: "b", confidence: 0.4 },
  ] } );

  assert.equal( await h.store.submitTfeResume( "the stalled one" ), false );
  assert.equal( h.store.tfeCandidates().length, 2 );
  assert.equal( h.store.status( "tfe" ).text, "Found 2 possible matches — pick one." );
} );

test( "an ambiguous response with no candidates array reads as zero matches", async () => {
  const h = setup();
  h.reply( { status: "ambiguous" } );
  await h.store.submitTfeResume( "x" );
  assert.deepEqual( h.store.tfeCandidates(), [] );
  assert.equal( h.store.status( "tfe" ).text, "Found 0 possible matches — pick one." );
} );

test( "a second submit CLEARS the previous candidate list before asking", async () => {
  const h = setup();
  h.reply( { status: "ambiguous", candidates: [ { job_id: "a" } ] } );
  await h.store.submitTfeResume( "vague" );
  assert.equal( h.store.tfeCandidates().length, 1 );

  h.reply( { status: "resumed", resumed_job_id: "a", source_type: "job_id", phase_name: "p" } );
  await h.store.submitTfeResume( "a" );
  assert.deepEqual( h.store.tfeCandidates(), [], "a stale list under a fresh answer is a dead menu" );
} );

test( "an empty TFE input asks for nothing — the ALERT is the renderer's, not the store's", async () => {
  // Legacy raises a browser alert() here, the one refusal in the four cards that is
  // not an inline status. A store that called alert() could not be unit-tested
  // without a DOM, so the divergence lives at the seam where it is visible.
  const h = setup();
  assert.equal( await h.store.submitTfeResume( "   " ), false );
  assert.deepEqual( h.posts, [] );
  assert.equal( h.store.status( "tfe" ).text, "" );
} );

test( "an unrecognised TFE status claims no outcome", async () => {
  const h = setup();
  h.reply( { status: "something_new" } );
  assert.equal( await h.store.submitTfeResume( "x" ), false );
  assert.deepEqual( h.store.tfeCandidates(), [] );
} );

test( "the TFE error line is '✗ <message>' — NOT the siblings' '✗ Error: <message>'", async () => {
  const h = setup();
  h.fail( new Error( "HTTP 404" ) );
  await h.store.submitTfeResume( "x" );
  assert.equal( h.store.status( "tfe" ).text, "✗ HTTP 404" );

  h.fail( new Error( "HTTP 404" ) );
  await h.store.submitTestSuite( SUITE );
  assert.equal( h.store.status( "testSuite" ).text, "✗ Error: HTTP 404" );
} );

test( "a thrown non-Error still produces a readable status", async () => {
  const h = setup();
  h.fail( "kaboom" );
  await h.store.submitCc( CC );
  assert.equal( h.store.status( "cc" ).text, "✗ Error: kaboom" );
} );

// ---------------------------------------------------------------------------
// Scheduling — shared, and its two halves
// ---------------------------------------------------------------------------

test( "scheduled_at rides only when the box AND the time are both set", async () => {
  const h = setup();
  for ( const s of [
    { scheduled: false, time: "2026-10-01T11:00" },
    { scheduled: true,  time: "" },
    { scheduled: false, time: "" },
  ] as SchedulingInput[] ) {
    await h.store.submitCc( { ...CC, scheduling: s } );
    assert.equal( "scheduled_at" in h.last().body, false,
      "a half-filled form must not give a job a time nobody chose" );
  }

  await h.store.submitCc( { ...CC, scheduling: { scheduled: true, time: "2026-10-01T11:00" } } );
  assert.equal( h.last().body.scheduled_at, new Date( "2026-10-01T11:00" ).toISOString() );
} );

test( "monopolize rides only when ticked, and only as a top-level directive", async () => {
  const h = setup();
  await h.store.submitCc( { ...CC, scheduling: { scheduled: false, time: "", monopolize: true } } );
  assert.equal( h.last().body.monopolize, true );
  assert.equal( "monopolize" in ( h.last().body.args as Record<string, unknown> ), false );

  await h.store.submitCc( CC );
  assert.equal( "monopolize" in h.last().body, false );
} );

// ---------------------------------------------------------------------------
// In-flight, and the auto-fix default
// ---------------------------------------------------------------------------

test( "a card is busy for the duration of its own submit and no sibling is", async () => {
  const h = setup();
  const seen: Array<Record<string, boolean>> = [];
  const store = createSubmitJobsStore( {
    bus : createEventBusForTesting(),
    api : { post: async <T>(): Promise<T> => {
      seen.push( {
        cc: store.busy( "cc" ), research: store.busy( "research" ),
        testSuite: store.busy( "testSuite" ), tfe: store.busy( "tfe" ),
      } );
      return { job_id: "x" } as T;
    } },
    sessionId : () => "s",
    nowFn     : () => 0,
  } );

  await store.submitResearch( RESEARCH );
  assert.deepEqual( seen, [ { cc: false, research: true, testSuite: false, tfe: false } ] );
  assert.equal( store.busy( "research" ), false, "released after" );
} );

test( "the in-flight flag is released even when the request throws", async () => {
  const h = setup();
  h.fail( new Error( "boom" ) );
  await h.store.submitCc( CC );
  assert.equal( h.store.busy( "cc" ), false );
} );

test( "the auto-fix default comes from the INI and emits only on a real change", () => {
  const bus = createEventBusForTesting();
  let changes = 0;
  bus.on( "store_submit_jobs_changed", () => { changes += 1; } );
  const store = createSubmitJobsStore( {
    bus, api: { post: async <T>(): Promise<T> => ( {} as T ) },
    sessionId: () => "s", nowFn: () => 0,
  } );

  assert.equal( store.autoFixDefault(), false, "unchecked until the config says otherwise" );
  store.setAutoFixDefault( true );
  assert.equal( store.autoFixDefault(), true );
  assert.equal( changes, 1 );

  store.setAutoFixDefault( true );
  assert.equal( changes, 1, "an identical write is not a change" );
} );
