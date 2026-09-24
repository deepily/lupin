// Parity B-1 — QaPaneRenderer + qaChrome unit tests.
//
// LEGACY UNDER TEST, by symbol and by the markup it mirrors:
//   notifications.html  #section-qa            — the section, its header and its chevron
//   notifications.html  #agent-mode            — the select that ships EMPTY, deliberately
//   notifications.html  #tts-mode              — the two options, markup, `instant` selected
//   notifications.html  #response-text         — "No response yet..."
//   notifications.html  #qa-metrics            — hidden until a stamp lands
//   notifications.js    submitQA               — the button and Enter are one door
//   notifications.js    updateModeUI           — the badge shows; the SELECT is not touched
//   notifications.js    handleQASTTButtonClick — the 🎤 delegates to the shared recorder
//
// 100% lines/branches/functions on QaPaneRenderer.ts and templates/qaChrome.ts.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/qa_pane_renderer.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createQaPaneRenderer,
  type QaPaneRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render/QaPaneRenderer";
import { renderQaChrome } from "../../../../lupin_app/static/js/multiplexer/render/templates/qaChrome";
import type {
  QaStore,
  QaMetrics,
  QaModeStatus,
  QaInterview,
  QaAgentsPayload,
} from "../../../../lupin_app/static/js/multiplexer/stores/QaStore";
import type { TtsMode } from "../../../../lupin_app/static/js/multiplexer/stores/AudioStore";
import type { StoreQaChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

const AGENTS: QaAgentsPayload = {
  auto_route : { value: "auto", label: "Auto-Route", description: "route it" },
  agents     : [
    { command: "agent router go to math", display_name: "Math", cls: "MathAgent",
      user_initiable: true, required_args: [ "question" ] },
  ],
};

interface FakeQa extends QaStore {
  // what the pane asked for
  submits        : Array<{ text: string; chosen: string | null }>;
  answers        : string[];
  selections     : Array<{ value: string | null; label: string | null }>;
  clearCalls     : number;
  loadAgentCalls : number;
  loadVoiceCalls : number;
  // what the pane is told
  setAgents    : ( p: QaAgentsPayload | null ) => void;
  setStatus    : ( s: QaModeStatus ) => void;
  setVoice     : ( v: string | null ) => void;
  setBusy      : ( b: boolean ) => void;
  setResponse  : ( r: string ) => void;
  setInterview : ( q: QaInterview | null ) => void;
  setMetrics   : ( m: QaMetrics ) => void;
  /** The value `submit()` returns — "was the question accepted AND answered". */
  submitResult : boolean;
}

function makeQa(): FakeQa {
  let agents   : QaAgentsPayload | null = null;
  let status   : QaModeStatus = { text: "Auto-routing enabled", color: "#6c757d" };
  let voice    : string | null = null;
  let busy     = false;
  let response = "No response yet...";
  let question : QaInterview | null = null;
  let metrics  : QaMetrics = { ttt: null, ttfa: null, rtt: null };

  const qa: FakeQa = {
    submits: [], answers: [], selections: [],
    clearCalls: 0, loadAgentCalls: 0, loadVoiceCalls: 0,
    submitResult: true,

    agentsPayload  : () => agents,
    modeStatus     : () => status,
    voiceModeLabel : () => voice,
    submitting     : () => busy,
    responseText   : () => response,
    interview      : () => question,
    metrics        : () => metrics,

    loadAgents        : async (): Promise<void> => { qa.loadAgentCalls += 1; },
    loadVoiceMode     : async (): Promise<void> => { qa.loadVoiceCalls += 1; },
    clearVoiceMode    : async (): Promise<void> => { qa.clearCalls += 1; },
    noteAgentSelected : ( value, label ): void => { qa.selections.push( { value, label } ); },
    submit            : async ( text, chosen ): Promise<boolean> => {
      qa.submits.push( { text, chosen } );
      return qa.submitResult;
    },
    answerInterview   : async ( answer ): Promise<void> => { qa.answers.push( answer ); },
    noteTtsRequested  : (): void => {},
    noteFirstAudio    : (): void => {},
    dispose           : (): void => {},

    setAgents    : ( p ) => { agents = p; },
    setStatus    : ( s ) => { status = s; },
    setVoice     : ( v ) => { voice = v; },
    setBusy      : ( b ) => { busy = b; },
    setResponse  : ( r ) => { response = r; },
    setInterview : ( q ) => { question = q; },
    setMetrics   : ( m ) => { metrics = m; },
  };
  return qa;
}

interface Harness {
  renderer : QaPaneRenderer;
  qa       : FakeQa;
  root     : HTMLElement;
  repaint  : () => void;
  modes    : TtsMode[];
  mics     : Array<{ contextId: string; button: HTMLButtonElement; input: HTMLInputElement }>;
  q        : <T extends Element>( testid: string ) => T;
}

function setup( opts: { withMic?: boolean } = {} ): Harness {
  const bus   = createEventBusForTesting();
  const qa    = makeQa();
  const modes : TtsMode[] = [];
  const mics  : Harness[ "mics" ] = [];

  const renderer = createQaPaneRenderer( {
    eventBus : bus,
    stores   : { qa, audio: { setTtsMode: ( m ) => { modes.push( m ); } } },
    ...( opts.withMic === false ? {} : {
      micHandler : ( contextId, button, input ) => { mics.push( { contextId, button, input } ); },
    } ),
  } );

  const root = document.createElement( "section" );
  document.body.replaceChildren( root );
  renderer.mount( root );

  return {
    renderer, qa, root, modes, mics,
    repaint : () => bus.emit<StoreQaChangedPayload>( {
      type: "store_qa_changed", payload: {}, source: "test", ts: 0,
    } ),
    q : <T extends Element>( testid: string ): T => {
      const el = root.querySelector( `[data-testid="${testid}"]` );
      assert.notEqual( el, null, `missing [data-testid="${testid}"]` );
      return el as T;
    },
  };
}

// ---------------------------------------------------------------------------
// The section contract — B1, B2, B3, B7, B10
// ---------------------------------------------------------------------------

test( "the pane renders the ❓ header and the body, and starts OPEN (B1, B7)", () => {
  const h = setup();
  const header = h.q<HTMLElement>( "multiplexer-qa-header" );
  assert.match( header.querySelector( "h3" )?.textContent ?? "", /❓ Q&A Interface/ );
  // B7 — a static header: no count text, no actions beside the chevron.
  assert.equal( header.querySelector( ".section-header-count" )?.textContent, "" );
  assert.equal( header.querySelectorAll( ".section-header-actions > *" ).length, 1 );
  // B1 — open: no collapsed marker on the root, chevron down.
  assert.equal( h.root.getAttribute( "data-collapsed" ), null );
  assert.equal( header.querySelector( ".toggle-button" )?.textContent, "▼" );
  h.renderer.unmount();
} );

test( "a header click toggles the section and flips the chevron (B2)", () => {
  const h = setup();
  const header = h.q<HTMLElement>( "multiplexer-qa-header" );
  const toggle = header.querySelector( ".toggle-button" ) as HTMLElement;

  header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( h.root.getAttribute( "data-collapsed" ), "true" );
  assert.equal( toggle.textContent, "▶" );

  toggle.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( h.root.getAttribute( "data-collapsed" ), "false" );
  assert.equal( toggle.textContent, "▼" );
  h.renderer.unmount();
} );

test( "the body carries .section-content so the shared collapse rule can hide it (B3)", () => {
  const h = setup();
  assert.ok( h.q<HTMLElement>( "multiplexer-qa-body" ).classList.contains( "section-content" ) );
  h.renderer.unmount();
} );

test( "the response pane starts on legacy's empty string (B10)", () => {
  const h = setup();
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-response-text" ).textContent, "No response yet..." );
  h.renderer.unmount();
} );

test( "mounting twice throws rather than painting a second subtree", () => {
  const h = setup();
  assert.throws( () => h.renderer.mount( document.createElement( "div" ) ), /already mounted/ );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Q1 — the agent select
// ---------------------------------------------------------------------------

test( "the agent select ships EMPTY — every option comes from the server", () => {
  // Legacy's markup carries a long comment and a python guard saying so; a
  // hand-written option would be a short mode key /api/v2/submit cannot route.
  const els = renderQaChrome();
  assert.equal( els.agentSelect.options.length, 0 );
} );

test( "mount asks for the agent list and the sticky voice mode", () => {
  const h = setup();
  assert.equal( h.qa.loadAgentCalls, 1 );
  assert.equal( h.qa.loadVoiceCalls, 1 );
  h.renderer.unmount();
} );

test( "a landed payload renders the select with the sentinel selected", () => {
  const h = setup();
  h.qa.setAgents( AGENTS );
  h.repaint();

  const select = h.q<HTMLSelectElement>( "multiplexer-qa-mode-select" );
  assert.ok( select.options.length > 1 );
  assert.equal( select.value, "auto" );
  h.renderer.unmount();
} );

test( "a repaint does NOT rebuild the select — an operator's mid-selection choice survives", () => {
  const h = setup();
  h.qa.setAgents( AGENTS );
  h.repaint();
  const select = h.q<HTMLSelectElement>( "multiplexer-qa-mode-select" );
  select.value = "agent router go to math";

  h.qa.setResponse( "something else changed" );
  h.repaint();

  assert.equal( select.value, "agent router go to math" );
  h.renderer.unmount();
} );

test( "a NEW payload does rebuild the select", () => {
  const h = setup();
  h.qa.setAgents( AGENTS );
  h.repaint();
  const select = h.q<HTMLSelectElement>( "multiplexer-qa-mode-select" );
  const first = select.options.length;

  h.qa.setAgents( { auto_route: { value: "auto", label: "Auto", description: "" }, agents: [] } );
  h.repaint();
  assert.notEqual( select.options.length, first );
  h.renderer.unmount();
} );

test( "changing the select tells the store, with the chosen option's label", () => {
  const h = setup();
  h.qa.setAgents( AGENTS );
  h.repaint();
  const select = h.q<HTMLSelectElement>( "multiplexer-qa-mode-select" );
  select.value = "agent router go to math";
  select.dispatchEvent( new Event( "change" ) );

  assert.equal( h.qa.selections.length, 1 );
  assert.equal( h.qa.selections[ 0 ]?.value, "agent router go to math" );
  assert.match( h.qa.selections[ 0 ]?.label ?? "", /Math/ );
  h.renderer.unmount();
} );

test( "changing an EMPTY select reports a null label rather than throwing", () => {
  // The select is empty until the payload lands; a change fired then has no
  // selectedOption, and `selectedOptions[0]` is undefined under
  // noUncheckedIndexedAccess.
  const h = setup();
  const select = h.q<HTMLSelectElement>( "multiplexer-qa-mode-select" );
  select.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( h.qa.selections, [ { value: "", label: null } ] );
  h.renderer.unmount();
} );

test( "the status line paints the store's words and colour", () => {
  const h = setup();
  h.qa.setStatus( { text: "Agent list unavailable — HTTP 503", color: "#dc3545" } );
  h.repaint();
  const status = h.q<HTMLElement>( "multiplexer-qa-mode-status" );
  assert.equal( status.textContent, "Agent list unavailable — HTTP 503" );
  assert.match( status.style.color, /220, 53, 69|#dc3545/ );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Q2 — the voice-mode badge
// ---------------------------------------------------------------------------

test( "the badge is hidden with no sticky mode and shows its label with one", () => {
  const h = setup();
  const badge = h.q<HTMLElement>( "multiplexer-qa-mode-badge" );
  assert.equal( badge.hidden, true );

  h.qa.setVoice( "Math Mode" );
  h.repaint();
  assert.equal( badge.hidden, false );
  assert.equal( badge.textContent, "Math Mode" );
  h.renderer.unmount();
} );

test( "clicking the badge clears the voice mode and does NOT touch the select", () => {
  // The badge is the STICKY VOICE mode; the select routes the NEXT question. Legacy's
  // updateModeUI comment exists because conflating them blanked the dropdown.
  const h = setup();
  h.qa.setAgents( AGENTS );
  h.qa.setVoice( "Math Mode" );
  h.repaint();
  const select = h.q<HTMLSelectElement>( "multiplexer-qa-mode-select" );
  select.value = "agent router go to math";

  h.q<HTMLElement>( "multiplexer-qa-mode-badge" ).dispatchEvent( new Event( "click" ) );

  assert.equal( h.qa.clearCalls, 1 );
  assert.equal( select.value, "agent router go to math" );
  assert.deepEqual( h.qa.selections, [] );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Q3 — submit
// ---------------------------------------------------------------------------

test( "the button submits what was typed, with the select's value", async () => {
  const h = setup();
  h.qa.setAgents( AGENTS );
  h.repaint();
  const input = h.q<HTMLInputElement>( "multiplexer-qa-input" );
  input.value = "six by seven";

  h.q<HTMLButtonElement>( "multiplexer-qa-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await Promise.resolve();
  await Promise.resolve();

  assert.deepEqual( h.qa.submits, [ { text: "six by seven", chosen: "auto" } ] );
  assert.equal( input.value, "" );
  h.renderer.unmount();
} );

test( "Enter in the input is the same door as the button", async () => {
  const h = setup();
  const input = h.q<HTMLInputElement>( "multiplexer-qa-input" );
  input.value = "via enter";
  input.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", cancelable: true } ) );
  await Promise.resolve();
  await Promise.resolve();

  assert.equal( h.qa.submits.length, 1 );
  assert.equal( h.qa.submits[ 0 ]?.text, "via enter" );
  h.renderer.unmount();
} );

test( "another key in the input submits nothing", async () => {
  const h = setup();
  const input = h.q<HTMLInputElement>( "multiplexer-qa-input" );
  input.value = "still typing";
  input.dispatchEvent( new KeyboardEvent( "keydown", { key: "a", cancelable: true } ) );
  await Promise.resolve();

  assert.deepEqual( h.qa.submits, [] );
  assert.equal( input.value, "still typing" );
  h.renderer.unmount();
} );

test( "a submit that was NOT answered leaves the operator's words where they typed them", async () => {
  // Two different outcomes share this path and both must keep the text: a REFUSAL
  // (empty, debounced, already in flight) and a FAILED request. Legacy clears inside
  // its try, after the response lands, and never in its catch — so a 500 leaves the
  // question in the box to retry (review finding, María 🌸). Clearing on "a submit
  // was attempted" silently eats a question that was never answered.
  const h = setup();
  h.qa.submitResult = false;
  const input = h.q<HTMLInputElement>( "multiplexer-qa-input" );
  input.value = "too soon";

  h.q<HTMLButtonElement>( "multiplexer-qa-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await Promise.resolve();
  await Promise.resolve();

  assert.equal( input.value, "too soon" );
  h.renderer.unmount();
} );

test( "the in-flight pair: the button disables and the spinner shows, then both release", () => {
  const h = setup();
  const button  = h.q<HTMLButtonElement>( "multiplexer-qa-submit-btn" );
  const spinner = h.q<HTMLElement>( "multiplexer-qa-submit-loading" );
  assert.equal( button.disabled, false );
  assert.equal( spinner.hidden, true );

  h.qa.setBusy( true );
  h.repaint();
  assert.equal( button.disabled, true );
  assert.equal( spinner.hidden, false );

  h.qa.setBusy( false );
  h.repaint();
  assert.equal( button.disabled, false );
  assert.equal( spinner.hidden, true );
  h.renderer.unmount();
} );

test( "the response pane repaints from the store", () => {
  const h = setup();
  h.qa.setResponse( "Job completed: 42" );
  h.repaint();
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-response-text" ).textContent, "Job completed: 42" );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Q4 — the inline interview
// ---------------------------------------------------------------------------

const QUESTION: QaInterview = {
  result : { path: "needs_input", status: "parked", answer: "Which repo?", pending_id: "pend-1" },
};

test( "an outstanding question renders exactly one answer box, and it takes focus", () => {
  const h = setup();
  h.qa.setInterview( QUESTION );
  h.repaint();

  const box = h.q<HTMLElement>( "multiplexer-qa-arg-interview" );
  assert.equal( box.hidden, false );
  assert.equal( box.querySelectorAll( "input" ).length, 1 );
  assert.equal( document.activeElement, box.querySelector( "input" ) );
  h.renderer.unmount();
} );

test( "the box is rebuilt per QUESTION, not per paint — typing survives a repaint", () => {
  const h = setup();
  h.qa.setInterview( QUESTION );
  h.repaint();
  const input = h.q<HTMLElement>( "multiplexer-qa-arg-interview" ).querySelector( "input" ) as HTMLInputElement;
  input.value = "half-typed";

  h.qa.setResponse( "unrelated change" );
  h.repaint();

  assert.equal( input.value, "half-typed" );
  h.renderer.unmount();
} );

test( "a NEW question replaces the box rather than stacking a second one", () => {
  const h = setup();
  h.qa.setInterview( QUESTION );
  h.repaint();
  h.qa.setInterview( { result: { ...QUESTION.result, answer: "Which branch?", pending_id: "pend-2" } } );
  h.repaint();

  const box = h.q<HTMLElement>( "multiplexer-qa-arg-interview" );
  assert.equal( box.querySelectorAll( "input" ).length, 1 );
  assert.match( box.textContent ?? "", /Which branch\?/ );
  h.renderer.unmount();
} );

test( "the box's Answer button sends what was typed", async () => {
  const h = setup();
  h.qa.setInterview( QUESTION );
  h.repaint();
  const box    = h.q<HTMLElement>( "multiplexer-qa-arg-interview" );
  const input  = box.querySelector( "input" ) as HTMLInputElement;
  const button = box.querySelector( "button" ) as HTMLButtonElement;
  input.value = "lupin";

  button.dispatchEvent( new Event( "click" ) );
  await Promise.resolve();
  assert.deepEqual( h.qa.answers, [ "lupin" ] );
  h.renderer.unmount();
} );

test( "Enter in the box is the same door as its button; another key is not", async () => {
  const h = setup();
  h.qa.setInterview( QUESTION );
  h.repaint();
  const input = h.q<HTMLElement>( "multiplexer-qa-arg-interview" ).querySelector( "input" ) as HTMLInputElement;
  input.value = "lupin";

  input.dispatchEvent( new KeyboardEvent( "keydown", { key: "x", cancelable: true } ) );
  await Promise.resolve();
  assert.deepEqual( h.qa.answers, [] );

  input.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", cancelable: true } ) );
  await Promise.resolve();
  assert.deepEqual( h.qa.answers, [ "lupin" ] );
  h.renderer.unmount();
} );

test( "no outstanding question clears the container and hides it", () => {
  const h = setup();
  h.qa.setInterview( QUESTION );
  h.repaint();
  h.qa.setInterview( null );
  h.repaint();

  const box = h.q<HTMLElement>( "multiplexer-qa-arg-interview" );
  assert.equal( box.hidden, true );
  assert.equal( box.children.length, 0 );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Q5 — the mic
// ---------------------------------------------------------------------------

test( "the 🎤 hands the shared handler this pane's context, its button and its input", () => {
  const h = setup();
  const button = h.q<HTMLButtonElement>( "multiplexer-qa-stt-btn" );
  button.dispatchEvent( new Event( "click" ) );

  assert.equal( h.mics.length, 1 );
  assert.equal( h.mics[ 0 ]?.contextId, "qa-input" );
  assert.equal( h.mics[ 0 ]?.button, button );
  assert.equal( h.mics[ 0 ]?.input, h.q<HTMLInputElement>( "multiplexer-qa-input" ) );
  h.renderer.unmount();
} );

test( "the 🎤 title states the 30 s cap and the Esc cancel the shared recorder enforces", () => {
  const h = setup();
  assert.equal(
    h.q<HTMLButtonElement>( "multiplexer-qa-stt-btn" ).title,
    "Click to record (30s max, ESC to cancel)",
  );
  h.renderer.unmount();
} );

test( "with no mic handler the button does nothing rather than throwing", () => {
  const h = setup( { withMic: false } );
  h.q<HTMLButtonElement>( "multiplexer-qa-stt-btn" ).dispatchEvent( new Event( "click" ) );
  assert.deepEqual( h.mics, [] );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Q6 — the page-wide TTS mode
// ---------------------------------------------------------------------------

test( "the TTS-mode select carries legacy's two options with instant selected", () => {
  const h = setup();
  const select = h.q<HTMLSelectElement>( "multiplexer-qa-tts-mode-select" );
  assert.deepEqual(
    Array.from( select.options ).map( ( o ) => [ o.value, o.textContent ] ),
    [
      [ "instant",  "Instant (11labs Streaming)" ],
      [ "reliable", "Reliable (OpenAI Batch)" ],
    ],
  );
  assert.equal( select.value, "instant" );
  h.renderer.unmount();
} );

test( "changing it writes the mode straight through to AudioStore", () => {
  const h = setup();
  const select = h.q<HTMLSelectElement>( "multiplexer-qa-tts-mode-select" );
  select.value = "reliable";
  select.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( h.modes, [ "reliable" ] );

  select.value = "instant";
  select.dispatchEvent( new Event( "change" ) );
  assert.deepEqual( h.modes, [ "reliable", "instant" ] );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Q7 — the metrics strip
// ---------------------------------------------------------------------------

test( "the strip is hidden until a stamp lands, and every stamp reads -- until it does", () => {
  const h = setup();
  const strip = h.q<HTMLElement>( "multiplexer-qa-metrics" );
  assert.equal( strip.hidden, true );
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-metric-ttt" ).textContent, "--" );
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-metric-ttfa" ).textContent, "--" );
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-metric-rtt" ).textContent, "--" );
  h.renderer.unmount();
} );

test( "any one stamp reveals the strip; the unstamped metrics still read --", () => {
  for ( const m of [
    { ttt: 750,  ttfa: null, rtt: null },
    { ttt: null, ttfa: 400,  rtt: null },
    { ttt: null, ttfa: null, rtt: 1100 },
  ] as QaMetrics[] ) {
    const h = setup();
    h.qa.setMetrics( m );
    h.repaint();
    assert.equal( h.q<HTMLElement>( "multiplexer-qa-metrics" ).hidden, false );
    h.renderer.unmount();
  }
} );

test( "the three stamps render as milliseconds", () => {
  const h = setup();
  h.qa.setMetrics( { ttt: 750, ttfa: 400, rtt: 1100 } );
  h.repaint();
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-metric-ttt" ).textContent, "750ms" );
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-metric-ttfa" ).textContent, "400ms" );
  assert.equal( h.q<HTMLElement>( "multiplexer-qa-metric-rtt" ).textContent, "1100ms" );
  h.renderer.unmount();
} );

test( "the metric labels are legacy's", () => {
  const els = renderQaChrome();
  assert.deepEqual(
    Array.from( els.metrics.querySelectorAll( ".metric-label" ) ).map( ( e ) => e.textContent ),
    [ "TTT:", "TTFA:", "RTT:" ],
  );
} );

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

test( "unmount empties the root and stops repainting", () => {
  const h = setup();
  h.renderer.unmount();
  assert.equal( h.root.children.length, 0 );

  h.qa.setResponse( "after unmount" );
  h.repaint();          // must not throw, and must not repaint a torn-down tree
  assert.equal( h.root.children.length, 0 );
} );

test( "unmount is safe to call twice", () => {
  const h = setup();
  h.renderer.unmount();
  h.renderer.unmount();
  assert.equal( h.root.children.length, 0 );
} );
