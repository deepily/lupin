// Parity row A-1c1 — the Jobs pane keeps an opened bucket and an expanded card.
// 100% lines/branches/functions per the multiplexer coverage mandate.
//
// 🔴 EVERY RE-RENDER HERE IS A REAL JOB EVENT through the real JobStore on the bus,
// never a call to the render by name. The defect (Phase 2 A12 B9c, Q7) is that
// `renderAll` rebuilds all five buckets on every job event, so an operator's click
// lasted exactly until the next job moved — which a test that re-renders by hand,
// between the click and the assertion, would reach only by accident.

import { test, before, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { GlobalRegistrator } from "@happy-dom/global-registrator";

import { createEventBusForTesting, type EventBus } from "../../../../lupin_app/static/js/multiplexer/shared/EventBus";
import { createJobStore } from "../../../../lupin_app/static/js/multiplexer/stores/JobStore";
import {
  createJobsPaneRenderer,
  type JobsPaneApiClient,
} from "../../../../lupin_app/static/js/multiplexer/render/JobsPaneRenderer";
import { renderJobBucket } from "../../../../lupin_app/static/js/multiplexer/render/templates/jobBucket";
import {
  JOBS_BUCKET_EXPAND_KEY,
  loadBucketExpandState,
  saveBucketExpandChoice,
  type BucketExpandStorage,
} from "../../../../lupin_app/static/js/multiplexer/render/jobsBucketExpand";
import type { JobBucket, JobStateTransitionPayload } from "../../../../lupin_app/static/js/multiplexer/shared/types";

before( () => {
  if ( typeof globalThis.document === "undefined" ) GlobalRegistrator.register();
} );

beforeEach( () => { localStorage.clear(); } );

const SERVER_STATE: Record<string, string> = { todo: "pending", running: "running", done: "completed", dead: "failed" };

function emitJob( bus: EventBus, idHash: string, status: string ): void {
  bus.emit<JobStateTransitionPayload>( {
    type    : "job_state_transition",
    payload : {
      job_id: idHash, id_hash: idHash, from_state: null, to_state: SERVER_STATE[ status ] as string,
      metadata: { agent_type: "DeepResearchJob", topic: `topic ${ idHash }` },
    },
    source  : "test",
    ts      : Date.now(),
  } );
}

function api(): JobsPaneApiClient {
  return {
    get    : async <T,>(): Promise<T> => ( { jobs: [] } ) as unknown as T,
    delete : async <T,>(): Promise<T> => null as T,
    post   : async <T,>(): Promise<T> => null as T,
  };
}

/** A Map-backed storage — survives an unmount, which is as close to a reload as a unit gets. */
function memoryStorage( seed: Record<string, string> = {} ): BucketExpandStorage & { data: Map<string, string> } {
  const data = new Map( Object.entries( seed ) );
  return { data, getItem: ( k ) => data.get( k ) ?? null, setItem: ( k, v ) => { data.set( k, v ); } };
}

function mountPane( storage: BucketExpandStorage | null = null ) {
  const bus  = createEventBusForTesting();
  const jobs = createJobStore( { bus } );
  const root = document.createElement( "section" );
  const mount = document.createElement( "div" );
  mount.id = "jobs-buckets-container";
  root.appendChild( mount );
  document.body.appendChild( root );
  const renderer = createJobsPaneRenderer( { eventBus: bus, stores: { jobs }, api: api(), storage } );
  renderer.mount( root );

  const bucket = ( name: JobBucket ): HTMLElement => {
    const el = Array.from( root.querySelectorAll<HTMLElement>( ".jobs-bucket" ) ).find( ( b ) => b.dataset.bucket === name );
    assert.ok( el, `no ${ name } bucket painted` );
    return el;
  };
  const card = ( idHash: string ): HTMLElement => {
    const el = Array.from( root.querySelectorAll<HTMLElement>( ".job-card" ) )
      .find( ( c ) => c.getAttribute( "data-id-hash" ) === idHash );
    assert.ok( el, `no card painted for ${ idHash }` );
    return el;
  };
  return {
    bus, root, renderer, bucket, card,
    headerOf  : ( name: JobBucket ) => bucket( name ).querySelector( ".jobs-bucket-header" ) as HTMLElement,
    isOpen    : ( name: JobBucket ) => bucket( name ).querySelector( ".jobs-bucket-header" )!.getAttribute( "aria-expanded" ) === "true",
    cardOpen  : ( idHash: string ) => !card( idHash ).querySelector( ".job-card-details" )!.classList.contains( "collapsed" ),
    unmount() { renderer.unmount(); root.remove(); },
  };
}

// ---------------------------------------------------------------------------
// Buckets survive a job event
// ---------------------------------------------------------------------------

test( "a bucket the operator OPENED stays open when the next job event repaints the pane", () => {
  const p = mountPane();
  emitJob( p.bus, "d1", "done" );
  assert.equal( p.isOpen( "done" ), false, "positive control: done starts collapsed (Q-A2)" );

  p.headerOf( "done" ).click();
  assert.equal( p.isOpen( "done" ), true );

  emitJob( p.bus, "t1", "todo" );   // an unrelated job moves — the pane rebuilds every bucket
  assert.equal( p.isOpen( "done" ), true, "the job event closed the bucket the operator opened" );
  assert.equal(
    p.bucket( "done" ).querySelector( ".jobs-bucket-cards" )!.classList.contains( "collapsed" ), false,
    "aria says open but the cards are still hidden" );
  p.unmount();
} );

test( "a bucket the operator CLOSED stays closed, overriding the Q-A2 open default", () => {
  const p = mountPane();
  emitJob( p.bus, "r1", "running" );
  assert.equal( p.isOpen( "running" ), true, "positive control: running starts open (Q-A2)" );

  p.headerOf( "running" ).dispatchEvent( new KeyboardEvent( "keydown", { key: "Enter", bubbles: true } ) );
  emitJob( p.bus, "t1", "todo" );
  assert.equal( p.isOpen( "running" ), false, "the job event reopened the bucket the operator closed" );
  p.unmount();
} );

test( "control arm: an untouched bucket keeps its Q-A2 default across a job event", () => {
  const p = mountPane();
  emitJob( p.bus, "d1", "done" );
  emitJob( p.bus, "r1", "running" );
  assert.equal( p.isOpen( "done" ), false );
  assert.equal( p.isOpen( "running" ), true );
  p.unmount();
} );

// ---------------------------------------------------------------------------
// Cards survive a job event
// ---------------------------------------------------------------------------

test( "a job card the operator EXPANDED stays expanded, with its meta, across a job event", () => {
  const p = mountPane();
  emitJob( p.bus, "r1", "running" );
  ( p.card( "r1" ).querySelector( ".job-card-header" ) as HTMLElement ).click();
  assert.equal( p.cardOpen( "r1" ), true, "positive control: the header click expanded the card" );

  emitJob( p.bus, "r2", "running" );
  assert.equal( p.cardOpen( "r1" ), true, "the job event collapsed the card the operator expanded" );
  assert.match( p.card( "r1" ).querySelector( ".job-card-details" )!.textContent ?? "", /topic r1/,
    "the card reopened without its meta" );
  assert.equal( p.cardOpen( "r2" ), false, "a card nobody opened came up expanded" );
  p.unmount();
} );

test( "a card the operator collapsed again is NOT reopened by the next job event", () => {
  const p = mountPane();
  emitJob( p.bus, "r1", "running" );
  const header = (): HTMLElement => p.card( "r1" ).querySelector( ".job-card-header" ) as HTMLElement;
  header().click();
  header().click();
  emitJob( p.bus, "r2", "running" );
  assert.equal( p.cardOpen( "r1" ), false );
  p.unmount();
} );

test( "an expanded card whose job leaves the pane is left gone — nothing re-creates it", () => {
  const p = mountPane();
  emitJob( p.bus, "r1", "running" );
  ( p.card( "r1" ).querySelector( ".job-card-header" ) as HTMLElement ).click();
  p.bus.emit( { type: "job_removed", payload: { id_hash: "r1" }, source: "test", ts: Date.now() } );
  assert.equal(
    Array.from( p.root.querySelectorAll( ".job-card" ) ).some( ( c ) => c.getAttribute( "data-id-hash" ) === "r1" ),
    false );
  p.unmount();
} );

// ---------------------------------------------------------------------------
// The template's two new seams, alone
// ---------------------------------------------------------------------------

test( "template: `expanded` overrides the default and `onToggle` reports the NEW state for click and key", () => {
  const job = { id_hash: "x", job_type: "T", status: "done", created_at: 0, completed_at: 0, meta: {} } as never;
  const seen: Array<[ JobBucket, boolean ]> = [];
  const el = renderJobBucket( "done", [ job ], { expanded: true, onToggle: ( b, e ) => seen.push( [ b, e ] ) } );
  const header = el.querySelector( ".jobs-bucket-header" ) as HTMLElement;
  assert.equal( header.getAttribute( "aria-expanded" ), "true" );

  header.click();
  header.dispatchEvent( new KeyboardEvent( "keydown", { key: " ", bubbles: true } ) );
  assert.deepEqual( seen, [ [ "done", false ], [ "done", true ] ] );
} );

// ---------------------------------------------------------------------------
// Buckets survive a reload — the shared legacy key
// ---------------------------------------------------------------------------

const HERE        = dirname( fileURLToPath( import.meta.url ) );
const LEGACY_PATH = resolve( HERE, "../../../../lupin_app/static/js/notifications.js" );

test( "the key and legacy's queue names are read off notifications.js, not retyped here", () => {
  const legacy = readFileSync( LEGACY_PATH, "utf8" );
  assert.ok( legacy.includes( `this.QUEUE_EXPAND_STATE_KEY = '${ JOBS_BUCKET_EXPAND_KEY }';` ),
    "the shared key no longer matches the JS card's QUEUE_EXPAND_STATE_KEY" );
  const block = legacy.slice( legacy.indexOf( "this.queueCategoryState = {" ), legacy.indexOf( "this.queueCounts =" ) );
  assert.ok( block.length > 50, "the legacy queueCategoryState block was not found" );
  const names = Array.from( block.matchAll( /^\s*(\w+)\s*:\s*\{/gm ) ).map( ( m ) => m[ 1 ] );
  assert.deepEqual( names, [ "todo", "run", "done", "dead", "history" ] );
} );

test( "RELOAD: a bucket opened and a bucket closed come back that way when the pane mounts again", () => {
  const storage = memoryStorage();
  const first = mountPane( storage );
  emitJob( first.bus, "d1", "done" );
  first.headerOf( "done" ).click();       // open
  first.headerOf( "running" ).click();    // close
  first.unmount();

  const second = mountPane( storage );
  emitJob( second.bus, "d1", "done" );
  assert.equal( second.isOpen( "done" ), true, "the reload closed a bucket the operator opened" );
  assert.equal( second.isOpen( "running" ), false, "the reload reopened a bucket the operator closed" );
  assert.equal( second.isOpen( "todo" ), true, "an untouched bucket lost its Q-A2 default" );
  second.unmount();
} );

test( "the mux writes legacy's shape: `run`, never `running`, merged into what legacy stored", () => {
  const storage = memoryStorage( { [ JOBS_BUCKET_EXPAND_KEY ]: JSON.stringify( { todo: false, done: true, custom: 1 } ) } );
  const p = mountPane( storage );
  p.headerOf( "running" ).click();
  p.unmount();
  assert.deepEqual( JSON.parse( storage.data.get( JOBS_BUCKET_EXPAND_KEY )! ), { todo: false, done: true, custom: 1, run: false } );
} );

test( "a state LEGACY saved opens the multiplexer the same way — the cross-client half", () => {
  const legacyWrote = { todo: false, run: false, done: true, dead: false, history: true };
  const p = mountPane( memoryStorage( { [ JOBS_BUCKET_EXPAND_KEY ]: JSON.stringify( legacyWrote ) } ) );
  emitJob( p.bus, "d1", "done" );
  const open = ( [ "todo", "running", "done", "dead", "history" ] as JobBucket[] ).map( ( b ) => p.isOpen( b ) );
  assert.deepEqual( open, [ false, false, true, false, true ] );
  p.unmount();
} );

test( "module: null storage, a corrupt payload, an array, JSON null and non-boolean values all mean no choice", () => {
  assert.deepEqual( loadBucketExpandState( null ), {} );
  for ( const bad of [ "{not json", "[true]", "null", "7" ] ) {
    assert.deepEqual( loadBucketExpandState( memoryStorage( { [ JOBS_BUCKET_EXPAND_KEY ]: bad } ) ), {}, bad );
  }
  assert.deepEqual( loadBucketExpandState( memoryStorage( { [ JOBS_BUCKET_EXPAND_KEY ]: '{"run":"yes","done":true}' } ) ), { done: true } );
  assert.deepEqual( loadBucketExpandState( memoryStorage() ), {} );
} );

test( "module: saving to null storage is a no-op, and a store that refuses the write does not throw", () => {
  saveBucketExpandChoice( null, "done", true );
  const refusing: BucketExpandStorage = { getItem: () => null, setItem: () => { throw new Error( "QuotaExceededError" ); } };
  assert.doesNotThrow( () => saveBucketExpandChoice( refusing, "done", true ) );
} );
