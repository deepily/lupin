// BOTH clients must offer the ticket lookup — and AGREE, proven by running them.
//
// 🔴 WHY THIS FILE EXISTS. Rick's standing instruction is that every facility
// lands on the notifications client AND the multiplexer. That instruction has
// now been restated at least three times in one week, and `taskVerbs.ts` is the
// standing receipt for what it costs when nothing enforces it: the shared module
// ships a `fixed` verb, the multiplexer's hand-written list does not, so one
// client cannot offer a verb the other can (rows 507183ff and 75044ab5).
//
// 🔴 WHAT THIS FILE USED TO BE, AND WHY THAT WAS WORTHLESS. Every assertion here
// was `assert.match( readFileSync( file ), /some regex/ )` — it read the two
// clients as TEXT and checked that certain words appeared in them. Mr. Radio
// killed it in review 2026-09-09 with one sentence: it is a MENTION test, not a
// USE test. It would have stayed green through a renamed export, a private copy
// that kept the import line for show, or a classifier that returned garbage —
// and it did in fact stay green through the real 401 divergence it existed to
// catch, because both files contained all the words it was looking for.
//
// ⇒ § A HIT IS NOT A USE. The irony is exact: the sibling assertion in this very
// file already carried a comment stripper and a positive control BECAUSE a grep
// had once matched a warning comment — the lesson was written down here, in this
// file, and the other six tests went on measuring mentions anyway.
//
// ⇒ SO THIS FILE NOW EXECUTES BOTH CLIENTS. It drives the real
// `renderTaskLookupBox` against a spy fetcher and the real `lookupTaskByRef` /
// `describeTaskLookup` off notifications.js against a spy transport, feeds both
// the SAME inputs, and compares what they actually do. A drift now has to
// survive both implementations producing identical observable behaviour, which
// is a far harder thing to fake than a matching substring.
//
// ⚠️ THE THREE TEXT ASSERTIONS THAT REMAIN are marked, and each is kept only
// because the thing it guards genuinely has no runtime to drive in this lane: a
// <script> tag in an HTML file, and a cache-busting token in a URL. They are
// labelled MENTION so nobody mistakes them for proof again.
//
// Run: npx tsx --test src/tests/unit/shared/both_clients_offer_the_ticket_lookup.test.ts

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import {
  taskLookupPath,
  taskRefRefusalMessage,
  TASK_LOOKUP_AUTH_REQUIRED_MESSAGE,
  TASK_LOOKUP_UNREACHABLE_MESSAGE,
} from "../../../lupin_app/static/js/shared/task-lookup.js";
import { renderTaskLookupBox } from "../../../lupin_app/static/js/multiplexer/render/taskLookupBox.js";
import { createHoldingAreaRenderer } from "../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer.js";
import { createTaskListRenderer } from "../../../lupin_app/static/js/multiplexer/render/TaskListRenderer.js";
import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus.js";

const HERE      = path.dirname( fileURLToPath( import.meta.url ) );
const REPO_ROOT = path.resolve( HERE, "../../../.." );

const NOTIFICATIONS_HTML = path.join( REPO_ROOT, "src/lupin_app/static/html/notifications.html" );
const NOTIFICATIONS_JS   = path.join( REPO_ROOT, "src/lupin_app/static/js/notifications.js" );

function read( file: string ): string {
  return readFileSync( file, "utf8" );
}

// ---------------------------------------------------------------------------
// Harness — the notifications client, actually loaded and actually run.
// Mirrors task_lookup_panel.test.ts: slice the file before its DOM-ready init,
// run it here, Object.create the prototype to skip the constructor.
// ---------------------------------------------------------------------------

interface Outcome { state: string; [ k: string ]: unknown }
interface NotificationsClient {
  lookupTaskByRef    : ( typed: string ) => Promise<Outcome>;
  describeTaskLookup : ( typed: string, outcome: Outcome ) => { text: string; state: string };
}

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  window.LUPIN_TASK_LOOKUP_PATH                  = taskLookupPath;
  window.LUPIN_TASK_REF_REFUSAL_MESSAGE          = taskRefRefusalMessage;
  window.LUPIN_TASK_LOOKUP_AUTH_REQUIRED_MESSAGE = TASK_LOOKUP_AUTH_REQUIRED_MESSAGE;
  window.LUPIN_TASK_LOOKUP_UNREACHABLE_MESSAGE   = TASK_LOOKUP_UNREACHABLE_MESSAGE;

  const fullSource = read( NOTIFICATIONS_JS );
  const initIdx    = fullSource.indexOf( "// Initialize when DOM is ready" );
  assert.ok( initIdx > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext(
    fullSource.slice( 0, initIdx ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
    { filename: NOTIFICATIONS_JS },
  );
} );

/** A Response-alike. `ok` is derived so a caller cannot set an incoherent pair. */
function response( status: number, body: unknown = {} ) {
  return { status, ok: status >= 200 && status < 300, json: async () => body };
}

/** The notifications client, wired to a spy transport that records every URL. */
function notificationsClient( fetchImpl: ( url: string ) => Promise<unknown> ) {
  const ui = Object.create(
    ( globalThis as never as { NotificationsUI: { prototype: object } } ).NotificationsUI.prototype,
  );
  ui.log = () => {};
  ui.authedFetch = fetchImpl;
  return ui as NotificationsClient;
}

/** What the notifications client shows for `typed`, given a server reply. */
async function notificationsOutcome(
  typed: string,
  reply: ( url: string ) => Promise<unknown>,
  seen: string[],
): Promise<{ text: string; state: string }> {
  const ui      = notificationsClient( ( url: string ) => { seen.push( url ); return reply( url ); } );
  const outcome = await ui.lookupTaskByRef( typed );
  return ui.describeTaskLookup( typed, outcome );
}

/** What the multiplexer box shows for `typed`, given the same server reply. */
async function multiplexerOutcome(
  typed: string,
  reply: ( url: string ) => Promise<unknown>,
  seen: string[],
): Promise<{ text: string; state: string }> {
  const box = renderTaskLookupBox( {
    fetchTask: async ( url: string ) => {
      seen.push( url );
      const res = ( await reply( url ) ) as { ok: boolean; status: number; json: () => Promise<unknown> };
      // ApiClient rejects on non-2xx with a status-bearing error; the box's
      // contract is written against that, so the spy must honour it.
      if ( !res.ok ) {
        const body = ( await res.json().catch( () => ( {} ) ) ) as { detail?: string };
        throw Object.assign( new Error( `HTTP ${ res.status }` ), { status: res.status, detail: body.detail } );
      }
      return res.json();
    },
  } );
  box.input.value = typed;
  await box.submit();
  return { text: box.result.textContent ?? "", state: box.result.getAttribute( "data-state" ) ?? "" };
}

const ROW  = { title: "a real row", status: "queued", owner_persona: "maria", priority: "P1" };
// A row the BOARD cannot see — the case the whole feature exists for.
const HELD = { id: "3fdf4fb4-2370-4117-9a02-c271fcecc331", title: "Main is RED",
               status: "not_approved", owner_persona: "maria", priority: "P0" };

// ---------------------------------------------------------------------------
// THE PARITY GUARD — both clients, same inputs, compared outputs
// ---------------------------------------------------------------------------

test( "🔴 BOTH clients send the SAME request for the same pasted ref", async () => {
  // The load-bearing one. Not "both files mention the endpoint" — both clients
  // are RUN, and the URLs they actually asked for are compared to each other.
  for ( const typed of [ "76032470", "732151f2-9aff-45cf-af4f-471e47481c8a", "  76032470  ", "76032470".toUpperCase() ] ) {
    const notifSeen: string[] = [];
    const muxSeen  : string[] = [];
    const reply = async () => response( 200, ROW );

    await notificationsOutcome( typed, reply, notifSeen );
    await multiplexerOutcome( typed, reply, muxSeen );

    assert.equal( notifSeen.length, 1, `notifications client must send exactly one request for "${ typed }"` );
    assert.deepEqual( muxSeen, notifSeen,
      `the two clients disagree about where to look up "${ typed }" — that is the drift this guard exists for` );
  }
} );

test( "🔴 NEITHER client resolves a hash through the board query, which hides held rows", async () => {
  // Measured 2026-09-09: /api/tasks?id_prefix= chains _apply_owed_filter after
  // the prefix match, and could see 1 of 23 holding-area rows. Asserted against
  // the URL each client REALLY requested, not against the text of its source.
  const seen: string[] = [];
  const reply = async () => response( 200, ROW );
  await notificationsOutcome( "76032470", reply, seen );
  await multiplexerOutcome( "76032470", reply, seen );

  assert.equal( seen.length, 2 );
  for ( const url of seen ) {
    assert.ok( !url.includes( "id_prefix=" ), `${ url } goes through the board query, which cannot see held rows` );
    assert.match( url, /^\/api\/tasks\/[0-9a-f]+$/, `${ url } is not the visibility-free single-row endpoint` );
  }
} );

test( "🔴 BOTH clients agree on what every server answer MEANS", async () => {
  // One condition, one state token, one sentence — on both clients. The 401 row
  // is the regression: it shipped as `auth_required` on one client and fell into
  // the catch-all on the other, so a signed-out user was told the store was down.
  const cases: Array<[ number, unknown, string ]> = [
    [ 404, {},                                    "missing" ],
    [ 422, { detail: "matches 3 tickets: a, b, c" }, "ambiguous" ],
    [ 401, {},                                    "auth_required" ],
    [ 500, {},                                    "unreachable" ],
  ];

  for ( const [ status, body, expectedState ] of cases ) {
    const reply = async () => response( status, body );
    const notif = await notificationsOutcome( "76032470", reply, [] );
    const mux   = await multiplexerOutcome( "76032470", reply, [] );

    assert.equal( notif.state, expectedState, `notifications client mislabels ${ status }` );
    assert.equal( mux.state,   expectedState, `multiplexer mislabels ${ status }` );
    assert.equal( mux.text, notif.text,
      `the two clients say different things about a ${ status } — "${ mux.text }" vs "${ notif.text }"` );
  }
} );

test( "🔴 BOTH clients refuse junk locally, identically, without spending a request", async () => {
  for ( const junk of [ "", "   ", "zz", "not-hex-at-all", "abc" ] ) {
    const notifSeen: string[] = [];
    const muxSeen  : string[] = [];
    const reply = async () => { throw new Error( "the server must not be asked" ); };

    const notif = await notificationsOutcome( junk, reply, notifSeen );
    const mux   = await multiplexerOutcome( junk, reply, muxSeen );

    assert.deepEqual( notifSeen, [], `notifications client spent a request on junk "${ junk }"` );
    assert.deepEqual( muxSeen,   [], `multiplexer spent a request on junk "${ junk }"` );
    assert.equal( notif.state, "refused" );
    assert.equal( mux.state,   "refused" );
    assert.equal( mux.text, notif.text, `the two clients refuse "${ junk }" with different wording` );
  }
} );

test( "🔴 BOTH clients FILTER THE LIST to the row they found", async () => {
  // 🔨 THIS PAIR OF TESTS USED TO ASSERT THE REJECTED BEHAVIOUR — that each
  // client's box printed a sentence leading with the row's title. Rick threw that
  // build out: "what do you think search does? Not confirm that it can find it
  // but find it and then display it… hide all of the other tickets in the task
  // list and only display the 1 that was found."
  //
  // ⇒ Parity now means both clients HAND THE SAME ROW to their list. The rendering
  // half is asserted per client against the real table renderer
  // (task_list_renderer_lookup_filter.test.ts and task_lookup_panel.test.ts);
  // what belongs HERE is that neither client is left behind.
  const reply = async () => response( 200, HELD );

  // Multiplexer: the box hands the row up through onFound.
  const muxPinned: Array<Record<string, unknown>> = [];
  const box = renderTaskLookupBox( {
    fetchTask: async ( url: string ) => {
      const res = ( await reply() ) as { ok: boolean; json: () => Promise<unknown> };
      void url;
      return res.json() as Promise<never>;
    },
    onFound: ( t ) => muxPinned.push( t as unknown as Record<string, unknown> ),
  } );
  box.input.value = "3fdf4fb4";
  await box.submit();

  // Notifications client: the row lands on the pin its renderer reads.
  const ui = notificationsClient( () => reply() as Promise<unknown> ) as unknown as Record<string, unknown>;
  const outcome = await ( ui.lookupTaskByRef as ( r: string ) => Promise<{ state: string; task?: unknown }> )( "3fdf4fb4" );

  assert.equal( muxPinned.length, 1, "the multiplexer never handed the row to its list" );
  assert.equal( outcome.state, "found", "the notifications client did not resolve the row" );
  assert.deepEqual( muxPinned[ 0 ], outcome.task,
    "the two clients disagree about WHICH row the same hash names" );
} );

test( "🔴 BOTH clients carry a held row's STATUS through to their list", async () => {
  // The reason the lookup uses the visibility-free endpoint at all. A held row
  // that reaches the list without its status renders as an ordinary live ticket,
  // and the gap between "queued" and "in your holding area" is usually the whole
  // reason the question was asked.
  const reply = async () => response( 200, HELD );

  const muxPinned: Array<{ status?: string }> = [];
  const box = renderTaskLookupBox( {
    fetchTask: async () => ( ( await reply() ).json() as Promise<never> ),
    onFound  : ( t ) => muxPinned.push( t as unknown as { status?: string } ),
  } );
  box.input.value = "3fdf4fb4";
  await box.submit();

  const ui = notificationsClient( () => reply() as Promise<unknown> ) as unknown as Record<string, unknown>;
  const outcome = await ( ui.lookupTaskByRef as ( r: string ) => Promise<{ task?: { status?: string } }> )( "3fdf4fb4" );

  assert.equal( muxPinned[ 0 ]?.status, "not_approved" );
  assert.equal( outcome.task?.status,   "not_approved" );
} );

test( "the parity guard can actually FAIL — a positive control on the comparison itself", async () => {
  // Without this, every assertion above could be comparing two identical empty
  // strings and reporting agreement. Drive ONE client with a different input and
  // prove the comparison notices, so "they agree" means something.
  const reply = async () => response( 200, ROW );
  const a = await multiplexerOutcome( "76032470", reply, [] );
  const b = await multiplexerOutcome( "aaaaaaaa", async () => response( 404 ), [] );
  assert.notEqual( a.state, b.state, "the comparison cannot distinguish two different outcomes" );
  assert.notEqual( a.text,  b.text  );
} );

// ---------------------------------------------------------------------------
// ONE FIND BOX, NOT TWO — Rick, row 700f0e1d, 2026-09-11: "remove the search
// facility from the holding area accordion since that is duplicative it already
// exists and search across both accordion so I don't need it in two places."
//
// The premise — the task list's box already reaches a HELD row — is pinned above
// by "BOTH clients carry a held row's STATUS through to their list". These pin
// the removal, and the two layout asks from the same ticket, in both clients.
// ---------------------------------------------------------------------------

test( "🔴 NEITHER holding area carries a search box", () => {
  const bus = createEventBusForTesting();
  const store = {
    composite : () => ( { status: "ok", tasks: [], count: 0 } ),
    refresh   : () => Promise.resolve(),
  };
  const root = document.createElement( "div" );
  createHoldingAreaRenderer( { eventBus: bus, store: store as never } ).mount( root );
  assert.ok( root.querySelector( "[data-testid='multiplexer-holding-area-header']" ),
    "positive control: the multiplexer's holding area really mounted" );
  assert.equal( root.querySelectorAll( ".task-lookup, .task-lookup-input" ).length, 0,
    "the multiplexer's holding area still carries a Find box" );

  const html = read( NOTIFICATIONS_HTML );
  const pane = html.slice( html.indexOf( 'id="section-holding-area"' ), html.indexOf( 'id="section-epic-board"' ) );
  assert.ok( pane.includes( 'id="holding-area-container"' ), "positive control: the slice really is the holding area" );
  assert.ok( !pane.includes( "task-lookup" ), "the notifications holding area still carries a Find box" );
  assert.ok( !read( NOTIFICATIONS_JS ).includes( "runHoldingAreaLookup" ), "the notifications client still ships the holding search" );
} );

test( "🔴 BOTH clients put the clear ✕ BETWEEN 🔎 and ＋ New — it acts on the search, not on New", () => {
  // Rick: "it should appear between the search icon and the new button… It affects
  // the search area, not the new button."
  const bus   = createEventBusForTesting();
  const store = { composite: () => ( { tasks: [], count: 0 } ), refresh: () => {} };
  const root  = document.createElement( "div" );
  createTaskListRenderer( {
    eventBus: bus, stores: { taskList: store as never }, nowDateFn: () => new Date( "2026-09-11T16:00:00Z" ),
    lookupFetch: () => Promise.resolve( {} as never ),
    postTicket : () => Promise.resolve( { status: 201 } as never ),
  } ).mount( root );
  const order = Array.from( root.querySelectorAll( ".task-lookup-go, .task-lookup-clear, .task-list-new-ticket" ) )
    .map( ( el ) => el.className );
  assert.deepEqual( order, [ "task-lookup-go", "task-lookup-clear", "task-list-new-ticket" ],
    "the multiplexer's header order is wrong" );

  const html  = read( NOTIFICATIONS_HTML );
  const go    = html.indexOf( 'id="task-lookup-go"' );
  const clear = html.indexOf( 'id="task-lookup-clear"' );
  const newer = html.indexOf( 'id="task-new-ticket"' );
  assert.ok( go > 0 && clear > go && newer > clear, "the notifications page's order is wrong" );
} );

test( "🔴 BOTH Find inputs are type=text — no browser ✕ that empties the box but keeps the filter", () => {
  const box = renderTaskLookupBox( { fetchTask: () => Promise.resolve( {} as never ) } );
  assert.equal( box.input.type, "text", "the multiplexer's Find box is a search input again" );

  const html  = read( NOTIFICATIONS_HTML );
  const input = html.match( /<input[^>]*id="task-lookup-input"[^>]*>/ );
  assert.ok( input, "positive control: the notifications Find input was found" );
  assert.match( input![ 0 ], /type="text"/, "the notifications Find box is a search input again" );
  assert.match( input![ 0 ], /enterkeyhint="search"/ );
} );

// ---------------------------------------------------------------------------
// MENTION assertions — kept, and labelled, because they have no runtime here
// ---------------------------------------------------------------------------

test( "MENTION: the notifications page loads the shared module with a <script> tag", () => {
  // Genuinely static: there is no page load in this lane to observe. Without the
  // tag the global is absent and every lookup takes the module_missing branch —
  // the deploy defect that branch exists to name.
  assert.match( read( NOTIFICATIONS_HTML ), /src="\/static\/js\/shared\/task-lookup\.js/,
    "the module must be loaded by the page, not merely written" );
} );

test( "MENTION: the notifications page carries the lookup markup", () => {
  assert.match( read( NOTIFICATIONS_HTML ), /data-testid="task-lookup-input"/,
    "the notifications client must offer the box" );
} );

test( "MENTION: the cache token on notifications.js was bumped past the last release", () => {
  // 🔴 THE DEFECT THIS CATCHES HAS FIRED TWICE IN ONE DAY (commits 1a958c49 and
  // 2033c006): a merged fix sat behind a byte-identical URL and every warm
  // browser held the old copy forever. Rick's ruling is that "fixed" means he
  // can SEE and USE it, so an unbumped token is an unshipped feature.
  //
  // ⚠️ A FLOOR, not a full guard — it cannot tell "bumped correctly" from
  // "bumped to something arbitrary". The real instrument is the stale-bundle
  // gate on row 75044ab5.
  const html  = read( NOTIFICATIONS_HTML );
  const match = html.match( /notifications\.js\?v=(\w+)/ );
  assert.ok( match, "notifications.js must carry a cache-busting token at all" );
  assert.notEqual( match![ 1 ], "20260909a",
    "notifications.js changed; its token must move or warm browsers keep the old file" );
} );
