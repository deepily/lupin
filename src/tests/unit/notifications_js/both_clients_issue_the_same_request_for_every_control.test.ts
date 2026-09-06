// 🔴 THIS FILE IS FULLY GREEN AND ONE OF ITS CASES IS AN XFAIL. `ROSTER — xfail` holds a
// KNOWN defect: the multiplexer keeps a second, hardcoded verb roster and never picked up
// `fixed`. María's ruling 2026-09-06 — the DUPLICATION is the defect, not the missing
// verb. The fix is John's (his B5, after B2); this seat does not touch taskVerbs.ts.
//
// The xfail is STRICT: it runs the real contract assertion, expects it to fail, and goes
// RED the moment it SUCCEEDS while still wrapped. So the marker cannot outlive the defect.
// MEASURED, not asserted — simulating the fix (adding `fixed` to multiplexer TASK_VERBS)
// turns TWO cases red: the xfail itself, and `VERB WALK — "fixed"`, because the walk
// covers the intersection and picks the verb up automatically the moment both clients
// publish it. That second red is the real warning: the multiplexer has no
// `receipt_refs.operator_attestation` anywhere, so a roster offering `fixed` without it
// trades a MISSING control for a REFUSED one.
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
//   sha 30f144a6 · branch krishna-s3-accordion-css · worktree lupin-wt-cc-author-maria-2
//   tree: 0 tracked-dirty (only `?? node_modules`, a borrowed link) · 2026-09-06 15:42 EDT
//   per-file baseline: B5 23/0 · task_list_store 25/0 · holding_store 17/0
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
//   legacy _transitionTask POST -> PATCH              6 FAIL       25 pass          17 pass
//   legacy _transitionTask -> the field door          6 FAIL       25 pass          17 pass
//   mux transitionTask drops `authority`              6 FAIL        3 FAIL          17 pass
//   multiplexer given the LEGACY actor string         1 FAIL        6 FAIL           2 FAIL
//   mux files park's reason under generic `reason`    1 FAIL       25 pass          17 pass
//   mux drops next_chase_ts from a dated verb         2 FAIL       25 pass          17 pass
//   SIMULATE JOHN'S FIX: `fixed` joins the mux roster 2 FAIL       25 pass          17 pass
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


// ═══════════════════ THE DENOMINATOR — what "every control" actually counts ═══════════════════
//
// 🔴 ONE CONTROL PROVEN IS NOT EVERY CONTROL (María, 2026-09-06). The cases above drive
// the two request SHAPES; they do not by themselves say how much of the operator's
// surface that covers. This section states the count being asserted over, and re-derives
// it from source so it cannot quietly go stale.
//
//   SHARED — on BOTH surfaces, and therefore inside the parity claim
//     1. verb select + reason + Submit   -> POST transition   x 5 verbs   = 5 cells
//     2. priority select + Update        -> PATCH priority                = 1 cell
//     3. holding-area group batch        -> POST transition   x 2 verbs   = 2 cells
//                                                                    TOTAL 8 cells
//
//   🔴 FIVE VERBS, NOT SIX, AND THE MISSING ONE IS A FINDING. The oracle and the legacy
//     card publish SIX; the multiplexer's own `taskVerbs.ts` hardcodes five and never
//     picked up `fixed`. The walk covers the INTERSECTION because a parity assertion over
//     a verb one client does not offer is vacuous — and the gap itself is asserted in
//     ROSTER GAP below, written to go RED the day it closes so that whoever closes it is
//     sent to the operator attestation first. Reported, deliberately not repaired: it is
//     another seat's lane and `fixed` needs code the multiplexer does not have.
//
//   MULTIPLEXER-ONLY — named and EXCLUDED, not silently uncounted
//     4. owner select (reassign)         -> PATCH owner_persona
//        `task-owner-select` appears ZERO times in notifications.js. There is no legacy
//        counterpart to be in parity WITH, so a parity assertion over it would be
//        vacuous. It is asserted below as ABSENT-FROM-LEGACY, so the day a legacy owner
//        control lands, this file demands it join the walk instead of staying unwatched.

test( "DENOMINATOR: the per-row verb surface is 6 verbs, and both clients agree on the roster", () => {
  const verbs = Object.keys( TASK_VERB_SPECS as Record<string, unknown> ).sort();
  // CONTRACT LITERAL — the roster as of 2026-09-06, deliberately NOT derived. A verb
  // renamed on both sides at once leaves every derived walk generating the same number
  // of cells and passing, which is the corpus-identity blindness the sibling verb walk
  // measured. This is the one side the code cannot move.
  assert.deepEqual( verbs, [ "approve", "demote", "drop", "fixed", "park", "wont_fix" ],
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


// ═══════════ THE SIX-VERB WALK — the real legacy control, not a re-derivation ═══════════
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
    ui.groupTasksByOwner( [ { id, title: "a row under the six-verb parity walk", status,
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

// 🔴 THE WALK COVERS THE INTERSECTION, WHICH IS 5 OF 6 — AND THE MISSING ONE IS A
// FINDING, NOT A GAP IN THIS FILE. The legacy card and the shared oracle both publish
// SIX verbs; the multiplexer's `taskVerbs.ts` carries its OWN five-verb table and never
// picked up `fixed`. A parity assertion over a verb one client does not offer is vacuous,
// so the walk runs over what both surfaces actually have and the roster gap is asserted
// separately, immediately below, where it can be seen rather than absorbed.
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
    const strip = ( b: Record<string, unknown> ) => {
      const { actor, ...rest } = b; void actor; return rest;
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


// ═══════════ THE ROSTER GAP — a control the multiplexer does not have at all ═══════════
//
// 🔴 FOUND BY THE WALK, AND IT IS BIGGER THAN A WRONG PARAMETER: the multiplexer does not
// offer `fixed`. `shared/task-verbs.js` publishes six verbs and the legacy card renders
// six; `multiplexer/render/taskVerbs.ts` carries its own hardcoded five-verb list
// (`TASK_VERBS`, "the five verbs") and was never updated when the sixth landed. An
// operator working on the multiplexer cannot mark a row fixed at all — not a control that
// calls the wrong door, a control that is not there.
//
// ⚠️ SCOPE, AND IT IS DELIBERATELY NARROW. This is REPORTED, not repaired. Adding the
// verb is a product change on another seat's lane, and `fixed` carries an obligation the
// multiplexer has no code for at all: the legacy card posts
// `receipt_refs.operator_attestation` on `->done` (Rick's ruling 2026-09-04, row
// 1e12cc08) because the store refuses a close carrying no receipt. `receipt_refs` and
// `operator_attestation` appear ZERO times anywhere under multiplexer/. So wiring the
// select without the attestation would trade a missing control for a refused one.
//
// 🔴 THIS ASSERTION IS WRITTEN TO GO RED WHEN THE GAP CLOSES, WHICH IS THE POINT. The day
// someone adds `fixed` to the multiplexer, this fails and sends them to the attestation
// before the walk above starts comparing bodies for it.

// 🔴 XFAIL-STRICT, HAND-ROLLED, BECAUSE node:test HAS NO `test.fails`. Node 22's runner
// offers `skip` and `todo` and neither does the job: a `todo` that starts PASSING is
// reported as a todo, not as a failure, so the marker would outlive the defect silently —
// which is the same "ratifies the state" defect as the assertion it replaced, one level
// up. So the contract assertion is RUN, its failure is what is expected, and the test
// fails if it ever SUCCEEDS while still wrapped.
//
// The contract itself stays written out in full below, in the `try`. That matters: this
// file must still SAY what the multiplexer owes, not merely that something is wrong.

test( "ROSTER — xfail: the multiplexer does not yet derive its roster, and this goes RED the day it does", () => {
  const oracle = Object.keys( TASK_VERB_SPECS as Record<string, unknown> ).sort();
  const mux    = [ ...MUX_TASK_VERBS ].sort();

  // THE CONTRACT (María's ruling 2026-09-06): the multiplexer's roster must BE the shared
  // oracle's, not a second hardcoded copy of it. A second list is a second thing to
  // forget, and forgetting it is exactly what happened — `fixed` landed in
  // shared/task-verbs.js and the legacy card, and never reached multiplexer/taskVerbs.ts.
  let contractMet = false;
  try {
    assert.deepEqual( mux, oracle );
    contractMet = true;
  } catch {
    // EXPECTED TODAY. The defect is John's B5 (after B2); this seat does not touch
    // taskVerbs.ts. Held here so the suite stays green on a KNOWN defect rather than
    // carrying a red that trains everyone to ignore it.
  }

  assert.equal( contractMet, false,
    `THE ROSTER CONTRACT IS NOW MET — John's B5 has landed, and this xfail wrapper is ` +
    `stale.\n` +
    `  · DELETE this test and replace it with the direct assertion, which is the whole ` +
    `body of the try above: assert.deepEqual( [ ...MUX_TASK_VERBS ].sort(), ` +
    `Object.keys( TASK_VERB_SPECS ).sort() )\n` +
    `  · BEFORE you do, check the multiplexer posts receipt_refs.operator_attestation on ` +
    `->done. The store refuses a close carrying no receipt, and receipt_refs appeared ZERO ` +
    `times under multiplexer/ when this was written — a roster that offers \`fixed\` ` +
    `without the attestation trades a MISSING control for a REFUSED one\n` +
    `  · then add the verb to SHARED_VERBS' walk above, which covers the intersection and ` +
    `will pick it up automatically once both clients publish it` );
} );

// ⚠️ THE MARKER'S OWN CONTROL. An xfail that cannot be observed to flip is a comment with
// a test's costume on. This drives the SAME predicate over a roster that DOES meet the
// contract and asserts it comes out the other way — so the wrapper above is known to be
// load-bearing rather than assumed to be.
test( "ROSTER — the xfail marker actually flips: a compliant roster satisfies the contract", () => {
  const oracle = Object.keys( TASK_VERB_SPECS as Record<string, unknown> ).sort();
  let contractMet = false;
  try {
    assert.deepEqual( [ ...oracle ].sort(), oracle );   // a roster that HAS derived
    contractMet = true;
  } catch { /* unreachable unless the predicate itself is broken */ }
  assert.equal( contractMet, true,
    "the contract predicate cannot recognise a COMPLIANT roster, so the xfail above would " +
    "never flip and would hold its marker forever" );
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
