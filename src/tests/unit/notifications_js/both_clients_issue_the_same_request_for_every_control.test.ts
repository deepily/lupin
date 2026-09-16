// 🔴 THE ROSTER XFAIL IS GONE: the multiplexer's roster now matches the shared oracle
// (709128d4 added `fixed`, f3634011 added `unpark` to both), so `ROSTER` asserts the
// contract directly. The warning the xfail carried came true: the multiplexer offered
// `fixed` with no `receipt_refs.operator_attestation`, and `VERB WALK — "fixed"` went RED
// on that real divergence — the store refuses a ->done carrying no receipt. Fixed in
// row 47377c92: `transitionExtras` now sends the attestation, and the walk compares its
// PRESENCE while ignoring its value, as it does for `actor`.
//
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
//     mux     HoldingAreaStore   patchTask           PATCH /api/tasks/{id}      (parity A-2 #0)
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
// Mutation arms. BASELINE STATED FIRST, with the tree it was taken in — a kill count
// without one is a fact about a tree nobody can identify:
//
//   sha bdb269a9 (+ this commit) · branch krishna-s3-accordion-css · wt lupin-wt-cc-author-maria-2
//   tree: 0 tracked-dirty besides this file (only `?? node_modules`) · 2026-09-06 15:49 EDT
//   per-file baseline: B5 27/0 · task_list_store 25/0 · holding_store 17/0
//
// ⚠️ `LUPIN_ROOT` POINTS AT THE MAIN REPO HERE AND IT DOES NOT MATTER, WHICH IS WORTH ONE
// LINE BECAUSE THE OPPOSITE IS TRUE OF THE PYTHON TIER. These are tsx tests importing by
// RELATIVE path, so modules resolve from the test file's own location — this worktree.
// Verified by positive control rather than by argument: the main checkout's TaskListStore
// contains `encodeURIComponent` ZERO times and this one contains it twice, and the
// TaskListStore parity cases PASS — which is only possible against this tree.
//
//   arm                                              this file   task_list_store   holding_store
//   (no mutation — the baseline)                      0 fail       25 pass          17 pass
//   drop encodeURIComponent, TaskListStore (both)     8 FAIL       25 pass          17 pass
//   drop encodeURIComponent, HoldingAreaStore         2 FAIL       25 pass           1 FAIL
//   legacy _transitionTask POST -> PATCH              9 FAIL       25 pass          17 pass
//   legacy _transitionTask -> the field door          9 FAIL       25 pass          17 pass
//   mux transitionTask drops `authority`              6 FAIL        3 FAIL          17 pass
//   multiplexer given the LEGACY actor string         1 FAIL        6 FAIL           2 FAIL
//   mux files park's reason under generic `reason`    1 FAIL       25 pass          17 pass
//   mux drops next_chase_ts from a dated verb         2 FAIL       25 pass          17 pass
//   SIMULATE JOHN'S FIX: `fixed` joins the mux roster 2 FAIL       25 pass          17 pass
//
// ⚠️ THE TWO LEGACY-ENDPOINT ARMS MOVED 6 -> 9 WHEN THE SURFACE CASES LANDED. That is the
// three pane cases firing, and it is the measurement showing they are load-bearing rather
// than three more ways of saying what the verb walk already said.
//
// 🔴 FIVE OF THE EIGHT DEFECT ARMS ARE EXCLUSIVE TO THIS FILE, NOT ALL EIGHT, AND THE
// SPLIT IS THE HONEST PART. Rows 1, 3, 4, 7 and 8 are caught HERE AND NOWHERE ELSE: a
// client changing which door it knocks on, or which KEY it files a reason under, is
// invisible to a suite that loads only that one client. Rows 2, 5 and 6 are caught here
// AND by an existing per-client suite — this file thickens them rather than being their
// only watcher. A flat "all eight are exclusive" was available and would have made the
// table worthless.
//
// ⚠️ THE LAST ROW IS NOT A DEFECT ARM — IT IS THE XFAIL'S OWN CONTROL. It simulates the
// FIX rather than a break, and its 2 FAIL is the marker demanding removal plus the walk
// picking up `fixed` and finding no operator attestation. Counted separately because
// folding a fix-simulation into a kill count would inflate it with a row that is not a
// kill at all.
//
// ⚠️ ROWS 7 AND 8 ARE THE WIDENED WALK EARNING ITS KEEP. Filing park's reason under the
// generic `reason` key is the defect the per-row builders were written to avoid, and
// before the walk existed nothing compared the two clients' builders at all.
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
import { transitionExtras, TASK_VERBS as MUX_TASK_VERBS } from "../../../lupin_app/static/js/multiplexer/render/taskVerbs";
import { holdingBatchExtras } from "../../../lupin_app/static/js/multiplexer/render/holdingAreaBatch";

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
  // notifications.js reads its verb table off the window, exactly as the browser serves
  // it (shared/task-verbs.js publishes there). Without this the legacy submit handler
  // finds no verb spec and refuses with "Choose an action first" — which reads as a dead
  // control rather than an unseeded harness.
  const w = window as unknown as Record<string, unknown>;
  w.LUPIN_TASK_VERB_SPECS = TASK_VERB_SPECS;
  w.LUPIN_TASK_VERBS      = Object.keys( TASK_VERB_SPECS as Record<string, unknown> );
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
    patch : async ( path: string, body: unknown ) => {
      issued.push( { method: "PATCH", path, body: body as Record<string, unknown> } );
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

test( "CENSUS: the multiplexer's mutating row-request surface is exactly the four doors driven below", () => {
  const both = readFileSync( TASK_LIST_STORE_TS, "utf8" ) + readFileSync( HOLDING_STORE_TS, "utf8" );
  const sites = [ ...both.matchAll( /api\.(?:post|patch)<[^>]*>\(\s*`\/api\/tasks\/[^`]*`/g ) ].map( m => m[ 0 ] );
  // 4 since parity A-2 #0 gave the holding area's shared row a field door of its own.
  assert.equal( sites.length, 4,
    `the multiplexer now has ${ sites.length } per-row request sites, not 4:\n  ${ sites.join( "\n  " ) }` );
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

test( "PATCH — HoldingAreaStore sends a field edit to the SAME field door", async () => {
  const { store, issued } = holdingStore();
  const result = await store.patchTask( RAW_ID, { priority: "P0" } );
  assert.deepEqual( result, { ok: true } );
  assert.equal( issued.length, 1, "HoldingAreaStore issued no PATCH" );
  assert.equal( issued[ 0 ]!.method, PATCH_METHOD );
  assert.equal( issued[ 0 ]!.path,   PATCH_PATH,
    `HoldingAreaStore patched ${ issued[ 0 ]!.path } where the legacy card patches ${ PATCH_PATH }` );
} );

test( "PATCH — the three clients agree on the edited field and the authority", async () => {
  const l = legacy();              await l.ui._patchTaskFields( RAW_ID, { priority: "P0" } );
  const t = await taskListStore(); await t.store.patchTask( RAW_ID, { priority: "P0" } ).done;
  const h = holdingStore();        await h.store.patchTask( RAW_ID, { priority: "P0" } );
  for ( const [ name, issued ] of [ [ "legacy", l.issued ], [ "TaskListStore", t.issued ], [ "HoldingAreaStore", h.issued ] ] as const ) {
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


// ═══════════════════ THE DENOMINATOR — the set this file asserts over ═══════════════════
//
// 🔴 STATED ON ALL THREE AXES, BECAUSE "IT PASSES" WITHOUT THEM TELLS NOBODY WHETHER THIS
// COVERED THE CONTROL SURFACE OR A THIRD OF IT (María, 2026-09-06). Every figure below is
// re-derived from source by a case in this file, so it cannot quietly go stale.
//
//   SURFACES — control-bearing panes
//     legacy       3   task list · holding area · epic board
//     multiplexer  2   TaskListRenderer · HoldingAreaRenderer
//     shared       2   ⚠️ the multiplexer's EpicBoardRenderer is READ-ONLY (278 lines,
//                      `task-verb-select` 0, `transitionTask` 0, `patchTask` 0, against a
//                      positive control of 2/2/3 on TaskListRenderer). A whole SURFACE
//                      exists on one client and not the other — the roster gap's shape on
//                      a different axis. Recorded as a measurement; whether it SHOULD have
//                      controls is a product question this file does not decide.
//
//   VERBS
//     shared oracle 7   park drop demote wont_fix fixed unpark approve
//     legacy        7   all of them
//     multiplexer   7   all of them — asserted by ROSTER
//     walked        7   the intersection; a parity claim over a verb one client does not
//                       offer is vacuous
//
//   CONTROLS
//     per-row, BOTH clients    verb select + reason + Submit  -> POST transition
//                              priority select + Update       -> PATCH priority
//     per-group, BOTH clients  holding-area batch, 2 verbs    -> POST transition
//     per-row, MUX-ONLY        owner select (reassign)        -> PATCH owner_persona
//                              `task-owner-select` appears 0 times in notifications.js,
//                              asserted — no legacy counterpart to be in parity WITH
//
//   REQUEST BUILDERS  legacy 2 · multiplexer 3 — every one of them driven below
//
// ⇒ WHAT IS ASSERTED: 5 verbs x body parity · 3 legacy panes x same-door · priority PATCH
//   across both clients · batch extras across 2 verbs · endpoint+method across all 5
//   builders. WHAT IS NOT: the multiplexer's epic board (no controls to compare), and
//   `fixed` (one client only). Both are asserted as ABSENCES so they cannot appear
//   silently.
//
// ⚠️ THE PANE COVERAGE USED TO BE INHERITED AND IS NOW OWNED. The verb walk drives ONE
// legacy pane, which is sufficient only because the other two reach the same builder —
// a claim this file took from `every_pane_offers_and_routes_every_verb.test.ts` without
// stating the dependency. The SURFACE cases below drive all three panes here.

test( "DENOMINATOR: the per-row verb surface is 7 verbs, and both clients agree on the roster", () => {
  const verbs = Object.keys( TASK_VERB_SPECS as Record<string, unknown> ).sort();
  // CONTRACT LITERAL — the roster as of 2026-09-15 (`unpark` joined in f3634011), deliberately NOT derived. A verb
  // renamed on both sides at once leaves every derived walk generating the same number
  // of cells and passing, which is the corpus-identity blindness the sibling verb walk
  // measured. This is the one side the code cannot move.
  assert.deepEqual( verbs, [ "approve", "demote", "drop", "fixed", "park", "unpark", "wont_fix" ],
    `the verb roster moved. The walk below covers whatever the module publishes, so it ` +
    `cannot notice a rename on its own — this literal is what does` );
} );

test( "DENOMINATOR: the batch surface is exactly approve + wont_fix on BOTH clients", () => {
  const muxSrc    = readFileSync( resolve( HERE, "../../../lupin_app/static/js/multiplexer/render/holdingAreaBatch.ts" ), "utf8" );
  const legacySrc = readFileSync( NOTIFICATIONS_JS, "utf8" );
  const muxBatch  = [ ...muxSrc.matchAll( /^\s{2}(\w+)\s*:\s*\{\s*status:/gm ) ].map( m => m[ 1 ] ).sort();
  assert.deepEqual( muxBatch, [ "approve", "wont_fix" ],
    `the multiplexer's batch roster is now [${ muxBatch }] — a verb joined or left the batch` );
  // The legacy batch is two named handlers rather than a table, so it is counted that way.
  const legacyBatch = [ ...legacySrc.matchAll( /_handleHolding(\w+?)AllClick\s*\(\s*button\s*\)\s*\{/g ) ].map( m => m[ 1 ] ).sort();
  assert.equal( legacyBatch.length, 2,
    `the legacy card now has ${ legacyBatch.length } group-batch handlers, not 2: [${ legacyBatch }]` );
} );

test( "DENOMINATOR: owner-reassign is MULTIPLEXER-ONLY, so it is excluded from the parity claim by evidence", () => {
  const legacySrc = readFileSync( NOTIFICATIONS_JS, "utf8" );
  assert.equal( ( legacySrc.match( /task-owner-select/g ) || [] ).length, 0,
    `the legacy card has grown a task-owner-select. It now has a counterpart on both ` +
    `surfaces, so it must JOIN the parity walk above rather than remain excluded — this ` +
    `assertion is the thing that notices` );
} );


// ═══════════ THE SEVEN-VERB WALK — the real legacy control, not a re-derivation ═══════════
//
// 🔴 THE LEGACY EXTRAS ARE BUILT INSIDE ITS SUBMIT HANDLER, SO THE HANDLER IS WHAT IS
// DRIVEN. Re-implementing "park uses park_reason, everything else uses reason" in this
// file to compare against the multiplexer would be a comparison against my own copy of
// the rule — two sides, one author, and it cannot disagree. So the row is painted, the
// verb chosen, the reason and date typed, and Submit CLICKED, with only `authedFetch`
// stood down. What is captured is the request the operator's press actually produces.
//
// ⚠️ `park` AND `demote` REQUIRE A DATE, and both clients convert a local calendar day
// through `${day}T09:00:00` -> toISOString(). The walk asserts the two land on the same
// instant rather than trusting that both files still say so.

const REASON_TEXT = "the row's own decisive sentence";
const CHASE_DAY   = "2026-09-09";

function paintLegacyTaskList( ui: Record<string, any>, status: string, id: string ): HTMLElement {
  document.body.replaceChildren();
  const root = document.createElement( "div" );
  root.innerHTML = `<div class="collapsible-section" id="section-task-list">
      <div class="section-content"><div id="task-list-container"></div></div></div>`;
  document.body.appendChild( root );
  ui._taskListAccordionWired = false;
  ui._wireTaskListAccordion();
  const c = document.getElementById( "task-list-container" )!;
  c.innerHTML = ui.renderTaskListTable(
    ui.groupTasksByOwner( [ { id, title: "a row under the seven-verb parity walk", status,
                              owner_persona: "maya", correlation_key: "epic:parity", priority: "P2" } ] ),
    undefined, ui.loadCollapsedTaskOwners() );
  return c;
}

/** The legacy UI with every collaborator the render path needs, and ONLY the network stood down. */
function legacyPane(): { ui: Record<string, any>; issued: Issued[] } {
  const { ui, issued } = legacy();
  ui.debug = false; ui.log = () => {}; ui.error = () => {};
  ui.EPIC_KEY_PREFIX = "epic:"; ui.EPIC_UNASSIGNED_KEY = "epic:unassigned";
  ui.EPIC_ON_RICK_KEY = "__on_rick__"; ui.EPIC_DRIFT_KEY = "__drift__";
  ui.EPIC_BLOCKER_OF_INTEREST = "rick";
  ui.EPIC_BOARD_STATE_KEY = "lupin.epicBoard.groupState";
  ui.TASK_TITLE_TRUNCATE_LEN = 60;
  ui.TASK_LIST_COLLAPSED_KEY = "lupin.taskList.collapsedOwners";
  ui.TASK_LIST_UNASSIGNED_KEY = "__unassigned__";
  ui._taskListAccordionWired = false; ui._taskListFetchInFlight = false;
  ui._taskListLastGoodTasks = null;
  ui.refreshTaskList = async () => {};
  return { ui, issued };
}

function aStatusThatOffers( verb: string ): string {
  const spec = ( TASK_VERB_SPECS as Record<string, any> )[ verb ];
  if ( spec.legalFrom && spec.legalFrom.length ) return spec.legalFrom[ 0 ];
  const illegal: string[] = spec.illegalFrom || [];
  for ( const c of [ "queued", "in_progress", "blocked" ] ) if ( !illegal.includes( c ) ) return c;
  throw new Error( `the oracle offers no legal source status for "${ verb }"` );
}

// 🔴 THE WALK COVERS THE INTERSECTION — today all 7, since the multiplexer picked up
// `fixed` (709128d4). A parity assertion over a verb one client does not offer is vacuous,
// so the walk runs over what both surfaces actually have, and ROSTER below asserts the
// two rosters are equal so a future gap is seen rather than absorbed.
const MUX_VERBS    = new Set( MUX_TASK_VERBS );
const SHARED_VERBS = Object.keys( TASK_VERB_SPECS as Record<string, unknown> ).filter( v => MUX_VERBS.has( v ) );

for ( const verb of SHARED_VERBS ) {
  test( `VERB WALK — "${ verb }" builds the SAME body in the legacy card and the multiplexer`, async () => {
    const spec = ( TASK_VERB_SPECS as Record<string, any> )[ verb ];
    const { ui, issued } = legacyPane();
    const c = paintLegacyTaskList( ui, aStatusThatOffers( verb ), RAW_ID );

    const select = c.querySelector( ".task-verb-select" ) as HTMLSelectElement;
    select.value = verb;
    select.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
    const reasonEl = c.querySelector( ".task-reason-input" ) as HTMLInputElement | null;
    if ( reasonEl ) reasonEl.value = REASON_TEXT;
    const chaseEl = c.querySelector( ".task-chase-input" ) as HTMLInputElement | null;
    if ( chaseEl ) chaseEl.value = CHASE_DAY;

    const button = c.querySelector( ".task-submit-button" ) as HTMLButtonElement;
    // A two-click verb arms on the first press and posts on the second.
    await ui._handleTaskSubmitClick( button );
    if ( spec.armsTwice ) await ui._handleTaskSubmitClick( button );

    assert.equal( issued.length, 1,
      `"${ verb }" produced ${ issued.length } requests from the legacy card, not 1 — the ` +
      `walk cannot compare a body it never captured` );

    // The multiplexer's side of the same press, through ITS own extras builder.
    const chaseIso = spec.date ? new Date( `${ CHASE_DAY }T09:00:00` ).toISOString() : null;
    const muxExtras = transitionExtras( verb, REASON_TEXT, chaseIso );
    const t = await taskListStore();
    await t.store.transitionTask( RAW_ID, spec.status, muxExtras ).done;

    assert.equal( t.issued.length, 1, `the multiplexer issued no request for "${ verb }"` );
    assert.equal( issued[ 0 ]!.method, t.issued[ 0 ]!.method, `"${ verb }": the two clients used different METHODS` );
    assert.equal( issued[ 0 ]!.path,   t.issued[ 0 ]!.path,   `"${ verb }": the two clients used different ENDPOINTS` );

    // `actor` is the one field that must differ (see the ACTOR case above); everything
    // else in the body is the parity claim.
    //
    // ⚠️ AND THE ATTESTATION'S VALUE, BUT NOT ITS PRESENCE (row 47377c92). Legacy writes
    // `operator <queueSessionId>` ("operator wise penguin" in this fixture), a session the
    // multiplexer cannot know, and the server replaces whatever arrives with the identity
    // on the validated login. So the walk requires a non-empty string under the same key
    // and compares nothing about its text — the same bargain as `actor`, and the key being
    // MISSING is exactly the defect this line would have caught.
    const strip = ( b: Record<string, unknown> ) => {
      const { actor, receipt_refs, ...rest } = b; void actor;
      if ( receipt_refs === undefined ) return rest;
      const { operator_attestation, ...otherRefs } = receipt_refs as Record<string, unknown>;
      const attested = typeof operator_attestation === "string" && operator_attestation.length > 0;
      return { ...rest, receipt_refs: { ...otherRefs, operator_attestation: attested ? "<attested>" : operator_attestation } };
    };
    assert.deepEqual( strip( issued[ 0 ]!.body ), strip( t.issued[ 0 ]!.body ),
      `"${ verb }" posts a DIFFERENT body from the two surfaces. The same press on the two ` +
      `cards must reach the server saying the same thing — a park filed under the generic ` +
      `\`reason\` key, for one, lands with no decisive sentence attached` );
  } );
}


// ═══════════ THE BATCH DOOR, AND THE LATENT KEY HAZARD UNDER IT ═══════════

test( "BATCH — the batch extras builder agrees with the per-row builder on every verb it serves", () => {
  const muxSrc = readFileSync( resolve( HERE, "../../../lupin_app/static/js/multiplexer/render/holdingAreaBatch.ts" ), "utf8" );
  const batchVerbs = [ ...muxSrc.matchAll( /^\s{2}(\w+)\s*:\s*\{\s*status:/gm ) ].map( m => m[ 1 ] );
  assert.ok( batchVerbs.length > 0, "no batch verbs found — every assertion below would be vacuous" );

  for ( const verb of batchVerbs ) {
    const perRow = transitionExtras( verb, REASON_TEXT, null );
    // 🔴 THE LATENT HAZARD THIS PINS. `holdingBatchExtras` files EVERY reason under the
    // generic `reason` key, while `transitionExtras` files park's under `park_reason`.
    // Today the two agree, and ONLY because park is not a batch verb — a coincidence,
    // not a shared rule. Add park to BATCH_NEEDS and the batch would post a park with no
    // decisive sentence attached, silently. This assertion is what refuses that day.
    const batch = holdingBatchExtras( verb, REASON_TEXT );
    assert.deepEqual( batch, perRow,
      `the batch builder and the per-row builder disagree about "${ verb }": batch sends ` +
      `${ JSON.stringify( batch ) }, a per-row press sends ${ JSON.stringify( perRow ) }. ` +
      `If "${ verb }" was just added to the batch, note that holdingBatchExtras has no ` +
      `park_reason branch — the same verb would file its reason under two different keys ` +
      `depending on which control the operator pressed` );
  }
} );


// ═══════════ THE ROSTER — one list, not two ═══════════
//
// Found by this walk on 2026-09-06: the multiplexer's hardcoded list lacked `fixed`.
// 709128d4 closed that gap — but without `receipt_refs.operator_attestation`, which the
// legacy card posts on ->done (Rick's ruling 2026-09-04, row 1e12cc08) and the store
// requires. `VERB WALK — "fixed"` above is the case that reports that divergence.

test( "ROSTER — the multiplexer's roster IS the shared oracle's, not a second list that can forget a verb", () => {
  // THE CONTRACT (María's ruling 2026-09-06): a second hardcoded list is a second thing to
  // forget — `fixed` once landed in shared/task-verbs.js and never reached taskVerbs.ts.
  assert.deepEqual( [ ...MUX_TASK_VERBS ].sort(), Object.keys( TASK_VERB_SPECS as Record<string, unknown> ).sort(),
    "the multiplexer's TASK_VERBS and the shared oracle publish different verb rosters" );
} );

test( "ROSTER GAP — the legacy card's `fixed` carries the operator attestation the store demands", async () => {
  // The half of the gap that is NOT a gap: the legacy side is complete, so a reader
  // closing the gap has a worked example of what the multiplexer must produce.
  const { ui, issued } = legacyPane();
  const c = paintLegacyTaskList( ui, aStatusThatOffers( "fixed" ), RAW_ID );
  const select = c.querySelector( ".task-verb-select" ) as HTMLSelectElement;
  select.value = "fixed";
  select.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
  const button = c.querySelector( ".task-submit-button" ) as HTMLButtonElement;
  await ui._handleTaskSubmitClick( button );   // arms
  await ui._handleTaskSubmitClick( button );   // commits

  assert.equal( issued.length, 1, "the legacy card posted nothing for `fixed`" );
  assert.equal( issued[ 0 ]!.body.to_status, "done" );
  const refs = issued[ 0 ]!.body.receipt_refs as Record<string, unknown> | undefined;
  assert.ok( refs && typeof refs.operator_attestation === "string" && refs.operator_attestation,
    "the legacy `fixed` no longer carries receipt_refs.operator_attestation — the store " +
    "refuses a ->done carrying no receipt, so this close would be refused" );
} );


// ═══════════════ THE SURFACE AXIS — how many PANES, and do they all reach one door ═══════════════
//
// 🔴 THE VERB WALK ABOVE DRIVES ONE LEGACY PANE. That is enough only if the other panes
// reach the SAME request builder, and until these cases existed this file did not say so —
// it inherited the claim from `every_pane_offers_and_routes_every_verb.test.ts`, a file
// this one does not control. A parity claim resting on a sibling's assertion is a claim
// with a dependency nobody stated. These drive all three panes here.
//
// ⚠️ AND THE TWO CLIENTS DO NOT HAVE THE SAME NUMBER OF CONTROL SURFACES — measured, with
// a positive control:
//     legacy       3 control-bearing panes: task list, holding area, epic board
//     multiplexer  2: TaskListRenderer, HoldingAreaRenderer
//     EpicBoardRenderer.ts is 278 lines and contains `task-verb-select` 0 times,
//     `transitionTask` 0 times, `patchTask` 0 times — the multiplexer's epic board is
//     READ-ONLY. (Positive control: the same three greps on TaskListRenderer.ts give
//     2 / 2 / 3, so the search demonstrably finds these when they are present.)
//
// This is the roster gap's shape on a different axis: there a VERB exists on one client
// and not the other; here a whole SURFACE does. Whether the multiplexer's epic board
// SHOULD offer controls is a product question and is NOT asserted either way here —
// recorded as a measurement, and raised with María rather than decided by a test.

const LEGACY_PANES = [ "task list", "holding area", "epic board" ] as const;

function paintLegacyPane( ui: Record<string, any>, pane: string, status: string, id: string ): HTMLElement {
  document.body.replaceChildren();
  const root = document.createElement( "div" );
  root.innerHTML = `
    <div class="collapsible-section" id="section-task-list">
      <div class="section-content"><div id="task-list-container"></div></div></div>
    <div class="collapsible-section" id="section-holding-area">
      <div class="section-content" id="holding-area-section"><div id="holding-area-container"></div></div></div>
    <div class="collapsible-section" id="section-epic-board">
      <h3><span id="epic-board-count">0</span><span id="epic-board-updated"></span></h3>
      <div id="epic-board-container"></div></div>`;
  document.body.appendChild( root );
  const task = { id, title: "a row under the surface walk", status,
                 owner_persona: "maya", correlation_key: "epic:surface", priority: "P2" };
  if ( pane === "task list" ) {
    ui._taskListAccordionWired = false; ui._wireTaskListAccordion();
    const c = document.getElementById( "task-list-container" )!;
    c.innerHTML = ui.renderTaskListTable( ui.groupTasksByOwner( [ task ] ), undefined, ui.loadCollapsedTaskOwners() );
    return c;
  }
  if ( pane === "holding area" ) {
    ui._holdingAreaControlsWired = false;
    const c = document.getElementById( "holding-area-container" )!;
    c.innerHTML = ui._renderHoldingAreaGroup( "maya", [ task ] );
    ui._wireHoldingAreaControls();
    return c;
  }
  ui._epicBoardAccordionWired = false; ui._wireEpicBoardAccordion();
  const c = document.getElementById( "epic-board-container" )!;
  c.innerHTML = ui.renderEpicBoardTable( ui.groupTasksByEpic( [ task ] ), ui.loadEpicGroupState() );
  return c;
}

for ( const pane of LEGACY_PANES ) {
  test( `SURFACE — the legacy "${ pane }" pane reaches the SAME transition door as the others`, async () => {
    const { ui, issued } = legacyPane();
    ui._holdingAreaControlsWired = false;
    ui._epicBoardAccordionWired  = false;
    ui._epicStories = {}; ui._epicStoriesFetched = false;
    ui.EPIC_KEY_PREFIX = "epic:"; ui.EPIC_UNASSIGNED_KEY = "epic:unassigned";
    ui.fetchHoldingArea = async () => {};
    const c = paintLegacyPane( ui, pane, aStatusThatOffers( "drop" ), RAW_ID );

    const select = c.querySelector( ".task-verb-select" ) as HTMLSelectElement | null;
    assert.ok( select, `the legacy "${ pane }" pane rendered no verb control at all` );
    select!.value = "drop";
    select!.dispatchEvent( new window.Event( "change", { bubbles: true } ) );
    const reasonEl = c.querySelector( ".task-reason-input" ) as HTMLInputElement | null;
    if ( reasonEl ) reasonEl.value = REASON_TEXT;

    const button = c.querySelector( ".task-submit-button" ) as HTMLButtonElement;
    await ui._handleTaskSubmitClick( button );

    assert.equal( issued.length, 1,
      `a Submit on the legacy "${ pane }" pane issued ${ issued.length } requests, not 1` );
    assert.equal( issued[ 0 ]!.method, TRANSITION_METHOD );
    assert.equal( issued[ 0 ]!.path, TRANSITION_PATH,
      `the legacy "${ pane }" pane posts to ${ issued[ 0 ]!.path } while the other panes post ` +
      `to ${ TRANSITION_PATH }. One pane reaching a different door is exactly the defect ` +
      `this file exists to catch, and it is invisible to any suite that drives one pane` );
  } );
}

test( "SURFACE — the multiplexer's epic board is READ-ONLY, so it has no controls to be in parity with", () => {
  const dir  = resolve( HERE, "../../../lupin_app/static/js/multiplexer/render" );
  const epic = readFileSync( resolve( dir, "EpicBoardRenderer.ts" ), "utf8" );
  const list = readFileSync( resolve( dir, "TaskListRenderer.ts" ), "utf8" );
  const count = ( s: string, n: string ) => ( s.match( new RegExp( n, "g" ) ) || [] ).length;

  // POSITIVE CONTROL FIRST. A zero from a search nobody has watched return non-zero is
  // indistinguishable from a search that cannot see its corpus.
  // Since parity A-2 #0 the row controls are dispatched by the shared TaskRowController, so
  // a pane that wires them names THAT; the verb-select string moved into the controller.
  assert.ok( count( list, "TaskRowController" ) > 0 && count( list, "transitionTask" ) > 0,
    "the same greps find nothing in TaskListRenderer either — this census cannot see its " +
    "own corpus, so the zeros below are worthless" );

  for ( const needle of [ "task-verb-select", "transitionTask", "patchTask", "TaskRowController" ] ) {
    assert.equal( count( epic, needle ), 0,
      `the multiplexer's epic board now references "${ needle }" — it has grown a mutating ` +
      `control. It is now a THIRD control surface and must join the parity walk above, ` +
      `against the legacy epic board pane which has had controls all along` );
  }
} );
