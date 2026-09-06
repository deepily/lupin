// B5 — ENDPOINT PARITY. For every row control on both accordion surfaces, the legacy
// card and the multiplexer must issue the SAME request to the SAME endpoint with the
// SAME parameters.
//
// 🔴 BOUNDED ON PURPOSE, AND THE BOUND IS MARÍA'S (2026-09-06): a wrong ENDPOINT is this
// file's job. A wrong RESPONSE is nobody's. Nothing here validates what comes back — the
// stores' own suites own refusal text, rollback and optimistic repaint, and duplicating
// that here would trade a sharp claim for a broad one.
//
// ─────────────────────────── WHAT THE SURFACE ACTUALLY IS ───────────────────────────
//
// Enumerated by PREDICATE, not by a hand list — every site in either client that issues
// a MUTATING request against a task row. The census below re-derives it from source on
// every run and fails if a new one appears, because a hand list is right about everything
// its author thought of and silently wrong about the rest.
//
//     legacy  notifications.js   _transitionTask     POST  /api/tasks/{id}/transition
//     legacy  notifications.js   _patchTaskFields    PATCH /api/tasks/{id}
//     mux     TaskListStore      transitionTask      POST  /api/tasks/{id}/transition
//     mux     TaskListStore      patchTask           PATCH /api/tasks/{id}
//     mux     HoldingAreaStore   transitionTask      POST  /api/tasks/{id}/transition
//
// The `/api/tasks/flow-ratio*` sites in notifications.js are deliberately OUT of scope:
// they are a header widget, not a row control, and no accordion surface reaches them.
//
// ─────────────────── THE FIXTURE IS THE WHOLE MEASUREMENT ───────────────────
//
// 🔴 THE ID MUST NEED PERCENT-ENCODING, OR THIS FILE MEASURES NOTHING. With an id like
// `t1`, `encodeURIComponent(id)` and a bare `${id}` produce byte-identical URLs, so a
// client that forgot to encode and one that did not are INDISTINGUISHABLE. That is not
// hypothetical: `task_list_store.test.ts` asserts both its paths with the id `t1` and is
// blind to the encoding question in both directions — measured 2026-09-06, adding the
// missing `encodeURIComponent` to TaskListStore left 51/51 GREEN, and removing it again
// left 42/42 GREEN. Neither form was pinned by anything. Its sibling
// `holding_area_store_transition.test.ts:87` DOES pin it, with `a%2Fb%3Fc%23d` — the same
// fixture choice, and the reason that store was correct while this one drifted.
//
// So every drive below uses an id carrying `/`, `?` and `#` — the three characters that
// would otherwise re-point the request at a different route entirely.
//
// ────────────────────── WHAT IS DELIBERATELY *NOT* EQUAL ──────────────────────
//
// ⚠️ `actor` DIVERGES BY DESIGN AND MUST NOT BE "FIXED" INTO PARITY.
//     legacy       `operator ${queueSessionId || "browser"}`
//     multiplexer  `${email} (multiplexer)`  /  `anonymous (multiplexer)`
// The suffix is provenance: the audit trail is supposed to record WHICH client an
// operator acted through. Asserting these equal would delete a distinction the server
// deliberately keeps, so this file asserts the two are DIFFERENT and that each matches
// its own contract — an exclusion that is itself guarded, rather than a silent skip.
//
// ⚠️ A COINCIDENCE, RECORDED SO IT IS NOT MISTAKEN FOR AGREEMENT. The two clients spread
// the body in OPPOSITE order:
//     legacy  { to_status, actor, authority, ...extras }   ← extras would WIN
//     mux     { to_status, ...extras, actor, authority }   ← actor/authority WIN
// They agree today only because no verb's extras ever carries `actor` or `authority` —
// the vocabulary is `reason` / `park_reason` / `next_chase_ts` (shared/task-verbs.js).
// That is two derivations landing on one value, not one rule applied twice. The census
// arm below pins the extras vocabulary so the day a verb grows an `authority` extra, this
// file goes red instead of the two clients quietly diverging.
//
// ─────────────────────────────── PROOF IT DISCRIMINATES ───────────────────────────────
//
// 🔴 THIS FILE WAS WRITTEN RED AND IS THE REASON TaskListStore NOW ENCODES. On first run,
// against TaskListStore as it stood at f17ab948, the two `TaskListStore` parity cases
// FAILED and every other case passed — it issued `/api/tasks/a/b?c#d/transition` where
// both the legacy card and its own sibling store issued `/api/tasks/a%2Fb%3Fc%23d/...`.
// A guard first watched to fail on a REAL defect is a stronger receipt than any mutation
// arm, because nobody chose the defect.
//
// Mutation arms, measured after the fix. Per-file green baseline taken FIRST — B5 11,
// task_list_store 25, holding_store 17 — and every arm restored and sha-verified. Counts
// are per-file runs, never a multi-file invocation, whose summary sums a union.
//
//   arm                                              this file   task_list_store   holding_store
//   drop encodeURIComponent, TaskListStore (both)     3 FAIL       25 pass          17 pass
//   drop encodeURIComponent, HoldingAreaStore         2 FAIL       25 pass           1 FAIL
//   legacy _transitionTask POST -> PATCH              1 FAIL       25 pass          17 pass
//   legacy _transitionTask -> the field door          1 FAIL       25 pass          17 pass
//   mux transitionTask drops `authority`              1 FAIL        3 FAIL          17 pass
//   multiplexer given the LEGACY actor string         1 FAIL        6 FAIL           2 FAIL
//
// 🔴 THREE OF THE SIX ARE EXCLUSIVE TO THIS FILE, NOT ALL SIX, AND THE SPLIT IS THE
// HONEST PART. Rows 1, 3 and 4 are caught HERE AND NOWHERE ELSE: a client changing which
// door it knocks on is invisible to a suite that only ever loads that one client. Rows 2,
// 5 and 6 are caught here AND by an existing per-client suite — this file thickens them
// rather than being their only watcher. A flat "all six are exclusive" was available and
// would have made the whole table worthless.
//
// :7999-eligible in spirit — pure, no server, no network. Runs in the TypeScript tier
// (:8000 scheduled) because that is where .test.ts lives.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../lupin_app/static/js/multiplexer/shared/EventBus";
import {
  createTaskListStore,
  type TaskListApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import {
  createHoldingAreaStore,
  type HoldingAreaApiClient,
} from "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import type { TaskListComposite } from "../../../lupin_app/static/js/multiplexer/render/taskListModel";
import { TASK_VERB_SPECS } from "../../../lupin_app/static/js/shared/task-verbs.js";

const HERE               = dirname( fileURLToPath( import.meta.url ) );
const NOTIFICATIONS_JS   = resolve( HERE, "../../../lupin_app/static/js/notifications.js" );
const TASK_LIST_STORE_TS = resolve( HERE, "../../../lupin_app/static/js/multiplexer/stores/TaskListStore.ts" );
const HOLDING_STORE_TS   = resolve( HERE, "../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore.ts" );


// ═══════════════════════════════ THE CONTRACT ═══════════════════════════════
//
// 🔴 HAND-WRITTEN LITERALS, AND DELIBERATELY NOT DERIVED FROM EITHER CLIENT. This is
// María's B1 ruling applied to the request shape: the KEY STRINGS a client owns may be
// read from it, but the CONTRACT both clients are measured against is not either client's
// to define. Derive these from a store and both sides of every comparison below move
// together — a symmetric drift in the two clients would then pass, which is the exact
// blindness the B1 lane measured and refused (§ A COMPARISON WHOSE TWO SIDES COME FROM
// ONE SOURCE CANNOT DISAGREE). Do NOT "de-duplicate" these against the stores.

/** CONTRACT LITERAL — the row id used for every drive. Chosen to need encoding. */
const RAW_ID = "a/b?c#d";
/** CONTRACT LITERAL — what that id must become inside a URL path segment. */
const ENC_ID = "a%2Fb%3Fc%23d";

/** CONTRACT LITERAL — the transition door, and the method it answers on. */
const TRANSITION_METHOD = "POST";
const TRANSITION_PATH   = `/api/tasks/${ENC_ID}/transition`;
/** CONTRACT LITERAL — the field-edit door, a DIFFERENT endpoint on purpose. */
const PATCH_METHOD      = "PATCH";
const PATCH_PATH        = `/api/tasks/${ENC_ID}`;

/** CONTRACT LITERAL — the authority every operator-driven control records. */
const AUTHORITY = "user_direct";
/** CONTRACT LITERAL — the extras vocabulary a verb may contribute to a body. */
const EXTRAS_VOCABULARY = [ "reason", "park_reason", "next_chase_ts" ];


// ═════════════════════════════ DRIVING THE LEGACY CARD ═════════════════════════════

type Issued = { method: string; path: string; body: Record<string, unknown> };

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const i   = src.indexOf( "// Initialize when DOM is ready" );
  assert.ok( i > 0, "bottom-of-file init marker must be found" );
  vm.runInThisContext( src.slice( 0, i ) + "\n;globalThis.NotificationsUI = NotificationsUI;",
                       { filename: NOTIFICATIONS_JS } );
} );

/**
 * The REAL legacy request builder, with only the network stood down.
 *
 * `authedFetch` is the single seam every legacy call goes through, so stubbing it there
 * — rather than stubbing `_transitionTask` itself, which is what every existing suite
 * does — is what makes the URL and body observable at all.
 */
function legacy(): { ui: Record<string, any>; issued: Issued[] } {
  const Ctor = ( globalThis as Record<string, any> ).NotificationsUI;
  const ui   = Object.create( Ctor.prototype );
  const issued: Issued[] = [];
  ui.queueSessionId = "wise penguin";
  ui.authedFetch = async ( path: string, opts?: Record<string, any> ) => {
    issued.push( {
      method : ( opts && opts.method ) || "GET",
      path,
      body   : opts && opts.body ? JSON.parse( opts.body ) : {},
    } );
    return { ok: true, status: 200, json: async () => ( {} ) };
  };
  return { ui, issued };
}


// ═══════════════════════════ DRIVING THE MULTIPLEXER ═══════════════════════════

const SEED = (): TaskListComposite => ( {
  status : "ok",
  tasks  : [ { id: RAW_ID, title: "the row under the parity walk", status: "in_progress",
               owner_persona: "maya", priority: "P2" } ],
} as unknown as TaskListComposite );

async function taskListStore(): Promise<{ store: any; issued: Issued[] }> {
  const issued: Issued[] = [];
  const api: TaskListApiClient = {
    get   : async <T,>(): Promise<T> => SEED() as unknown as T,
    patch : async <T,>( path: string, body: unknown ): Promise<T> => {
      issued.push( { method: "PATCH", path, body: body as Record<string, unknown> } );
      return null as T;
    },
    post  : async <T,>( path: string, body: unknown ): Promise<T> => {
      issued.push( { method: "POST", path, body: body as Record<string, unknown> } );
      return null as T;
    },
  };
  const store = createTaskListStore( {
    bus: createEventBusForTesting(), api, endpoint: "/api/tasks?limit=750",
    nowFn: () => 0, actorProvider: () => "rick@example.com",
    setIntervalFn: () => 1, clearIntervalFn: () => { /* no timer here */ },
  } as any );
  // The store refuses to mutate a row it has never seen, so it must be primed first —
  // a cache miss is a silent no-op and would make every assertion below vacuous.
  await store.refresh();
  return { store, issued };
}

function holdingStore(): { store: any; issued: Issued[] } {
  const issued: Issued[] = [];
  const api: HoldingAreaApiClient = {
    get  : async () => ( { status: "ok", tasks: [] } ) as never,
    post : async ( path: string, body: unknown ) => {
      issued.push( { method: "POST", path, body: body as Record<string, unknown> } );
      return {} as never;
    },
  };
  const store = createHoldingAreaStore( {
    bus: createEventBusForTesting(), api,
    actorProvider: () => "rick@example.com",
    setIntervalFn: () => 1, clearIntervalFn: () => { /* no timer here */ },
  } );
  return { store, issued };
}


// ═════════════════ CENSUS — the corpus states its own denominator ═════════════════
//
// 🔴 A PARITY FILE THAT DRIVES A HAND-PICKED SET OF CONTROLS REPORTS ON ITS AUTHOR'S
// MEMORY, NOT ON THE PRODUCT. These re-derive the request surface from source on every
// run, so a NEW mutating call site added to either client reddens here instead of
// shipping unwatched.

test( "CENSUS: the legacy card's mutating row-request surface is exactly the two doors driven below", () => {
  const src = readFileSync( NOTIFICATIONS_JS, "utf8" );
  // Every authedFetch against a task ROW — the `${` is what distinguishes a per-row
  // endpoint from the flow-ratio singletons, which are out of scope by construction.
  const sites = [ ...src.matchAll( /authedFetch\(\s*`\/api\/tasks\/\$\{[^`]*`/g ) ].map( m => m[ 0 ] );
  assert.equal( sites.length, 2,
    `the legacy card now has ${ sites.length } per-row request sites, not 2. A new one has ` +
    `appeared and nothing in this file drives it:\n  ${ sites.join( "\n  " ) }` );
  // Both must encode. This is asserted on the SOURCE as well as driven below, because the
  // drive can only ever speak for the paths it exercises.
  for ( const site of sites ) {
    assert.match( site, /encodeURIComponent/,
      `a legacy per-row request builds its URL without encoding the id: ${ site }` );
  }
} );

test( "CENSUS: the multiplexer's mutating row-request surface is exactly the three doors driven below", () => {
  const both = readFileSync( TASK_LIST_STORE_TS, "utf8" ) + readFileSync( HOLDING_STORE_TS, "utf8" );
  const sites = [ ...both.matchAll( /api\.(?:post|patch)<[^>]*>\(\s*`\/api\/tasks\/[^`]*`/g ) ].map( m => m[ 0 ] );
  assert.equal( sites.length, 3,
    `the multiplexer now has ${ sites.length } per-row request sites, not 3:\n  ${ sites.join( "\n  " ) }` );
  for ( const site of sites ) {
    assert.match( site, /encodeURIComponent/,
      `a multiplexer store builds its URL without encoding the id: ${ site }\n` +
      `  · with a uuid-shaped id this is invisible — encoded and raw are byte-identical\n` +
      `  · with an id carrying / ? or #, the request lands on a different route entirely` );
  }
} );

test( "CENSUS: no verb's extras can collide with the keys the two clients spread in opposite order", () => {
  const seen = new Set<string>();
  for ( const spec of Object.values( TASK_VERB_SPECS as Record<string, any> ) ) {
    if ( spec.reason ) seen.add( "reason" );
    if ( spec.date )   seen.add( "next_chase_ts" );
  }
  assert.ok( seen.size > 0, "no verb contributes any extras — the walk below would be vacuous" );
  for ( const key of seen ) {
    assert.ok( EXTRAS_VOCABULARY.includes( key ),
      `a verb now contributes the extra "${ key }", which this file has never seen. If it is ` +
      `"actor" or "authority", the two clients spread the body in OPPOSITE order and will ` +
      `silently disagree — see the coincidence note in this file's header` );
  }
} );


// ═══════════════════ CELL 1: the transition door, all three clients ═══════════════════

test( "TRANSITION — the legacy card posts to the row's own transition door, id encoded", async () => {
  const { ui, issued } = legacy();
  await ui._transitionTask( RAW_ID, "parked", { park_reason: "quoted", next_chase_ts: "2026-09-09" } );
  assert.equal( issued.length, 1, "the legacy card issued no request at all" );
  assert.equal( issued[ 0 ]!.method, TRANSITION_METHOD );
  assert.equal( issued[ 0 ]!.path,   TRANSITION_PATH,
    `the legacy card posted to ${ issued[ 0 ]!.path }, not the contracted transition door` );
} );

test( "TRANSITION — TaskListStore posts to the SAME door with the SAME method and encoding", async () => {
  const { store, issued } = await taskListStore();
  await store.transitionTask( RAW_ID, "parked", { park_reason: "quoted", next_chase_ts: "2026-09-09" } ).done;
  assert.equal( issued.length, 1, "TaskListStore issued no request — was the row in its cache?" );
  assert.equal( issued[ 0 ]!.method, TRANSITION_METHOD );
  assert.equal( issued[ 0 ]!.path,   TRANSITION_PATH,
    `TaskListStore posted to ${ issued[ 0 ]!.path } where the legacy card posts to ` +
    `${ TRANSITION_PATH }. An operator doing the same thing on the two surfaces reaches ` +
    `two different routes` );
} );

test( "TRANSITION — HoldingAreaStore posts to the SAME door with the SAME method and encoding", async () => {
  const { store, issued } = holdingStore();
  await store.transitionTask( RAW_ID, "parked", { park_reason: "quoted", next_chase_ts: "2026-09-09" } );
  assert.equal( issued.length, 1, "HoldingAreaStore issued no request" );
  assert.equal( issued[ 0 ]!.method, TRANSITION_METHOD );
  assert.equal( issued[ 0 ]!.path,   TRANSITION_PATH );
} );

test( "TRANSITION — the three clients agree on to_status, the extras and the authority", async () => {
  const extras = { park_reason: "quoted", next_chase_ts: "2026-09-09" };
  const l = legacy();          await l.ui._transitionTask( RAW_ID, "parked", extras );
  const t = await taskListStore(); await t.store.transitionTask( RAW_ID, "parked", extras ).done;
  const h = holdingStore();    await h.store.transitionTask( RAW_ID, "parked", extras );

  for ( const [ name, issued ] of [ [ "legacy", l.issued ], [ "TaskListStore", t.issued ],
                                    [ "HoldingAreaStore", h.issued ] ] as const ) {
    const body = issued[ 0 ]!.body;
    assert.equal( body.to_status,   "parked",              `${ name } posted the wrong to_status` );
    assert.equal( body.park_reason, "quoted",              `${ name } dropped the verb's park_reason` );
    assert.equal( body.next_chase_ts, "2026-09-09",        `${ name } dropped the verb's next_chase_ts` );
    assert.equal( body.authority,   AUTHORITY,
      `${ name } recorded authority "${ body.authority }" — an operator's own press must not ` +
      `read as automation` );
  }
} );


// ═══════════════════ CELL 2: the field-edit door, a DIFFERENT endpoint ═══════════════════

test( "PATCH — the legacy card sends a field edit to the field door, never the transition door", async () => {
  const { ui, issued } = legacy();
  await ui._patchTaskFields( RAW_ID, { priority: "P0" } );
  assert.equal( issued.length, 1 );
  assert.equal( issued[ 0 ]!.method, PATCH_METHOD );
  assert.equal( issued[ 0 ]!.path,   PATCH_PATH );
} );

test( "PATCH — TaskListStore sends a field edit to the SAME field door", async () => {
  const { store, issued } = await taskListStore();
  await store.patchTask( RAW_ID, { priority: "P0" } ).done;
  assert.equal( issued.length, 1, "TaskListStore issued no PATCH — was the row in its cache?" );
  assert.equal( issued[ 0 ]!.method, PATCH_METHOD );
  assert.equal( issued[ 0 ]!.path,   PATCH_PATH,
    `TaskListStore patched ${ issued[ 0 ]!.path } where the legacy card patches ${ PATCH_PATH }` );
} );

test( "PATCH — the two clients agree on the edited field and the authority", async () => {
  const l = legacy();              await l.ui._patchTaskFields( RAW_ID, { priority: "P0" } );
  const t = await taskListStore(); await t.store.patchTask( RAW_ID, { priority: "P0" } ).done;
  for ( const [ name, issued ] of [ [ "legacy", l.issued ], [ "TaskListStore", t.issued ] ] as const ) {
    assert.equal( issued[ 0 ]!.body.priority,  "P0",      `${ name } dropped the edited field` );
    assert.equal( issued[ 0 ]!.body.authority, AUTHORITY, `${ name } recorded the wrong authority` );
    assert.equal( issued[ 0 ]!.body.status,    undefined,
      `${ name } smuggled a status into the FIELD door — the server sets extra="forbid" and ` +
      `omits status precisely so a field edit can never bypass validate_transition` );
  }
} );


// ═══════════ THE ONE DIFFERENCE THAT IS DELIBERATE, GUARDED AS A DIFFERENCE ═══════════
//
// 🔴 ASSERTED, NOT SKIPPED. An exclusion nobody watches is how a real divergence hides
// behind a documented one: "actor differs on purpose" would also cover a client that had
// stopped sending an actor at all, or one whose provenance suffix had been ported away.

test( "ACTOR — the two clients record DIFFERENT provenance, and each matches its own contract", async () => {
  const l = legacy();              await l.ui._transitionTask( RAW_ID, "queued", {} );
  const t = await taskListStore(); await t.store.transitionTask( RAW_ID, "queued", {} ).done;

  const legacyActor = l.issued[ 0 ]!.body.actor;
  const muxActor    = t.issued[ 0 ]!.body.actor;

  // CONTRACT LITERAL — the legacy card names the browser session it acted from.
  assert.equal( legacyActor, "operator wise penguin",
    "the legacy card's actor no longer names its queue session" );
  // CONTRACT LITERAL — the multiplexer names the signed-in operator AND its own surface.
  assert.equal( muxActor, "rick@example.com (multiplexer)",
    "the multiplexer's actor no longer carries its provenance suffix" );

  assert.notEqual( legacyActor, muxActor,
    "the two clients now record the SAME actor. This is the one field that must differ — " +
    "the audit trail is supposed to say which surface an operator acted through, and " +
    "collapsing them deletes that distinction silently" );
} );
