// Parity row A-1a (now-part) — operator state survives a poll on the Task List and
// the Holding Area. 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 EVERY PANE TEST PUTS A REAL POLL TICK BETWEEN THE OPERATOR'S ACTION AND THE CLICK.
// The stores are the real TaskListStore / HoldingAreaStore, fired through their injected
// `setIntervalFn`. Legacy's post-mortem of Rick's dead button is the reason: "every test
// called the handler by name so no poll could run between them." A test that types,
// calls restore by name and asserts is testing the function, not the property.
//
// The property (spec, "The contract, in one paragraph"): a poll tick landing between an
// operator's keystroke and their click must not change what that click does.
//
// ⚠️ NOT YET HERE, BY RULING (Mr. Radio 🦉, recorded on row e55cab0d): the pending-priority
// category through the real renderer waits for A-2 #0, and the Epic Board waits for A-2 #9.
// The module tests at the foot exercise the priority slot's feature-detect only; they are
// not a substitute for the renderer test that A-2 #0 owes.
//
// 🔴 NEVER `assert.equal` TWO DOM NODES. On failure node:assert inspects both to build a
// diff, walks happy-dom's whole object graph, and the process is SIGKILLed for memory —
// measured here against the pre-fix renderers, where the focus test took the runner down
// and every test after it went unreported. Compare with `===` inside `assert.ok`.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { createHoldingAreaRenderer } from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import { createTaskListStore, type TaskListApiClient } from "../../../../lupin_app/static/js/multiplexer/stores/TaskListStore";
import { createHoldingAreaStore, type HoldingAreaApiClient } from "../../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";
import {
  KEY_SEP,
  captureOperatorState,
  operatorInputByKey,
  operatorInputKey,
  restoreOperatorState,
} from "../../../../lupin_app/static/js/multiplexer/render/operatorState";
import { renderRowError } from "../../../../lupin_app/static/js/multiplexer/render/templates/rowDisclosure";
import type { TaskItem, TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => { localStorage.clear(); document.body.replaceChildren(); } );

const settle = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

function makeTimers() {
  const intervals: Array<() => void> = [];
  return {
    setIntervalFn   : ( cb: () => void ): number => intervals.push( cb ),
    clearIntervalFn : (): void => undefined,
    async poll(): Promise<void> { for ( const cb of intervals ) cb(); await settle(); },
  };
}

function openRow( id: string, title: string ): TaskItem {
  return { id, title, status: "in_progress", priority: "P2", owner_persona: "amy" } as unknown as TaskItem;
}

function heldRow( id: string ): TaskItem {
  return { id, title: `row ${ id }`, status: "not_approved", priority: "P2", created_by: "krishna 0e61abe3" } as unknown as TaskItem;
}

function inPane<T extends Element>( pane: ParentNode, selector: string, attr: string, value: string ): T {
  const el = Array.from( pane.querySelectorAll<T>( selector ) ).find( ( e ) => e.getAttribute( attr ) === value );
  assert.ok( el, `no ${ selector } with ${ attr }=${ value } in the pane` );
  return el;
}

function choose( select: HTMLSelectElement, value: string ): void {
  select.value = value;
  select.dispatchEvent( new Event( "change", { bubbles: true } ) );
}

// ---------------------------------------------------------------------------
// Task List
// ---------------------------------------------------------------------------

function mountTaskList( tasks: TaskItem[] ) {
  const timers = makeTimers();
  const bus    = createEventBusForTesting();
  let composite: TaskListComposite | "fail" = { tasks, count: tasks.length };
  const posts: Array<{ path: string; body: Record<string, unknown> }> = [];
  const api: TaskListApiClient = {
    get   : async <T,>(): Promise<T> => {
      if ( composite === "fail" ) { const e = new Error( "500" ) as Error & { status: number }; e.status = 500; throw e; }
      return composite as T;
    },
    patch : async <T,>(): Promise<T> => null as T,
    post  : async <T,>( path: string, body: unknown ): Promise<T> => {
      posts.push( { path, body: body as Record<string, unknown> } ); return {} as T;
    },
  };
  const store = createTaskListStore( {
    bus, api, nowFn: () => 0, setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createTaskListRenderer( { eventBus: bus, stores: { taskList: store }, nowDateFn: () => new Date( 0 ) } );
  renderer.mount( root );
  store.startPolling();
  const pane = root.querySelector( ".task-list-container" ) as HTMLElement;
  return {
    timers, pane, posts,
    set( next: TaskItem[] | "fail" ) { composite = next === "fail" ? "fail" : { tasks: next, count: next.length }; },
    disclose( id: string ) { inPane<HTMLElement>( pane, ".task-disclose-button", "data-task-id", id ).click(); },
    verb    : ( id: string ) => inPane<HTMLSelectElement>( pane, ".task-verb-select", "data-task-id", id ),
    reason  : ( id: string ) => inPane<HTMLInputElement>( pane, ".task-reason-input", "data-task-id", id ),
    submit  : ( id: string ) => inPane<HTMLButtonElement>( pane, ".task-submit-button", "data-task-id", id ),
    stripe  : ( id: string ) => inPane<HTMLElement>( pane, ".task-row-error-stripe", "data-error-for", id ),
    controls: ( id: string ) => inPane<HTMLElement>( pane, ".task-controls-row", "data-controls-for", id ),
    unmount() { renderer.unmount(); root.remove(); },
  };
}

test( "RICK'S DEAD BUTTON: a reason typed, a poll, then Submit — the drop still leaves the browser WITH the reason", async () => {
  const h = mountTaskList( [ openRow( "t1", "first" ) ] );
  await settle();
  h.disclose( "t1" );
  choose( h.verb( "t1" ), "drop" );
  h.reason( "t1" ).value = "superseded by the v2 door";

  h.set( [ openRow( "t1", "second" ) ] );
  await h.timers.poll();
  assert.match( h.pane.textContent ?? "", /second/, "positive control: the poll really repainted the pane" );

  h.submit( "t1" ).click();
  await settle();
  assert.equal( h.posts.length, 1, "the click sent nothing — the poll wiped the reason or the verb" );
  assert.equal( h.posts[ 0 ]!.body.reason, "superseded by the v2 door" );
  h.unmount();
} );

test( "the verb goes back BEFORE the text, so Park's date box exists to receive its date", async () => {
  const h = mountTaskList( [ openRow( "t1", "first" ) ] );
  await settle();
  h.disclose( "t1" );
  choose( h.verb( "t1" ), "park" );
  h.reason( "t1" ).value = "waiting on Rick";
  inPane<HTMLInputElement>( h.pane, ".task-chase-input", "data-task-id", "t1" ).value = "2026-09-20";

  await h.timers.poll();
  assert.equal( h.verb( "t1" ).value, "park" );
  assert.equal( h.reason( "t1" ).value, "waiting on Rick" );
  assert.equal( inPane<HTMLInputElement>( h.pane, ".task-chase-input", "data-task-id", "t1" ).value, "2026-09-20",
    "the date was dropped — text restored before its verb built the box" );
  h.unmount();
} );

test( "an open controls row stays open, and a shown refusal stays shown, across a poll", async () => {
  const h = mountTaskList( [ openRow( "t1", "first" ), openRow( "t2", "other" ) ] );
  await settle();
  h.disclose( "t1" );
  h.submit( "t1" ).click();   // no verb chosen → a refusal stripe
  const refusal = h.stripe( "t1" ).textContent ?? "";
  assert.ok( refusal.length > 0 && !h.stripe( "t1" ).hidden, "positive control: the refusal is shown" );

  await h.timers.poll();
  assert.equal( h.controls( "t1" ).hidden, false, "the poll re-collapsed the row mid-sentence" );
  assert.equal( inPane<HTMLElement>( h.pane, ".task-disclose-button", "data-task-id", "t1" ).getAttribute( "aria-expanded" ), "true" );
  assert.equal( h.stripe( "t1" ).hidden, false, "the poll wiped the only explanation of the refusal" );
  assert.equal( h.stripe( "t1" ).textContent, refusal );
  assert.equal( h.controls( "t2" ).hidden, true, "a row nobody opened came back open" );
  h.unmount();
} );

test( "focus and the caret come back to the box the operator was typing in", async () => {
  const h = mountTaskList( [ openRow( "t1", "first" ) ] );
  await settle();
  h.disclose( "t1" );
  choose( h.verb( "t1" ), "drop" );
  const box = h.reason( "t1" );
  box.value = "half a sentence";
  box.focus();
  box.setSelectionRange( 4, 6 );
  assert.ok( document.activeElement === box, "positive control: happy-dom observes focus" );

  await h.timers.poll();
  const fresh = h.reason( "t1" );
  assert.ok( fresh !== box, "positive control: the poll replaced the node" );
  assert.ok( document.activeElement === fresh, "the next keystroke would land nowhere" );
  assert.deepEqual( [ fresh.selectionStart, fresh.selectionEnd ], [ 4, 6 ] );
  h.unmount();
} );

test( "the unreachable repaint of last-known rows keeps the typed reason too", async () => {
  const h = mountTaskList( [ openRow( "t1", "first" ) ] );
  await settle();
  h.disclose( "t1" );
  choose( h.verb( "t1" ), "drop" );
  h.reason( "t1" ).value = "kept through an outage";
  h.set( "fail" );
  await h.timers.poll();
  assert.match( h.pane.textContent ?? "", /unreachable/i, "positive control: the unreachable branch painted" );
  assert.equal( h.reason( "t1" ).value, "kept through an outage" );
  h.unmount();
} );

test( "a row the poll no longer returns is LEFT GONE — its typed text is not re-created anywhere", async () => {
  const h = mountTaskList( [ openRow( "t1", "first" ), openRow( "t2", "stays" ) ] );
  await settle();
  h.disclose( "t1" );
  choose( h.verb( "t1" ), "drop" );
  h.reason( "t1" ).value = "orphaned";
  h.set( [ openRow( "t2", "stays" ) ] );
  await h.timers.poll();
  assert.equal( h.pane.querySelectorAll( ".task-verb-select" ).length, 1 );
  assert.ok( !Array.from( h.pane.querySelectorAll<HTMLInputElement>( "input" ) ).some( ( i ) => i.value === "orphaned" ) );
  h.unmount();
} );

// ---------------------------------------------------------------------------
// Holding Area — the batch reason is keyed by FILER, not task id
// ---------------------------------------------------------------------------

test( "HOLDING AREA: a batch won't-fix reason typed, a poll, then Won't fix all — every row posts WITH the reason", async () => {
  const timers = makeTimers();
  const bus    = createEventBusForTesting();
  let rows = [ heldRow( "a" ), heldRow( "b" ) ];
  const posts: Array<{ path: string; body: Record<string, unknown> }> = [];
  const api: HoldingAreaApiClient = {
    get  : async <T,>(): Promise<T> => ( { tasks: rows, count: rows.length } ) as T,
    post : async <T,>( path: string, body: unknown ): Promise<T> => {
      posts.push( { path, body: body as Record<string, unknown> } ); return {} as T;
    },
  };
  const store = createHoldingAreaStore( {
    bus, api, nowFn: () => 0, setIntervalFn: timers.setIntervalFn, clearIntervalFn: timers.clearIntervalFn,
  } );
  const root = document.createElement( "div" );
  document.body.appendChild( root );
  const renderer = createHoldingAreaRenderer( { eventBus: bus, store, nowDateFn: () => new Date( 0 ) } );
  renderer.mount( root );
  store.startPolling();
  await settle();
  const pane = root.querySelector( ".holding-area-container" ) as HTMLElement;
  const reasonBox = (): HTMLInputElement => pane.querySelector( ".holding-wont-fix-all-reason" ) as HTMLInputElement;

  const box = reasonBox();
  box.value = "duplicate of the epic";
  box.focus();
  box.setSelectionRange( 3, 3 );
  rows = [ heldRow( "a" ), heldRow( "b" ) ];
  await timers.poll();
  assert.ok( reasonBox() !== box, "positive control: the poll replaced the batch reason box" );
  assert.equal( reasonBox().value, "duplicate of the epic", "the poll wiped a whole group's typing" );
  assert.ok( document.activeElement === reasonBox(), "focus left the batch reason box" );

  ( pane.querySelector( ".holding-wont-fix-all" ) as HTMLButtonElement ).click();
  await settle();
  const transitions = posts.filter( ( p ) => p.path.endsWith( "/transition" ) );
  assert.equal( transitions.length, 2, "the batch refused — the reason was blank to the handler" );
  assert.ok( transitions.every( ( p ) => p.body.reason === "duplicate of the epic" ) );
  renderer.unmount();
  root.remove();
} );

// ---------------------------------------------------------------------------
// The module alone — edges no pane reaches today
// ---------------------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>( tag: K, cls: string, attrs: Record<string, string> = {} ): HTMLElementTagNameMap[ K ] {
  const e = document.createElement( tag );
  e.className = cls;
  for ( const [ k, v ] of Object.entries( attrs ) ) e.setAttribute( k, v );
  return e;
}

test( "module: the key is attr NUL owner NUL class, task id wins, and an ownerless or unnamed box has none", () => {
  const both = el( "input", "task-action-input task-reason-input", { "data-task-id": "t1", "data-filer": "f" } );
  assert.equal( operatorInputKey( both ), [ "data-task-id", "t1", "task-reason-input" ].join( KEY_SEP ) );
  assert.equal( operatorInputKey( el( "input", "task-action-input holding-wont-fix-all-reason", { "data-filer": "Krishna" } ) ),
    [ "data-filer", "Krishna", "holding-wont-fix-all-reason" ].join( KEY_SEP ) );
  assert.equal( operatorInputKey( el( "input", "task-action-input task-reason-input" ) ), null );
  assert.equal( operatorInputKey( el( "input", "task-action-input other", { "data-task-id": "t1" } ) ), null );
  assert.ok( operatorInputByKey( document.body, "not-a-key" ) === null, "a malformed key resolved to an element" );
} );

test( "module: an id full of selector punctuation round-trips, because no id ever enters a selector", () => {
  const pane = document.createElement( "div" );
  const nasty = `a"] , b[x='y'] \\`;
  pane.appendChild( el( "input", "task-action-input task-reason-input", { "data-task-id": nasty } ) );
  const key = operatorInputKey( pane.firstElementChild! )!;
  assert.ok( operatorInputByKey( pane, key ) === pane.firstElementChild, "the punctuated id did not round-trip" );
} );

test( "module: the triage date is focus-tracked but NOT value-swept (ruling 5)", () => {
  const pane   = document.createElement( "div" );
  document.body.appendChild( pane );
  const triage = el( "input", "task-action-input task-request-triage", { "data-task-id": "t1", type: "date" } );
  pane.appendChild( triage );
  triage.value = "2026-09-20";
  triage.focus();
  const state = captureOperatorState( pane );
  assert.deepEqual( state.inputs, [] );
  assert.equal( state.focusKey, operatorInputKey( triage ) );
  assert.deepEqual( [ state.selStart, state.selEnd ], [ 10, 10 ], "a date's null selection defaults to the value's end" );

  // Restoring focus into a type that refuses a selection range is tolerated.
  const fresh = triage.cloneNode() as HTMLInputElement;
  pane.replaceChildren( fresh );
  assert.doesNotThrow( () => restoreOperatorState( pane, state, { renderRowError: () => undefined } ) );
  assert.ok( document.activeElement === fresh, "focus did not return to the triage box" );
} );

test( "module: the text step skips an empty capture, a missing box and a DISABLED box", () => {
  const pane = document.createElement( "div" );
  const disabled = el( "input", "task-action-input task-reason-input", { "data-task-id": "t1" } );
  const live     = el( "input", "task-action-input task-chase-input", { "data-task-id": "t1" } );
  pane.append( disabled, live );
  live.value = "painted by the render";
  const state = {
    inputs: [ [ operatorInputKey( disabled )!, "a reason the verb just emptied" ], [ operatorInputKey( live )!, "" ],
              [ [ "data-task-id", "gone", "task-reason-input" ].join( KEY_SEP ), "x" ] ] as Array<[ string, string ]>,
    selects: [], priorities: [], stripes: [], disclosed: [], focusKey: null, selStart: 0, selEnd: 0,
  };
  disabled.disabled = true;
  restoreOperatorState( pane, state, { renderRowError: () => undefined } );
  assert.equal( disabled.value, "", "a reason was written back into a box its verb disabled" );
  assert.equal( live.value, "painted by the render", "a stale empty overwrote fresh content" );
} );

test( "module: only a PENDING priority with data-original is captured, and it is restored only through a handler and a real option", () => {
  const pane = document.createElement( "div" );
  const sel = ( id: string, value: string, original: string | null ): HTMLSelectElement => {
    const s = el( "select", "task-priority-select", { "data-task-id": id } );
    if ( original !== null ) s.setAttribute( "data-original", original );
    for ( const p of [ "P1", "P2", "P3" ] ) { const o = document.createElement( "option" ); o.value = p; s.appendChild( o ); }
    s.value = value;
    return s;
  };
  pane.append( sel( "pending", "P1", "P2" ), sel( "untouched", "P2", "P2" ), sel( "no-original", "P1", null ) );
  const state = captureOperatorState( pane );
  assert.deepEqual( state.priorities, [ [ "pending", "P1" ] ] );

  const seen: string[] = [];
  const fresh = (): void => { pane.replaceChildren( sel( "pending", "P2", "P2" ) ); };

  fresh();
  restoreOperatorState( pane, state, { renderRowError: () => undefined } );
  assert.equal( ( pane.firstElementChild as HTMLSelectElement ).value, "P2", "restored with no handler to recompute Update" );

  fresh();
  restoreOperatorState( pane, { ...state, priorities: [ [ "pending", "P9" ], [ "gone", "P1" ], [ "pending", "P1" ] ] },
    { renderRowError: () => undefined, onPriorityChange: ( s ) => seen.push( s.value ) } );
  assert.deepEqual( seen, [ "P1" ], "an option-less value or an absent row reached the handler" );
} );

test( "module: capture skips an idless verb, stripe or controls row, and a hidden or text-less stripe", () => {
  const pane = document.createElement( "div" );
  const verb = el( "select", "task-verb-select" );
  const o = document.createElement( "option" ); o.value = "drop"; verb.appendChild( o ); verb.value = "drop";
  const idless  = el( "tr", "task-row-error-stripe" );
  const hidden  = el( "tr", "task-row-error-stripe", { "data-error-for": "t1" } ); hidden.hidden = true;
  const noCell  = el( "tr", "task-row-error-stripe", { "data-error-for": "t2" } );
  const ctl     = el( "tr", "task-controls-row" );
  pane.append( verb, idless, hidden, noCell, ctl );
  pane.appendChild( el( "input", "task-action-input task-reason-input" ) );   // no owner → no key
  const state = captureOperatorState( pane );
  assert.deepEqual( [ state.inputs, state.selects, state.stripes, state.disclosed ], [ [], [], [ [ "t2", "" ] ], [] ] );

  const painted: string[] = [];
  restoreOperatorState( pane, { ...state, disclosed: [ "absent" ], selects: [ [ "absent", "drop" ] ] },
    { renderRowError: ( id ) => painted.push( id ) } );
  assert.deepEqual( painted, [], "an empty refusal was re-painted" );
} );

test( "module: disclosure restores without a toggle button, and an absent focus target is skipped", () => {
  const pane = document.createElement( "div" );
  const row  = el( "tr", "task-controls-row", { "data-controls-for": "t1" } );
  row.hidden = true;
  pane.appendChild( row );
  restoreOperatorState( pane, {
    inputs: [], selects: [], priorities: [], stripes: [], disclosed: [ "t1" ],
    focusKey: [ "data-task-id", "gone", "task-reason-input" ].join( KEY_SEP ), selStart: 0, selEnd: 0,
  }, { renderRowError: () => undefined } );
  assert.equal( row.hidden, false );
} );

test( "shared renderRowError: pane-scoped, a missing stripe is a no-op, an empty message hides", () => {
  const pane = document.createElement( "div" );
  const other = document.createElement( "div" );
  const mk = (): HTMLElement => { const tr = el( "tr", "task-row-error-stripe", { "data-error-for": "t1" } ); tr.hidden = true; tr.appendChild( document.createElement( "td" ) ); return tr; };
  const mine = mk(); const theirs = mk();
  pane.appendChild( mine ); other.appendChild( theirs );

  renderRowError( pane, "t1", "refused" );
  assert.equal( mine.hidden, false );
  assert.equal( mine.getAttribute( "role" ), "alert" );
  assert.equal( theirs.hidden, true, "the refusal appeared in a pane the operator is not looking at" );
  renderRowError( pane, "t1", "" );
  assert.equal( mine.hidden, true );
  assert.doesNotThrow( () => renderRowError( pane, "absent", "x" ) );
} );

test( "module: a pane with no verb handler (the Holding Area today) gets its verb value back and nothing else", () => {
  const pane = document.createElement( "div" );
  const verb = el( "select", "task-verb-select", { "data-task-id": "t1" } );
  for ( const v of [ "", "approve" ] ) { const o = document.createElement( "option" ); o.value = v; verb.appendChild( o ); }
  pane.appendChild( verb );
  restoreOperatorState( pane, {
    inputs: [], selects: [ [ "t1", "approve" ] ], priorities: [], stripes: [], disclosed: [], focusKey: null, selStart: 0, selEnd: 0,
  }, { renderRowError: () => undefined } );
  assert.equal( verb.value, "approve" );
} );
