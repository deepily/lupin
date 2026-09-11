// A CLOSED RESPONSE WINDOW MUST REPORT WHAT THE SERVER RECORDED — NEVER A DEFAULT
// THE SERVER NEVER APPLIED.
//
// Row bf4f65c3. Rick ruled 2026-09-08, after a measurement corrected the question he
// had already answered once.
//
// 🔴 THE DEFECT. `handleGracePeriodExceeded` used to file
// `state.notification.response_default || '(no response)'` into conversation history as
// the OUTCOME, under a message reading "Default response was used."
//
// But a past-grace `/respond` returns 400 with `response_value` NULL and `responded_at`
// NULL — nothing is recorded server-side — and the orphan sweeper passes
// `apply_default=False` explicitly, so it applies no default either. Measured on the
// live database: of 39 orphaned response-required rows, 20 carry a `response_default`,
// and the sampled value is the string "no".
//
// ⇒ A human pressing YES on one of those twenty had "no" filed as their answer. That is
// e5f21fff — an unanswered question read as a ruling — arriving client-side, which is
// the exact defect class this epic exists to kill.
//
// ⚠️ AND IT CANNOT BE FIXED BY GUESSING THE OTHER WAY. Some paths DO apply a default
// (`mark_expired( apply_default=True )`), so hard-coding "(no response)" would be wrong
// exactly as often. The only honest source is the row itself, read back through
// GET /api/notifications/response/{id} — the same pure-read the MCP re-attach poll uses.
//
// 🔴 THIS PATH HAD NO TEST AT ALL, AND THAT WAS MEASURED, NOT ASSUMED. A fixed-string
// search for `handleGracePeriodExceeded` across every .js and .ts file in the tree
// returns exactly ONE hit: the source. Zero of the 33 notifications.js test files touch
// it. The instrument was proved first — the same search for `task-priority-select`
// returns two of those files — so the zero is a finding rather than a silence.
//
// ⇒ The mislabel could never have been caught by the suite. This file is that guard.

import { test, before, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

const HERE = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );

const NOTIFICATION_ID = "11111111-2222-3333-4444-555555555555";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const fullSource = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS }
  );
} );

const STUB_LOGIN_HEADER = "Bearer test-token";

/**
 * A UI instance with the collaborators this path uses, and nothing else stubbed.
 *
 * The token seams are stubbed and `authedFetch` is NOT: the real wrapper is what attaches
 * the credential, so it stays in the path under test (row cc899c44).
 */
function newUI(): any {
  const Ctor = ( globalThis as Record<string, unknown> ).NotificationsUI as { prototype: object };
  const ui: any = Object.create( Ctor.prototype );
  ui.debug             = false;
  ui.log               = (): void => {};
  ui.error             = (): void => {};
  ui.ensureValidToken  = async (): Promise<void> => {};
  ui.getAuthHeader     = (): string => STUB_LOGIN_HEADER;
  // The seam under inspection: what gets FILED, and with what value.
  ui.routed            = [];
  ui.routeCompletedNotification = ( notification: any, value: any, wasDefault: any ): void => {
    ui.routed.push( { notification, value, wasDefault } );
  };
  return ui;
}

let ui: any;
let realFetch: any;
let fetchCalls: string[];
let fetchAuth: Array<string | undefined>;

beforeEach( () => {
  ui         = newUI();
  fetchCalls = [];
  fetchAuth  = [];
  realFetch  = globalThis.fetch;
} );

afterEach( () => { globalThis.fetch = realFetch; } );

/**
 * Stand in for the server's pure-read endpoint, recording what was asked.
 *
 * 🔴 IT REFUSES A REQUEST WITHOUT THE CREDENTIAL, BECAUSE THE REAL ROUTE DOES. The route has
 * required one since it was born (1fa05b16), while this file's first stand-in answered
 * anyone — so it passed a client that sent a fake `?api_key=` query and got a 401 on every
 * live call, filing OUTCOME_UNKNOWN for a real recorded answer (row cc899c44).
 */
function serverSays( body: any, ok = true ): void {
  globalThis.fetch = ( ( url: string, init?: { headers?: Record<string, string> } ) => {
    fetchCalls.push( String( url ) );
    const auth = init?.headers?.Authorization;
    fetchAuth.push( auth );
    if ( auth !== STUB_LOGIN_HEADER ) return Promise.resolve( { ok: false, status: 401, json: () => Promise.resolve( {} ) } );
    return Promise.resolve( { ok, json: () => Promise.resolve( body ) } );
  } ) as any;
}

function aState(): any {
  return { notification: { id: NOTIFICATION_ID, response_default: "no", sender_id: "s" } };
}

// ---------------------------------------------------------------------------
// THE ARM THIS FILE EXISTS FOR
// ---------------------------------------------------------------------------

test( "a closed window does NOT file the response_default the server never applied", async () => {
  // The exact live shape: 20 of 39 orphans carry response_default "no", and the row
  // records nothing. Pressing anything must not become "no".
  serverSays( { state: "expired", response_value: null, responded_at: null } );
  const state = aState();

  await ui.reportGracePeriodOutcome( NOTIFICATION_ID, state );

  assert.equal( ui.routed.length, 1, "nothing was filed into history at all" );
  assert.notEqual( ui.routed[ 0 ].value, "no",
    "the client filed the row's response_default as the human's answer — the e5f21fff defect" );
  assert.equal( ui.routed[ 0 ].value, ui.NO_ANSWER_RECORDED );
} );

test( "it files the server's recorded value when there genuinely IS one", async () => {
  // 🔴 THE POSITIVE ARM. Without it, every assertion above is satisfied by a client
  // that files "(no answer was recorded)" unconditionally — which would be a second
  // way of ignoring the server, not a fix.
  serverSays( { state: "responded", response_value: "yes", responded_at: "2026-09-08T12:00:00Z" } );

  await ui.reportGracePeriodOutcome( NOTIFICATION_ID, aState() );

  assert.equal( ui.routed[ 0 ].value, "yes",
    "a real recorded answer was discarded" );
} );

test( "it asks the server about THIS notification, at the pure-read endpoint", async () => {
  // Pins WHICH call crosses the seam. Without it the method could read a different
  // row, or the wrong endpoint, and every value assertion above would still pass.
  serverSays( { state: "expired", response_value: null, responded_at: null } );

  await ui.reportGracePeriodOutcome( NOTIFICATION_ID, aState() );

  assert.equal( fetchCalls.length, 1, "the server was not consulted exactly once" );
  assert.ok( fetchCalls[ 0 ].includes( `/api/notifications/response/${NOTIFICATION_ID}` ),
    `asked the wrong thing: ${fetchCalls[ 0 ]}` );
} );

test( "the server read carries the refreshed login credential, not a query-string key", async () => {
  // Row cc899c44. The route answers 401 to anything else, so a read without this header
  // can never learn what was recorded. Its own test, so no earlier assertion carries it.
  serverSays( { state: "responded", response_value: "yes", responded_at: "2026-09-08T12:00:00Z" } );

  await ui.reportGracePeriodOutcome( NOTIFICATION_ID, aState() );

  assert.equal( fetchAuth[ 0 ], STUB_LOGIN_HEADER, "the read went out without the login credential" );
  assert.ok( !fetchCalls[ 0 ].includes( "api_key=" ), `a query-string key is still sent: ${fetchCalls[ 0 ]}` );
} );

// ---------------------------------------------------------------------------
// THE THREE OUTCOMES STAY THREE — collapsing any pair is the same defect quieter
// ---------------------------------------------------------------------------

test( "a FAILED read reports an unknown, not a fabricated absence", async () => {
  // ⚠️ "Nothing was recorded" and "I could not tell" are DIFFERENT FACTS. Reporting
  // the second as the first is reporting a guess as a measurement — one step quieter
  // than the defect this file exists for, and the same shape.
  serverSays( {}, false );

  await ui.reportGracePeriodOutcome( NOTIFICATION_ID, aState() );

  assert.equal( ui.routed[ 0 ].value, ui.OUTCOME_UNKNOWN );
  assert.notEqual( ui.routed[ 0 ].value, ui.NO_ANSWER_RECORDED,
    "an unreadable server was reported as a confirmed absence" );
} );

test( "a THROWN read still files something rather than stranding the card", async () => {
  globalThis.fetch = ( () => Promise.reject( new Error( "network down" ) ) ) as any;

  await ui.reportGracePeriodOutcome( NOTIFICATION_ID, aState() );

  assert.equal( ui.routed.length, 1,
    "a network failure left the notification filed nowhere" );
  assert.equal( ui.routed[ 0 ].value, ui.OUTCOME_UNKNOWN );
} );

test( "the two sentences are distinct, so a test cannot pass by conflating them", () => {
  assert.notEqual( ui.NO_ANSWER_RECORDED, ui.OUTCOME_UNKNOWN );
} );

// ---------------------------------------------------------------------------
// THE CALL SITE — the arm that exists because a mutation SURVIVED without it
// ---------------------------------------------------------------------------

test( "handleGracePeriodExceeded routes through the server read, not response_default", async () => {
  // 🔴 THIS ARM WAS ADDED BECAUSE THE FIRST CUT OF THIS FILE COULD NOT SEE THE DEFECT.
  // Every test above calls `reportGracePeriodOutcome` DIRECTLY. Restoring the original
  // bug verbatim at the CALL SITE — putting `response_default || '(no response)'` back
  // inside `handleGracePeriodExceeded` — left all seven GREEN, because the method they
  // exercise was still present and still correct; nothing simply called it any more.
  //
  // That is the "implemented but not installed" shape: a unit at 100% that the path
  // never reaches. This file warns about exactly that in its own header, and then
  // walked into it. The mutation arm is what caught it, not re-reading the tests.
  //
  // ⇒ So this arm drives the REAL entry point and asserts on what gets FILED.

  const state: any = aState();
  state.notification.response_default = "no";

  document.body.innerHTML = `<div id="action-required-${NOTIFICATION_ID}"></div>`;
  serverSays( { state: "expired", response_value: null, responded_at: null } );

  ui.stopCountdownTimer          = (): void => {};
  ui.updateActionRequiredCount   = (): void => {};
  ui.saveActionRequiredState     = (): void => {};
  ui.activateNextNotification    = (): void => {};
  ui.actionRequiredNotifications = new Map();
  ui.activeActionRequiredId      = null;
  ui.activeTTSItem               = null;
  ui.focusModeNotificationId     = null;
  ui.UNKNOWN_SENDER              = "unknown";

  // The handler defers its routing behind a 2s timer and an animation. Both are
  // presentation; running them immediately keeps this arm about the DATA that gets
  // filed rather than about the wait.
  const realTimeout = globalThis.setTimeout;
  globalThis.setTimeout = ( ( fn: any ) => { fn(); return 0 as any; } ) as any;
  const card = document.getElementById( `action-required-${NOTIFICATION_ID}` ) as HTMLElement;
  const realAdd = card.addEventListener.bind( card );
  card.addEventListener = ( ( ev: string, fn: any, opts: any ) => {
    if ( ev === "animationend" ) { fn(); return; }
    return realAdd( ev, fn, opts );
  } ) as any;

  try {
    ui.handleGracePeriodExceeded( NOTIFICATION_ID, state );
    // the routing is async inside the (now-immediate) timer — let it settle
    await new Promise( r => realTimeout( r, 0 ) );
  } finally {
    globalThis.setTimeout = realTimeout;
  }

  assert.equal( ui.routed.length, 1, "the closed window filed nothing into history" );
  assert.notEqual( ui.routed[ 0 ].value, "no",
    "the CALL SITE still files response_default as the human's answer, whatever the "
    + "method it should be calling does" );
  assert.equal( ui.routed[ 0 ].value, ui.NO_ANSWER_RECORDED );
} );

// ---------------------------------------------------------------------------
// The message the human READS must not claim a default either
// ---------------------------------------------------------------------------

test( "the closed-window message no longer claims a default response was used", () => {
  // Read off the source, because this string is built in a DOM branch that needs a
  // live card to reach — and the claim here is about the WORDING, which is exactly
  // what a source read can settle. A stale reassurance disarms the reader who would
  // otherwise have caught the defect.
  const source = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const shown  = source.split( "\n" ).filter(
    l => l.includes( "msgDiv.innerHTML" ) && l.includes( "Response window has closed" ) );

  assert.equal( shown.length, 1, "expected exactly one closed-window message line" );
  assert.ok( !shown[ 0 ].includes( "Default response was used" ),
    "the card still tells the reader a default was applied when usually none was" );
} );
