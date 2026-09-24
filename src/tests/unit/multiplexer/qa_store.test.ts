// Parity B-1 — QaStore unit tests.
//
// LEGACY UNDER TEST, by symbol (the manifest's standing rule 1: cite the symbol,
// never the line, because a line goes stale on the edit above it):
//   notifications.js  submitQA                 — the 2 s debounce, the two doors, the spinner pair
//   notifications.js  handleQAResult           — interview vs raw dump, and the clear-first rule
//   notifications.js  submitArgAnswer          — POST /api/v2/resume, re-entry, the box stays on error
//   notifications.js  loadAgentSelect          — the cache, and the VISIBLE failure
//   notifications.js  updateOneShotRouteStatus — the one-shot status line
//   notifications.js  updateModeUI             — the badge, and the select it must not touch
//   notifications.js  handleJobCompletion      — "Job completed: …" and the TTT stamp
//
// 100% lines/branches/functions on QaStore.ts per the coverage mandate.
//
// Run: npx tsx --test src/tests/unit/multiplexer/qa_store.test.ts

import { test } from "node:test";
import assert from "node:assert/strict";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createQaStore,
  QA_EMPTY_RESPONSE,
  type QaStore,
  type QaApiClient,
  type QaAgentsPayload,
} from "../../../lupin_app/static/js/multiplexer/stores/QaStore";
import type { TtsJobRequestPayload } from "../../../lupin_app/static/js/multiplexer/shared/types";

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

interface Call { path: string; body?: unknown }

interface FakeApi extends QaApiClient {
  calls   : Call[];
  getFn   : ( path: string ) => Promise<unknown>;
  postFn  : ( path: string, body: unknown ) => Promise<unknown>;
}

function makeApi(): FakeApi {
  const api: FakeApi = {
    calls  : [],
    getFn  : async () => ( {} ),
    postFn : async () => ( {} ),
    get    : async <T>( path: string ): Promise<T> => {
      api.calls.push( { path } );
      return await api.getFn( path ) as T;
    },
    post   : async <T>( path: string, body: unknown ): Promise<T> => {
      api.calls.push( { path, body } );
      return await api.postFn( path, body ) as T;
    },
  };
  return api;
}

// A payload whose sentinel is "auto", with one single-arg agent and one two-arg one.
const AGENTS: QaAgentsPayload = {
  auto_route : { value: "auto", label: "Auto-Route", description: "route it" },
  agents     : [
    { command: "agent router go to math", display_name: "Math", cls: "MathAgent",
      user_initiable: true, required_args: [ "question" ] },
    { command: "agent router go to research", display_name: "Research", cls: "DeepResearch",
      user_initiable: true, required_args: [ "query", "source" ] },
  ],
};

interface Harness {
  store  : QaStore;
  api    : FakeApi;
  bus    : ReturnType<typeof createEventBusForTesting>;
  ticks  : () => number;
  setNow : ( ms: number ) => void;
  changes: () => number;
}

function setup( opts: { now?: number } = {} ): Harness {
  const bus = createEventBusForTesting();
  const api = makeApi();
  let now = opts.now ?? 1_000;
  let changes = 0;
  bus.on( "store_qa_changed", () => { changes += 1; } );
  const store = createQaStore( {
    bus,
    api,
    sessionId : () => "queue-sess",
    nowFn     : () => now,
  } );
  return {
    store, api, bus,
    ticks   : () => now,
    setNow  : ( ms ) => { now = ms; },
    changes : () => changes,
  };
}

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

test( "a fresh store shows legacy's empty response and the auto-route status", () => {
  const h = setup();
  assert.equal( h.store.responseText(), QA_EMPTY_RESPONSE );
  assert.deepEqual( h.store.modeStatus(), { text: "Auto-routing enabled", color: "#6c757d" } );
  assert.equal( h.store.agentsPayload(), null );
  assert.equal( h.store.voiceModeLabel(), null );
  assert.equal( h.store.submitting(), false );
  assert.equal( h.store.interview(), null );
  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: null, rtt: null } );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// loadAgents — the cache, and the VISIBLE failure
// ---------------------------------------------------------------------------

test( "loadAgents caches the payload and asks the documented endpoint", async () => {
  const h = setup();
  h.api.getFn = async () => AGENTS;
  await h.store.loadAgents();
  assert.deepEqual( h.api.calls.map( ( c ) => c.path ), [ "/api/v2/agents" ] );
  assert.equal( h.store.agentsPayload(), AGENTS );
  assert.equal( h.store.modeStatus().text, "Auto-routing enabled" );
  h.store.dispose();
} );

test( "a failed agent load says so in red and caches NOTHING", async () => {
  // Legacy's own comment is the reason this is asserted rather than assumed: "A
  // shortened list looks exactly like a working one, and the failure that matters
  // here is a MISSING agent."
  const h = setup();
  h.api.getFn = async () => { throw new Error( "HTTP 503" ); };
  await h.store.loadAgents();
  assert.equal( h.store.agentsPayload(), null );
  assert.deepEqual( h.store.modeStatus(), {
    text  : "Agent list unavailable — HTTP 503",
    color : "#dc3545",
  } );
  h.store.dispose();
} );

test( "a thrown non-Error still produces a readable status line", async () => {
  const h = setup();
  h.api.getFn = async () => { throw "boom"; };
  await h.store.loadAgents();
  assert.equal( h.store.modeStatus().text, "Agent list unavailable — boom" );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// noteAgentSelected — the one-shot status line
// ---------------------------------------------------------------------------

test( "selecting the sentinel reads as auto-routing; selecting an agent names it, one-shot", async () => {
  const h = setup();
  h.api.getFn = async () => AGENTS;
  await h.store.loadAgents();

  h.store.noteAgentSelected( "agent router go to math", "🧮 Math" );
  assert.deepEqual( h.store.modeStatus(), {
    text  : "Next question goes to 🧮 Math",
    color : "#0d6efd",
  } );

  h.store.noteAgentSelected( "auto", "Auto-Route" );
  assert.equal( h.store.modeStatus().text, "Auto-routing enabled" );
  h.store.dispose();
} );

test( "a selection with no option label falls back to the value, and a null value to empty", async () => {
  const h = setup();
  h.api.getFn = async () => AGENTS;
  await h.store.loadAgents();

  h.store.noteAgentSelected( "agent router go to math", null );
  assert.equal( h.store.modeStatus().text, "Next question goes to agent router go to math" );
  h.store.dispose();
} );

test( "a null selection WITH a payload names nothing rather than printing 'null'", async () => {
  // A select whose value is genuinely null is not the sentinel, so it takes the
  // named-agent arm. Both fallbacks fire here, and the sentence must still read.
  const h = setup();
  h.api.getFn = async () => AGENTS;
  await h.store.loadAgents();

  h.store.noteAgentSelected( null, null );
  assert.deepEqual( h.store.modeStatus(), { text: "Next question goes to ", color: "#0d6efd" } );
  h.store.dispose();
} );

test( "with no payload every selection reads as auto-routing — an unrouted value is never posted as a command", () => {
  // isAutoRoute returns true for a missing payload, and legacy leans on exactly
  // that: "Posting an unrecognised value to /api/v2/submit as though it were a
  // command is worse than routing normally."
  const h = setup();
  h.store.noteAgentSelected( "agent router go to math", "Math" );
  assert.equal( h.store.modeStatus().text, "Auto-routing enabled" );
  h.store.dispose();
} );

test( "a null selection with no payload also reads as auto-routing", () => {
  const h = setup();
  h.store.noteAgentSelected( null, null );
  assert.equal( h.store.modeStatus().text, "Auto-routing enabled" );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// submit — the refusals
// ---------------------------------------------------------------------------

test( "an empty or whitespace-only question is refused without a request", async () => {
  const h = setup();
  assert.equal( await h.store.submit( "", "auto" ), false );
  assert.equal( await h.store.submit( "   ", "auto" ), false );
  assert.deepEqual( h.api.calls, [] );
  assert.equal( h.store.responseText(), QA_EMPTY_RESPONSE );
  h.store.dispose();
} );

test( "a second submit inside the 2 s window is refused", async () => {
  const h = setup( { now: 10_000 } );
  h.api.postFn = async () => ( { answer: "ok" } );

  assert.equal( await h.store.submit( "first", "auto" ), true );
  h.setNow( 11_999 );
  assert.equal( await h.store.submit( "second", "auto" ), false );
  assert.equal( h.api.calls.length, 1 );

  h.setNow( 12_000 );
  assert.equal( await h.store.submit( "third", "auto" ), true );
  assert.equal( h.api.calls.length, 2 );
  h.store.dispose();
} );

test( "a submit while one is already in flight is refused", async () => {
  const h = setup();
  let release: ( () => void ) | null = null;
  h.api.postFn = async () => {
    await new Promise<void>( ( resolve ) => { release = resolve; } );
    return { answer: "ok" };
  };

  const first = h.store.submit( "first", "auto" );
  // The store is in flight; the clock has not moved, but the in-flight guard is a
  // SEPARATE refusal from the debounce and this asserts that one.
  assert.equal( h.store.submitting(), true );
  const second = await h.store.submit( "second", "auto" );
  assert.equal( second, false );

  ( release as unknown as () => void )();
  await first;
  assert.equal( h.store.submitting(), false );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// submit — the two doors
// ---------------------------------------------------------------------------

test( "Auto-Route posts the ask door with the question and the queue session id", async () => {
  const h = setup();
  h.api.getFn  = async () => AGENTS;
  h.api.postFn = async () => ( { path: "done", answer: "42" } );
  await h.store.loadAgents();

  await h.store.submit( "  what is six by seven  ", "auto" );

  const post = h.api.calls[ h.api.calls.length - 1 ];
  assert.equal( post?.path, "/api/v2/ask" );
  assert.deepEqual( post?.body, { question: "what is six by seven", websocket_id: "queue-sess" } );
  h.store.dispose();
} );

test( "a named agent posts the submit door, with the args the shared module derives", async () => {
  const h = setup();
  h.api.getFn  = async () => AGENTS;
  h.api.postFn = async () => ( { path: "done", answer: "42" } );
  await h.store.loadAgents();

  await h.store.submit( "six by seven", "agent router go to math" );

  const post = h.api.calls[ h.api.calls.length - 1 ];
  assert.equal( post?.path, "/api/v2/submit" );
  assert.deepEqual( post?.body, {
    command      : "agent router go to math",
    args         : { question: "six by seven" },
    question     : "six by seven",
    websocket_id : "queue-sess",
  } );
  h.store.dispose();
} );

test( "a two-argument command sends {} rather than guessing which arg the text fills", async () => {
  const h = setup();
  h.api.getFn  = async () => AGENTS;
  h.api.postFn = async () => ( { path: "needs_input", status: "needs_input" } );
  await h.store.loadAgents();

  await h.store.submit( "something", "agent router go to research" );

  const post = h.api.calls[ h.api.calls.length - 1 ];
  assert.deepEqual( ( post?.body as { args: unknown } ).args, {} );
  h.store.dispose();
} );

test( "the in-flight pair is true during the request and false after", async () => {
  const h = setup();
  const seen: boolean[] = [];
  h.api.postFn = async () => { seen.push( h.store.submitting() ); return { answer: "ok" }; };
  await h.store.submit( "q", "auto" );
  assert.deepEqual( seen, [ true ] );
  assert.equal( h.store.submitting(), false );
  h.store.dispose();
} );

test( "a transport failure renders the error and leaves no interview box up", async () => {
  const h = setup();
  h.api.postFn = async () => { throw new Error( "HTTP 500: Internal Server Error" ); };
  assert.equal( await h.store.submit( "q", "auto" ), true );
  assert.equal( h.store.responseText(), "Error: HTTP 500: Internal Server Error" );
  assert.equal( h.store.interview(), null );
  assert.equal( h.store.submitting(), false );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// handleQAResult — the interview, and the three needs_input states
// ---------------------------------------------------------------------------

test( "an answerable needs_input becomes the outstanding question and shows the flow's prose", async () => {
  const h = setup();
  h.api.postFn = async () => ( {
    path: "needs_input", status: "parked", answer: "Which repo?",
    pending_id: "pend-1", args_missing: [ "repo" ],
  } );
  await h.store.submit( "research something", "auto" );

  assert.equal( h.store.responseText(), "Which repo?" );
  const q = h.store.interview();
  assert.notEqual( q, null );
  assert.equal( q?.result.pending_id, "pend-1" );
  h.store.dispose();
} );

test( "a needs_input with NO pending_id renders as a result, never as a dead box", async () => {
  // The submit door's non-parking refusal. A box whose submit cannot succeed is the
  // failure arg-interview.js's isAnswerable exists to prevent.
  const h = setup();
  h.api.postFn = async () => ( { path: "needs_input", status: "needs_input", answer: "need args" } );
  await h.store.submit( "q", "auto" );

  assert.equal( h.store.interview(), null );
  assert.match( h.store.responseText(), /"status": "needs_input"/ );
  h.store.dispose();
} );

test( "a terminal result CLEARS an outstanding question rather than stacking under the answer", async () => {
  const h = setup( { now: 1_000 } );
  h.api.postFn = async () => ( {
    path: "needs_input", status: "parked", answer: "Which repo?", pending_id: "pend-1",
  } );
  await h.store.submit( "q", "auto" );
  assert.notEqual( h.store.interview(), null );

  h.api.postFn = async () => ( { path: "done", answer: "all set" } );
  await h.store.answerInterview( "lupin" );

  assert.equal( h.store.interview(), null );
  assert.match( h.store.responseText(), /"answer": "all set"/ );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// answerInterview
// ---------------------------------------------------------------------------

test( "answering posts the resume door with the module's own body shape", async () => {
  const h = setup();
  h.api.postFn = async () => ( {
    path: "needs_input", status: "parked", answer: "Which repo?", pending_id: "pend-1",
  } );
  await h.store.submit( "q", "auto" );

  h.api.postFn = async () => ( { path: "done", answer: "ok" } );
  await h.store.answerInterview( "  lupin  " );

  const post = h.api.calls[ h.api.calls.length - 1 ];
  assert.equal( post?.path, "/api/v2/resume" );
  assert.deepEqual( post?.body, { pending_id: "pend-1", answer: "lupin", websocket_id: "queue-sess" } );
  h.store.dispose();
} );

test( "a blank answer is ignored rather than posted — resume 422s on one", async () => {
  const h = setup();
  h.api.postFn = async () => ( {
    path: "needs_input", status: "parked", answer: "Which repo?", pending_id: "pend-1",
  } );
  await h.store.submit( "q", "auto" );
  const before = h.api.calls.length;

  await h.store.answerInterview( "   " );
  assert.equal( h.api.calls.length, before );
  assert.notEqual( h.store.interview(), null );
  h.store.dispose();
} );

test( "an answer with no question outstanding is ignored", async () => {
  const h = setup();
  await h.store.answerInterview( "lupin" );
  assert.deepEqual( h.api.calls, [] );
  h.store.dispose();
} );

test( "a second missing argument renders as the NEXT question — the interview loops", async () => {
  const h = setup();
  h.api.postFn = async () => ( {
    path: "needs_input", status: "parked", answer: "Which repo?", pending_id: "pend-1",
  } );
  await h.store.submit( "q", "auto" );

  h.api.postFn = async () => ( {
    path: "needs_input", status: "parked", answer: "Which branch?", pending_id: "pend-2",
  } );
  await h.store.answerInterview( "lupin" );

  assert.equal( h.store.responseText(), "Which branch?" );
  assert.equal( h.store.interview()?.result.pending_id, "pend-2" );
  h.store.dispose();
} );

test( "a failed resume leaves the box UP — the pending entry is still parked server-side", async () => {
  const h = setup();
  h.api.postFn = async () => ( {
    path: "needs_input", status: "parked", answer: "Which repo?", pending_id: "pend-1",
  } );
  await h.store.submit( "q", "auto" );

  h.api.postFn = async () => { throw new Error( "HTTP 502" ); };
  await h.store.answerInterview( "lupin" );

  assert.equal( h.store.responseText(), "Error: HTTP 502" );
  assert.equal( h.store.interview()?.result.pending_id, "pend-1" );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// The voice-mode badge
// ---------------------------------------------------------------------------

test( "a sticky voice mode paints the badge with the server's display name", async () => {
  const h = setup();
  h.api.getFn = async () => ( { mode: "math", display_name: "Math Mode" } );
  await h.store.loadVoiceMode();
  assert.equal( h.store.voiceModeLabel(), "Math Mode" );
  h.store.dispose();
} );

test( "a mode with no display name falls back to the mode key", async () => {
  const h = setup();
  h.api.getFn = async () => ( { mode: "math" } );
  await h.store.loadVoiceMode();
  assert.equal( h.store.voiceModeLabel(), "math" );
  h.store.dispose();
} );

test( "'system', null and an absent mode all leave the badge hidden", async () => {
  for ( const body of [ { mode: "system" }, { mode: null }, {} ] ) {
    const h = setup();
    h.api.getFn = async () => body;
    await h.store.loadVoiceMode();
    assert.equal( h.store.voiceModeLabel(), null );
    h.store.dispose();
  }
} );

test( "a failed voice-mode read leaves the badge hidden and never throws", async () => {
  const h = setup();
  h.api.getFn = async () => { throw new Error( "HTTP 401" ); };
  await h.store.loadVoiceMode();
  assert.equal( h.store.voiceModeLabel(), null );
  h.store.dispose();
} );

test( "clearing the voice mode posts {mode: null} and repaints from the SERVER's answer", async () => {
  const h = setup();
  h.api.getFn  = async () => ( { mode: "math", display_name: "Math Mode" } );
  await h.store.loadVoiceMode();

  h.api.postFn = async () => ( { mode: "system", display_name: "System" } );
  await h.store.clearVoiceMode();

  const post = h.api.calls[ h.api.calls.length - 1 ];
  assert.equal( post?.path, "/api/mode/current" );
  assert.deepEqual( post?.body, { mode: null } );
  assert.equal( h.store.voiceModeLabel(), null );
  h.store.dispose();
} );

test( "a refused clear leaves the badge exactly as it was", async () => {
  const h = setup();
  h.api.getFn  = async () => ( { mode: "math", display_name: "Math Mode" } );
  await h.store.loadVoiceMode();

  h.api.postFn = async () => { throw new Error( "HTTP 403" ); };
  await h.store.clearVoiceMode();
  assert.equal( h.store.voiceModeLabel(), "Math Mode" );
  h.store.dispose();
} );

test( "re-reading the same voice mode emits nothing — an identical write is not a change", async () => {
  const h = setup();
  h.api.getFn = async () => ( { mode: "math", display_name: "Math Mode" } );
  await h.store.loadVoiceMode();
  const after = h.changes();
  await h.store.loadVoiceMode();
  assert.equal( h.changes(), after );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// The job-completion writer, and the metric stamps
// ---------------------------------------------------------------------------

function jobFrame( bus: ReturnType<typeof createEventBusForTesting>, payload: TtsJobRequestPayload ): void {
  bus.emit<TtsJobRequestPayload>( {
    type: "tts_job_request", payload, source: "test", ts: 0,
  } );
}

test( "a job-completion frame writes the response pane and stamps TTT from the submit", async () => {
  const h = setup( { now: 5_000 } );
  h.api.postFn = async () => ( { path: "done", answer: "queued" } );
  await h.store.submit( "q", "auto" );

  h.setNow( 5_750 );
  jobFrame( h.bus, { text: "the answer is 42" } );

  assert.equal( h.store.responseText(), "Job completed: the answer is 42" );
  assert.equal( h.store.metrics().ttt, 750 );
  h.store.dispose();
} );

test( "a frame with no text reads legacy's 'No text provided'", () => {
  const h = setup();
  jobFrame( h.bus, {} );
  assert.equal( h.store.responseText(), "Job completed: No text provided" );
  h.store.dispose();
} );

test( "an empty-string text is the same case as an absent one", () => {
  const h = setup();
  jobFrame( h.bus, { text: "" } );
  assert.equal( h.store.responseText(), "Job completed: No text provided" );
  h.store.dispose();
} );

test( "a frame arriving with NO submit behind it writes the pane and stamps nothing", () => {
  // Another client's job, or a cold reload. A stamp measured from zero would be a
  // number with no question behind it, which is worse than `--`.
  const h = setup();
  jobFrame( h.bus, { text: "someone else's job" } );
  assert.equal( h.store.responseText(), "Job completed: someone else's job" );
  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: null, rtt: null } );
  h.store.dispose();
} );

test( "TTFA measures from the TTS REQUEST and RTT from the SUBMIT — two clocks, not one", async () => {
  // Legacy updateMetricsTTFA is explicit: "audio generation only". Measured from
  // submit instead, TTFA would silently contain TTT and the two numbers would stop
  // meaning different things.
  const h = setup( { now: 2_000 } );
  h.api.postFn = async () => ( { path: "done", answer: "ok" } );
  await h.store.submit( "q", "auto" );   // submit clock starts at 2_000

  h.setNow( 2_900 );
  h.store.noteTtsRequested();            // request clock starts at 2_900
  h.setNow( 3_100 );
  h.store.noteFirstAudio();

  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: 200, rtt: 1_100 } );
  h.store.dispose();
} );

test( "first audio with no REQUEST behind it stamps RTT only, leaving TTFA at --", async () => {
  const h = setup( { now: 1_000 } );
  h.api.postFn = async () => ( { path: "done", answer: "ok" } );
  await h.store.submit( "q", "auto" );

  h.setNow( 1_500 );
  h.store.noteFirstAudio();

  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: null, rtt: 500 } );
  h.store.dispose();
} );

test( "first audio with a request but no SUBMIT stamps TTFA only", () => {
  const h = setup( { now: 1_000 } );
  h.store.noteTtsRequested();
  h.setNow( 1_250 );
  h.store.noteFirstAudio();
  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: 250, rtt: null } );
  h.store.dispose();
} );

test( "first audio with NEITHER clock started stamps nothing and emits nothing", () => {
  const h = setup();
  const before = h.changes();
  h.store.noteFirstAudio();
  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: null, rtt: null } );
  assert.equal( h.changes(), before );
  h.store.dispose();
} );

test( "a new submit clears the previous question's stamps AND its request clock", async () => {
  // The request clock must reset too: left standing, the next question's TTFA would
  // be measured from the PREVIOUS question's speech request.
  const h = setup( { now: 1_000 } );
  h.api.postFn = async () => ( { path: "done", answer: "ok" } );
  await h.store.submit( "first", "auto" );
  h.store.noteTtsRequested();
  h.setNow( 1_300 );
  h.store.noteFirstAudio();
  assert.equal( h.store.metrics().ttfa, 300 );

  h.setNow( 9_000 );
  await h.store.submit( "second", "auto" );
  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: null, rtt: null } );

  h.setNow( 9_400 );
  h.store.noteFirstAudio();
  assert.deepEqual( h.store.metrics(), { ttt: null, ttfa: null, rtt: 400 } );
  h.store.dispose();
} );

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test( "dispose releases the frame subscription", () => {
  const h = setup();
  h.store.dispose();
  jobFrame( h.bus, { text: "after dispose" } );
  assert.equal( h.store.responseText(), QA_EMPTY_RESPONSE );
} );

test( "the production clock is the default when none is injected", async () => {
  // The nowFn default is a c8-ignored production fallback; this proves the store is
  // constructible without it rather than asserting a wall-clock value.
  const bus = createEventBusForTesting();
  const api = makeApi();
  api.postFn = async () => ( { path: "done", answer: "ok" } );
  const store = createQaStore( { bus, api, sessionId: () => "s" } );
  assert.equal( await store.submit( "q", "auto" ), true );
  store.dispose();
} );

test( "the debounce window defaults to legacy's 2 s when none is injected", async () => {
  const bus = createEventBusForTesting();
  const api = makeApi();
  api.postFn = async () => ( { path: "done", answer: "ok" } );
  let now = 0;
  const store = createQaStore( { bus, api, sessionId: () => "s", nowFn: () => now } );

  assert.equal( await store.submit( "first", "auto" ), true );
  now = 1_999;
  assert.equal( await store.submit( "second", "auto" ), false );
  now = 2_000;
  assert.equal( await store.submit( "third", "auto" ), true );
  store.dispose();
} );
