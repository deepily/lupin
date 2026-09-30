// Guard — parity A-2 #0: the shared row controls, built once, reach every pane that
// paints the shared row.
//
// 🔴 WHAT WAS WRONG AT 807621f8, MEASURED BEFORE THIS FILE EXISTED:
//   · the Holding Area painted the shared row and listened only for its two batch
//     buttons — Submit, ⋯, 📄, the id cell, priority and owner all reached no handler
//     (Phase 2 A9 H4 / plan §6a T7)
//   · no pane had the reason mic 🎤 (A8 T7)
//   · no pane offered the drop-reason suggestions (A8 T8)
//   · the priority select committed on CHANGE; the lead stages it behind an Update
//     button that stays disabled until the value moves (A8 T9)
//
// ⚠️ EVERY PANE CASE DRIVES THE ASSEMBLED RENDERER, not the controller alone. A
// component can be complete, correct and covered and never mounted; the Holding
// Area's row was exactly that.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting, type EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createTaskListRenderer } from "../../../../lupin_app/static/js/multiplexer/render/TaskListRenderer";
import { createHoldingAreaRenderer } from "../../../../lupin_app/static/js/multiplexer/render/HoldingAreaRenderer";
import {
  TaskRowController,
  MIC_NO_REASON_BOX,
  reasonMicContextId,
  type TaskRowRecorderLike,
} from "../../../../lupin_app/static/js/multiplexer/render/taskRowController";
import {
  DROP_REASON_DATALIST_ID,
  DROP_REASON_SUGGESTIONS,
  PRIORITY_UPDATE_IDLE_TITLE,
  REASON_MIC_TITLE,
  ensureDropReasonDatalist,
  renderPriorityControl,
} from "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowControls";
import { renderDisclosedRow } from "../../../../lupin_app/static/js/multiplexer/render/templates/taskRowDisclosed";
import type { TaskItem, TaskListComposite } from "../../../../lupin_app/static/js/multiplexer/render/taskListModel";
import type { RecordingManagerStartOptions } from "../../../../lupin_app/static/js/multiplexer/audio/recordingManager";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );
beforeEach( () => {
  localStorage.clear();
  document.body.replaceChildren();
} );

const ID = "aaaa1111-2222-3333-4444-555566667777";

// ---------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------

interface Calls {
  patches     : Array<{ id: string; fields: Record<string, unknown> }>;
  transitions : Array<{ id: string; toStatus: string; extras: Record<string, unknown> }>;
  refreshAfterWrite : number;
}

interface FakeRecorder extends TaskRowRecorderLike {
  starts : RecordingManagerStartOptions[];
  stops  : string[];
  active : string | null;
}

function fakeRecorder(): FakeRecorder {
  const r: FakeRecorder = {
    starts : [], stops : [], active : null,
    async startRecording( opts ) { r.starts.push( opts ); r.active = opts.contextId; },
    async stopRecording( id )    { r.stops.push( id ); },
    getActiveContextId()         { return r.active; },
  };
  return r;
}

type PaneName = "task list" | "holding area";

interface Mounted {
  root     : HTMLElement;
  calls    : Calls;
  recorder : FakeRecorder;
  unmount  : () => void;
  bus      : EventBus;
}

function task( over: Partial<TaskItem> = {} ): TaskItem {
  return { id: ID, title: "a row", status: "queued", owner_persona: "amy", priority: "P2",
           created_by: "maya", project: "lupin", ...over } as TaskItem;
}

/**
 * Mount one pane over a fake store.
 *
 * `holdingResult` decides what the holding store's writes answer; the task list's
 * writes always succeed.
 */
function mountPane( pane: PaneName, row: TaskItem = task( { status: pane === "holding area" ? "not_approved" : "queued" } ),
                    holdingResult: { ok: boolean; message?: string } = { ok: true } ): Mounted {
  const calls: Calls = { patches: [], transitions: [], refreshAfterWrite: 0 };
  const composite = { status: "ok", tasks: [ row ] } as unknown as TaskListComposite;
  const recorder  = fakeRecorder();
  const bus  = createEventBusForTesting();
  const root = document.createElement( "div" );
  document.body.appendChild( root );

  if ( pane === "task list" ) {
    const r = createTaskListRenderer( {
      eventBus : bus, recorder, getAuthToken : () => "tok",
      stores   : { taskList : {
        composite : () => composite,
        refresh   : async () => {},
        patchTask : ( id, fields ) => { calls.patches.push( { id, fields } ); return { restoreState: () => {}, done: Promise.resolve() }; },
        transitionTask : ( id, toStatus, extras ) => {
          calls.transitions.push( { id, toStatus, extras } ); return { restoreState: () => {}, done: Promise.resolve() };
        },
      } },
    } );
    r.mount( root );
    return { root, calls, recorder, bus, unmount: () => r.unmount() };
  }

  const r = createHoldingAreaRenderer( {
    eventBus : bus, recorder, getAuthToken : () => "tok",
    store    : {
      composite : () => composite,
      refresh   : async () => {},
      refreshAfterWrite : async () => { calls.refreshAfterWrite += 1; },
      transitionTask : async ( id, toStatus, extras ) => { calls.transitions.push( { id, toStatus, extras } ); return holdingResult; },
      patchTask      : async ( id, fields ) => { calls.patches.push( { id, fields } ); return holdingResult; },
    },
  } );
  r.mount( root );
  return { root, calls, recorder, bus, unmount: () => r.unmount() };
}

function q<T extends Element>( root: ParentNode, sel: string ): T {
  const el = root.querySelector<T>( sel );
  assert.ok( el, `not rendered: ${ sel }` );
  return el;
}

function click( el: Element ): void { el.dispatchEvent( new Event( "click", { bubbles: true } ) ); }

function change( el: HTMLSelectElement | HTMLInputElement, value: string ): void {
  el.value = value;
  el.dispatchEvent( new Event( "change", { bubbles: true } ) );
}

const tick = (): Promise<void> => new Promise( ( r ) => setTimeout( r, 0 ) );

function stripeText( root: ParentNode ): string {
  const stripe = q<HTMLElement>( root, ".task-row-error-stripe" );
  return stripe.hidden ? "" : ( stripe.textContent ?? "" );
}

const PANES: ReadonlyArray<PaneName> = [ "task list", "holding area" ];

// ---------------------------------------------------------------------------
// Every pane: the row controls reach a handler
// ---------------------------------------------------------------------------

for ( const pane of PANES ) {
  test( `🔴 ${ pane }: Submit with a verb and a reason reaches the store's transition door`, async () => {
    const m = mountPane( pane );
    change( q<HTMLSelectElement>( m.root, ".task-verb-select" ), "drop" );
    q<HTMLInputElement>( m.root, ".task-reason-input" ).value = "superseded";
    click( q( m.root, ".task-submit-button" ) );
    await tick();
    assert.equal( m.calls.transitions.length, 1,
      `a Submit on the ${ pane } issued ${ m.calls.transitions.length } transitions — its row controls reach no handler` );
    assert.equal( m.calls.transitions[ 0 ]!.id, ID );
    assert.equal( m.calls.transitions[ 0 ]!.toStatus, "dropped" );
  } );

  test( `${ pane }: a priority CHANGE only arms Update; the click posts; moving back disarms it`, async () => {
    const m = mountPane( pane );
    const sel    = q<HTMLSelectElement>( m.root, ".task-priority-select" );
    const update = q<HTMLButtonElement>( m.root, ".task-priority-update" );
    assert.equal( update.disabled, true, "Update must start disabled" );
    assert.equal( sel.dataset.original, "P2" );

    change( sel, "P0" );
    assert.deepEqual( m.calls.patches, [], "a change alone posted — the edit is not staged" );
    assert.equal( update.disabled, false );
    assert.equal( update.getAttribute( "aria-disabled" ), "false" );
    assert.equal( update.getAttribute( "title" ), "Set priority to P0" );

    change( sel, "P2" );
    assert.equal( update.disabled, true, "choosing the painted value again must disarm Update" );
    assert.equal( update.getAttribute( "aria-disabled" ), "true" );
    assert.equal( update.getAttribute( "title" ), PRIORITY_UPDATE_IDLE_TITLE );

    // 🔴 RE-CHECKED ON THE CLICK, not trusted from `disabled`.
    update.disabled = false;
    click( update );
    assert.deepEqual( m.calls.patches, [], "Update posted a priority equal to the painted one" );

    change( sel, "P0" );
    click( update );
    await tick();
    assert.deepEqual( m.calls.patches, [ { id: ID, fields: { priority: "P0" } } ] );
  } );

  test( `${ pane }: the owner select still commits on change`, async () => {
    const m = mountPane( pane );
    const owner = q<HTMLSelectElement>( m.root, ".task-owner-select" );
    const opt = document.createElement( "option" );
    opt.value = "bob"; owner.appendChild( opt );
    change( owner, "bob" );
    await tick();
    assert.deepEqual( m.calls.patches, [ { id: ID, fields: { owner_persona: "bob" } } ] );
  } );

  test( `${ pane }: choosing Drop offers the suggestions; any other verb withdraws them`, () => {
    const m = mountPane( pane );
    const verb   = q<HTMLSelectElement>( m.root, ".task-verb-select" );
    const reason = q<HTMLInputElement>( m.root, ".task-reason-input" );
    assert.equal( reason.getAttribute( "list" ), null, "no verb chosen yet, no suggestions" );
    change( verb, "drop" );
    assert.equal( reason.getAttribute( "list" ), DROP_REASON_DATALIST_ID );
    change( verb, "wont_fix" );
    assert.equal( reason.getAttribute( "list" ), null, "the drop suggestions outlived the Drop verb" );
    const lists = document.querySelectorAll( `datalist#${ DROP_REASON_DATALIST_ID }` );
    assert.equal( lists.length, 1 );
    assert.deepEqual( Array.from( lists[ 0 ]!.querySelectorAll( "option" ) ).map( ( o ) => o.value ), DROP_REASON_SUGGESTIONS );
  } );

  test( `${ pane }: the ⋯ toggle opens and closes the row's controls`, () => {
    const m = mountPane( pane );
    const btn  = q<HTMLElement>( m.root, ".task-disclose-button" );
    const ctrl = q<HTMLElement>( m.root, ".task-controls-row" );
    const was  = ctrl.hidden;
    click( btn );
    assert.equal( ctrl.hidden, !was );
    click( btn );
    assert.equal( ctrl.hidden, was );
  } );

  test( `${ pane }: the 📄 opens the body overlay by click and by Enter; unmount closes it`, () => {
    const m = mountPane( pane, task( { status: pane === "holding area" ? "not_approved" : "queued", body: "the body" } ) );
    const emoji = q<HTMLElement>( m.root, ".task-detail-emoji" );
    click( emoji );
    assert.equal( document.getElementById( "task-body-overlay" )?.querySelector( "pre" )?.textContent, "the body" );
    document.dispatchEvent( new KeyboardEvent( "keydown", { key: "Escape" } ) );
    assert.equal( document.getElementById( "task-body-overlay" ) === null, true );

    const enter = new KeyboardEvent( "keydown", { key: "Enter", bubbles: true, cancelable: true } );
    emoji.dispatchEvent( enter );
    assert.ok( document.getElementById( "task-body-overlay" ), "Enter on a focused 📄 must open it" );
    assert.equal( enter.defaultPrevented, true );
    m.unmount();
    assert.equal( document.getElementById( "task-body-overlay" ) === null, true, "unmount left the overlay open" );
  } );

  test( `${ pane }: the id cell copies the full id`, async () => {
    const m = mountPane( pane );
    const written: string[] = [];
    Object.defineProperty( navigator, "clipboard", { configurable: true, value: { writeText: async ( t: string ) => { written.push( t ); } } } );
    try {
      click( q( m.root, "tr.task-row .task-col-id" ) );
      await tick();
    } finally {
      Object.defineProperty( navigator, "clipboard", { configurable: true, value: undefined } );
    }
    assert.deepEqual( written, [ ID ] );
  } );

  test( `${ pane }: a key other than Enter/Space, or on a plain cell, does nothing`, () => {
    const m = mountPane( pane, task( { status: pane === "holding area" ? "not_approved" : "queued", body: "b" } ) );
    const x = new KeyboardEvent( "keydown", { key: "x", bubbles: true, cancelable: true } );
    q( m.root, ".task-detail-emoji" ).dispatchEvent( x );
    const enter = new KeyboardEvent( "keydown", { key: "Enter", bubbles: true, cancelable: true } );
    q( m.root, ".task-reason-input" ).dispatchEvent( enter );
    assert.equal( document.getElementById( "task-body-overlay" ) === null, true );
    assert.equal( enter.defaultPrevented, false );
  } );

  // ---------------------------------------------------------------------------
  // The mic
  // ---------------------------------------------------------------------------

  test( `${ pane }: the 🎤 sits immediately before the reason box and dictates into it at the caret`, async () => {
    const m = mountPane( pane );
    const mic    = q<HTMLButtonElement>( m.root, ".task-reason-stt" );
    const reason = q<HTMLInputElement>( m.root, ".task-reason-input" );
    // A BOOLEAN of the comparison, not the two nodes: a failing `assert.equal( node, node )`
    // deep-inspects the happy-dom Window graph at ~2.5 GB/s until the kernel steps in
    // (rows f5768ee4 / 32c58572), so the failure that would tell you about this bug is the
    // one that kills the run instead. Same assertion, survivable failure.
    assert.ok( mic.nextElementSibling === reason, "the mic must sit immediately before the field it fills" );
    assert.equal( mic.getAttribute( "title" ), REASON_MIC_TITLE );

    reason.value = "ab";
    reason.setSelectionRange( 1, 1 );
    click( mic );
    assert.equal( m.recorder.starts.length, 1 );
    const opts = m.recorder.starts[ 0 ]!;
    assert.equal( opts.contextId, reasonMicContextId( ID ) );
    assert.equal( opts.authToken, "tok" );
    assert.ok( mic.classList.contains( "recording" ) );

    click( mic );                               // this row records → stop
    assert.deepEqual( m.recorder.stops, [ reasonMicContextId( ID ) ] );
    assert.ok( mic.classList.contains( "processing" ) );
    click( mic );                               // processing → ignored
    assert.equal( m.recorder.stops.length, 1 );
    assert.equal( m.recorder.starts.length, 1 );

    opts.onComplete!( "XY", new Blob() );
    assert.equal( reason.value, "aXYb", "the transcription must splice at the caret, not clobber" );
    assert.equal( reason.selectionStart, 3 );
    assert.equal( mic.classList.contains( "recording" ) || mic.classList.contains( "processing" ), false );
  } );

  test( `${ pane }: a dictation error reaches the row stripe; a cancel just resets the mic`, () => {
    const m = mountPane( pane );
    const mic = q<HTMLButtonElement>( m.root, ".task-reason-stt" );
    click( mic );
    m.recorder.starts[ 0 ]!.onError!( { type: "x", message: "mic denied", originalError: null } );
    assert.equal( stripeText( m.root ), "Dictation failed: mic denied" );
    assert.equal( mic.classList.contains( "recording" ), false );

    m.recorder.active = null;
    click( mic );
    assert.ok( mic.classList.contains( "recording" ) );
    m.recorder.starts[ 1 ]!.onCancel!();
    assert.equal( mic.classList.contains( "recording" ), false );
  } );
}

// ---------------------------------------------------------------------------
// Holding-area specifics: its store never rejects, so the pane adapts it
// ---------------------------------------------------------------------------

test( "holding area: a refused write paints the server's words in the row stripe and does not refresh", async () => {
  const m = mountPane( "holding area", undefined, { ok: false, message: "not allowlisted" } );
  change( q<HTMLSelectElement>( m.root, ".task-priority-select" ), "P0" );
  click( q( m.root, ".task-priority-update" ) );
  await tick(); await tick();
  assert.equal( stripeText( m.root ), "Edit failed: not allowlisted" );
  assert.equal( m.calls.refreshAfterWrite, 0 );
} );

test( "holding area: a successful write takes a read that began after it", async () => {
  const m = mountPane( "holding area" );
  change( q<HTMLSelectElement>( m.root, ".task-priority-select" ), "P0" );
  click( q( m.root, ".task-priority-update" ) );
  await tick(); await tick();
  assert.equal( m.calls.refreshAfterWrite, 1 );
  assert.equal( stripeText( m.root ), "" );
} );

test( "holding area: after unmount the container's row listeners are gone", () => {
  const m = mountPane( "holding area" );
  const verb = q<HTMLSelectElement>( m.root, ".task-verb-select" );
  const ctrl = q<HTMLElement>( m.root, ".task-controls-row" );
  const container = q<HTMLElement>( m.root, ".holding-area-container" );
  m.unmount();
  document.body.appendChild( container );
  change( verb, "drop" );
  assert.equal( q<HTMLInputElement>( ctrl, ".task-reason-input" ).getAttribute( "list" ), null,
    "a change after unmount still reached the controller" );
} );

test( "holding area: the batch buttons still work beside the row controls", async () => {
  const m = mountPane( "holding area" );
  click( q( m.root, ".holding-approve-all" ) );
  await tick(); await tick();
  assert.deepEqual( m.calls.transitions.map( ( t ) => t.toStatus ), [ "queued" ] );
} );

// ---------------------------------------------------------------------------
// The mic's refusals
// ---------------------------------------------------------------------------

test( "the mic refuses in words when its row has no reason box, and records nothing", () => {
  const m = mountPane( "task list" );
  q( m.root, ".task-reason-input" ).remove();
  click( q( m.root, ".task-reason-stt" ) );
  assert.equal( m.recorder.starts.length, 0 );
  assert.equal( stripeText( m.root ), MIC_NO_REASON_BOX );
} );

test( "an idless mic does nothing", () => {
  const m = mountPane( "task list" );
  const mic = q<HTMLButtonElement>( m.root, ".task-reason-stt" );
  mic.dataset.taskId = "";
  click( mic );
  assert.equal( m.recorder.starts.length, 0 );
} );

test( "a terminal row's mic and priority select are disabled", () => {
  const frag = renderDisclosedRow( task( { status: "done" } ), "task-list", undefined );
  const host = document.createElement( "table" );
  host.appendChild( frag );
  assert.equal( q<HTMLButtonElement>( host, ".task-reason-stt" ).disabled, true );
  assert.equal( q<HTMLSelectElement>( host, ".task-priority-select" ).disabled, true );
  assert.equal( q<HTMLSelectElement>( host, ".task-priority-select" ).getAttribute( "aria-disabled" ), "true" );
} );

// ---------------------------------------------------------------------------
// Controller edges the panes cannot reach
// ---------------------------------------------------------------------------

function bareController( recorder?: TaskRowRecorderLike ): { c: TaskRowController; container: HTMLElement; patches: string[] } {
  const container = document.createElement( "div" );
  document.body.appendChild( container );
  const patches: string[] = [];
  const c = new TaskRowController( {
    container, logLabel: "[test]", recorder,
    writer: {
      patchTask      : ( id ) => { patches.push( id ); return { restoreState: () => {}, done: Promise.resolve() }; },
      transitionTask : () => ( { restoreState: () => {}, done: Promise.resolve() } ),
    },
  } );
  return { c, container, patches };
}

test( "controller: an Update with no select beside it, or no id, posts nothing", () => {
  const { c, container, patches } = bareController();
  const row = document.createElement( "div" );
  row.className = "task-controls-row";
  row.setAttribute( "data-controls-for", ID );
  const update = document.createElement( "button" );
  update.className = "task-priority-update";
  row.appendChild( update );
  container.appendChild( row );
  assert.equal( c.handleClick( update ), true );
  assert.deepEqual( patches, [], "no select beside Update" );

  row.setAttribute( "data-controls-for", "" );
  const sel = document.createElement( "select" );
  sel.className = "task-priority-select";
  row.appendChild( sel );
  c.handleClick( update );
  assert.deepEqual( patches, [], "no id" );
} );

test( "controller: a priority select with no Update beside it is a no-op; an unclaimed click is declined", () => {
  const { c, container } = bareController();
  const sel = document.createElement( "select" );
  sel.className = "task-priority-select";
  container.appendChild( sel );
  c.handleChange( sel );
  const span = document.createElement( "span" );
  container.appendChild( span );
  assert.equal( c.handleClick( span ), false );
  c.handleChange( span );
} );

test( "controller: with no auth-token getter the dictation carries a null token", () => {
  const rec = fakeRecorder();
  const { c, container } = bareController( rec );
  const row = document.createElement( "tr" );
  row.className = "task-controls-row";
  const mic = document.createElement( "button" );
  mic.className = "task-reason-stt";
  mic.dataset.taskId = ID;
  const input = document.createElement( "input" );
  input.className = "task-reason-input";
  row.append( mic, input );
  container.appendChild( row );
  c.handleClick( mic );
  assert.equal( rec.starts[ 0 ]!.authToken, null );
} );

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

test( "priority template: an unrecognised stored value keeps its own selected option", () => {
  const frag = renderPriorityControl( task( { priority: "P9" } ) );
  const sel = q<HTMLSelectElement>( frag, ".task-priority-select" );
  assert.equal( sel.options[ 0 ]!.value, "P9" );
  assert.equal( sel.value, "P9" );
  assert.equal( sel.dataset.original, "P9" );
} );

test( "priority template: a stored value anywhere in the list paints AS ITSELF, so an untouched row is never pending", () => {
  for ( const p of [ "P0", "P1", "P2", "P3", "P4", "P5" ] ) {
    const sel = q<HTMLSelectElement>( renderPriorityControl( task( { priority: p } ) ), ".task-priority-select" );
    assert.equal( sel.value, p, `a stored ${ p } painted as ${ sel.value }` );
    assert.equal( sel.value, sel.dataset.original );
  }
} );

test( "priority template: an idless row stamps empty ids, and the heat class tints the select", () => {
  const frag = renderPriorityControl( { title: "x", status: "queued", priority: "P0" } as TaskItem );
  const sel = q<HTMLSelectElement>( frag, ".task-priority-select" );
  assert.equal( sel.dataset.taskId, "" );
  assert.equal( q<HTMLButtonElement>( frag, ".task-priority-update" ).dataset.taskId, "" );
  assert.match( sel.className, /task-prio-high/ );
  assert.equal( sel.disabled, false );
} );

test( "datalist: ensuring it twice leaves exactly one", () => {
  const a = ensureDropReasonDatalist( document );
  const b = ensureDropReasonDatalist( document );
  assert.equal( a, b );
  assert.equal( document.querySelectorAll( `#${ DROP_REASON_DATALIST_ID }` ).length, 1 );
} );

// ---------------------------------------------------------------------------
// HoldingAreaStore.patchTask — the field door the holding area's row now reaches
// ---------------------------------------------------------------------------

import { createHoldingAreaStore } from "../../../../lupin_app/static/js/multiplexer/stores/HoldingAreaStore";

function holdingStoreWith( patch: ( path: string, body: unknown ) => Promise<unknown> ) {
  return createHoldingAreaStore( {
    bus : createEventBusForTesting(),
    api : { get: async () => ( {} as never ), post: async () => ( {} as never ), patch: patch as never },
    actorProvider : () => "rick@example.com",
    setIntervalFn : () => 1, clearIntervalFn : () => {},
  } );
}

test( "HoldingAreaStore.patchTask: one PATCH to the encoded row, carrying actor and authority", async () => {
  const sent: Array<{ path: string; body: Record<string, unknown> }> = [];
  const store = holdingStoreWith( async ( path, body ) => { sent.push( { path, body: body as Record<string, unknown> } ); return {}; } );
  assert.deepEqual( await store.patchTask( "a/b?c#d", { priority: "P1" } ), { ok: true } );
  assert.equal( sent.length, 1 );
  assert.equal( sent[ 0 ]!.path, "/api/tasks/a%2Fb%3Fc%23d" );
  assert.equal( sent[ 0 ]!.body.priority, "P1" );
  assert.equal( sent[ 0 ]!.body.authority, "user_direct" );
  assert.match( String( sent[ 0 ]!.body.actor ), /rick@example\.com/ );
} );

test( "HoldingAreaStore.patchTask: a refusal resolves with the server's words and never rejects", async () => {
  const store = holdingStoreWith( async () => {
    throw Object.assign( new Error( 'HTTP 403 /api/tasks/x: {"detail":"not yours"}' ), { status: 403, url: "/api/tasks/x" } );
  } );
  assert.deepEqual( await store.patchTask( "x", { priority: "P1" } ), { ok: false, message: "not yours" } );
} );

test( "controller: a select painted with no data-original compares against \"\" on change and on Update", () => {
  const { c, container, patches } = bareController();
  const row = document.createElement( "tr" );
  row.className = "task-controls-row";
  row.setAttribute( "data-controls-for", ID );
  const sel = document.createElement( "select" );
  sel.className = "task-priority-select";
  for ( const v of [ "", "P1" ] ) { const o = document.createElement( "option" ); o.value = v; sel.appendChild( o ); }
  const update = document.createElement( "button" );
  update.className = "task-priority-update";
  row.append( sel, update );
  container.appendChild( row );

  sel.value = "";
  c.handleChange( sel );
  assert.equal( update.disabled, true, "\"\" equals a missing original — nothing moved" );
  c.handleClick( update );
  assert.deepEqual( patches, [], "an empty choice posts nothing" );

  sel.value = "P1";
  c.handleChange( sel );
  assert.equal( update.disabled, false );
  c.handleClick( update );
  assert.deepEqual( patches, [ ID ] );
} );

test( "controller: a mic with no data-task-id at all does nothing", () => {
  const rec = fakeRecorder();
  const { c, container } = bareController( rec );
  const mic = document.createElement( "button" );
  mic.className = "task-reason-stt";
  container.appendChild( mic );
  assert.equal( c.handleClick( mic ), true );
  assert.equal( rec.starts.length, 0 );
} );

// ---------------------------------------------------------------------------
// With A-1a: a staged priority and a chosen verb survive a poll's repaint
// ---------------------------------------------------------------------------

for ( const pane of PANES ) {
  test( `${ pane }: a poll repaint keeps a staged priority armed and a chosen Drop offering its suggestions`, () => {
    const m = mountPane( pane );
    change( q<HTMLSelectElement>( m.root, ".task-priority-select" ), "P0" );
    change( q<HTMLSelectElement>( m.root, ".task-verb-select" ), "drop" );
    const before = q<HTMLSelectElement>( m.root, ".task-priority-select" );

    const type = pane === "task list" ? "store_task_list_changed" : "store_holding_area_changed";
    m.bus.emit( { type, payload: { stampUpdated: true }, source: "test", ts: 0 } as never );

    const sel = q<HTMLSelectElement>( m.root, ".task-priority-select" );
    assert.notEqual( sel, before, "positive control: the poll really repainted the row" );
    assert.equal( sel.value, "P0" );
    assert.equal( q<HTMLButtonElement>( m.root, ".task-priority-update" ).disabled, false,
      "the restored priority must re-arm Update, or the operator's edit is on screen and unsendable" );
    assert.deepEqual( m.calls.patches, [], "restoring a staged priority must never send it" );
    assert.equal( q<HTMLInputElement>( m.root, ".task-reason-input" ).getAttribute( "list" ), DROP_REASON_DATALIST_ID );
  } );
}
