// Parity B-2 — SubmitJobsPaneRenderer + submitJobsChrome unit tests.
//
// LEGACY UNDER TEST, by symbol and by the markup it mirrors:
//   notifications.html  #section-job-submit  — the section and its four cards
//   notifications.html  the three `.section-content collapsed` card bodies, and the
//                       FOURTH card, which has neither a chevron nor that class
//   notifications.html  #cc-project / #cc-task-type / #test-suite-types — the static lists
//   notifications.js    submitClaudeCodeToQueue / submitResearchJob /
//                       submitTestSuiteJob / submitTFEResume — the four gestures
//   notifications.js    _renderTFEResumeCandidates / _pickTFEResumeCandidate
//   notifications.js    onTestSuiteTypeChange — the two conditional rows
//
// 🔴 MOST OF THIS FILE PINS PLACES THE FOUR CARDS DIFFER. A suite that asserted one
// shape four times would stay green while the cards drifted into each other, and the
// differences ARE the parity.
//
// Run: npx tsx --test src/tests/unit/multiplexer/render/submit_jobs_pane_renderer.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createSubmitJobsPaneRenderer,
  type SubmitJobsPaneRenderer,
} from "../../../../lupin_app/static/js/multiplexer/render/SubmitJobsPaneRenderer";
import { renderSubmitJobsChrome } from "../../../../lupin_app/static/js/multiplexer/render/templates/submitJobsChrome";
import type {
  SubmitJobsStore, CardKey, CardStatus, TfeCandidate,
  CcSubmitInput, ResearchSubmitInput, TestSuiteSubmitInput,
} from "../../../../lupin_app/static/js/multiplexer/stores/SubmitJobsStore";
import type { StoreSubmitJobsChangedPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

interface FakeStore extends SubmitJobsStore {
  cc         : CcSubmitInput[];
  research   : ResearchSubmitInput[];
  testSuite  : TestSuiteSubmitInput[];
  tfe        : string[];
  setStatus  : ( card: CardKey, s: CardStatus ) => void;
  setBusy    : ( card: CardKey, b: boolean ) => void;
  setCands   : ( c: ReadonlyArray<TfeCandidate> ) => void;
  setAutoFix : ( b: boolean ) => void;
  /** What each submit resolves to. */
  results    : Record<CardKey, boolean>;
}

function makeStore(): FakeStore {
  const statuses: Record<CardKey, CardStatus> = {
    cc: { text: "", color: "#666" }, research: { text: "", color: "#666" },
    testSuite: { text: "", color: "#666" }, tfe: { text: "", color: "#666" },
  };
  const busy: Record<CardKey, boolean> = { cc: false, research: false, testSuite: false, tfe: false };
  let candidates: ReadonlyArray<TfeCandidate> = [];
  let autoFix = false;

  const s: FakeStore = {
    cc: [], research: [], testSuite: [], tfe: [],
    results: { cc: true, research: true, testSuite: true, tfe: true },

    status        : ( c ) => statuses[ c ],
    busy          : ( c ) => busy[ c ],
    tfeCandidates : () => candidates,
    autoFixDefault: () => autoFix,
    setAutoFixDefault: ( b ): void => { autoFix = b; },

    submitCc        : async ( i ): Promise<boolean> => { s.cc.push( i );        return s.results.cc; },
    submitResearch  : async ( i ): Promise<boolean> => { s.research.push( i );  return s.results.research; },
    submitTestSuite : async ( i ): Promise<boolean> => { s.testSuite.push( i ); return s.results.testSuite; },
    submitTfeResume : async ( t ): Promise<boolean> => { s.tfe.push( t );       return s.results.tfe; },

    setStatus : ( c, v ) => { statuses[ c ] = v; },
    setBusy   : ( c, b ) => { busy[ c ] = b; },
    setCands  : ( c ) => { candidates = c; },
    setAutoFix: ( b ) => { autoFix = b; },
  };
  return s;
}

interface Harness {
  renderer : SubmitJobsPaneRenderer;
  store    : FakeStore;
  root     : HTMLElement;
  repaint  : () => void;
  alerts   : string[];
  mics     : Array<{ contextId: string; button: HTMLButtonElement }>;
  q        : <T extends Element>( testid: string ) => T;
}

function setup( opts: { withMic?: boolean } = {} ): Harness {
  const bus    = createEventBusForTesting();
  const store  = makeStore();
  const alerts : string[] = [];
  const mics   : Harness[ "mics" ] = [];

  const renderer = createSubmitJobsPaneRenderer( {
    eventBus : bus,
    stores   : { submitJobs: store },
    alertFn  : ( m ) => { alerts.push( m ); },
    ...( opts.withMic === false ? {} : {
      micHandler : ( contextId, button ) => { mics.push( { contextId, button } ); },
    } ),
  } );

  const root = document.createElement( "section" );
  document.body.replaceChildren( root );
  renderer.mount( root );

  return {
    renderer, store, root, alerts, mics,
    repaint : () => bus.emit<StoreSubmitJobsChangedPayload>( {
      type: "store_submit_jobs_changed", payload: {}, source: "test", ts: 0,
    } ),
    q : <T extends Element>( testid: string ): T => {
      const el = root.querySelector( `[data-testid="${testid}"]` );
      assert.notEqual( el, null, `missing [data-testid="${testid}"]` );
      return el as T;
    },
  };
}

/** Let the click handler's promise chain settle. */
async function settle(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

// ---------------------------------------------------------------------------
// The section — B1, B2, B7, B10
// ---------------------------------------------------------------------------

test( "the pane renders the 📝 header, static, and starts open (B1, B7)", () => {
  const h = setup();
  const header = h.q<HTMLElement>( "multiplexer-submit-jobs-header" );
  assert.match( header.querySelector( "h3" )?.textContent ?? "", /📝 Submit Agentic Jobs/ );
  assert.equal( header.querySelector( ".section-header-count" )?.textContent, "" );
  assert.equal( h.root.getAttribute( "data-collapsed" ), null );
  h.renderer.unmount();
} );

test( "a header click toggles the section (B2)", () => {
  const h = setup();
  const header = h.q<HTMLElement>( "multiplexer-submit-jobs-header" );
  header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( h.root.getAttribute( "data-collapsed" ), "true" );
  h.renderer.unmount();
} );

test( "every card's status line starts EMPTY and every spinner hidden (B10)", () => {
  const h = setup();
  for ( const t of [ "cc", "research", "test-suite", "tfe-resume" ] ) {
    assert.equal( h.q<HTMLElement>( `multiplexer-${t}-submit-status` ).textContent, "" );
  }
  h.renderer.unmount();
} );

test( "mounting twice throws", () => {
  const h = setup();
  assert.throws( () => h.renderer.mount( document.createElement( "div" ) ), /already mounted/ );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// B9 — three collapsing cards, and a fourth that does not
// ---------------------------------------------------------------------------

test( "🔴 the first three cards ship COLLAPSED with a ▶; the FOURTH has no chevron and is open (B9)", () => {
  const els = renderSubmitJobsChrome();

  for ( const card of [ els.cc, els.research, els.testSuite ] ) {
    assert.ok( card.body.classList.contains( "collapsed" ), "card must start collapsed" );
    assert.equal( card.toggle.textContent, "▶" );
  }
  // The asymmetry is legacy's. A fourth chevron "for consistency" is a behaviour change.
  assert.equal( els.tfe.body.classList.contains( "collapsed" ), false );
  assert.equal( els.tfe.card.querySelector( ".toggle-button" ), null );
} );

test( "clicking a card header toggles that card and flips its chevron", () => {
  const h = setup();
  const card = h.q<HTMLElement>( "multiplexer-cc-card" );
  const body = h.q<HTMLElement>( "multiplexer-cc-card-body" );
  const toggle = card.querySelector( ".toggle-button" ) as HTMLElement;
  const header = card.querySelector( ".job-submit-card-header" ) as HTMLElement;

  header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( body.classList.contains( "collapsed" ), false );
  assert.equal( toggle.textContent, "▼" );

  header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( body.classList.contains( "collapsed" ), true );
  assert.equal( toggle.textContent, "▶" );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Card 1 — Claude Code
// ---------------------------------------------------------------------------

test( "the CC project select has legacy's three static options, lupin selected (J1)", () => {
  const h = setup();
  const sel = h.q<HTMLSelectElement>( "multiplexer-cc-project-select" );
  assert.deepEqual( Array.from( sel.options ).map( ( o ) => o.value ), [ "lupin", "cosa", "plan" ] );
  assert.equal( sel.value, "lupin" );
  h.renderer.unmount();
} );

test( "INTERACTIVE is present and DISABLED, carrying its explanation (J3)", () => {
  // Omitting it would hide that the mode exists and is coming back.
  const h = setup();
  const sel = h.q<HTMLSelectElement>( "multiplexer-cc-task-type-select" );
  const interactive = Array.from( sel.options ).find( ( o ) => o.value === "INTERACTIVE" );
  assert.notEqual( interactive, undefined );
  assert.equal( interactive?.disabled, true );
  assert.match( interactive?.title ?? "", /inject\/interrupt\/end_session/ );
  assert.equal( sel.value, "BOUNDED" );
  h.renderer.unmount();
} );

test( "the CC dry-run box is CHECKED by default (J4)", () => {
  const h = setup();
  assert.equal( h.q<HTMLInputElement>( "multiplexer-cc-dry-run-checkbox" ).checked, true );
  h.renderer.unmount();
} );

test( "the CC button submits what the card holds", async () => {
  const h = setup();
  h.q<HTMLTextAreaElement>( "multiplexer-cc-prompt-textarea" ).value = "do the thing";
  h.q<HTMLButtonElement>( "multiplexer-cc-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();

  assert.equal( h.store.cc.length, 1 );
  assert.equal( h.store.cc[ 0 ]?.prompt, "do the thing" );
  assert.equal( h.store.cc[ 0 ]?.project, "lupin" );
  assert.equal( h.store.cc[ 0 ]?.taskType, "BOUNDED" );
  assert.equal( h.store.cc[ 0 ]?.dryRun, true );
  h.renderer.unmount();
} );

test( "🔴 CC submits on Ctrl+Enter and NOT on a plain Enter (J5)", async () => {
  // A plain Enter has to put a newline in a textarea. A shared "submit on Enter"
  // helper would make a multi-line prompt impossible to type.
  const h = setup();
  const prompt = h.q<HTMLTextAreaElement>( "multiplexer-cc-prompt-textarea" );
  prompt.value = "line one";

  prompt.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", cancelable: true } ) );
  await settle();
  assert.equal( h.store.cc.length, 0, "a plain Enter must type a newline, not submit" );

  prompt.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", ctrlKey: true, cancelable: true } ) );
  await settle();
  assert.equal( h.store.cc.length, 1 );
  h.renderer.unmount();
} );

test( "another Ctrl+key in the CC prompt submits nothing", async () => {
  const h = setup();
  const prompt = h.q<HTMLTextAreaElement>( "multiplexer-cc-prompt-textarea" );
  prompt.dispatchEvent( new KeyboardEvent( "keydown", { key: "s", ctrlKey: true, cancelable: true } ) );
  await settle();
  assert.equal( h.store.cc.length, 0 );
  h.renderer.unmount();
} );

test( "🔴 a successful CC submit KEEPS the prompt (J7) — research clears, CC does not", async () => {
  const h = setup();
  const prompt = h.q<HTMLTextAreaElement>( "multiplexer-cc-prompt-textarea" );
  prompt.value = "keep me";
  h.q<HTMLButtonElement>( "multiplexer-cc-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( prompt.value, "keep me" );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Card 2 — Research
// ---------------------------------------------------------------------------

test( "the research budget input carries legacy's range and step (J10)", () => {
  const h = setup();
  const b = h.q<HTMLInputElement>( "multiplexer-research-budget-input" );
  assert.deepEqual( [ b.value, b.min, b.max, b.step ], [ "3.00", "0.50", "20.00", "0.50" ] );
  h.renderer.unmount();
} );

test( "🔴 research submits on a PLAIN Enter — a different gesture from CC's (J13)", async () => {
  const h = setup();
  const topic = h.q<HTMLInputElement>( "multiplexer-research-topic-input" );
  topic.value = "what is a lupin";
  topic.dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", cancelable: true } ) );
  await settle();
  assert.equal( h.store.research.length, 1 );
  h.renderer.unmount();
} );

test( "another key in the research topic submits nothing", async () => {
  const h = setup();
  const topic = h.q<HTMLInputElement>( "multiplexer-research-topic-input" );
  topic.dispatchEvent( new KeyboardEvent( "keydown", { key: "a", cancelable: true } ) );
  await settle();
  assert.equal( h.store.research.length, 0 );
  h.renderer.unmount();
} );

test( "🔴 a successful research submit CLEARS the topic (J15), and a failed one does not", async () => {
  const h = setup();
  const topic = h.q<HTMLInputElement>( "multiplexer-research-topic-input" );

  topic.value = "clear me";
  h.q<HTMLButtonElement>( "multiplexer-research-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( topic.value, "" );

  h.store.results.research = false;
  topic.value = "keep me";
  h.q<HTMLButtonElement>( "multiplexer-research-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( topic.value, "keep me" );
  h.renderer.unmount();
} );

test( "🔴 podcast and presentation are mutually exclusive AT RUNTIME (J11)", () => {
  // Legacy's markup lets both be ticked, and its submit path then disagrees with
  // itself about which won. Making them exclusive puts that state out of reach.
  const h = setup();
  const podcast      = h.q<HTMLInputElement>( "multiplexer-research-podcast-checkbox" );
  const presentation = h.q<HTMLInputElement>( "multiplexer-research-presentation-checkbox" );

  podcast.checked = true;
  podcast.dispatchEvent( new Event( "change" ) );
  assert.equal( presentation.checked, false );

  presentation.checked = true;
  presentation.dispatchEvent( new Event( "change" ) );
  assert.equal( podcast.checked, false );
  h.renderer.unmount();
} );

test( "UNticking one box does not tick the other", () => {
  const h = setup();
  const podcast      = h.q<HTMLInputElement>( "multiplexer-research-podcast-checkbox" );
  const presentation = h.q<HTMLInputElement>( "multiplexer-research-presentation-checkbox" );

  podcast.checked = false;
  podcast.dispatchEvent( new Event( "change" ) );
  assert.equal( presentation.checked, false );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Card 3 — Test Suite
// ---------------------------------------------------------------------------

test( "the type select has four optgroups and twelve options, integration,e2e selected (J17)", () => {
  const h = setup();
  const sel = h.q<HTMLSelectElement>( "multiplexer-test-suite-types-select" );
  assert.equal( sel.querySelectorAll( "optgroup" ).length, 4 );
  assert.equal( sel.options.length, 12 );
  assert.equal( sel.value, "integration,e2e" );
  h.renderer.unmount();
} );

test( "🔴 the two conditional rows key on TWO DIFFERENT predicates (J18)", () => {
  // The file-path row asks about membership of the file-driven set; the fail-fast row
  // asks whether the type is EXACTLY `all`. One predicate for both would be wrong for
  // every non-`all` type.
  const h = setup();
  const sel      = h.q<HTMLSelectElement>( "multiplexer-test-suite-types-select" );
  const pathRow  = h.q<HTMLElement>( "multiplexer-test-suite-file-path-row" );
  const ffRow    = h.q<HTMLElement>( "multiplexer-test-suite-fail-fast-row" );

  assert.deepEqual( [ pathRow.hidden, ffRow.hidden ], [ true, true ], "both hidden at the default type" );

  for ( const [ type, path, ff ] of [
    [ "smoke_direct",  false, true  ],
    [ "pytest_direct", false, true  ],
    [ "all",           true,  false ],
    [ "unit",          true,  true  ],
  ] as ReadonlyArray<readonly [ string, boolean, boolean ]> ) {
    sel.value = type;
    sel.dispatchEvent( new Event( "change" ) );
    assert.equal( pathRow.hidden, path, `file-path row for ${type}` );
    assert.equal( ffRow.hidden, ff, `fail-fast row for ${type}` );
  }
  h.renderer.unmount();
} );

test( "the test-suite card submits what it holds", async () => {
  const h = setup();
  const sel = h.q<HTMLSelectElement>( "multiplexer-test-suite-types-select" );
  sel.value = "pytest_direct";
  sel.dispatchEvent( new Event( "change" ) );
  h.q<HTMLInputElement>( "multiplexer-test-suite-file-path-input" ).value = "src/tests/x.py";
  h.q<HTMLInputElement>( "multiplexer-test-suite-pytest-args-input" ).value = "-v";
  h.q<HTMLButtonElement>( "multiplexer-test-suite-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();

  assert.equal( h.store.testSuite.length, 1 );
  assert.equal( h.store.testSuite[ 0 ]?.testTypes, "pytest_direct" );
  assert.equal( h.store.testSuite[ 0 ]?.filePath, "src/tests/x.py" );
  assert.equal( h.store.testSuite[ 0 ]?.pytestArgs, "-v" );
  h.renderer.unmount();
} );

test( "the test-suite schedule row has NO monopolize box — always-on server-side", () => {
  const h = setup();
  assert.equal( h.root.querySelector( '[data-testid="multiplexer-test-suite-monopolize-checkbox"]' ), null );
  // The two v2 cards DO carry one — the positive control for that absence.
  assert.notEqual( h.root.querySelector( '[data-testid="multiplexer-cc-monopolize-checkbox"]' ), null );
  assert.notEqual( h.root.querySelector( '[data-testid="multiplexer-research-monopolize-checkbox"]' ), null );
  h.renderer.unmount();
} );

test( "🔴 the auto-fix box starts UNCHECKED and follows the INI when it lands (J20)", () => {
  // A box that painted itself checked before the config resolved would be claiming a
  // setting nobody had read yet.
  const h = setup();
  const box = h.q<HTMLInputElement>( "multiplexer-test-suite-auto-fix-checkbox" );
  assert.equal( box.checked, false );

  h.store.setAutoFix( true );
  h.repaint();
  assert.equal( box.checked, true );
  h.renderer.unmount();
} );

test( "🔴 the operator's auto-fix choice SURVIVES a repaint — the INI default is not re-imposed (María 🌸, B-2 review)", () => {
  // THE BUG THIS PINS. `paint()` wrote `autoFix.checked = store.autoFixDefault()` on EVERY
  // paint, and the store emits store_submit_jobs_changed for ANY card's status or in-flight
  // change. So submitting on the CC card — a different card entirely — silently re-checked a
  // box the operator had just unchecked, and the NEXT test-suite submit then ran with
  // auto_fix_on_failure true against their explicit choice.
  //
  // ⚠️ THE ORIGINAL LINE WAS DELIBERATE AND STILL WRONG. Its comment read "written on every
  // paint rather than once, so a config arriving after mount still lands" — it was solving the
  // late-config race, and the fix has to keep solving it, which is why the test above stays.
  // Applying the default when the VALUE CHANGES does both: a late config still lands (false →
  // true is a change) and a repaint at an unchanged default touches nothing.
  const h   = setup();
  const box = h.q<HTMLInputElement>( "multiplexer-test-suite-auto-fix-checkbox" );

  h.store.setAutoFix( true );
  h.repaint();
  assert.equal( box.checked, true, "precondition: the INI default landed" );

  box.checked = false;                               // the operator unticks it
  h.store.setStatus( "cc", { text: "Submitted", color: "#0a0" } );
  h.repaint();                                       // another card's status change

  assert.equal( box.checked, false,
    "a repaint re-imposed the INI default over the operator's choice" );
  h.renderer.unmount();
} );

test( "a LATE config still lands after the operator has touched the box — the change is what applies it", () => {
  // The other side of the same rule, so the fix cannot be "never write after mount".
  const h   = setup();
  const box = h.q<HTMLInputElement>( "multiplexer-test-suite-auto-fix-checkbox" );

  box.checked = true;                                // operator ticks it before config lands
  h.store.setAutoFix( true );                        // config arrives agreeing — no change to apply
  h.repaint();
  assert.equal( box.checked, true );

  h.store.setAutoFix( false );                       // and a config that DISAGREES still lands
  h.repaint();
  assert.equal( box.checked, false, "a changed default did not reach the box" );
  h.renderer.unmount();
} );

test( "a REMOUNT re-applies the default — the cached 'already applied' does not outlive the DOM (María 🌸)", () => {
  // The cache is per-MOUNT, not per-renderer. unmount() throws the DOM away, so the next
  // mount builds a fresh box at the markup default (unchecked). A cache that survived
  // would say "true is already applied" and leave that fresh box unticked while the store
  // said true — the config silently not landing, which is the bug the on-every-paint write
  // was there to prevent in the first place.
  //
  // `paintedCandidates` directly above it is the same class of per-mount paint cache and
  // has always been reset here; this field was simply inconsistent with its own sibling.
  const h = setup();
  h.store.setAutoFix( true );
  h.repaint();
  assert.equal( h.q<HTMLInputElement>( "multiplexer-test-suite-auto-fix-checkbox" ).checked, true,
    "precondition: the default landed on the first mount" );

  h.renderer.unmount();
  h.renderer.mount( h.root );

  assert.equal( h.q<HTMLInputElement>( "multiplexer-test-suite-auto-fix-checkbox" ).checked, true,
    "the remounted box ignored a default the store still holds" );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Card 4 — TFE
// ---------------------------------------------------------------------------

test( "the TFE card has a textarea and NO voice button (J25)", () => {
  const h = setup();
  assert.notEqual( h.q<HTMLElement>( "multiplexer-tfe-resume-input" ), null );
  const card = h.q<HTMLElement>( "multiplexer-tfe-resume-card" );
  assert.equal( card.querySelector( ".stt-button" ), null );
  // Its two siblings DO have one — the positive control.
  assert.notEqual( h.root.querySelector( '[data-testid="multiplexer-cc-stt-btn"]' ), null );
  assert.notEqual( h.root.querySelector( '[data-testid="multiplexer-research-stt-btn"]' ), null );
  h.renderer.unmount();
} );

test( "🔴 an empty TFE input raises a browser ALERT, not an inline status (J26)", async () => {
  // The one refusal in the four cards that is not a status line. It is legacy's.
  const h = setup();
  h.q<HTMLButtonElement>( "multiplexer-tfe-resume-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();

  assert.deepEqual( h.alerts, [ "Enter a job ID, plan path, or description." ] );
  assert.deepEqual( h.store.tfe, [], "and nothing is asked of the server" );
  h.renderer.unmount();
} );

test( "a whitespace-only TFE input is the same case as an empty one", async () => {
  const h = setup();
  h.q<HTMLTextAreaElement>( "multiplexer-tfe-resume-input" ).value = "   ";
  h.q<HTMLButtonElement>( "multiplexer-tfe-resume-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( h.alerts.length, 1 );
  h.renderer.unmount();
} );

test( "a successful resume clears the input; an unsuccessful one keeps it (J30)", async () => {
  const h = setup();
  const input = h.q<HTMLTextAreaElement>( "multiplexer-tfe-resume-input" );

  input.value = "tfe-7";
  h.q<HTMLButtonElement>( "multiplexer-tfe-resume-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( input.value, "" );

  h.store.results.tfe = false;
  input.value = "vague";
  h.q<HTMLButtonElement>( "multiplexer-tfe-resume-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( input.value, "vague", "an ambiguous answer leaves the text to pick from" );
  h.renderer.unmount();
} );

test( "the candidate list renders confidence, id, stalled stamp, summary and reason (J28)", () => {
  const h = setup();
  h.store.setCands( [
    { job_id: "tfe-a", confidence: 0.87, stalled_at: "2026-09-20", summary: "ran out of budget", reason: "cap" },
  ] );
  h.repaint();

  const row = h.q<HTMLElement>( "multiplexer-tfe-resume-candidate" );
  assert.match( row.textContent ?? "", /87%/ );
  assert.match( row.textContent ?? "", /tfe-a/ );
  assert.match( row.textContent ?? "", /stalled 2026-09-20/ );
  assert.match( row.textContent ?? "", /ran out of budget — cap/ );
  h.renderer.unmount();
} );

test( "a missing confidence reads '?' rather than NaN%", () => {
  const h = setup();
  h.store.setCands( [ { job_id: "tfe-b" } ] );
  h.repaint();
  const row = h.q<HTMLElement>( "multiplexer-tfe-resume-candidate" );
  assert.match( row.textContent ?? "", /\?/ );
  assert.doesNotMatch( row.textContent ?? "", /NaN/ );
  h.renderer.unmount();
} );

test( "a candidate with a summary and no reason renders the summary alone", () => {
  const h = setup();
  h.store.setCands( [ { job_id: "tfe-c", summary: "just this" } ] );
  h.repaint();
  const detail = h.q<HTMLElement>( "multiplexer-tfe-resume-candidate" )
    .querySelector( ".tfe-resume-candidate-detail" );
  assert.equal( detail?.textContent, "just this" );
  h.renderer.unmount();
} );

test( "🔴 a candidate's server-supplied text goes in as TEXT, never as markup", () => {
  // Legacy string-concatenates these into innerHTML and escapes by hand; one missed
  // escape there is an injection. Building nodes removes the question.
  const h = setup();
  h.store.setCands( [ {
    job_id: "tfe-d", summary: "<img src=x onerror=alert(1)>", reason: "<script>bad()</script>",
  } ] );
  h.repaint();

  const row = h.q<HTMLElement>( "multiplexer-tfe-resume-candidate" );
  assert.equal( row.querySelector( "img" ), null );
  assert.equal( row.querySelector( "script" ), null );
  assert.match( row.textContent ?? "", /<img src=x onerror=alert\(1\)>/ );
  h.renderer.unmount();
} );

test( "clicking a candidate writes its id into the input and RE-SUBMITS (J29)", async () => {
  const h = setup();
  h.store.setCands( [ { job_id: "tfe-e" }, { job_id: "tfe-f" } ] );
  h.repaint();

  const rows = h.root.querySelectorAll( '[data-testid="multiplexer-tfe-resume-candidate"]' );
  assert.equal( rows.length, 2 );
  ( rows[ 1 ] as HTMLElement ).dispatchEvent( new Event( "click" ) );
  await settle();

  assert.deepEqual( h.store.tfe, [ "tfe-f" ] );
  h.renderer.unmount();
} );

test( "an empty candidate list hides the container", () => {
  const h = setup();
  h.store.setCands( [ { job_id: "x" } ] );
  h.repaint();
  assert.equal( h.q<HTMLElement>( "multiplexer-tfe-resume-candidates" ).hidden, false );

  h.store.setCands( [] );
  h.repaint();
  const box = h.q<HTMLElement>( "multiplexer-tfe-resume-candidates" );
  assert.equal( box.hidden, true );
  assert.equal( box.children.length, 0 );
  h.renderer.unmount();
} );

test( "the list is rebuilt only when it CHANGES — a repaint cannot drop a click", async () => {
  const h = setup();
  const cands = [ { job_id: "tfe-g" } ];
  h.store.setCands( cands );
  h.repaint();
  const first = h.q<HTMLElement>( "multiplexer-tfe-resume-candidate" );

  h.repaint();
  assert.equal( h.q<HTMLElement>( "multiplexer-tfe-resume-candidate" ), first, "same node" );
  h.renderer.unmount();
} );

// ---------------------------------------------------------------------------
// Scheduling, status painting, mics, lifecycle
// ---------------------------------------------------------------------------

test( "each schedule checkbox reveals its OWN time input and no sibling's", () => {
  const h = setup();
  const ccCheck = h.q<HTMLInputElement>( "multiplexer-cc-schedule-checkbox" );
  const ccTime  = h.q<HTMLElement>( "multiplexer-cc-scheduled-time" );
  const rsTime  = h.q<HTMLElement>( "multiplexer-research-scheduled-time" );

  assert.equal( ccTime.hidden, true );
  ccCheck.checked = true;
  ccCheck.dispatchEvent( new Event( "change" ) );
  assert.equal( ccTime.hidden, false );
  assert.equal( rsTime.hidden, true, "a sibling's row must not move" );

  ccCheck.checked = false;
  ccCheck.dispatchEvent( new Event( "change" ) );
  assert.equal( ccTime.hidden, true );
  h.renderer.unmount();
} );

test( "the scheduling pair reaches the store, monopolize included where there is one", async () => {
  const h = setup();
  const check = h.q<HTMLInputElement>( "multiplexer-cc-schedule-checkbox" );
  check.checked = true;
  check.dispatchEvent( new Event( "change" ) );
  ( h.q<HTMLInputElement>( "multiplexer-cc-scheduled-time" ) ).value = "2026-10-01T11:00";
  h.q<HTMLInputElement>( "multiplexer-cc-monopolize-checkbox" ).checked = true;
  h.q<HTMLTextAreaElement>( "multiplexer-cc-prompt-textarea" ).value = "x";
  h.q<HTMLButtonElement>( "multiplexer-cc-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();

  assert.deepEqual( h.store.cc[ 0 ]?.scheduling, {
    scheduled: true, time: "2026-10-01T11:00", monopolize: true,
  } );
  h.renderer.unmount();
} );

test( "the test-suite card's scheduling carries NO monopolize key at all", async () => {
  const h = setup();
  h.q<HTMLButtonElement>( "multiplexer-test-suite-submit-btn" ).dispatchEvent( new Event( "click" ) );
  await settle();
  assert.equal( "monopolize" in ( h.store.testSuite[ 0 ]?.scheduling ?? {} ), false );
  h.renderer.unmount();
} );

test( "each card paints its own status and its own in-flight pair", () => {
  const h = setup();
  h.store.setStatus( "research", { text: "✓ submitted", color: "#28a745" } );
  h.store.setBusy( "research", true );
  h.repaint();

  const status = h.q<HTMLElement>( "multiplexer-research-submit-status" );
  assert.equal( status.textContent, "✓ submitted" );
  assert.match( status.style.color, /40, 167, 69|#28a745/ );
  assert.equal( h.q<HTMLButtonElement>( "multiplexer-research-submit-btn" ).disabled, true );
  // A sibling must not move.
  assert.equal( h.q<HTMLButtonElement>( "multiplexer-cc-submit-btn" ).disabled, false );
  h.renderer.unmount();
} );

test( "the two mics hand the shared handler their own contexts", () => {
  const h = setup();
  h.q<HTMLButtonElement>( "multiplexer-cc-stt-btn" ).dispatchEvent( new Event( "click" ) );
  h.q<HTMLButtonElement>( "multiplexer-research-stt-btn" ).dispatchEvent( new Event( "click" ) );
  assert.deepEqual( h.mics.map( ( m ) => m.contextId ), [ "cc-prompt", "research-topic" ] );
  h.renderer.unmount();
} );

test( "with no mic handler the buttons do nothing rather than throwing", () => {
  const h = setup( { withMic: false } );
  h.q<HTMLButtonElement>( "multiplexer-cc-stt-btn" ).dispatchEvent( new Event( "click" ) );
  h.q<HTMLButtonElement>( "multiplexer-research-stt-btn" ).dispatchEvent( new Event( "click" ) );
  assert.deepEqual( h.mics, [] );
  h.renderer.unmount();
} );

test( "unmount empties the root, stops repainting, and is safe twice", () => {
  const h = setup();
  h.renderer.unmount();
  assert.equal( h.root.children.length, 0 );
  h.store.setStatus( "cc", { text: "after", color: "#000" } );
  h.repaint();
  assert.equal( h.root.children.length, 0 );
  h.renderer.unmount();
} );

test( "after unmount a card header click does nothing — the listeners are gone", () => {
  const h = setup();
  const header = h.root.querySelector( ".job-submit-card-header" ) as HTMLElement;
  h.renderer.unmount();
  header.dispatchEvent( new Event( "click", { bubbles: true } ) );
  assert.equal( h.root.children.length, 0 );
} );
